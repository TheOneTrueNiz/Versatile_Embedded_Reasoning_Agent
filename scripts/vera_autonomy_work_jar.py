#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

JAR_PATH = ROOT / "vera_memory" / "autonomy_work_jar.json"

try:
    from observability.improvement_archive import build_archive_seed_payload
except Exception:
    build_archive_seed_payload = None


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_state() -> Dict[str, Any]:
    if not JAR_PATH.exists():
        return {"version": 1, "items": [], "archived_items": [], "updated_at_utc": utc_iso()}
    try:
        data = json.loads(JAR_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("items"), list):
        data["items"] = []
    if not isinstance(data.get("archived_items"), list):
        data["archived_items"] = []
    data.setdefault("version", 1)
    data.setdefault("updated_at_utc", utc_iso())
    return data


def save_state(state: Dict[str, Any]) -> None:
    state["updated_at_utc"] = utc_iso()
    JAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    JAR_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def cmd_list(args: argparse.Namespace) -> int:
    state = load_state()
    payload = {"items": state.get("items") or []}
    if bool(getattr(args, "include_archived", False)):
        payload["archived_items"] = state.get("archived_items") or []
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    state = load_state()
    item_id = str(args.id or f"awj_{uuid.uuid4().hex[:12]}")
    required_markers = [part.strip() for part in (args.required_marker or []) if part.strip()]
    context = str(args.context or "").strip()
    metadata: Dict[str, Any] = {}
    archive_path = Path(str(args.archive or ROOT / "vera_memory" / "improvement_archive.json"))
    problem_signature = str(args.problem_signature or "").strip()
    failure_class = str(args.failure_class or "").strip()
    suggest_limit = max(0, int(args.suggest_limit or 3))
    if build_archive_seed_payload and (problem_signature or failure_class) and archive_path.exists():
        seed_payload = build_archive_seed_payload(
            archive_path=archive_path,
            problem_signature=problem_signature,
            failure_class=failure_class,
            limit=suggest_limit,
        )
        if int(seed_payload.get("match_count") or 0) > 0:
            block = str(seed_payload.get("context_block") or "").strip()
            if block:
                context = f"{context}\n\n{block}".strip() if context else block
            metadata["archive_query"] = dict(seed_payload.get("query") or {})
            metadata["archive_suggestions"] = list(seed_payload.get("matches") or [])
    entry = {
        "id": item_id,
        "title": str(args.title or "").strip(),
        "objective": str(args.objective or "").strip(),
        "context": context,
        "source": str(args.source or "manual").strip(),
        "priority": str(args.priority or "normal").strip().lower(),
        "tool_choice": str(args.tool_choice or "").strip().lower() or None,
        "status": "pending",
        "next_eligible_utc": str(args.next_eligible_utc or "").strip(),
        "retry_count": 0,
        "created_at_utc": utc_iso(),
        "updated_at_utc": utc_iso(),
        "last_attempt_utc": "",
        "completion_contract": {
            "kind": str(args.contract_kind or "task_completed").strip(),
            "match_mode": str(args.match_mode or "any").strip(),
            "required_markers": required_markers,
        },
        "metadata": metadata,
    }
    state.setdefault("items", []).append(entry)
    save_state(state)
    print(json.dumps(entry, indent=2, ensure_ascii=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and seed Vera autonomy work jar items.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List current work-jar items.")
    p_list.add_argument("--include-archived", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="Add a pending work-jar item.")
    p_add.add_argument("--id", default="")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--objective", required=True)
    p_add.add_argument("--context", default="")
    p_add.add_argument("--source", default="manual")
    p_add.add_argument("--priority", default="normal")
    p_add.add_argument("--tool-choice", default="")
    p_add.add_argument("--archive", default=str(ROOT / "vera_memory" / "improvement_archive.json"))
    p_add.add_argument("--problem-signature", default="")
    p_add.add_argument("--failure-class", default="")
    p_add.add_argument("--suggest-limit", type=int, default=3)
    p_add.add_argument("--next-eligible-utc", default="")
    p_add.add_argument("--contract-kind", default="task_completed")
    p_add.add_argument("--match-mode", default="any")
    p_add.add_argument("--required-marker", action="append", default=[])
    p_add.set_defaults(func=cmd_add)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
