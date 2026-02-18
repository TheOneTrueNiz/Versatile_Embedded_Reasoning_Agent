#!/usr/bin/env python3
"""
Apply JSON patch operations to the genome config with validation.
"""

import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from core.runtime.genome_config import (
    DEFAULT_GENOME_PATH,
    apply_genome_patch,
    load_genome_config,
    save_genome_config,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_GENOME_PATH)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config, validation = load_genome_config(args.config)
    if not validation.valid:
        print("Genome config invalid:")
        for err in validation.errors:
            print(f"- {err}")
        return 1

    patch_ops = json.loads(args.patch.read_text(encoding="utf-8"))
    if not isinstance(patch_ops, list):
        print("Patch must be a JSON array of operations.")
        return 1

    patched, patch_validation = apply_genome_patch(config, patch_ops)
    if not patch_validation.valid:
        print("Patched config invalid:")
        for err in patch_validation.errors:
            print(f"- {err}")
        return 1

    if args.dry_run:
        print("Patch valid (dry-run). No changes written.")
        return 0

    output_path = args.output or args.config
    save_genome_config(output_path, patched, backup=True)
    print(f"Patched genome saved to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
