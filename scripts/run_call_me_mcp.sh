#!/usr/bin/env bash
# Launcher for call-me phone MCP server (requires bun)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="${ROOT_DIR}/mcp_server_and_tools/call-me/server"
CALLME_PROFILE="${CALLME_PROFILE:-carol-prod}"
CALLME_PROFILE_FILE="${ROOT_DIR}/config/callme_profiles/${CALLME_PROFILE}.env"

if [ -f "${CALLME_PROFILE_FILE}" ]; then
  # shellcheck disable=SC1090
  source "${CALLME_PROFILE_FILE}"
else
  echo "Warning: call-me profile '${CALLME_PROFILE}' not found at ${CALLME_PROFILE_FILE}" >&2
fi

export PATH="${PATH}:${HOME}/.bun/bin"
export CALLME_NGROK_POOLING="${CALLME_NGROK_POOLING:-1}"
export CALLME_TUNNEL_PROVIDER="${CALLME_TUNNEL_PROVIDER:-auto}"
export CALLME_ASSISTANT_NAME="${CALLME_ASSISTANT_NAME:-Vera}"
export CALLME_USE_PROVIDER_TTS="${CALLME_USE_PROVIDER_TTS:-1}"
export CALLME_TELNYX_TTS_VOICE="${CALLME_TELNYX_TTS_VOICE:-Telnyx.Natural.carol}"
export CALLME_TELNYX_TTS_SERVICE_LEVEL="${CALLME_TELNYX_TTS_SERVICE_LEVEL:-premium}"

if ! command -v bun >/dev/null 2>&1; then
  echo "Error: bun runtime required for call-me. Install: curl -fsSL https://bun.sh/install | bash" >&2
  exit 1
fi

# Reap stale standalone call-me instances from the same server directory.
# This prevents ngrok endpoint conflicts and port 3333 deadlocks on restart.
stale_pids=()
while IFS= read -r pid; do
  [ -z "${pid}" ] && continue
  [ "${pid}" = "$$" ] && continue
  cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
  if [ "${cwd}" = "${SERVER_DIR}" ]; then
    stale_pids+=("${pid}")
  fi
done < <(pgrep -u "$(id -u)" -f "bun run src/index.ts" || true)

if [ "${#stale_pids[@]}" -gt 0 ]; then
  echo "Cleaning up stale call-me process(es): ${stale_pids[*]}" >&2
  kill "${stale_pids[@]}" 2>/dev/null || true
  for _ in $(seq 1 20); do
    alive=0
    for pid in "${stale_pids[@]}"; do
      if kill -0 "${pid}" 2>/dev/null; then
        alive=1
        break
      fi
    done
    [ "${alive}" -eq 0 ] && break
    sleep 0.25
  done
  for pid in "${stale_pids[@]}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      echo "Force-stopping stale call-me process ${pid}" >&2
      kill -9 "${pid}" 2>/dev/null || true
    fi
  done
fi

cd "${SERVER_DIR}"

# Avoid reinstalling dependencies on every launch; install only if absent.
if [ ! -d "${SERVER_DIR}/node_modules" ]; then
  bun install --silent
fi

# Run entrypoint directly so package.json prestart hooks don't force reinstall.
exec bun run src/index.ts
