#!/usr/bin/env bash
# Launcher for call-me phone MCP server (requires bun)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="${ROOT_DIR}/mcp_server_and_tools/call-me/server"
ENV_FILE="${ROOT_DIR}/scripts/vera_env.local"
CALLME_PROFILE="${CALLME_PROFILE:-carol-prod}"
CALLME_PROFILE_FILE="${ROOT_DIR}/config/callme_profiles/${CALLME_PROFILE}.env"
CALLME_PROFILE_EXAMPLE_FILE="${ROOT_DIR}/config/callme_profiles/${CALLME_PROFILE}.example.env"

if [ -f "${ENV_FILE}" ]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

if [ -f "${CALLME_PROFILE_FILE}" ]; then
  # shellcheck disable=SC1090
  source "${CALLME_PROFILE_FILE}"
elif [ -f "${CALLME_PROFILE_EXAMPLE_FILE}" ]; then
  # shellcheck disable=SC1090
  source "${CALLME_PROFILE_EXAMPLE_FILE}"
  echo "Info: using call-me example profile '${CALLME_PROFILE_EXAMPLE_FILE}'" >&2
else
  echo "Warning: call-me profile '${CALLME_PROFILE}' not found at ${CALLME_PROFILE_FILE}" >&2
fi

export PATH="${PATH}:${HOME}/.bun/bin"
export CALLME_NGROK_POOLING="${CALLME_NGROK_POOLING:-1}"
export CALLME_TUNNEL_PROVIDER="${CALLME_TUNNEL_PROVIDER:-auto}"
export CALLME_NGROK_CONTENTION_COOLDOWN_MS="${CALLME_NGROK_CONTENTION_COOLDOWN_MS:-900000}"
export CALLME_NGROK_DISABLE_DOMAIN_ON_CONTENTION="${CALLME_NGROK_DISABLE_DOMAIN_ON_CONTENTION:-1}"
export CALLME_RUNTIME_STATUS_PATH="${CALLME_RUNTIME_STATUS_PATH:-${ROOT_DIR}/vera_memory/callme_runtime_status.json}"
export CALLME_ASSISTANT_NAME="${CALLME_ASSISTANT_NAME:-Vera}"
export CALLME_USE_PROVIDER_TTS="${CALLME_USE_PROVIDER_TTS:-1}"
export CALLME_TELNYX_TTS_VOICE="${CALLME_TELNYX_TTS_VOICE:-Telnyx.Natural.carol}"
export CALLME_TELNYX_TTS_SERVICE_LEVEL="${CALLME_TELNYX_TTS_SERVICE_LEVEL:-premium}"
export CALLME_PUSH_TIMEOUT_MS="${CALLME_PUSH_TIMEOUT_MS:-30000}"
export CALLME_CALL_ANSWER_TIMEOUT_MS="${CALLME_CALL_ANSWER_TIMEOUT_MS:-60000}"
export CALLME_CALL_ANSWER_RETRY_MS="${CALLME_CALL_ANSWER_RETRY_MS:-20000}"

if ! command -v bun >/dev/null 2>&1; then
  echo "Error: bun runtime required for call-me. Install: curl -fsSL https://bun.sh/install | bash" >&2
  exit 1
fi

collect_stale_callme_pids() {
  local pid=""
  local cmd=""
  while read -r pid cmd; do
    [ -z "${pid}" ] && continue
    [ "${pid}" = "$$" ] && continue
    cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
    if [ "${cwd}" != "${SERVER_DIR}" ]; then
      continue
    fi
    case "${cmd}" in
      *"bun run src/index.ts"*|*"localtunnel"*|*"lt --port 3333"*|*"npx -y localtunnel --port 3333"*|*"sh -c lt --port 3333"*)
        printf '%s\n' "${pid}"
        ;;
    esac
  done < <(ps -eo pid=,args= 2>/dev/null)
}

# Reap stale call-me runtime and tunnel instances from the same server directory.
# This prevents ngrok/localtunnel endpoint conflicts and port 3333 deadlocks on restart.
stale_pids=()
while IFS= read -r pid; do
  [ -z "${pid}" ] && continue
  stale_pids+=("${pid}")
done < <(collect_stale_callme_pids)

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
