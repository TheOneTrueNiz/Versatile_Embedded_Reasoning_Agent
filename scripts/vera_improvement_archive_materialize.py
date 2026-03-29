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

from observability.improvement_archive import (  # noqa: E402
    materialize_improvement_archive,
    suggest_improvement_entries,
)


DEFAULT_WORK_JAR = ROOT / "vera_memory" / "autonomy_work_jar.json"
DEFAULT_ARCHIVE = ROOT / "vera_memory" / "improvement_archive.json"


def cmd_materialize(args: argparse.Namespace) -> int:
    result = materialize_improvement_archive(
        work_jar_path=Path(args.work_jar),
        archive_path=Path(args.archive),
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    result = suggest_improvement_entries(
        archive_path=Path(args.archive),
        problem_signature=str(args.problem_signature or ""),
        failure_class=str(args.failure_class or ""),
        limit=int(args.limit),
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize and query Vera's bounded improvement archive.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_materialize = sub.add_parser("materialize", help="Generate vera_memory/improvement_archive.json from archived work-jar items.")
    p_materialize.add_argument("--work-jar", default=str(DEFAULT_WORK_JAR))
    p_materialize.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    p_materialize.set_defaults(func=cmd_materialize)

    p_suggest = sub.add_parser("suggest", help="Suggest prior successful interventions by signature or failure class.")
    p_suggest.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    p_suggest.add_argument("--problem-signature", default="")
    p_suggest.add_argument("--failure-class", default="")
    p_suggest.add_argument("--limit", type=int, default=3)
    p_suggest.set_defaults(func=cmd_suggest)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
