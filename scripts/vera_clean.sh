#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Prefer rootless Docker socket when available to avoid sudo.
if [ -z "${DOCKER_HOST:-}" ]; then
  ROOTLESS_DOCKER_SOCK="/run/user/$(id -u)/docker.sock"
  if [ -S "${ROOTLESS_DOCKER_SOCK}" ]; then
    export DOCKER_HOST="unix://${ROOTLESS_DOCKER_SOCK}"
  fi
fi

docker_exec() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
    return
  fi
  sudo -n docker "$@"
}

docker_compose_exec() {
  if docker_exec compose version >/dev/null 2>&1; then
    docker_exec compose "$@"
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
      docker-compose "$@"
      return
    fi
    sudo -n docker-compose "$@"
    return
  fi
  return 1
}

if command -v docker >/dev/null 2>&1; then
  compose_file="${ROOT_DIR}/services/searxng/docker-compose.yml"
  if [ -f "${compose_file}" ]; then
    if ! docker_compose_exec -f "${compose_file}" down >/dev/null 2>&1; then
      echo "Note: unable to stop searxng via docker compose (permissions?)."
    fi
  fi
fi

if ! command -v pgrep >/dev/null 2>&1; then
  exit 0
fi

PATTERN="(@modelcontextprotocol/server-|mcp_server_and_tools/|grokipedia_mcp|wikipedia_mcp|grokipedia-mcp|wikipedia-mcp|run_google_workspace_mcp.sh|run_memvid_mcp.sh|searxng/mcp_server.py)"

pids="$(pgrep -u "$(id -u)" -f "${PATTERN}" || true)"
if [ -z "${pids}" ]; then
  exit 0
fi

kill ${pids} 2>/dev/null || true
sleep 2

still_running="$(pgrep -u "$(id -u)" -f "${PATTERN}" || true)"
if [ -n "${still_running}" ]; then
  kill -9 ${still_running} 2>/dev/null || true
fi
