#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERA_API_PORT="${VERA_API_PORT:-8788}"
CALLME_SERVER_DIR="${ROOT_DIR}/mcp_server_and_tools/call-me/server"

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
declare -A SKIP_PIDS=()

add_pid() {
  local pid="$1"
  if [[ "${pid}" =~ ^[0-9]+$ ]]; then
    PIDS["${pid}"]=1
  fi
}

add_skip_pid() {
  local pid="$1"
  if [[ "${pid}" =~ ^[0-9]+$ ]]; then
    SKIP_PIDS["${pid}"]=1
  fi
}

collect_ancestor_pids() {
  local pid="$1"
  local next=""
  while [[ "${pid}" =~ ^[0-9]+$ ]] && [ "${pid}" -gt 1 ]; do
    if [ -n "${SKIP_PIDS["${pid}"]+x}" ]; then
      break
    fi
    add_skip_pid "${pid}"
    next="$(ps -o ppid= -p "${pid}" 2>/dev/null | tr -d '[:space:]')"
    if [[ ! "${next}" =~ ^[0-9]+$ ]] || [ "${next}" -le 0 ] || [ "${next}" = "${pid}" ]; then
      break
    fi
    pid="${next}"
  done
}

list_child_pids() {
  local parent="$1"
  ps -eo pid=,ppid= 2>/dev/null | awk -v p="${parent}" '$2 == p {print $1}'
}

collect_descendants() {
  local parent="$1"
  local child=""
  while read -r child; do
    if [[ ! "${child}" =~ ^[0-9]+$ ]]; then
      continue
    fi
    if [ -n "${SKIP_PIDS["${child}"]+x}" ]; then
      continue
    fi
    if [ -z "${PIDS["${child}"]+x}" ]; then
      add_pid "${child}"
      collect_descendants "${child}"
    fi
  done < <(list_child_pids "${parent}")
}

refresh_descendants() {
  local snapshot=()
  local pid=""
  for pid in "${!PIDS[@]}"; do
    snapshot+=("${pid}")
  done
  for pid in "${snapshot[@]}"; do
    collect_descendants "${pid}"
  done
}

signal_pid_set() {
  local signal_name="$1"
  local pid=""
  for pid in "${!PIDS[@]}"; do
    if [ -n "${SKIP_PIDS["${pid}"]+x}" ]; then
      continue
    fi
    kill "-${signal_name}" "${pid}" 2>/dev/null || true
  done
}

prune_dead_pids() {
  local pid=""
  for pid in "${!PIDS[@]}"; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      unset 'PIDS[$pid]'
    fi
  done
}

report_survivors() {
  local pid=""
  local survivors=()
  for pid in "${!PIDS[@]}"; do
    if [ -n "${SKIP_PIDS["${pid}"]+x}" ]; then
      continue
    fi
    if kill -0 "${pid}" 2>/dev/null; then
      survivors+=("${pid}")
    fi
  done
  if [ "${#survivors[@]}" -gt 0 ]; then
    echo "Processes still running after cleanup:"
    ps -fp "$(printf '%s,' "${survivors[@]}" | sed 's/,$//')" || true
    return 1
  fi
  return 0
}

collect_ancestor_pids "$$"

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
  "run_vera_full.sh"
  "run_vera.py"
  "run_vera_monolithic.py"
  "run_vera.sh"
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

# Reap orphaned call-me tunnel children by cwd. These can survive after bun exits
# and are not always descendants of the current runtime tree.
while read -r pid cmd; do
  [ -z "${pid}" ] && continue
  cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
  if [ "${cwd}" != "${CALLME_SERVER_DIR}" ]; then
    continue
  fi
  case "${cmd}" in
    *"bun run src/index.ts"*|*"localtunnel"*|*"lt --port 3333"*|*"npx -y localtunnel --port 3333"*|*"sh -c lt --port 3333"*)
      add_pid "${pid}"
      ;;
  esac
done < <(ps -eo pid=,args= 2>/dev/null || true)

refresh_descendants

if [ "${#PIDS[@]}" -eq 0 ]; then
  echo "No lingering VERA processes detected."
else
  TARGET_PIDS=()
  for pid in "${!PIDS[@]}"; do
    if [ -z "${SKIP_PIDS["${pid}"]+x}" ]; then
      TARGET_PIDS+=("${pid}")
    fi
  done
  echo "Found lingering VERA processes:"
  if [ "${#TARGET_PIDS[@]}" -gt 0 ]; then
    ps -fp "$(printf '%s,' "${TARGET_PIDS[@]}" | sed 's/,$//')" || true
  else
    echo "Only current cleanup ancestry matched; nothing to stop."
  fi
  if confirm "Stop these processes?"; then
    signal_pid_set TERM
    for _ in $(seq 1 8); do
      sleep 1
      prune_dead_pids
      refresh_descendants
      prune_dead_pids
      if report_survivors >/dev/null 2>&1; then
        break
      fi
    done
    prune_dead_pids
    refresh_descendants
    prune_dead_pids
    if ! report_survivors >/dev/null 2>&1; then
      signal_pid_set KILL
      sleep 1
      prune_dead_pids
      refresh_descendants
      prune_dead_pids
    fi
    if ! report_survivors; then
      echo "Cleanup did not fully stop all VERA processes." >&2
      exit 1
    fi
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
