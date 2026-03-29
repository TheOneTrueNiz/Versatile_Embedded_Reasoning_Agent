#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
UI_DIR="${ROOT_DIR}/ui/minimal-chat"
CREDS_DIR="${CREDS_DIR:-${VERA_CREDS_DIR:-${XDG_CONFIG_HOME:-${HOME}/.config}/vera/creds}}"
ENV_FILE="${ROOT_DIR}/scripts/vera_env.local"
KEYCHAIN_SCRIPT="${ROOT_DIR}/scripts/vera_secret_store.sh"
PYTHON_CMD="$(command -v python3 || command -v python || true)"
export CREDS_DIR
CREDS_POINTER="${CREDS_DIR}/.vera_creds_pointer"
BOOTSTRAP_SENTINEL="${CREDS_DIR}/.vera_bootstrap_complete"
export GOOGLE_MCP_CREDENTIALS_DIR="${GOOGLE_MCP_CREDENTIALS_DIR:-${CREDS_DIR}/google/credentials}"

if [ -z "${PYTHON_CMD}" ]; then
  echo "Python interpreter not found (need python3 or python)." >&2
  exit 1
fi

# Ensure venv environment variables are available for subprocesses and nohup.
if [ -f "${VENV_DIR}/bin/activate" ]; then
  # shellcheck disable=SC1090
  source "${VENV_DIR}/bin/activate"
else
  echo "Warning: venv not found at ${VENV_DIR}. Run ./scripts/run_vera.sh first."
fi

if [ -f "${ENV_FILE}" ]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi
if [ "${VERA_KEYCHAIN_LOAD:-1}" != "0" ] && [ -x "${KEYCHAIN_SCRIPT}" ]; then
  eval "$("${KEYCHAIN_SCRIPT}" load 2>/dev/null || true)"
fi
if [ -z "${XAI_API_KEY:-}" ] && [ -n "${API_KEY:-}" ]; then
  export XAI_API_KEY="${API_KEY}"
fi
if [ -z "${API_KEY:-}" ] && [ -n "${XAI_API_KEY:-}" ]; then
  export API_KEY="${XAI_API_KEY}"
fi

# Broad filesystem access defaults for Vera (can be overridden by env).
export VERA_FILESYSTEM_AUTO_EXPAND_HOME="${VERA_FILESYSTEM_AUTO_EXPAND_HOME:-1}"
if [ -z "${VERA_FILESYSTEM_EXTRA_ROOTS:-}" ]; then
  export VERA_FILESYSTEM_EXTRA_ROOTS="${HOME}:${HOME}/Desktop:${HOME}/Documents:${HOME}/Downloads:/tmp:/media:/mnt"
fi

CALLME_PROFILE="${CALLME_PROFILE:-carol-prod}"
CALLME_PROFILE_FILE="${ROOT_DIR}/config/callme_profiles/${CALLME_PROFILE}.env"
CALLME_PROFILE_EXAMPLE_FILE="${ROOT_DIR}/config/callme_profiles/${CALLME_PROFILE}.example.env"
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

rm -f "${ROOT_DIR}/tmp/shutdown_requested" 2>/dev/null || true

# Respect manual halt sentinel — don't launch if user intentionally stopped VERA
if [ -f "${ROOT_DIR}/vera_memory/manual_halt" ]; then
  echo "[VERA] Manual halt active. Remove vera_memory/manual_halt to start."
  exit 0
fi

VERA_API_HOST="${VERA_API_HOST:-127.0.0.1}"
VERA_API_PORT="${VERA_API_PORT:-8788}"
VERA_SETUP_HOST="${VERA_SETUP_HOST:-127.0.0.1}"
VERA_SETUP_PORT="${VERA_SETUP_PORT:-8787}"

LOGGING=0
FORCE_INSTALL=0
SKIP_UI=0
SKIP_SEARXNG=0
VERIFY=1
QUIET=0
DIAG_ONLY=0
CLEANUP=0
FORCE_CLEANUP=0
BOOTSTRAP=0
TRAY_ENABLED="${VERA_TRAY_ENABLED:-auto}"
MEMORY_FOOTPRINT_MB=""

while [ $# -gt 0 ]; do
  case "$1" in
    --logging)
      LOGGING=1
      ;;
    --dev)
      LOGGING=1
      FORCE_INSTALL=1
      ;;
    --force-install)
      FORCE_INSTALL=1
      ;;
    --no-ui)
      SKIP_UI=1
      ;;
    --no-searxng)
      SKIP_SEARXNG=1
      ;;
    --verify)
      VERIFY=1
      ;;
    --no-verify)
      VERIFY=0
      ;;
    --cleanup)
      CLEANUP=1
      ;;
    --force-cleanup)
      CLEANUP=1
      FORCE_CLEANUP=1
      ;;
    --quiet)
      QUIET=1
      ;;
    --diag-only)
      DIAG_ONLY=1
      VERIFY=1
      ;;
    --bootstrap)
      BOOTSTRAP=1
      ;;
    --no-tray)
      TRAY_ENABLED=0
      ;;
    --memory-footprint-mb)
      if [ $# -lt 2 ]; then
        echo "Missing value for --memory-footprint-mb" >&2
        exit 1
      fi
      MEMORY_FOOTPRINT_MB="$2"
      shift
      ;;
    *)
      echo "Unknown flag: $1"
      exit 1
      ;;
  esac
  shift
done

if [ -n "${MEMORY_FOOTPRINT_MB}" ]; then
  if ! [[ "${MEMORY_FOOTPRINT_MB}" =~ ^([0-9]+([.][0-9]+)?|[.][0-9]+)$ ]]; then
    echo "Invalid --memory-footprint-mb value: ${MEMORY_FOOTPRINT_MB}" >&2
    exit 1
  fi
  export VERA_MEMORY_MAX_FOOTPRINT_MB="${MEMORY_FOOTPRINT_MB}"
elif [ -z "${VERA_MEMORY_MAX_FOOTPRINT_MB:-}" ]; then
  export VERA_MEMORY_MAX_FOOTPRINT_MB="1024"
fi

if [ "${TRAY_ENABLED}" = "auto" ]; then
  if [ "${SKIP_UI}" = "1" ]; then
    TRAY_ENABLED=0
  else
    TRAY_ENABLED=1
  fi
fi

