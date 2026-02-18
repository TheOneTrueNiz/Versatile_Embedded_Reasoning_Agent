#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${1:-http://127.0.0.1:8788}"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [ ! -x "${PYTHON_BIN}" ]; then
  PYTHON_BIN="python3"
fi

exec "${PYTHON_BIN}" "${ROOT_DIR}/scripts/vera_followthrough_executor.py" \
  --base-url "${BASE_URL}" \
  --vera-root "${ROOT_DIR}"

