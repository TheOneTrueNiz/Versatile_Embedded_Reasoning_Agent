#!/usr/bin/env bash
# Launcher for AIO Sandbox Docker container
# Provides isolated shell, browser, file, MCP, Jupyter, VSCode in a container
set -euo pipefail

SANDBOX_PORT="${SANDBOX_PORT:-8090}"
SANDBOX_IMAGE="${SANDBOX_IMAGE:-ghcr.io/agent-infra/sandbox:latest}"
CONTAINER_NAME="vera-sandbox"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: Docker required for sandbox. Install docker first." >&2
  exit 1
fi

docker_exec() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
    return
  fi
  sudo -n docker "$@"
}

# Check if already running
if docker_exec ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Sandbox already running on port ${SANDBOX_PORT}" >&2
  exit 0
fi

# Remove stale container if exists
docker_exec rm -f "${CONTAINER_NAME}" 2>/dev/null || true

echo "Starting AIO Sandbox on port ${SANDBOX_PORT}..." >&2
exec docker_exec run \
  --name "${CONTAINER_NAME}" \
  --security-opt seccomp=unconfined \
  --rm \
  -p "${SANDBOX_PORT}:8080" \
  -e TZ=America/Chicago \
  -e DISPLAY_WIDTH=1280 \
  -e DISPLAY_HEIGHT=1024 \
  "${SANDBOX_IMAGE}"
