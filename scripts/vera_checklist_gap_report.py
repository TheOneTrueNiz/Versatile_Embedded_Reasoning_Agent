#!/usr/bin/env python3
"""
Generate a structured gap report from VERA_PREFLIGHT_CHECKLIST.md.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


@dataclass
class Item:
    section: str
    subsection: str
    state: str
    text: str
    line: int


_ITEM_RE = re.compile(r"^\s*-\s*\[( |X|P|N/A)\]\s*(.+?)\s*$")


def parse(path: Path) -> List[Item]:
    section = ""
    subsection = ""
    items: List[Item] = []
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.rstrip("\n")
        if line.startswith("## "):
            section = line[3:].strip()
            subsection = ""
            continue
        if line.startswith("### "):
            subsection = line[4:].strip()
            continue
        match = _ITEM_RE.match(line)
        if not match:
            continue
        marker = match.group(1)
        state = "unchecked" if marker == " " else ("checked" if marker == "X" else ("partial" if marker == "P" else "na"))
        items.append(
            Item(
                section=section or "(none)",
                subsection=subsection or "(none)",
                state=state,
                text=match.group(2).strip(),
                line=idx,
            )
        )
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Build checklist unresolved-items report")
    parser.add_argument("--checklist", default="VERA_PREFLIGHT_CHECKLIST.md")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    checklist = Path(args.checklist).resolve()
    if not checklist.exists():
        raise SystemExit(f"Checklist not found: {checklist}")

    items = parse(checklist)
    totals = defaultdict(int)
    by_section: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unresolved: List[Dict[str, object]] = []

    for it in items:
        totals[it.state] += 1
        by_section[it.section][it.state] += 1
        if it.state in {"unchecked", "partial"}:
            unresolved.append(asdict(it))

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.output) if args.output else (checklist.parent / "tmp" / f"checklist_gaps_{ts}.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "timestamp_utc": ts,
        "checklist": str(checklist),
        "totals": dict(totals),
        "sections": {sec: dict(states) for sec, states in by_section.items()},
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
    }
    out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Report written to {out}")
    print(f"Totals: {dict(totals)}")
    print(f"Unresolved items: {len(unresolved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