export VERA_MAX="${VERA_MAX:-1}"
if [ "${VERA_MAX}" = "1" ]; then
  export VERA_VOICE=1
  export VERA_BROWSER=1
  export VERA_DESKTOP=1
  export VERA_PDF=1
  export VERA_MCP_LOCAL=1
fi

if [ -n "${VERA_MCP_AUTOSTART_FORCE:-}" ]; then
  case "$(printf '%s' "${VERA_MCP_AUTOSTART_FORCE}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on)
      export VERA_MCP_AUTOSTART=1
      ;;
    0|false|no|off)
      export VERA_MCP_AUTOSTART=0
      ;;
    *)
      echo "Warning: ignoring invalid VERA_MCP_AUTOSTART_FORCE='${VERA_MCP_AUTOSTART_FORCE}'" >&2
      ;;
  esac
fi
export VERA_MCP_AUTOSTART="${VERA_MCP_AUTOSTART:-1}"
export MEMVID_ENV="${MEMVID_ENV:-memvid}"
export MEMVID_USE_GPU="${MEMVID_USE_GPU:-0}"
export GOOGLE_WORKSPACE_TOOL_TIER="${GOOGLE_WORKSPACE_TOOL_TIER:-complete}"
export VERA_TOOL_MODE="${VERA_TOOL_MODE:-auto}"
export VERA_TOOL_MAX="${VERA_TOOL_MAX:-30}"
export VERA_TOOL_ROUTER="${VERA_TOOL_ROUTER:-1}"
export VERA_TOOL_ROUTER_MAX="${VERA_TOOL_ROUTER_MAX:-12}"
export VERA_OPEN_BROWSER="${VERA_OPEN_BROWSER:-0}"
if [ "${VERA_MEMVID_ENABLED:-0}" = "1" ] || [ "${VERA_MEMVID_ENABLED:-0}" = "true" ]; then
  echo "[VERA] Memvid fast recall is experimental in VERA 2.0 and disabled by default."
  echo "[VERA] Proceeding because VERA_MEMVID_ENABLED is set."
fi

# Prefer rootless Docker socket when available to avoid sudo.
if [ -z "${DOCKER_HOST:-}" ]; then
  ROOTLESS_DOCKER_SOCK="/run/user/$(id -u)/docker.sock"
  if [ -S "${ROOTLESS_DOCKER_SOCK}" ]; then
    export DOCKER_HOST="unix://${ROOTLESS_DOCKER_SOCK}"
    echo "Docker: using rootless socket at ${ROOTLESS_DOCKER_SOCK}"
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

report_week1_source() {
  local docx_candidates=()
  local seed_csv="${ROOT_DIR}/ops/week1/WEEK1_SEEDED_TASK_BACKLOG.csv"
  local candidate resolved

  if [ -n "${VERA_WEEK1_DOCX_PATH:-}" ]; then
    docx_candidates+=("${VERA_WEEK1_DOCX_PATH}")
  fi
  docx_candidates+=(
    "${HOME}/Desktop/Vera_Week1_Operating_System_v10.docx"
    "${ROOT_DIR}/ops/week1/Vera_Week1_Operating_System_v10.docx"
  )

  for candidate in "${docx_candidates[@]}"; do
    [ -n "${candidate}" ] || continue
    resolved="$(realpath -m "${candidate}")"
    if [ -f "${resolved}" ]; then
      echo "[VERA] Week1 source: docx (${resolved})"
      return 0
    fi
  done

  if [ -f "${seed_csv}" ]; then
    echo "[VERA] Week1 source: seed CSV fallback (${seed_csv})"
    return 0
  fi

  echo "[VERA] Week1 source: unavailable (no docx and no seed CSV at ${seed_csv})"
}

if [ "${QUIET}" = "1" ]; then
  export VERA_CONFIG_WATCH_ENABLED="${VERA_CONFIG_WATCH_ENABLED:-0}"
  export VERA_TASK_CHECK_INTERVAL="${VERA_TASK_CHECK_INTERVAL:-600}"
  export VERA_TASK_CHECK_COOLDOWN="${VERA_TASK_CHECK_COOLDOWN:-1800}"
  export VERA_DND_LEVEL="${VERA_DND_LEVEL:-low}"
  export VERA_DND_MINUTES="${VERA_DND_MINUTES:-120}"
  export VERA_DND_REASON="${VERA_DND_REASON:-Quiet startup}"
fi

report_week1_source

if [ "${DIAG_ONLY}" = "1" ]; then
  SKIP_UI=1
fi

BOOTSTRAP_MODE="${VERA_BOOTSTRAP_CREDS:-auto}"

has_llm_creds() {
  if [ -n "${XAI_API_KEY:-}" ] || [ -n "${API_KEY:-}" ]; then
    return 0
  fi
  if [ -n "${VERA_LLM_BASE_URL:-}" ]; then
    return 0
  fi
  if [ -f "${CREDS_DIR}/xai/xai_api" ]; then
    return 0
  fi
  if [ -f "${CREDS_DIR}/local/llm_base_url" ]; then
    return 0
  fi
  return 1
}

has_workspace_email() {
  if [ -n "${GOOGLE_WORKSPACE_USER_EMAIL:-}" ]; then
    return 0
  fi
  if [ -f "${CREDS_DIR}/google/user_email" ]; then
    return 0
  fi
  return 1
}

creds_have_files() {
  if [ ! -d "${CREDS_DIR}" ]; then
    return 1
  fi
  if command -v find >/dev/null 2>&1; then
    if find "${CREDS_DIR}" -type f \
      ! -name '.vera_creds_pointer' \
      ! -name '.vera_bootstrap_complete' \
      -print -quit | grep -q .; then
      return 0
    fi
  fi
  for candidate in \
    "${CREDS_DIR}/xai/xai_api" \
    "${CREDS_DIR}/local/llm_base_url" \
    "${CREDS_DIR}/google/user_email" \
    "${CREDS_DIR}/brave/brave_api" \
    "${CREDS_DIR}/git/git_token" \
    "${CREDS_DIR}/searxng/searxng_url"; do
    if [ -f "${candidate}" ]; then
      return 0
    fi
  done
  return 1
}

ensure_bootstrap_sentinel() {
  if has_llm_creds && has_workspace_email; then
    mkdir -p "${CREDS_DIR}"
    printf 'complete\n' > "${BOOTSTRAP_SENTINEL}"
  fi
}

