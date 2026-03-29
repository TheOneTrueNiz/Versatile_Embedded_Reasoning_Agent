#!/usr/bin/env python3
"""
VERA Red-Team + Regression Harness
==================================

Reads flight recorder transitions to generate hard cases and
build a regression set from successful prompts.
"""

import argparse
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from core.services.red_team_harness import (
    DEFAULT_HARD_CASES,
    DEFAULT_REGRESSION,
    DEFAULT_TRANSITIONS,
    run_red_team,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transitions", type=Path, default=DEFAULT_TRANSITIONS)
    parser.add_argument("--hard-output", type=Path, default=DEFAULT_HARD_CASES)
    parser.add_argument("--regression-output", type=Path, default=DEFAULT_REGRESSION)
    parser.add_argument("--failure-limit", type=int, default=10)
    parser.add_argument("--hard-count", type=int, default=10)
    parser.add_argument("--regression-count", type=int, default=20)
    parser.add_argument("--model", type=str, default=os.getenv("XAI_MODEL", "grok-4.20-experimental-beta-0304-reasoning"))
    parser.add_argument("--base-url", type=str, default=os.getenv("XAI_API_BASE", "https://api.x.ai/v1"))
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    result = run_red_team(
        transitions_path=args.transitions,
        hard_output=args.hard_output,
        regression_output=args.regression_output,
        failure_limit=args.failure_limit,
        hard_count=args.hard_count,
        regression_count=args.regression_count,
        use_llm=not args.no_llm,
        base_url=args.base_url,
        model=args.model,
    )

    print(f"Wrote {result['hard_cases']} hard cases to {args.hard_output}")
    print(f"Wrote {result['regression_cases']} regression prompts to {args.regression_output}")
    if result.get("budget_note"):
        print(f"Budget note: {result['budget_note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
