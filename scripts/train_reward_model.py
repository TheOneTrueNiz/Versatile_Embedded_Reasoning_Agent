#!/usr/bin/env python3
"""
Train the lightweight reward model from flight recorder transitions.
"""

import argparse
from pathlib import Path

import sys

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from learning.reward_model import (
    DEFAULT_MODEL_PATH,
    DEFAULT_TRANSITIONS,
    train_reward_model,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transitions", type=Path, default=DEFAULT_TRANSITIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--lr", type=float, default=0.08)
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument("--min-samples", type=int, default=20)
    args = parser.parse_args()

    result = train_reward_model(
        transitions_path=args.transitions,
        output_path=args.output,
        epochs=args.epochs,
        lr=args.lr,
        l2=args.l2,
        min_examples=args.min_samples,
    )
    if not result.get("trained"):
        print(f"Reward model not trained: {result.get('reason')} (samples={result.get('samples')})")
        return 1
    print(f"Reward model saved to {result.get('output_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