port_listening() {
  local host="$1"
  local port="$2"
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"${port}" -sTCP:LISTEN -P -n >/dev/null 2>&1
    return $?
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -lptn "sport = :${port}" 2>/dev/null | tail -n +2 | grep -q .
    return $?
  fi
  local python_bin=""
  if command -v python3 >/dev/null 2>&1; then
    python_bin="python3"
  elif command -v python >/dev/null 2>&1; then
    python_bin="python"
  else
    return 1
  fi
  if [ "${host}" = "0.0.0.0" ] || [ "${host}" = "::" ]; then
    host="127.0.0.1"
  fi
  "${python_bin}" - <<'PY' "${host}" "${port}"
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket()
sock.settimeout(0.5)
try:
    sock.connect((host, port))
    sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    sock.close()
PY
}

setup_port_in_use() {
  port_listening "${VERA_SETUP_HOST}" "${VERA_SETUP_PORT}"
}

setup_wizard_responding() {
  local host="${VERA_SETUP_HOST}"
  if [ "${host}" = "0.0.0.0" ] || [ "${host}" = "::" ]; then
    host="127.0.0.1"
  fi
  local python_bin=""
  if command -v python3 >/dev/null 2>&1; then
    python_bin="python3"
  elif command -v python >/dev/null 2>&1; then
    python_bin="python"
  else
    return 1
  fi
  "${python_bin}" - <<'PY' "${host}" "${VERA_SETUP_PORT}"
import json
import sys
import urllib.request

host = sys.argv[1]
port = sys.argv[2]
url = f"http://{host}:{port}/api/setup/config"
try:
    with urllib.request.urlopen(url, timeout=1.5) as resp:
        if resp.status != 200:
            raise RuntimeError("bad status")
        data = json.loads(resp.read().decode("utf-8"))
        if not data.get("main_url"):
            raise RuntimeError("missing main_url")
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
}

NEEDS_BOOTSTRAP=0
if [ "${BOOTSTRAP}" != "1" ] && [ ! -f "${BOOTSTRAP_SENTINEL}" ]; then
  ensure_bootstrap_sentinel
fi
if [ ! -f "${BOOTSTRAP_SENTINEL}" ] && creds_have_files && ! setup_port_in_use; then
  echo "Detected credentials at ${CREDS_DIR} without a bootstrap sentinel."
  echo "Remove the creds directory and re-run to start a clean setup:"
  echo "  rm -rf \"${CREDS_DIR}\""
  exit 1
fi
if [ "${BOOTSTRAP}" = "1" ] || { \
  [ "${BOOTSTRAP_MODE}" != "0" ] && \
  [ "${QUIET}" != "1" ] && \
  [ "${DIAG_ONLY}" != "1" ] && \
  [ -t 0 ] && [ -t 1 ] && \
  [ ! -f "${BOOTSTRAP_SENTINEL}" ]; \
}; then
  NEEDS_BOOTSTRAP=1
fi

is_headless() {
  if [ -n "${VERA_SETUP_FORCE_TUI:-}" ]; then
    return 0
  fi
  if [ -n "${VERA_SETUP_FORCE_WEB:-}" ]; then
    return 1
  fi
  if [[ "${OSTYPE:-}" == darwin* ]]; then
    return 1
  fi
  if [ "${OS:-}" = "Windows_NT" ]; then
    return 1
  fi
  if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
    return 1
  fi
  return 0
}

if [ "${NEEDS_BOOTSTRAP}" = "1" ]; then
  if ! command -v gum >/dev/null 2>&1; then
    echo "Gum is required for the VERA first-run wizard."
    echo "Install gum, then re-run:"
    echo "  - Debian/Ubuntu (if available): sudo apt-get install gum"
    echo "  - Homebrew: brew install gum"
    echo "  - Go: go install github.com/charmbracelet/gum@latest"
    read -r -p "Press Enter to exit and install gum." _ || true
    exit 1
  fi
  cleanup_wizard() {
    if [ -z "${WIZARD_PID:-}" ]; then
      return
    fi
    if ! kill -0 "${WIZARD_PID}" 2>/dev/null; then
      return
    fi
    kill "${WIZARD_PID}" 2>/dev/null || true
    for _ in {1..10}; do
      if ! kill -0 "${WIZARD_PID}" 2>/dev/null; then
        return
      fi
      sleep 0.2
    done
    kill -9 "${WIZARD_PID}" 2>/dev/null || true
  }
  trap cleanup_wizard EXIT INT TERM
  if is_headless; then
    if [ -f "${ROOT_DIR}/scripts/bootstrap_creds.sh" ]; then
      "${ROOT_DIR}/scripts/bootstrap_creds.sh"
    fi
  else
    export VERA_OPEN_BROWSER=0
    WIZARD_RUNNING=0
    if setup_port_in_use; then
      if setup_wizard_responding; then
        WIZARD_RUNNING=1
        echo "Setup wizard already running at http://${VERA_SETUP_HOST}:${VERA_SETUP_PORT}"
        if command -v xdg-open >/dev/null 2>&1; then
          xdg-open "http://${VERA_SETUP_HOST}:${VERA_SETUP_PORT}" >/dev/null 2>&1 || true
        fi
      else
        echo "Setup port ${VERA_SETUP_PORT} is in use, but no wizard responded."
        echo "Close the process using that port or set VERA_SETUP_PORT."
        exit 1
      fi
    elif [ -f "${ROOT_DIR}/scripts/run_setup_wizard.py" ]; then
      "${VENV_DIR}/bin/python" "${ROOT_DIR}/scripts/run_setup_wizard.py" \
        --host "${VERA_SETUP_HOST}" \
        --port "${VERA_SETUP_PORT}" \
        --main-host "${VERA_API_HOST}" \
        --main-port "${VERA_API_PORT}" \
        --open-browser &
      WIZARD_PID=$!
    fi
  fi
  if [ -n "${WIZARD_PID:-}" ] || [ "${WIZARD_RUNNING:-0}" = "1" ]; then
    while [ ! -f "${BOOTSTRAP_SENTINEL}" ]; do
      if [ -n "${WIZARD_PID:-}" ]; then
        if ! kill -0 "${WIZARD_PID}" 2>/dev/null; then
          break
        fi
      else
        if ! setup_port_in_use; then
          break
        fi
      fi
      sleep 1
    done
  fi
  if [ ! -f "${BOOTSTRAP_SENTINEL}" ]; then
    echo "Setup wizard did not complete. Exiting."
    exit 1
  fi
