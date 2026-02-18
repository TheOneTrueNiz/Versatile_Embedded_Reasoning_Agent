#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${VERA_API_HOST:-127.0.0.1}"
PORT="${VERA_API_PORT:-8788}"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [ ! -x "${PYTHON_BIN}" ]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [ -z "${PYTHON_BIN}" ] || [ ! -x "${PYTHON_BIN}" ]; then
  echo "[FAIL] No usable Python interpreter found."
  exit 1
fi

cd "${ROOT_DIR}"

echo "[INFO] Running golden deploy gate..."
"${PYTHON_BIN}" scripts/vera_golden_deploy.py --host "${HOST}" --port "${PORT}" --with-chat-check

echo "[INFO] Running manual-item automation suite..."
if "${PYTHON_BIN}" scripts/vera_manual_items_automation.py --host "${HOST}" --port "${PORT}"; then
  echo "[PASS] Extended preflight completed."
  exit 0
fi

echo "[WARN] Golden gate passed but manual-item automation reported failures/skips requiring review."
exit 1

