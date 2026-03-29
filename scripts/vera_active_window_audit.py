#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import os
import time


def _local_tzinfo():
    try:
        if os.getenv("TZ"):
            time.tzset()
    except Exception:
        pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def _parse_ts(value: str, *, naive_tz=None) -> Optional[datetime]:
    raw = str(value or '').strip()
    if not raw:
        return None
    if raw.endswith('Z'):
        raw = raw[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=naive_tz or timezone.utc).astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _iter_active_cycles(rows: Iterable[Dict[str, Any]], since_utc: datetime) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        ts = _parse_ts(row.get('timestamp_utc') or row.get('ts_utc') or '', naive_tz=timezone.utc)
        if ts is None or ts < since_utc:
            continue
        cycle = row.get('cycle_result') if isinstance(row.get('cycle_result'), dict) else row
        if str(cycle.get('phase') or '') != 'active':
            continue
        out.append({
            'ts_utc': ts.isoformat().replace('+00:00', 'Z'),
            'trigger': row.get('trigger') or cycle.get('trigger'),
            'reflection_reason': cycle.get('reflection_reason'),
            'reflection_outcome': cycle.get('reflection_outcome'),
            'workflow_reason': (cycle.get('workflow_result') or {}).get('reason'),
            'followthrough_reason': (cycle.get('followthrough_result') or {}).get('reason'),
            'week1_reason': (cycle.get('week1_result') or {}).get('reason'),
            'calendar_reason': (cycle.get('calendar_result') or {}).get('reason'),
            'sentinel_processed': (cycle.get('sentinel_result') or {}).get('processed'),
            'sentinel_pending': (cycle.get('sentinel_result') or {}).get('pending_remaining'),
        })
    return out


def _iter_recent_journal(rows: Iterable[Dict[str, Any]], since_utc: datetime, *, naive_tz) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        ts = _parse_ts(row.get('timestamp') or row.get('ts_utc') or '', naive_tz=naive_tz)
        if ts is None or ts < since_utc:
            continue
        out.append({
            'ts_utc': ts.isoformat().replace('+00:00', 'Z'),
            'trigger': row.get('trigger'),
            'intent': row.get('intent'),
            'thought': str(row.get('thought') or '')[:220],
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit active-window autonomy behavior for a recent time window.')
    parser.add_argument('--hours', type=float, default=24.0, help='Lookback window in hours (default: 24).')
    parser.add_argument('--memory-dir', default='vera_memory', help='Memory directory root (default: vera_memory).')
    parser.add_argument('--json', action='store_true', help='Emit JSON only.')
    args = parser.parse_args()

    memory_dir = Path(args.memory_dir)
    since_utc = datetime.now(timezone.utc) - timedelta(hours=max(0.1, float(args.hours)))
    local_tz = _local_tzinfo()

    autonomy_rows = _load_jsonl(memory_dir / 'autonomy_cadence_events.jsonl')
    journal_rows = _load_jsonl(memory_dir / 'personality' / 'inner_journal.ndjson')

    active_cycles = _iter_active_cycles(autonomy_rows, since_utc)
    recent_journal = _iter_recent_journal(journal_rows, since_utc, naive_tz=local_tz)

    cycle_counts = {
        'trigger': Counter(r.get('trigger') for r in active_cycles),
        'reflection_reason': Counter(r.get('reflection_reason') for r in active_cycles),
        'reflection_outcome': Counter(r.get('reflection_outcome') for r in active_cycles),
        'workflow_reason': Counter(r.get('workflow_reason') for r in active_cycles),
    }
    journal_counts = {
        'intent': Counter(r.get('intent') for r in recent_journal),
        'trigger': Counter(r.get('trigger') for r in recent_journal),
    }

    report: Dict[str, Any] = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'window_hours': float(args.hours),
        'since_utc': since_utc.isoformat().replace('+00:00', 'Z'),
        'active_cycle_count': len(active_cycles),
        'journal_entry_count': len(recent_journal),
        'cycle_counts': {k: dict(v) for k, v in cycle_counts.items()},
        'journal_counts': {k: dict(v) for k, v in journal_counts.items()},
        'recent_active_cycles': active_cycles[-12:],
        'recent_journal_entries': recent_journal[-12:],
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"Active-window audit: last {args.hours:.1f}h")
    print(f"Since UTC: {report['since_utc']}")
    print(f"Active cycles: {report['active_cycle_count']}")
    print(f"Journal entries: {report['journal_entry_count']}")
    print('\nCycle counts:')
    for key, counts in report['cycle_counts'].items():
        print(f"- {key}: {counts}")
    print('\nJournal counts:')
    for key, counts in report['journal_counts'].items():
        print(f"- {key}: {counts}")
    print('\nRecent active cycles:')
    for row in report['recent_active_cycles']:
        print(json.dumps(row, ensure_ascii=True))
    print('\nRecent journal entries:')
    for row in report['recent_journal_entries']:
        print(json.dumps(row, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
