#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from observability.rollout_service import RolloutService, default_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a cross-subsystem rollout scorecard from comparison artifacts.")
    parser.add_argument(
        "--comparison",
        action="append",
        dest="comparisons",
        help="Explicit comparison artifact path. Repeat for multiple artifacts.",
    )
    parser.add_argument(
        "--glob",
        dest="glob_pattern",
        default="tmp/audits/rollout_service_compare_*live*.json",
        help="Glob pattern used when --comparison is omitted.",
    )
    parser.add_argument("--promote", action="store_true", help="Promote preferred subsystem policies into the rollout policy registry.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = [Path(p) for p in list(args.comparisons or [])]
    if not paths:
        paths = [Path(p) for p in sorted(glob.glob(str(args.glob_pattern or "").strip()))]
    service = RolloutService(default_paths(ROOT))
    result = service.build_cross_subsystem_scorecard(
        comparison_paths=paths,
        promote=bool(args.promote),
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
