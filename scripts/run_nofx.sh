#!/usr/bin/env bash
# Launcher for NOFX trading OS (Docker)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NOFX_DIR="${ROOT_DIR}/mcp_server_and_tools/nofx"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: Docker required for NOFX. Install docker first." >&2
  exit 1
fi

cd "${NOFX_DIR}"

if [ -f docker-compose.prod.yml ]; then
  exec docker compose -f docker-compose.prod.yml up -d
elif [ -f docker-compose.yml ]; then
  exec docker compose up -d
else
  echo "Error: No docker-compose file found in ${NOFX_DIR}" >&2
  exit 1
fi
