#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import List, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from core.atomic_io import atomic_json_write, safe_json_read


_VIDEO_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\[INFO\]\s+core\.runtime\.vera: "
    r"Video generation complete: urls=\[(?P<urls>.+?)\]"
)


def _extract_urls(raw: str) -> List[str]:
    return re.findall(r"'(https?://[^']+)'", str(raw or ""))


def _collect_video_urls(log_path: Path, since_prefix: str, until_prefix: str, limit: int) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    for line in log_path.read_text(errors="ignore").splitlines():
        match = _VIDEO_LINE_RE.match(line.strip())
        if not match:
            continue
        ts = match.group("ts")
        if since_prefix and ts < since_prefix:
            continue
        if until_prefix and ts > until_prefix:
            continue
        for url in _extract_urls(match.group("urls")):
            rows.append((ts, url))
    if limit > 0:
        rows = rows[-limit:]
    return rows


def _generated_media_root() -> Path:
    return Path("vera_memory") / "generated_media"


def _generated_media_manifest_path() -> Path:
    return _generated_media_root() / "manifest.json"


def _guess_suffix(url: str) -> str:
    try:
        suffix = Path(urlparse(str(url or "")).path).suffix.strip().lower()
    except Exception:
        suffix = ""
    return suffix if suffix else ".mp4"


def _slugify(value: str, maximum: int = 48) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    if not cleaned:
        cleaned = "generated"
    return cleaned[:maximum].rstrip("-") or "generated"


def _record_manifest(items: List[dict]) -> Path:
    manifest_path = _generated_media_manifest_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = safe_json_read(manifest_path, default={}) or {}
    rows = payload.get("items")
    existing = list(rows) if isinstance(rows, list) else []
    existing.extend(items)
    payload["items"] = existing[-500:]
    payload["updated_at"] = asyncio.get_event_loop_policy().get_event_loop().time()  # placeholder to be overwritten
    atomic_json_write(manifest_path, payload)
    return manifest_path


async def _cache_urls(prompt: str, model: str, urls: List[str]) -> dict:
    root = _generated_media_root()
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    kind_dir = root / "video" / now.strftime("%Y%m%d")
    kind_dir.mkdir(parents=True, exist_ok=True)
    prompt_slug = _slugify(prompt)
    prompt_hash = hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()[:12]
    timeout_seconds = 120
    items = []
    local_paths = []
    for index, url in enumerate(urls, start=1):
        item_now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        filename = f"{item_now.strftime('%Y%m%dT%H%M%SZ')}_{prompt_slug}_{prompt_hash}_{index:02d}{_guess_suffix(url)}"
        target = kind_dir / filename
        item = {
            "created_at": item_now.isoformat().replace("+00:00", "Z"),
            "media_kind": "video",
            "model": str(model or ""),
            "prompt": str(prompt or ""),
            "remote_url": url,
            "local_path": str(target),
            "status": "pending",
        }
        try:
            with urlopen(url, timeout=timeout_seconds) as response:
                content = response.read()
                target.write_bytes(content)
                item["status"] = "cached"
                item["bytes"] = target.stat().st_size
                item["content_type"] = str(response.headers.get("content-type") or "")
                local_paths.append(str(target))
        except Exception as exc:
            item["status"] = "download_failed"
            item["error"] = str(exc)
        items.append(item)
    manifest_path = _generated_media_manifest_path()
    payload = safe_json_read(manifest_path, default={}) or {}
    rows = payload.get("items")
    existing = list(rows) if isinstance(rows, list) else []
    existing.extend(items)
    payload["items"] = existing[-500:]
    payload["updated_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z")
    atomic_json_write(manifest_path, payload)
    return {"local_paths": local_paths, "items": items, "manifest_path": str(manifest_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill older generated video URLs from logs into vera_memory/generated_media.")
    parser.add_argument("--log-path", default="logs/vera_tray.log")
    parser.add_argument("--since-prefix", default="", help="Inclusive timestamp prefix filter, e.g. '2026-03-12 03:30'")
    parser.add_argument("--until-prefix", default="", help="Inclusive timestamp prefix filter, e.g. '2026-03-12 03:59'")
    parser.add_argument("--limit", type=int, default=5, help="Maximum URLs to backfill from the filtered set (latest first).")
    parser.add_argument("--prompt-label", default="log-backfill-video", help="Prompt label used in cache filenames/manifest.")
    parser.add_argument("--model", default="xai-video-log-backfill")
    parser.add_argument("--dry-run", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    log_path = Path(args.log_path)
    if not log_path.exists():
        print(json.dumps({"ok": False, "reason": "missing_log", "log_path": str(log_path)}, indent=2))
        return 1

    rows = _collect_video_urls(
        log_path=log_path,
        since_prefix=str(args.since_prefix or ""),
        until_prefix=str(args.until_prefix or ""),
        limit=int(args.limit or 0),
    )
    urls = [url for _, url in rows]
    payload = {
        "ok": True,
        "log_path": str(log_path),
        "count": len(urls),
        "items": [{"timestamp": ts, "remote_url": url} for ts, url in rows],
    }
    if args.dry_run or not urls:
        print(json.dumps(payload, indent=2))
        return 0

    cache_result = await _cache_urls(
        str(args.prompt_label or "log-backfill-video"),
        str(args.model or "xai-video-log-backfill"),
        urls,
    )
    payload.update(
        {
            "local_paths": list(cache_result.get("local_paths") or []),
            "manifest_path": str(cache_result.get("manifest_path") or ""),
            "cache_items": list(cache_result.get("items") or []),
        }
    )
    print(json.dumps(payload, indent=2))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
