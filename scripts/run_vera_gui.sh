#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="${ROOT_DIR}/ui/minimal-chat"

export VERA_MAX="${VERA_MAX:-1}"

if [ "${VERA_MAX}" = "1" ]; then
  export VERA_VOICE=1
  export VERA_BROWSER=1
  export VERA_DESKTOP=1
  export VERA_PDF=1
  export VERA_MCP_LOCAL=1
fi
if [ "${VERA_MEMVID_ENABLED:-0}" = "1" ] || [ "${VERA_MEMVID_ENABLED:-0}" = "true" ]; then
  echo "[VERA] Memvid fast recall is experimental in VERA 2.0 and disabled by default."
  echo "[VERA] Proceeding because VERA_MEMVID_ENABLED is set."
fi

VERA_NO_RUN=1 "${ROOT_DIR}/scripts/run_vera.sh"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [ -x "${ROOT_DIR}/.venv/bin/python" ]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
fi

if [ ! -d "${UI_DIR}" ]; then
  echo "UI directory not found: ${UI_DIR}"
  exit 1
fi

if [ ! -d "${UI_DIR}/node_modules" ] || [ "${VERA_FORCE_UI_INSTALL:-0}" = "1" ]; then
  (cd "${UI_DIR}" && npm install)
fi

if [ ! -d "${UI_DIR}/dist" ] || [ "${VERA_FORCE_UI_BUILD:-0}" = "1" ]; then
  (cd "${UI_DIR}" && npm run build)
fi

export VERA_UI_DIST="${UI_DIR}/dist"
"${PYTHON_BIN}" "${ROOT_DIR}/run_vera_api.py" --host "${VERA_API_HOST:-127.0.0.1}" --port "${VERA_API_PORT:-8000}" --logging
