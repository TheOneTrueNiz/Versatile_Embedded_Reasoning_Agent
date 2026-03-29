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
    parser = argparse.ArgumentParser(description="Inspect or promote Vera rollout policy registry entries.")
    parser.add_argument("--comparison", default="", help="Optional comparison artifact path to promote into the registry.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = RolloutService(default_paths(ROOT))
    if str(args.comparison or "").strip():
        payload = json.loads(Path(args.comparison).read_text(encoding="utf-8"))
        result = service.promote_comparison_result(payload)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0 if result.get("ok") else 1
    print(json.dumps(service.load_policy_registry(), indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
