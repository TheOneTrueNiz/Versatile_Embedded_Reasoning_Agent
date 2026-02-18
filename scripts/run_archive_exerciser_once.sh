#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"

if [ ! -x "${PYTHON_BIN}" ]; then
  PYTHON_BIN="python3"
fi

OUT_DIR="${1:-${ROOT_DIR}/tmp/archive_exerciser}"
mkdir -p "${OUT_DIR}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_PATH="${OUT_DIR}/archive_retrieval_probe_${TS}.json"

echo "[archive-exerciser] writing ${OUT_PATH}"
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/vera_archive_retrieval_probe.py" --output "${OUT_PATH}"

echo "[archive-exerciser] done"
