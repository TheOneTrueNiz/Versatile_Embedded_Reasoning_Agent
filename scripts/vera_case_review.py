#!/usr/bin/env python3
"""
Review and approve hard cases for self-improvement.
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict, Any


DEFAULT_HARD_CASES = Path("vera_memory/flight_recorder/hard_cases.jsonl")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def _write_jsonl(path: Path, items: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")


def list_cases(path: Path) -> None:
    items = _read_jsonl(path)
    if not items:
        print("No hard cases found.")
        return
    for idx, item in enumerate(items):
        status = "approved" if item.get("approved") else "pending"
        prompt = (item.get("prompt") or "").strip()
        preview = prompt if len(prompt) <= 120 else prompt[:117] + "..."
        print(f"[{idx}] {status} - {preview}")


def approve_cases(path: Path, indices: List[int]) -> None:
    items = _read_jsonl(path)
    if not items:
        print("No hard cases found.")
        return
    if indices:
        for idx in indices:
            if idx < 0 or idx >= len(items):
                print(f"Index out of range: {idx}")
                continue
            items[idx]["approved"] = True
    else:
        for item in items:
            item["approved"] = True
    _write_jsonl(path, items)
    print("Hard cases updated.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=DEFAULT_HARD_CASES)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--approve-all", action="store_true")
    parser.add_argument("--approve", type=int, nargs="*", default=[])
    args = parser.parse_args()

    if args.list:
        list_cases(args.path)
        return 0

    if args.approve_all or args.approve:
        approve_cases(args.path, args.approve if not args.approve_all else [])
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
