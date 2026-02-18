#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERA_API_PORT="${VERA_API_PORT:-8788}"

FORCE=0
NO_SEARXNG=0

usage() {
  cat <<'EOF'
Usage: ./scripts/cleanup_vera.sh [--force] [--no-searxng]

Stops lingering VERA processes and (optionally) the SearxNG container.

  --force       Skip confirmation prompts
  --no-searxng  Do not stop the SearxNG docker compose stack
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --force)
      FORCE=1
      ;;
    --no-searxng)
      NO_SEARXNG=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown flag: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

confirm() {
  local prompt="$1"
  if [ "${FORCE}" = "1" ]; then
    return 0
  fi
  read -r -p "${prompt} [y/N] " reply
  [[ "${reply}" =~ ^[Yy]$ ]]
}

# Prefer rootless Docker socket when available to avoid sudo.
if [ -z "${DOCKER_HOST:-}" ]; then
  ROOTLESS_DOCKER_SOCK="/run/user/$(id -u)/docker.sock"
  if [ -S "${ROOTLESS_DOCKER_SOCK}" ]; then
    export DOCKER_HOST="unix://${ROOTLESS_DOCKER_SOCK}"
  fi
fi

docker_available() {
  command -v docker >/dev/null 2>&1 || return 1
  if docker info >/dev/null 2>&1; then
    return 0
  fi
  sudo -n docker info >/dev/null 2>&1
}

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

declare -A PIDS=()

add_pid() {
  local pid="$1"
  if [[ "${pid}" =~ ^[0-9]+$ ]]; then
    PIDS["${pid}"]=1
  fi
}

if command -v lsof >/dev/null 2>&1; then
  while read -r pid; do
    add_pid "${pid}"
  done < <(lsof -t -iTCP:"${VERA_API_PORT}" -sTCP:LISTEN -P -n 2>/dev/null || true)
elif command -v ss >/dev/null 2>&1; then
  while read -r pid; do
    add_pid "${pid}"
  done < <(ss -lptn "sport = :${VERA_API_PORT}" 2>/dev/null | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | sort -u)
fi

patterns=(
  "run_vera_api.py"
  "run_vera.py"
  "vera_tray.py"
  "mcp_server_and_tools"
  "modelcontextprotocol"
  "server-"
  "grokipedia"
  "wikipedia-mcp"
  "memvid"
)

for pattern in "${patterns[@]}"; do
  while read -r pid cmd; do
    if [[ "${cmd}" == *"${ROOT_DIR}"* ]]; then
      add_pid "${pid}"
    fi
  done < <(pgrep -af "${pattern}" 2>/dev/null || true)
done

if [ "${#PIDS[@]}" -eq 0 ]; then
  echo "No lingering VERA processes detected."
else
  echo "Found lingering VERA processes:"
  ps -fp "$(printf '%s,' "${!PIDS[@]}" | sed 's/,$//')" || true
  if confirm "Stop these processes?"; then
    for pid in "${!PIDS[@]}"; do
      kill "${pid}" 2>/dev/null || true
    done
    sleep 1
    for pid in "${!PIDS[@]}"; do
      if kill -0 "${pid}" 2>/dev/null; then
        echo "PID ${pid} is still running. Stop it manually if needed."
      fi
    done
  fi
fi

if [ "${NO_SEARXNG}" = "0" ] && docker_available; then
  # Check for docker-compose managed SearxNG
  if docker_compose_exec -f "${ROOT_DIR}/services/searxng/docker-compose.yml" ps -q 2>/dev/null | grep -q .; then
    if confirm "Stop SearxNG docker compose stack?"; then
      docker_compose_exec -f "${ROOT_DIR}/services/searxng/docker-compose.yml" down 2>/dev/null || true
    fi
  fi
  # Also check for standalone SearxNG container (e.g., started with docker run)
  STANDALONE_SEARXNG="$(docker_exec ps -q --filter "name=searxng" 2>/dev/null || true)"
  if [ -n "${STANDALONE_SEARXNG}" ]; then
    if confirm "Stop standalone SearxNG container?"; then
      docker_exec stop searxng 2>/dev/null || true
      docker_exec rm searxng 2>/dev/null || true
    fi
  fi
fi
