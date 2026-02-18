#!/usr/bin/env python3
"""
Export Flight Recorder transitions to Memvid JSON archive.
"""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from core.services.flight_recorder import FlightRecorder


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("vera_memory/flight_recorder/vera_blackbox.mv2.json"))
    parser.add_argument("--title", type=str, default="vera_flight_recorder")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    recorder = FlightRecorder(base_dir=Path("vera_memory/flight_recorder"), enabled=True)
    payload = recorder.export_memvid(
        output_path=args.output,
        title=args.title,
        limit=args.limit or None
    )
    print(f"Exported memvid archive to {args.output} (video_id={payload.get('video_id')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