fi

port_in_use() {
  port_listening "${VERA_API_HOST}" "${VERA_API_PORT}"
}

if [ "${CLEANUP}" = "1" ]; then
  CLEANUP_ARGS=()
  if [ "${FORCE_CLEANUP}" = "1" ]; then
    CLEANUP_ARGS+=(--force)
  fi
  if [ "${SKIP_SEARXNG}" = "1" ]; then
    CLEANUP_ARGS+=(--no-searxng)
  fi
  if [ -f "${ROOT_DIR}/scripts/cleanup_vera.sh" ]; then
    chmod +x "${ROOT_DIR}/scripts/cleanup_vera.sh" || true
  fi
  "${ROOT_DIR}/scripts/cleanup_vera.sh" "${CLEANUP_ARGS[@]}"
fi

if port_in_use; then
  echo "Port ${VERA_API_PORT} is already in use."
  echo "Run ./scripts/cleanup_vera.sh or re-run with --cleanup/--force-cleanup."
  exit 1
fi

read_trim() {
  if [ -f "$1" ]; then
    tr -d '\r' < "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
  fi
}

normalize_value() {
  local value="$1"
  value="${value#export }"
  value="${value#XAI_API_KEY=}"
  value="${value#API_KEY=}"
  value="${value#BRAVE_API_KEY=}"
  value="${value#SEARXNG_BASE_URL=}"
  value="${value#GITHUB_PERSONAL_ACCESS_TOKEN=}"
  if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  value="$(printf '%s' "${value}" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  echo "${value}"
}

