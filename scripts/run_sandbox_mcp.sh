#!/usr/bin/env bash
# Launcher for AIO Sandbox MCP server
# Starts the Docker container (if needed) then runs the MCP bridge on stdio
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX_PORT="${SANDBOX_PORT:-8090}"
SANDBOX_IMAGE="${SANDBOX_IMAGE:-ghcr.io/agent-infra/sandbox:latest}"
CONTAINER_NAME="vera-sandbox"
PYTHON_BIN="${VERA_MCP_PYTHON:-${ROOT_DIR}/.venv/bin/python}"
BRIDGE_SCRIPT="${ROOT_DIR}/mcp_server_and_tools/sandbox_mcp_bridge.py"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: Docker required for sandbox." >&2
  exit 1
fi

docker_exec() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
    return
  fi
  sudo -n docker "$@"
}

# Start container if not running
if ! docker_exec ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  docker_exec rm -f "${CONTAINER_NAME}" 2>/dev/null || true
  echo "Starting sandbox container on port ${SANDBOX_PORT}..." >&2
  docker_exec run -d \
    --name "${CONTAINER_NAME}" \
    --security-opt seccomp=unconfined \
    --restart unless-stopped \
    -p "${SANDBOX_PORT}:8080" \
    -e TZ=America/Chicago \
    -e DISPLAY_WIDTH=1280 \
    -e DISPLAY_HEIGHT=1024 \
    "${SANDBOX_IMAGE}" >/dev/null
else
  echo "Sandbox container already running." >&2
fi

# Wait for container to be ready (up to 30s)
for i in $(seq 1 30); do
  if curl -sf --connect-timeout 2 "http://127.0.0.1:${SANDBOX_PORT}/" >/dev/null 2>&1; then
    echo "Sandbox container ready." >&2
    break
  fi
  if [ "$i" = "30" ]; then
    echo "Warning: Sandbox container not responding after 30s, starting bridge anyway." >&2
  fi
  sleep 1
done

# Run the MCP bridge (stdio transport)
export SANDBOX_BASE_URL="http://127.0.0.1:${SANDBOX_PORT}"
exec "${PYTHON_BIN}" "${BRIDGE_SCRIPT}"
