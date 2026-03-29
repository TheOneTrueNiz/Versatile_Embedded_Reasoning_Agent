#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from observability.rollout_service import RolloutService, default_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded Vera rollout replay for one explicit work-jar item.")
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--artifact", default="")
    parser.add_argument("--mode", choices=["auto", "artifact", "executor", "registry"], default="auto")
    parser.add_argument("--policy", default="", help="Optional explicit rollout policy override.")
    args = parser.parse_args()

    service = RolloutService(default_paths(ROOT))
    result = service.run_work_item_rollout(
        item_id=str(args.item_id),
        include_archived=bool(args.include_archived),
        artifact_override=Path(args.artifact) if str(args.artifact).strip() else None,
        mode=str(args.mode or "auto"),
        policy_override=str(args.policy or "").strip() or None,
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
