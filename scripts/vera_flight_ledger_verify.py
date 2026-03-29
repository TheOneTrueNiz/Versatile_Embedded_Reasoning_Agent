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

from core.services.flight_recorder import verify_flight_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Vera's hash-chained flight ledger.")
    parser.add_argument(
        "--ledger",
        default=str(ROOT / "vera_memory" / "flight_recorder" / "ledger.jsonl"),
        help="Path to ledger.jsonl",
    )
    parser.add_argument(
        "--cross-check-source",
        action="store_true",
        help="Also verify payload_sha256 against matching source events in transitions.ndjson.",
    )
    parser.add_argument("--max-errors", type=int, default=10)
    args = parser.parse_args()

    result = verify_flight_ledger(
        Path(args.ledger),
        cross_check_source=bool(args.cross_check_source),
        max_errors=max(1, int(args.max_errors)),
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return int(result.get("exit_code", 30))


if __name__ == "__main__":
    raise SystemExit(main())
