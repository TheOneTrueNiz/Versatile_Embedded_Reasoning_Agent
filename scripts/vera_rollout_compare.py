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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare rollout modes for a single Vera work item.")
    parser.add_argument("--item-id", required=True, help="Work-jar item id to compare.")
    parser.add_argument("--mode", action="append", dest="modes", help="Replay mode to include. Repeat for multiple modes.")
    parser.add_argument("--policy", action="append", dest="policies", help="Optional rollout policy variant. Repeat for multiple policies.")
    parser.add_argument("--include-archived", action="store_true", help="Search archived work-jar items too.")
    parser.add_argument("--artifact", default="", help="Optional artifact override path.")
    parser.add_argument("--promote", action="store_true", help="Promote the preferred comparison policy into the rollout policy registry.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = RolloutService(default_paths(ROOT))
    artifact_override = Path(args.artifact) if args.artifact else None
    result = service.compare_work_item_rollout(
        item_id=args.item_id,
        modes=list(args.modes or []),
        include_archived=bool(args.include_archived),
        artifact_override=artifact_override,
        policies=list(args.policies or []),
        promote=bool(args.promote),
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
