#!/usr/bin/env bash
# Launcher for MCP memory server with deterministic local install.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/services/memory_mcp"
BIN_PATH="${RUNTIME_DIR}/node_modules/.bin/mcp-server-memory"
PACKAGE_JSON="${RUNTIME_DIR}/package.json"

if ! command -v npm >/dev/null 2>&1; then
  echo "Error: npm is required for memory MCP server." >&2
  exit 1
fi

mkdir -p "${RUNTIME_DIR}"

if [ ! -x "${BIN_PATH}" ]; then
  if [ ! -f "${PACKAGE_JSON}" ]; then
    cat > "${PACKAGE_JSON}" <<'EOF'
{
  "name": "vera-memory-mcp-runtime",
  "private": true,
  "version": "1.0.0"
}
EOF
  fi

  (
    cd "${RUNTIME_DIR}"
    npm install --silent --no-audit --no-fund @modelcontextprotocol/server-memory
  )
fi

exec "${BIN_PATH}"