normalize_url() {
  local value
  value="$(normalize_value "$1")"
  value="$(printf '%s' "${value}" | tr -d ' \t')"
  if [ -n "${value}" ] && [[ ! "${value}" =~ ^https?:// ]]; then
    value="http://${value}"
  fi
  echo "${value}"
}

normalize_llm_base_url() {
  local value
  value="$(normalize_url "$1")"
  if [ -n "${value}" ] && [[ ! "${value}" =~ /v1/?$ ]]; then
    value="${value%/}/v1"
  fi
  echo "${value}"
}

mkdir -p "${CREDS_DIR}"
printf 'VERA credentials live at: %s\n' "${CREDS_DIR}" > "${CREDS_POINTER}"
mkdir -p "${GOOGLE_MCP_CREDENTIALS_DIR}"

if [ -d "${CREDS_DIR}" ]; then
  if [ -z "${BRAVE_API_KEY:-}" ] && [ -f "${CREDS_DIR}/brave/brave_api" ]; then
    export BRAVE_API_KEY="$(normalize_value "$(read_trim "${CREDS_DIR}/brave/brave_api")")"
  fi

  if [ -z "${GOOGLE_WORKSPACE_USER_EMAIL:-}" ] && [ -f "${CREDS_DIR}/google/user_email" ]; then
    export GOOGLE_WORKSPACE_USER_EMAIL="$(normalize_value "$(read_trim "${CREDS_DIR}/google/user_email")")"
  fi
  if [ -n "${GOOGLE_WORKSPACE_USER_EMAIL:-}" ] && [ -z "${USER_GOOGLE_EMAIL:-}" ]; then
    export USER_GOOGLE_EMAIL="${GOOGLE_WORKSPACE_USER_EMAIL}"
  fi
  if [ -z "${VERA_DEFAULT_SESSION_LINK_ID:-}" ] && [ -n "${GOOGLE_WORKSPACE_USER_EMAIL:-}" ]; then
    # Single-owner default: use known onboarded workspace identity to keep cross-channel continuity.
    export VERA_DEFAULT_SESSION_LINK_ID="$(printf '%s' "${GOOGLE_WORKSPACE_USER_EMAIL}" | tr '[:upper:]' '[:lower:]')"
  fi

  if [ -z "${GITHUB_PERSONAL_ACCESS_TOKEN:-}" ] && [ -f "${CREDS_DIR}/git/git_token" ]; then
    raw_token="$(read_trim "${CREDS_DIR}/git/git_token")"
    token_candidate="$(echo "${raw_token}" | sed -n 's/.*\\(ghp_[A-Za-z0-9]*\\).*/\\1/p' | head -n 1)"
    if [ -z "${token_candidate}" ]; then
      token_candidate="$(echo "${raw_token}" | sed -n 's/.*\\(github_pat_[A-Za-z0-9_]*\\).*/\\1/p' | head -n 1)"
    fi
    if [ -z "${token_candidate}" ]; then
      token_candidate="$(echo "${raw_token}" | sed 's/.*=//')"
    fi
    token_candidate="$(normalize_value "${token_candidate}")"
    token_candidate="$(printf '%s' "${token_candidate}" | tr -d ' \t\r\n')"
    export GITHUB_PERSONAL_ACCESS_TOKEN="${token_candidate}"
  fi

  if [ -z "${SEARXNG_BASE_URL:-}" ] && [ -f "${CREDS_DIR}/searxng/searxng_url" ]; then
    raw_line="$(read_trim "${CREDS_DIR}/searxng/searxng_url")"
    url_candidate="$(printf '%s' "${raw_line}" | grep -oE 'https?://[^[:space:]]+' | tail -n 1 || true)"
    if [ -z "${url_candidate}" ]; then
      url_candidate="$(normalize_url "${raw_line}")"
    fi
    export SEARXNG_BASE_URL="$(normalize_url "${url_candidate}")"
  fi

  # Obsidian vault path for obsidian-vault MCP server
  if [ -z "${OBSIDIAN_VAULT_PATH:-}" ] && [ -f "${CREDS_DIR}/obsidian/vault_path" ]; then
    export OBSIDIAN_VAULT_PATH="$(normalize_value "$(read_trim "${CREDS_DIR}/obsidian/vault_path")")"
  fi

  # Composio MCP Hub configuration
  if [ -z "${COMPOSIO_API_KEY:-}" ] && [ -f "${CREDS_DIR}/composio/composio_api" ]; then
    export COMPOSIO_API_KEY="$(normalize_value "$(read_trim "${CREDS_DIR}/composio/composio_api")")"
  fi
  if [ -z "${COMPOSIO_API_KEY:-}" ] && [ -f "${CREDS_DIR}/hub/composio_api_key" ]; then
    export COMPOSIO_API_KEY="$(normalize_value "$(read_trim "${CREDS_DIR}/hub/composio_api_key")")"
  fi
  if [ -z "${MCP_HUB_COMMAND:-}" ] && [ -f "${CREDS_DIR}/composio/command" ]; then
    export MCP_HUB_COMMAND="$(normalize_value "$(read_trim "${CREDS_DIR}/composio/command")")"
  fi
  if [ -z "${MCP_HUB_COMMAND:-}" ] && [ -f "${CREDS_DIR}/hub/command" ]; then
    export MCP_HUB_COMMAND="$(normalize_value "$(read_trim "${CREDS_DIR}/hub/command")")"
  fi
  if [ -z "${MCP_HUB_ARGS:-}" ] && [ -f "${CREDS_DIR}/composio/args" ]; then
    export MCP_HUB_ARGS="$(read_trim "${CREDS_DIR}/composio/args")"
  fi
  if [ -z "${MCP_HUB_ARGS:-}" ] && [ -f "${CREDS_DIR}/hub/args" ]; then
    export MCP_HUB_ARGS="$(read_trim "${CREDS_DIR}/hub/args")"
  fi

  if [ -z "${XAI_API_KEY:-}" ] && [ -f "${CREDS_DIR}/xai/xai_api" ]; then
    export XAI_API_KEY="$(normalize_value "$(read_trim "${CREDS_DIR}/xai/xai_api")")"
  fi
  if [ -n "${XAI_API_KEY:-}" ] && [ -z "${API_KEY:-}" ]; then
    export API_KEY="${XAI_API_KEY}"
  fi

  if [ -z "${YOUTUBE_API_KEY:-}" ] && [ -f "${CREDS_DIR}/google/youtube_api_key" ]; then
    export YOUTUBE_API_KEY="$(normalize_value "$(read_trim "${CREDS_DIR}/google/youtube_api_key")")"
  fi

  if [ -z "${BROWSERBASE_API_KEY:-}" ] && [ -f "${CREDS_DIR}/browserbase/browserbase_api_key" ]; then
    export BROWSERBASE_API_KEY="$(normalize_value "$(read_trim "${CREDS_DIR}/browserbase/browserbase_api_key")")"
  fi
  if [ -z "${BROWSERBASE_PROJECT_ID:-}" ]; then
    if [ -f "${CREDS_DIR}/browserbase/browserbase_project_id" ]; then
      export BROWSERBASE_PROJECT_ID="$(normalize_value "$(read_trim "${CREDS_DIR}/browserbase/browserbase_project_id")")"
    elif [ -f "${CREDS_DIR}/browserbase/browswerbase_project_id" ]; then
      export BROWSERBASE_PROJECT_ID="$(normalize_value "$(read_trim "${CREDS_DIR}/browserbase/browswerbase_project_id")")"
    fi
  fi

  if [ -z "${SCRAPELESS_KEY:-}" ] && [ -f "${CREDS_DIR}/scrapeless/scrapeless_api" ]; then
    export SCRAPELESS_KEY="$(normalize_value "$(read_trim "${CREDS_DIR}/scrapeless/scrapeless_api")")"
  fi

  if [ -z "${TWITTER_API_KEY:-}" ] && [ -f "${CREDS_DIR}/X/X_API_KEY" ]; then
    export TWITTER_API_KEY="$(normalize_value "$(read_trim "${CREDS_DIR}/X/X_API_KEY")")"
  fi
  if [ -z "${TWITTER_API_SECRET:-}" ] && [ -f "${CREDS_DIR}/X/X_API_KEY_SECRET" ]; then
    export TWITTER_API_SECRET="$(normalize_value "$(read_trim "${CREDS_DIR}/X/X_API_KEY_SECRET")")"
  fi
  if [ -z "${TWITTER_ACCESS_TOKEN:-}" ] && [ -f "${CREDS_DIR}/X/Access_Token" ]; then
    export TWITTER_ACCESS_TOKEN="$(normalize_value "$(read_trim "${CREDS_DIR}/X/Access_Token")")"
  fi
  if [ -z "${TWITTER_ACCESS_TOKEN_SECRET:-}" ] && [ -f "${CREDS_DIR}/X/Access_Token_Secret" ]; then
    export TWITTER_ACCESS_TOKEN_SECRET="$(normalize_value "$(read_trim "${CREDS_DIR}/X/Access_Token_Secret")")"
  fi
  if [ -z "${TWITTER_BEARER_TOKEN:-}" ] && [ -f "${CREDS_DIR}/X/Bearer_Token" ]; then
    export TWITTER_BEARER_TOKEN="$(normalize_value "$(read_trim "${CREDS_DIR}/X/Bearer_Token")")"
  fi

  if [ -z "${CALLME_NGROK_AUTHTOKEN:-}" ] && [ -f "${CREDS_DIR}/ngrok/ngrok_auth_token" ]; then
    export CALLME_NGROK_AUTHTOKEN="$(normalize_value "$(read_trim "${CREDS_DIR}/ngrok/ngrok_auth_token")")"
  fi
  if [ -z "${NGROK_AUTHTOKEN:-}" ] && [ -n "${CALLME_NGROK_AUTHTOKEN:-}" ]; then
    export NGROK_AUTHTOKEN="${CALLME_NGROK_AUTHTOKEN}"
  fi
  if [ -z "${CALLME_NGROK_DOMAIN:-}" ] && [ -f "${CREDS_DIR}/ngrok/domain_and_id" ]; then
    domain_line="$(grep -i 'Domain:' "${CREDS_DIR}/ngrok/domain_and_id" 2>/dev/null | head -n 1 || true)"
    domain_value="$(printf '%s' "${domain_line#*:}" | tr -d '\r\n')"
    domain_value="$(normalize_value "${domain_value}")"
    if [ -n "${domain_value}" ]; then
      export CALLME_NGROK_DOMAIN="${domain_value}"
    fi
  fi
  if [ -z "${CALLME_NGROK_DOMAIN:-}" ] && [ -f "${CREDS_DIR}/ngrok/domain" ]; then
    export CALLME_NGROK_DOMAIN="$(normalize_value "$(read_trim "${CREDS_DIR}/ngrok/domain")")"
  fi
  if [ -n "${CALLME_NGROK_DOMAIN:-}" ] && [ -z "${CALLME_NGROK_POOLING:-}" ]; then
    export CALLME_NGROK_POOLING=1
  fi

  if [ -z "${CALLME_PHONE_AUTH_TOKEN:-}" ] && [ -f "${CREDS_DIR}/telnyx/telnyx_api_key" ]; then
    export CALLME_PHONE_AUTH_TOKEN="$(normalize_value "$(read_trim "${CREDS_DIR}/telnyx/telnyx_api_key")")"
  fi
  if [ -z "${CALLME_PHONE_ACCOUNT_SID:-}" ] && [ -f "${CREDS_DIR}/telnyx/connection_id" ]; then
    export CALLME_PHONE_ACCOUNT_SID="$(normalize_value "$(read_trim "${CREDS_DIR}/telnyx/connection_id")")"
  fi
  if [ -z "${CALLME_TELNYX_PUBLIC_KEY:-}" ] && [ -f "${CREDS_DIR}/telnyx/public_key" ]; then
    export CALLME_TELNYX_PUBLIC_KEY="$(normalize_value "$(read_trim "${CREDS_DIR}/telnyx/public_key")")"
  fi
  if [ -z "${CALLME_PHONE_NUMBER:-}" ] && [ -f "${CREDS_DIR}/telnyx/phone_number" ]; then
    export CALLME_PHONE_NUMBER="$(normalize_value "$(read_trim "${CREDS_DIR}/telnyx/phone_number")")"
  fi
  if [ -z "${CALLME_SMS_FROM_NUMBER:-}" ] && [ -f "${CREDS_DIR}/telnyx/sms_from_number" ]; then
    export CALLME_SMS_FROM_NUMBER="$(normalize_value "$(read_trim "${CREDS_DIR}/telnyx/sms_from_number")")"
  fi
  if [ -z "${CALLME_MESSAGING_PROFILE_ID:-}" ] && [ -f "${CREDS_DIR}/telnyx/messaging_profile_id" ]; then
    export CALLME_MESSAGING_PROFILE_ID="$(normalize_value "$(read_trim "${CREDS_DIR}/telnyx/messaging_profile_id")")"
  fi
  if [ -z "${CALLME_USER_PHONE_NUMBER:-}" ] && [ -f "${CREDS_DIR}/telnyx/user_phone_number" ]; then
    export CALLME_USER_PHONE_NUMBER="$(normalize_value "$(read_trim "${CREDS_DIR}/telnyx/user_phone_number")")"
  fi
  if [ -z "${CALLME_USER_NAME:-}" ] && [ -f "${CREDS_DIR}/vera/user_name" ]; then
    export CALLME_USER_NAME="$(normalize_value "$(read_trim "${CREDS_DIR}/vera/user_name")")"
  fi
  if [ -z "${CALLME_ASSISTANT_NAME:-}" ]; then
    export CALLME_ASSISTANT_NAME="Vera"
  fi
  if [ -z "${CALLME_GREETING_TEMPLATE:-}" ]; then
    export CALLME_GREETING_TEMPLATE="Hey {name}, it's Vera."
  fi
  if [ -z "${CALLME_HANGUP_DELAY_MS:-}" ]; then
    export CALLME_HANGUP_DELAY_MS=1200
  fi
  if [ -z "${CALLME_USE_PROVIDER_TTS:-}" ]; then
    export CALLME_USE_PROVIDER_TTS=1
  fi
  if [ -z "${CALLME_TELNYX_TTS_VOICE:-}" ]; then
    export CALLME_TELNYX_TTS_VOICE="Telnyx.Natural.carol"
  fi
  if [ -z "${CALLME_TELNYX_TTS_SERVICE_LEVEL:-}" ]; then
    export CALLME_TELNYX_TTS_SERVICE_LEVEL="premium"
  fi
  if [ -z "${CALLME_SMS_MODE:-}" ]; then
    # Carrier policy currently blocks outbound SMS/MMS for this deployment.
    # Keep mode off by default so tool routing stays on working channels.
    export CALLME_SMS_MODE=off
  fi
  case "$(printf '%s' "${CALLME_SMS_MODE}" | tr '[:upper:]' '[:lower:]')" in
    two-way|two_way|twoway|reply|autoreply|auto-reply|bidirectional)
      export CALLME_SMS_MODE="two-way"
      ;;
    send-only|send_only|sendonly|send|outbound|one-way|one_way)
      export CALLME_SMS_MODE="send-only"
      ;;
    off|disabled|disable|none|false|0|no)
      export CALLME_SMS_MODE="off"
      ;;
    *)
      echo "[call-me] Unknown CALLME_SMS_MODE='${CALLME_SMS_MODE}', defaulting to off"
      export CALLME_SMS_MODE="off"
      ;;
  esac
  if [ -z "${CALLME_SMS_ENABLED:-}" ]; then
    if [ "${CALLME_SMS_MODE}" = "off" ]; then
      export CALLME_SMS_ENABLED=0
    else
      export CALLME_SMS_ENABLED=1
    fi
  fi
  if [ -z "${CALLME_SMS_AUTOREPLY:-}" ]; then
    if [ "${CALLME_SMS_MODE}" = "two-way" ]; then
      export CALLME_SMS_AUTOREPLY=1
    else
      # send-only/off modes disable inbound auto-reply loop.
      export CALLME_SMS_AUTOREPLY=0
    fi
  fi
  if [ -z "${CALLME_SMS_DELIVERY_WAIT_MS:-}" ]; then
    export CALLME_SMS_DELIVERY_WAIT_MS=15000
  fi
  if [ -z "${CALLME_SMS_DELIVERY_POLL_MS:-}" ]; then
    export CALLME_SMS_DELIVERY_POLL_MS=1000
  fi
  if [ -z "${CALLME_SYNC_MESSAGING_WEBHOOK:-}" ]; then
    if [ "${CALLME_SMS_MODE}" = "two-way" ]; then
      export CALLME_SYNC_MESSAGING_WEBHOOK=1
    else
      export CALLME_SYNC_MESSAGING_WEBHOOK=0
    fi
  fi

  if [ -z "${CALLME_VOICE_PROVIDER:-}" ] && [ -n "${XAI_API_KEY:-}" ]; then
    export CALLME_VOICE_PROVIDER="xai"
  fi
  if [ -z "${CALLME_VOICE_API_KEY:-}" ] && [ -n "${XAI_API_KEY:-}" ]; then
    export CALLME_VOICE_API_KEY="${XAI_API_KEY}"
  fi
  if [ -z "${CALLME_VOICE_NAME:-}" ]; then
    export CALLME_VOICE_NAME="eve"
  fi

  if [ -z "${VERA_LLM_BASE_URL:-}" ] && [ -f "${CREDS_DIR}/local/llm_base_url" ]; then
    export VERA_LLM_BASE_URL="$(normalize_llm_base_url "$(read_trim "${CREDS_DIR}/local/llm_base_url")")"
  fi
  if [ -z "${VERA_LLM_API_KEY:-}" ] && [ -f "${CREDS_DIR}/local/llm_api_key" ]; then
    export VERA_LLM_API_KEY="$(normalize_value "$(read_trim "${CREDS_DIR}/local/llm_api_key")")"
  fi
  if [ -z "${VERA_MODEL:-}" ] && [ -f "${CREDS_DIR}/local/model_id" ]; then
    export VERA_MODEL="$(normalize_value "$(read_trim "${CREDS_DIR}/local/model_id")")"
  fi

  if [ -d "${CREDS_DIR}/google" ]; then
    export GOOGLE_WORKSPACE_CRED_DIR="${GOOGLE_WORKSPACE_CRED_DIR:-${CREDS_DIR}/google}"
    export WORKSPACE_MCP_PORT="${WORKSPACE_MCP_PORT:-8080}"
    # NOTE: Do NOT export bare "PORT" here — it leaks into all MCP subprocesses
    # and causes servers like scrapeless to bind HTTP instead of stdio.
    # The google-workspace launch script sets PORT internally from WORKSPACE_MCP_PORT.
    export GOOGLE_OAUTH_REDIRECT_URI="${GOOGLE_OAUTH_REDIRECT_URI:-http://127.0.0.1:${WORKSPACE_MCP_PORT}/oauth2callback}"
    export REDIRECT_URL="${REDIRECT_URL:-${GOOGLE_OAUTH_REDIRECT_URI}}"
    export GOOGLE_REDIRECT_URI="${GOOGLE_REDIRECT_URI:-${GOOGLE_OAUTH_REDIRECT_URI}}"
    if [ -z "${GOOGLE_CLIENT_SECRET_PATH:-}" ]; then
      GENERATED_SECRET_PATH="${CREDS_DIR}/google/client_secret_generated.json"
      if [ -f "${GENERATED_SECRET_PATH}" ]; then
        GOOGLE_CLIENT_SECRET_PATH="${GENERATED_SECRET_PATH}"
      else
        GOOGLE_CLIENT_SECRET_PATH="$(ls "${CREDS_DIR}/google"/*.json 2>/dev/null | head -n 1 || true)"
      fi
      export GOOGLE_CLIENT_SECRET_PATH
    fi
  fi
