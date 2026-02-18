#!/usr/bin/env bash
# Launcher for MARM memory MCP server (stdio mode)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="${ROOT_DIR}/mcp_server_and_tools/MARM-Systems/marm-mcp-server"
VENV_DIR="${SERVER_DIR}/.venv"
ROOT_VENV_PY="${ROOT_DIR}/.venv/bin/python"

resolve_python() {
  local candidates=(
    "${VIRTUAL_ENV:-}/bin/python"
    "${ROOT_DIR}/.venv/bin/python"
    "$(command -v python3 2>/dev/null || true)"
    "$(command -v python 2>/dev/null || true)"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    [ -n "${candidate}" ] || continue
    [ -x "${candidate}" ] || continue
    echo "${candidate}"
    return 0
  done
  echo "No usable Python interpreter found for MARM MCP server." >&2
  return 1
}

venv_healthy() {
  [ -x "${VENV_DIR}/bin/python" ] || return 1
  [ -x "${VENV_DIR}/bin/pip" ] || return 1
  "${VENV_DIR}/bin/python" -c "import fastmcp" >/dev/null 2>&1
}

create_venv() {
  local py_cmd
  py_cmd="$(resolve_python)"
  rm -rf "${VENV_DIR}" 2>/dev/null || true
  if "${py_cmd}" -m venv "${VENV_DIR}" >/dev/null 2>&1 && [ -x "${VENV_DIR}/bin/pip" ]; then
    return
  fi
  if "${py_cmd}" -m pip --version >/dev/null 2>&1; then
    "${py_cmd}" -m pip install --quiet virtualenv >/dev/null 2>&1 || true
    if "${py_cmd}" -m virtualenv "${VENV_DIR}" >/dev/null 2>&1; then
      return
    fi
  fi
  if command -v virtualenv >/dev/null 2>&1; then
    virtualenv "${VENV_DIR}" >/dev/null 2>&1
    return
  fi
  echo "Unable to create Python virtualenv for MARM MCP server." >&2
  return 1
}

if [ -x "${ROOT_VENV_PY}" ] && "${ROOT_VENV_PY}" -c "import fastmcp, pydantic, sentence_transformers, torch, psutil" >/dev/null 2>&1; then
  cd "${SERVER_DIR}"
  exec "${ROOT_VENV_PY}" server_stdio.py
fi

if ! venv_healthy; then
  echo "Bootstrapping MARM MCP server environment..." >&2
  create_venv
  "${VENV_DIR}/bin/pip" install --quiet -r "${SERVER_DIR}/requirements_stdio.txt" 2>/dev/null || \
    "${VENV_DIR}/bin/pip" install --quiet -r "${SERVER_DIR}/requirements.txt"
fi

cd "${SERVER_DIR}"
exec "${VENV_DIR}/bin/python" server_stdio.py
