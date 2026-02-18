#!/usr/bin/env bash
set -euo pipefail

if [ -z "${OBSIDIAN_VAULT_PATH:-}" ]; then
  echo "OBSIDIAN_VAULT_PATH is required to start the Obsidian MCP server." >&2
  exit 1
fi

exec npx -y @modelcontextprotocol/server-filesystem "$OBSIDIAN_VAULT_PATH"