fi

if [ -n "${GOOGLE_CLIENT_SECRET_PATH:-}" ] && [ -f "${GOOGLE_CLIENT_SECRET_PATH}" ]; then
  readarray -t _oauth_values < <("${PYTHON_CMD}" - <<'PY' "${GOOGLE_CLIENT_SECRET_PATH}"
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
block = data.get("installed") or data.get("web") or {}
client_id = block.get("client_id", "")
client_secret = block.get("client_secret", "")
redirects = block.get("redirect_uris") or []
redirect_uri = redirects[0] if redirects else ""
print(client_id)
print(client_secret)
print(redirect_uri)
PY
)

  if [ -n "${_oauth_values[0]:-}" ]; then
    export GOOGLE_OAUTH_CLIENT_ID="${_oauth_values[0]}"
    export GOOGLE_CLIENT_ID="${_oauth_values[0]}"
  fi
  if [ -n "${_oauth_values[1]:-}" ]; then
    export GOOGLE_OAUTH_CLIENT_SECRET="${_oauth_values[1]}"
    export GOOGLE_CLIENT_SECRET="${_oauth_values[1]}"
  fi
  if [ -z "${GOOGLE_OAUTH_REDIRECT_URI:-}" ] && [ -n "${_oauth_values[2]:-}" ]; then
    export GOOGLE_OAUTH_REDIRECT_URI="${_oauth_values[2]}"
  fi
  if [ -z "${GOOGLE_REDIRECT_URI:-}" ] && [ -n "${GOOGLE_OAUTH_REDIRECT_URI:-}" ]; then
    export GOOGLE_REDIRECT_URI="${GOOGLE_OAUTH_REDIRECT_URI}"
  fi
  export OAUTHLIB_INSECURE_TRANSPORT="${OAUTHLIB_INSECURE_TRANSPORT:-1}"
