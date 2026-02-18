#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMVID_SERVER="${ROOT_DIR}/mcp_server_and_tools/memvid/mcp_server.py"
PYTHON_CMD="${VERA_MCP_PYTHON:-$(command -v python3 || command -v python || true)}"

if [ -n "${MEMVID_CUDA_VISIBLE_DEVICES:-}" ]; then
  export CUDA_VISIBLE_DEVICES="${MEMVID_CUDA_VISIBLE_DEVICES}"
fi

export MEMVID_USE_GPU="${MEMVID_USE_GPU:-1}"

if [ -n "${MEMVID_ENV:-}" ]; then
  if command -v conda >/dev/null 2>&1; then
    exec conda run --no-capture-output -n "${MEMVID_ENV}" "${PYTHON_CMD}" "${MEMVID_SERVER}"
  elif command -v micromamba >/dev/null 2>&1; then
    exec micromamba run -n "${MEMVID_ENV}" "${PYTHON_CMD}" "${MEMVID_SERVER}"
  fi
fi

if [ -z "${PYTHON_CMD}" ]; then
  echo "Python interpreter not found (need python3 or python)." >&2
  exit 1
fi

exec "${PYTHON_CMD}" "${MEMVID_SERVER}"
