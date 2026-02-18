#!/usr/bin/env bash
set -euo pipefail

if [ -z "${MCP_HUB_COMMAND:-}" ]; then
  echo "MCP_HUB_COMMAND is required to start the hub MCP server." >&2
  exit 1
fi

if [ -n "${MCP_HUB_ARGS:-}" ]; then
  read -r -a hub_args <<< "$MCP_HUB_ARGS"
  exec "$MCP_HUB_COMMAND" "${hub_args[@]}"
else
  exec "$MCP_HUB_COMMAND"
fi