fi

if [ -z "${XAI_API_KEY:-}" ] && [ -z "${API_KEY:-}" ] && [ -z "${VERA_LLM_BASE_URL:-}" ]; then
  echo "Missing required LLM configuration."
  echo "Set XAI_API_KEY or configure a local OpenAI-compatible endpoint."
  echo "Run ./scripts/bootstrap_creds.sh or ./scripts/run_vera_full.sh --bootstrap."
  exit 1
fi

if [ -f "${ROOT_DIR}/scripts/run_memvid_mcp.sh" ]; then
  chmod +x "${ROOT_DIR}/scripts/run_memvid_mcp.sh" || true
fi
if [ -f "${ROOT_DIR}/scripts/run_youtube_transcript_mcp.sh" ]; then
  chmod +x "${ROOT_DIR}/scripts/run_youtube_transcript_mcp.sh" || true
fi
if [ -f "${ROOT_DIR}/scripts/run_google_workspace_mcp.sh" ]; then
  chmod +x "${ROOT_DIR}/scripts/run_google_workspace_mcp.sh" || true
fi
if [ -f "${ROOT_DIR}/scripts/bootstrap_creds.sh" ]; then
  chmod +x "${ROOT_DIR}/scripts/bootstrap_creds.sh" || true
fi
if [ -f "${ROOT_DIR}/scripts/cleanup_vera.sh" ]; then
  chmod +x "${ROOT_DIR}/scripts/cleanup_vera.sh" || true
fi

VERA_NO_RUN=1 VERA_FORCE_INSTALL="${FORCE_INSTALL}" "${ROOT_DIR}/scripts/run_vera.sh"

