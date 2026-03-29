#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sessions.keys import derive_link_session_key


def _post_json(base_url: str, path: str, payload: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
    req = urllib.request.Request(
        base_url.rstrip('/') + path,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _get_json(base_url: str, path: str, timeout: float = 60.0) -> Dict[str, Any]:
    with urllib.request.urlopen(base_url.rstrip('/') + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _get_json_with_rate_limit_retry(
    base_url: str,
    path: str,
    timeout: float = 60.0,
    deadline: float | None = None,
) -> Dict[str, Any]:
    while True:
        try:
            return _get_json(base_url, path, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            retry_after = 1.0
            try:
                retry_after = max(0.25, float(exc.headers.get("Retry-After", "1")))
            except Exception:
                retry_after = 1.0
            now = time.time()
            if deadline is not None and now + retry_after > deadline:
                raise
            time.sleep(retry_after)


def main() -> int:
    parser = argparse.ArgumentParser(description='Deterministic cross-channel continuity probe for Vera.')
    parser.add_argument('--base-url', default='http://127.0.0.1:8788')
    parser.add_argument('--link-id', default='')
    parser.add_argument('--run-id', default='')
    parser.add_argument('--sleep-seconds', type=float, default=2.5)
    parser.add_argument('--reply-timeout-seconds', type=float, default=40.0)
    parser.add_argument('--poll-interval-seconds', type=float, default=0.5)
    parser.add_argument('--output', default='')
    parser.add_argument('--clear-outbox', action='store_true')
    args = parser.parse_args()

    run_id = args.run_id.strip() or f"cross_channel_probe_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    link_id = args.link_id.strip() or f"{run_id}@example.com"
    canonical_key = derive_link_session_key(link_id)
    api_alias = f'api:{run_id}:api-user'
    api_conversation_id = f'{run_id}:api'
    local_alias = f'local-loopback:{run_id}:local-user'

    if args.clear_outbox:
        try:
            _post_json(args.base_url, '/api/channels/local/outbox/clear', {})
        except Exception:
            pass

    link_result = _post_json(
        args.base_url,
        '/api/session/link',
        {
            'session_link_id': link_id,
            'alias_keys': [api_alias, api_conversation_id, local_alias],
            'channel_id': 'api',
            'sender_id': f'{run_id}:api-user',
        },
    )

    api_touch = _post_json(
        args.base_url,
        '/api/session/activity',
        {
            'conversation_id': api_conversation_id,
            'sender_id': f'{run_id}:api-user',
            'channel_id': 'api',
            'session_link_id': link_id,
            'trigger': 'cross_channel_probe',
        },
    )

    loopback_error = None
    loopback_result: Dict[str, Any] = {}
    try:
        loopback_result = _post_json(
            args.base_url,
            '/api/channels/local/inbound',
            {
                'text': 'Reply with exactly LOOPBACK_CONTINUITY_OK',
                'sender_id': f'{run_id}:local-user',
                'conversation_id': f'{run_id}:local',
                'session_link_id': link_id,
                'channel_id': 'local-loopback',
                'tool_choice': 'none',
                'wait': False,
            },
            timeout=10.0,
        )
    except Exception as exc:
        loopback_error = str(exc)

    outbox = {'ok': True, 'count': 0, 'messages': []}
    deadline = time.time() + max(0.1, float(args.reply_timeout_seconds))
    while True:
        try:
            outbox = _get_json_with_rate_limit_retry(
                args.base_url,
                '/api/channels/local/outbox?limit=10',
                timeout=10.0,
                deadline=deadline,
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                if not loopback_error:
                    loopback_error = 'reply_timeout_rate_limited'
                break
            raise
        messages = outbox.get('messages') or outbox.get('rows') or []
        if messages:
            break
        if time.time() >= deadline:
            if not loopback_error:
                loopback_error = 'reply_timeout'
            break
        time.sleep(max(0.05, float(args.poll_interval_seconds)))
    canonical_view = _get_json(args.base_url, '/api/session/links?session_key=' + urllib.parse.quote(canonical_key, safe=''))
    api_alias_view = _get_json(args.base_url, '/api/session/links?session_key=' + urllib.parse.quote(api_alias, safe=''))
    local_alias_view = _get_json(args.base_url, '/api/session/links?session_key=' + urllib.parse.quote(local_alias, safe=''))

    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'base_url': args.base_url,
        'run_id': run_id,
        'link_id': link_id,
        'canonical_key': canonical_key,
        'link_result': link_result,
        'api_touch': api_touch,
        'loopback_result': loopback_result,
        'loopback_error': loopback_error,
        'outbox': outbox,
        'canonical_view': canonical_view,
        'api_alias_view': api_alias_view,
        'local_alias_view': local_alias_view,
    }

    output_path = Path(args.output) if args.output else Path('tmp/audits') / f'{run_id}.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding='utf-8')

    summary = {
        'artifact': str(output_path),
        'canonical_session_key': canonical_view.get('canonical_session_key'),
        'api_canonical': api_alias_view.get('canonical_session_key'),
        'local_canonical': local_alias_view.get('canonical_session_key'),
        'aliases': canonical_view.get('aliases'),
        'session_exists': canonical_view.get('session_exists'),
        'message_count': canonical_view.get('message_count'),
        'outbox_count': len((outbox.get('messages') or outbox.get('rows') or [])),
        'loopback_error': loopback_error,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
