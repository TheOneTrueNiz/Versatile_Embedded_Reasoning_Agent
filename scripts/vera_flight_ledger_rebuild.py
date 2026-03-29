#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.services.flight_recorder import _canonical_json, _compute_ledger_hash_self, _sha256_hex


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Vera flight ledger from transitions.ndjson")
    parser.add_argument("--transitions", default=str(ROOT / "vera_memory" / "flight_recorder" / "transitions.ndjson"))
    parser.add_argument("--ledger", default=str(ROOT / "vera_memory" / "flight_recorder" / "ledger.jsonl"))
    args = parser.parse_args()

    transitions_path = Path(args.transitions)
    ledger_path = Path(args.ledger)
    if not transitions_path.exists():
        raise SystemExit(f"missing transitions file: {transitions_path}")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    backup_path = None
    if ledger_path.exists():
        backup_path = ledger_path.with_suffix(ledger_path.suffix + f".bak.{datetime.now().strftime('%Y%m%dT%H%M%SZ')}")
        shutil.copy2(ledger_path, backup_path)

    rows = []
    genesis = {
        "ledger_version": 1,
        "timestamp_utc": utc_iso(),
        "record_type": "GENESIS",
        "event_uuid": "",
        "source_file": "",
        "source_kind": "flight_recorder",
        "hash_prev": "0" * 64,
        "hash_self": "",
        "payload_sha256": "",
        "summary": "flight ledger genesis",
        "meta": {},
    }
    genesis["hash_self"] = _compute_ledger_hash_self(genesis)
    rows.append(genesis)
    last_hash = genesis["hash_self"]

    for payload in iter_jsonl(transitions_path):
        action = payload.get("action") or {}
        meta = payload.get("meta") or {}
        result = payload.get("result") or {}
        record_type = str(payload.get("type") or "transition")
        summary = record_type
        if isinstance(action, dict):
            action_type = str(action.get("type") or "")
            tool_name = str(action.get("tool_name") or "")
            model = str(action.get("model") or "")
            if tool_name:
                summary = f"{record_type}:{action_type}:{tool_name}"
            elif model:
                summary = f"{record_type}:{action_type}:{model}"
            elif action_type:
                summary = f"{record_type}:{action_type}"
        if isinstance(result, dict) and "success" in result and summary == record_type:
            summary = f"{record_type}:success={bool(result.get('success'))}"
        compact_meta = {
            "action_type": str(action.get("type") or "") if isinstance(action, dict) else "",
            "tool_name": str(action.get("tool_name") or "") if isinstance(action, dict) else "",
            "model": str(action.get("model") or "") if isinstance(action, dict) else "",
            "success": bool(meta.get("success")) if "success" in meta else None,
            "air_score": payload.get("air_score"),
            "air_reason": str(payload.get("air_reason") or ""),
            "latency_ms": meta.get("latency_ms") if isinstance(meta, dict) else None,
        }
        compact_meta = {k: v for k, v in compact_meta.items() if v not in ("", None)}
        record = {
            "ledger_version": 1,
            "timestamp_utc": utc_iso(),
            "record_type": record_type,
            "event_uuid": str(payload.get("uuid") or ""),
            "source_file": str(transitions_path),
            "source_kind": "flight_recorder",
            "hash_prev": last_hash,
            "hash_self": "",
            "payload_sha256": _sha256_hex(_canonical_json(payload)),
            "summary": summary[:160],
            "meta": compact_meta,
        }
        record["hash_self"] = _compute_ledger_hash_self(record)
        rows.append(record)
        last_hash = record["hash_self"]

    with ledger_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_canonical_json(row) + "\n")

    print(json.dumps({
        "ok": True,
        "ledger_path": str(ledger_path),
        "backup_path": str(backup_path) if backup_path else "",
        "records": len(rows),
        "rebuilt_at_utc": utc_iso(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
