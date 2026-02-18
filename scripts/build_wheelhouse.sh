#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHEELHOUSE_DIR="${VERA_WHEELHOUSE_DIR:-${WHEELHOUSE_DIR:-${ROOT_DIR}/wheelhouse}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python interpreter not found: ${PYTHON_BIN}" >&2
  exit 1
fi

mkdir -p "${WHEELHOUSE_DIR}"

echo "[VERA] Building wheelhouse in ${WHEELHOUSE_DIR}"
DOWNLOAD_OK=1
if ! "${PYTHON_BIN}" -m pip download -r "${ROOT_DIR}/requirements.txt" -d "${WHEELHOUSE_DIR}"; then
  DOWNLOAD_OK=0
  echo "[VERA] Wheel download failed (likely offline). Will rely on local venv seed if available." >&2
fi

SEED_ARCHIVE="${WHEELHOUSE_DIR}/venv_seed.tar.gz"
if [ -d "${ROOT_DIR}/.venv" ]; then
  echo "[VERA] Refreshing local venv seed archive: ${SEED_ARCHIVE}"
  tar -czf "${SEED_ARCHIVE}" -C "${ROOT_DIR}" ".venv"
fi

WHEEL_COUNT="$(find "${WHEELHOUSE_DIR}" -maxdepth 1 -type f -name '*.whl' | wc -l | tr -d '[:space:]')"

if [ "${DOWNLOAD_OK}" -ne 1 ] && [ ! -f "${SEED_ARCHIVE}" ]; then
  echo "[VERA] Unable to build wheelhouse: no downloaded wheels and no local .venv seed archive." >&2
  exit 1
fi

STAMP_FILE="${WHEELHOUSE_DIR}/WHEELHOUSE_STAMP.txt"
"${PYTHON_BIN}" - <<'PY' "${ROOT_DIR}" "${WHEELHOUSE_DIR}" "${STAMP_FILE}" "${PYTHON_BIN}" "${DOWNLOAD_OK}" "${SEED_ARCHIVE}"
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
wheelhouse = Path(sys.argv[2])
stamp = Path(sys.argv[3])
python_bin = sys.argv[4]
download_ok = sys.argv[5] == "1"
seed_archive = Path(sys.argv[6])
requirements = root / "requirements.txt"

sha256 = hashlib.sha256(requirements.read_bytes()).hexdigest()
py_ver = subprocess.check_output([python_bin, "-c", "import sys; print(sys.version.replace('\\n', ' '))"], text=True).strip()
pip_ver = subprocess.check_output([python_bin, "-m", "pip", "--version"], text=True).strip()

stamp.write_text(
    "\n".join(
        [
            f"generated_utc={datetime.now(timezone.utc).isoformat()}",
            f"python_bin={python_bin}",
            f"python_version={py_ver}",
            f"pip_version={pip_ver}",
            f"requirements_file={requirements}",
            f"requirements_sha256={sha256}",
            f"wheel_count={len(list(wheelhouse.glob('*.whl')))}",
            f"download_ok={download_ok}",
            f"venv_seed_archive={seed_archive if seed_archive.exists() else ''}",
        ]
    )
    + "\n",
    encoding="utf-8",
)
PY

if [ "${DOWNLOAD_OK}" -ne 1 ]; then
  echo "[VERA] WARNING: No wheels downloaded (offline). Only venv_seed.tar.gz was produced." >&2
fi

if [ "${WHEEL_COUNT}" -gt 0 ]; then
  echo "[VERA] Wheelhouse ready with ${WHEEL_COUNT} wheel(s). Stamp: ${STAMP_FILE}"
elif [ -f "${SEED_ARCHIVE}" ]; then
  echo "[VERA] Wheelhouse has 0 wheel files; seed fallback available at ${SEED_ARCHIVE}."
  echo "[VERA] Build completed in seed-only mode. Stamp: ${STAMP_FILE}"
else
  echo "[VERA] Wheelhouse has 0 wheel files and no seed archive. Stamp: ${STAMP_FILE}" >&2
fi