# Install Google Workspace MCP deps once per venv.
if [ "${FORCE_INSTALL}" = "1" ] || [ ! -f "${VENV_DIR}/.deps_google_workspace_mcp" ]; then
  "${VENV_DIR}/bin/python" -m pip install -e "${ROOT_DIR}/mcp_server_and_tools/google_workspace_mcp"
  touch "${VENV_DIR}/.deps_google_workspace_mcp"
fi

YOUTUBE_TRANSCRIPT_DIR="${ROOT_DIR}/mcp_server_and_tools/mcp-server-youtube-transcript"
if [ -d "${YOUTUBE_TRANSCRIPT_DIR}" ]; then
  if [ "${FORCE_INSTALL}" = "1" ] || [ ! -d "${YOUTUBE_TRANSCRIPT_DIR}/node_modules" ]; then
    (cd "${YOUTUBE_TRANSCRIPT_DIR}" && npm install)
  fi
  if [ "${FORCE_INSTALL}" = "1" ] || [ ! -d "${YOUTUBE_TRANSCRIPT_DIR}/dist" ]; then
    (cd "${YOUTUBE_TRANSCRIPT_DIR}" && npm run build)
  fi
fi

if [ "${SKIP_SEARXNG}" = "0" ] && docker_available; then
  # Check if SearxNG is already running on the expected port
  SEARXNG_PORT="${SEARXNG_PORT:-8081}"
  if curl -s --connect-timeout 2 "http://127.0.0.1:${SEARXNG_PORT}/healthz" >/dev/null 2>&1; then
    echo "SearxNG already running on port ${SEARXNG_PORT}, skipping container start."
  else
    # Try to start SearxNG, but don't fail if it doesn't work
    if ! docker_compose_exec -f "${ROOT_DIR}/services/searxng/docker-compose.yml" up -d 2>&1; then
      echo "Warning: Failed to start SearxNG container. Web search may be unavailable."
    fi
  fi
elif [ "${SKIP_SEARXNG}" = "0" ]; then
  echo "Docker not found. Skipping SearxNG container."
fi

if [ "${SKIP_UI}" = "0" ]; then
  if [ ! -d "${UI_DIR}" ]; then
    echo "UI directory not found: ${UI_DIR}"
    exit 1
  fi
  if [ ! -d "${UI_DIR}/node_modules" ] || [ "${FORCE_INSTALL}" = "1" ]; then
    (cd "${UI_DIR}" && npm install)
  fi
  if [ ! -d "${UI_DIR}/dist" ] || [ "${FORCE_INSTALL}" = "1" ]; then
    (cd "${UI_DIR}" && npm run build)
  fi
  export VERA_UI_DIST="${UI_DIR}/dist"
fi

API_ARGS=(--host "${VERA_API_HOST}" --port "${VERA_API_PORT}")
if [ "${LOGGING}" = "1" ]; then
  API_ARGS+=(--logging)
fi
if [ -n "${MEMORY_FOOTPRINT_MB}" ]; then
  API_ARGS+=(--memory-footprint-mb "${MEMORY_FOOTPRINT_MB}")
fi

launch_tray() {
  if [ "${TRAY_ENABLED}" != "1" ]; then
    return
  fi
  # If a persistent user service manages the tray, avoid launching a duplicate
  # from this script path.
  if command -v systemctl >/dev/null 2>&1; then
    if systemctl --user is-active --quiet vera-tray.service 2>/dev/null; then
      echo "vera-tray.service is active; skipping script-managed tray launch."
      return
    fi
  fi
  local tray_pid_file="${ROOT_DIR}/vera_memory/vera_tray.pid"
  if [ -f "${tray_pid_file}" ]; then
    local existing_tray_pid
    existing_tray_pid="$(tr -d '[:space:]' < "${tray_pid_file}" 2>/dev/null || true)"
    if [[ "${existing_tray_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_tray_pid}" 2>/dev/null; then
      echo "Tray already running (PID ${existing_tray_pid}), skipping duplicate tray launch."
      return
    fi
  fi
  if [ -f "${ROOT_DIR}/scripts/vera_tray.py" ]; then
    if ! "${VENV_DIR}/bin/python" - <<'PY' >/dev/null 2>&1
import sys
system_dist = "/usr/lib/python3/dist-packages"
if system_dist not in sys.path:
    sys.path.insert(0, system_dist)
import gi
for namespace in ("AppIndicator3", "AyatanaAppIndicator3"):
    try:
        gi.require_version(namespace, "0.1")
        break
    except ValueError:
        continue
else:
    raise RuntimeError("No AppIndicator GI namespace available")
import pystray
PY
    then
      echo "Tray dependencies unavailable; skipping tray launch."
      return
    fi
    local tray_pid
    "${VENV_DIR}/bin/python" "${ROOT_DIR}/scripts/vera_tray.py" --attach &
    tray_pid=$!
    (
      while true; do
        sleep 5
        if ! kill -0 "${tray_pid}" 2>/dev/null; then
          echo "Tray process exited; relaunching."
          "${VENV_DIR}/bin/python" "${ROOT_DIR}/scripts/vera_tray.py" --attach &
          tray_pid=$!
        fi
      done
    ) &
  fi
}

if [ "${VERIFY}" = "1" ]; then
  "${VENV_DIR}/bin/python" "${ROOT_DIR}/run_vera_api.py" "${API_ARGS[@]}" &
  API_PID=$!
  trap 'kill ${API_PID} 2>/dev/null || true' INT TERM
  [ "${DIAG_ONLY}" = "0" ] && launch_tray

  VERIFY_EXIT=0
  if ! "${VENV_DIR}/bin/python" "${ROOT_DIR}/scripts/vera_tool_verification.py" \
    --host "${VERA_API_HOST}" \
    --port "${VERA_API_PORT}" \
    --timeout 45 \
    --memvid-timeout 240 \
    --wait 60; then
    VERIFY_EXIT=$?
    echo "Tool verification reported failures. See logs for details."
  fi

  if [ "${DIAG_ONLY}" = "1" ]; then
    kill -INT "${API_PID}" 2>/dev/null || true
    wait "${API_PID}" || true
    exit "${VERIFY_EXIT}"
  fi

  wait "${API_PID}"
else
  launch_tray
  exec "${VENV_DIR}/bin/python" "${ROOT_DIR}/run_vera_api.py" "${API_ARGS[@]}"
fi
