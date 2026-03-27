#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_SCRIPT="${ROOT_DIR}/mcp_server_and_tools/google_workspace_mcp/main.py"
PYTHON_CMD="$(command -v python3 || command -v python || true)"

CREDS_ROOT="${CREDS_DIR:-${VERA_CREDS_DIR:-${XDG_CONFIG_HOME:-${HOME}/.config}/vera/creds}}"
CRED_DIR="${GOOGLE_WORKSPACE_CRED_DIR:-${CREDS_ROOT}/google}"
CLIENT_SECRET_PATH="${GOOGLE_CLIENT_SECRET_PATH:-}"
DEFAULT_CREDS_DIR="${CRED_DIR}/credentials"

export GOOGLE_MCP_CREDENTIALS_DIR="${GOOGLE_MCP_CREDENTIALS_DIR:-${DEFAULT_CREDS_DIR}}"
# Use a fixed OAuth callback on port 8080 to match the Workspace MCP defaults
export WORKSPACE_MCP_PORT="${WORKSPACE_MCP_PORT:-8080}"
export PORT="${PORT:-${WORKSPACE_MCP_PORT}}"
export GOOGLE_OAUTH_REDIRECT_URI="${GOOGLE_OAUTH_REDIRECT_URI:-http://localhost:${WORKSPACE_MCP_PORT}/oauth2callback}"
# Some server variants look for REDIRECT_URL explicitly
export REDIRECT_URL="${REDIRECT_URL:-${GOOGLE_OAUTH_REDIRECT_URI}}"
mkdir -p "${GOOGLE_MCP_CREDENTIALS_DIR}"

if [ -z "${CLIENT_SECRET_PATH}" ]; then
  GENERATED_SECRET_PATH="${CRED_DIR}/client_secret_generated.json"
  if [ -f "${GENERATED_SECRET_PATH}" ]; then
    CLIENT_SECRET_PATH="${GENERATED_SECRET_PATH}"
  else
    CLIENT_SECRET_PATH="$(ls "${CRED_DIR}"/*.json 2>/dev/null | head -n 1 || true)"
  fi
fi

if [ -n "${CLIENT_SECRET_PATH}" ] && [ -f "${CLIENT_SECRET_PATH}" ]; then
  export GOOGLE_CLIENT_SECRET_PATH="${CLIENT_SECRET_PATH}"

  if [ -z "${PYTHON_CMD}" ]; then
    echo "Python interpreter not found (need python3 or python)." >&2
    exit 1
  fi

  readarray -t _oauth_values < <("${PYTHON_CMD}" - <<'PY' "${CLIENT_SECRET_PATH}"
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
block = data.get("installed") or data.get("web") or {}
client_id = block.get("client_id", "")
client_secret = block.get("client_secret", "")
redirects = block.get("redirect_uris") or []
redirect_uri = redirects[0] if redirects else ""
print(client_id)
print(client_secret)
print(redirect_uri)
PY
)

  if [ -n "${_oauth_values[0]:-}" ]; then
    export GOOGLE_OAUTH_CLIENT_ID="${_oauth_values[0]}"
  fi
  if [ -n "${_oauth_values[1]:-}" ]; then
    export GOOGLE_OAUTH_CLIENT_SECRET="${_oauth_values[1]}"
  fi
  if [ -n "${_oauth_values[2]:-}" ] && [ -z "${GOOGLE_OAUTH_REDIRECT_URI:-}" ]; then
    export GOOGLE_OAUTH_REDIRECT_URI="${_oauth_values[2]}"
  fi
fi

export OAUTHLIB_INSECURE_TRANSPORT="${OAUTHLIB_INSECURE_TRANSPORT:-1}"
export REDIRECT_URL="${REDIRECT_URL:-${GOOGLE_OAUTH_REDIRECT_URI}}"

TOOL_TIER="${GOOGLE_WORKSPACE_TOOL_TIER:-complete}"
PYTHON_BIN="${VERA_MCP_PYTHON:-${ROOT_DIR}/.venv/bin/python}"

exec "${PYTHON_BIN}" "${SERVER_SCRIPT}" --transport stdio --tool-tier "${TOOL_TIER}" --single-user
