#!/usr/bin/env python3
"""
Specialist Bundle Exporter
==========================

Packages a genome config plus a Memvid slice into a shareable zip.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zipfile import ZipFile, ZIP_DEFLATED

from core.runtime.genome_config import DEFAULT_GENOME_PATH


def export_specialist_bundle(
    *,
    vera: Any,
    output_dir: Path,
    genome_path: Path = DEFAULT_GENOME_PATH,
    memvid_limit: Optional[int] = None,
) -> Dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_root = output_dir / f"bundle_{timestamp}"
    bundle_root.mkdir(parents=True, exist_ok=True)

    genome_path = Path(genome_path)
    if not genome_path.exists():
        raise FileNotFoundError(f"Genome config not found: {genome_path}")

    genome_dest = bundle_root / "genome.json"
    shutil.copy2(genome_path, genome_dest)

    memvid_path = bundle_root / "flight_recorder_memvid.json"
    if vera and getattr(vera, "flight_recorder", None):
        vera.flight_recorder.export_memvid(output_path=memvid_path, limit=memvid_limit)
    else:
        raise RuntimeError("Flight recorder unavailable for memvid export.")

    manifest = {
        "created_at": datetime.now().isoformat(),
        "genome_config": genome_dest.name,
        "memvid_archive": memvid_path.name,
        "memvid_limit": memvid_limit,
    }
    manifest_path = bundle_root / "bundle_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    zip_path = output_dir / f"vera_specialist_{timestamp}.zip"
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for file_path in (genome_dest, memvid_path, manifest_path):
            archive.write(file_path, arcname=file_path.name)

    return {
        "zip_path": str(zip_path),
        "bundle_dir": str(bundle_root),
        "manifest": manifest,
    }
