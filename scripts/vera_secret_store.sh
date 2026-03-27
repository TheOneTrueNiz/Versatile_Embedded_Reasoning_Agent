#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${VERA_KEYCHAIN_SERVICE:-vera.dev}"
BACKEND_PREFERENCE="${VERA_KEYCHAIN_BACKEND:-auto}"
DEFAULT_CREDS_DIR="${CREDS_DIR:-${VERA_CREDS_DIR:-${XDG_CONFIG_HOME:-${HOME}/.config}/vera/creds}}"

declare -a DEFAULT_VARS=(
  XAI_API_KEY
  API_KEY
  ANTHROPIC_API_KEY
  OPENAI_API_KEY
  GOOGLE_API_KEY
  GEMINI_API_KEY
  BRAVE_API_KEY
  GITHUB_PERSONAL_ACCESS_TOKEN
  SEARXNG_BASE_URL
  COMPOSIO_API_KEY
  MCP_HUB_COMMAND
  MCP_HUB_ARGS
  YOUTUBE_API_KEY
  BROWSERBASE_API_KEY
  BROWSERBASE_PROJECT_ID
  SCRAPELESS_KEY
  TWITTER_API_KEY
  TWITTER_API_SECRET
  TWITTER_ACCESS_TOKEN
  TWITTER_ACCESS_TOKEN_SECRET
  TWITTER_BEARER_TOKEN
  CALLME_NGROK_AUTHTOKEN
  NGROK_AUTHTOKEN
  CALLME_NGROK_DOMAIN
  CALLME_PHONE_AUTH_TOKEN
  CALLME_PHONE_ACCOUNT_SID
  CALLME_TELNYX_PUBLIC_KEY
  CALLME_PHONE_NUMBER
  CALLME_SMS_FROM_NUMBER
  CALLME_MESSAGING_PROFILE_ID
  CALLME_USER_PHONE_NUMBER
  CALLME_USER_NAME
  GOOGLE_WORKSPACE_USER_EMAIL
  OBSIDIAN_VAULT_PATH
  VERA_LLM_BASE_URL
  VERA_LLM_API_KEY
  VERA_MODEL
)

declare -A CREDS_PATHS=(
  [XAI_API_KEY]="xai/xai_api"
  [API_KEY]="xai/xai_api"
  [ANTHROPIC_API_KEY]="anthropic/anthropic_api"
  [OPENAI_API_KEY]="openai/openai_api"
  [GOOGLE_API_KEY]="google/google_api"
  [GEMINI_API_KEY]="google/google_api"
  [BRAVE_API_KEY]="brave/brave_api"
  [GITHUB_PERSONAL_ACCESS_TOKEN]="git/git_token"
  [SEARXNG_BASE_URL]="searxng/searxng_url"
  [COMPOSIO_API_KEY]="composio/composio_api"
  [MCP_HUB_COMMAND]="composio/command"
  [MCP_HUB_ARGS]="composio/args"
  [YOUTUBE_API_KEY]="google/youtube_api_key"
  [BROWSERBASE_API_KEY]="browserbase/browserbase_api_key"
  [BROWSERBASE_PROJECT_ID]="browserbase/browserbase_project_id"
  [SCRAPELESS_KEY]="scrapeless/scrapeless_api"
  [TWITTER_API_KEY]="X/X_API_KEY"
  [TWITTER_API_SECRET]="X/X_API_KEY_SECRET"
  [TWITTER_ACCESS_TOKEN]="X/Access_Token"
  [TWITTER_ACCESS_TOKEN_SECRET]="X/Access_Token_Secret"
  [TWITTER_BEARER_TOKEN]="X/Bearer_Token"
  [CALLME_NGROK_AUTHTOKEN]="ngrok/ngrok_auth_token"
  [NGROK_AUTHTOKEN]="ngrok/ngrok_auth_token"
  [CALLME_NGROK_DOMAIN]="ngrok/domain"
  [CALLME_PHONE_AUTH_TOKEN]="telnyx/telnyx_api_key"
  [CALLME_PHONE_ACCOUNT_SID]="telnyx/connection_id"
  [CALLME_TELNYX_PUBLIC_KEY]="telnyx/public_key"
  [CALLME_PHONE_NUMBER]="telnyx/phone_number"
  [CALLME_SMS_FROM_NUMBER]="telnyx/sms_from_number"
  [CALLME_MESSAGING_PROFILE_ID]="telnyx/messaging_profile_id"
  [CALLME_USER_PHONE_NUMBER]="telnyx/user_phone_number"
  [CALLME_USER_NAME]="vera/user_name"
  [GOOGLE_WORKSPACE_USER_EMAIL]="google/user_email"
  [OBSIDIAN_VAULT_PATH]="obsidian/vault_path"
  [VERA_LLM_BASE_URL]="local/llm_base_url"
  [VERA_LLM_API_KEY]="local/llm_api_key"
  [VERA_MODEL]="local/model_id"
)

print_usage() {
  cat <<'EOF'
Usage:
  scripts/vera_secret_store.sh backend
  scripts/vera_secret_store.sh set <ENV_VAR> <VALUE>
  scripts/vera_secret_store.sh get <ENV_VAR>
  scripts/vera_secret_store.sh delete <ENV_VAR>
  scripts/vera_secret_store.sh load [ENV_VAR...]
  scripts/vera_secret_store.sh status [ENV_VAR...]
  scripts/vera_secret_store.sh migrate-creds [CREDS_DIR]

Environment:
  VERA_KEYCHAIN_SERVICE     Secret service label (default: vera.dev)
  VERA_KEYCHAIN_BACKEND     auto|secret-tool|security|none
EOF
}

trim_value() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value}"
}

detect_backend() {
  case "${BACKEND_PREFERENCE}" in
    auto|"")
      if command -v secret-tool >/dev/null 2>&1; then
        echo "secret-tool"
      elif command -v security >/dev/null 2>&1; then
        echo "security"
      else
        echo "none"
      fi
      ;;
    secret-tool|libsecret|linux)
      if command -v secret-tool >/dev/null 2>&1; then
        echo "secret-tool"
      else
        echo "none"
      fi
      ;;
    security|macos|osx)
      if command -v security >/dev/null 2>&1; then
        echo "security"
      else
        echo "none"
      fi
      ;;
    none|off|disabled)
      echo "none"
      ;;
    *)
      echo "none"
      ;;
  esac
}

KEYCHAIN_BACKEND="$(detect_backend)"

has_backend() {
  [ "${KEYCHAIN_BACKEND}" != "none" ]
}

require_backend() {
  if ! has_backend; then
    echo "No keychain backend available. Install libsecret (secret-tool) or use macOS keychain." >&2
    exit 2
  fi
}

store_get() {
  local name="$1"
  case "${KEYCHAIN_BACKEND}" in
    secret-tool)
      secret-tool lookup service "${SERVICE_NAME}" account "${name}" 2>/dev/null || true
      ;;
    security)
      security find-generic-password -s "${SERVICE_NAME}" -a "${name}" -w 2>/dev/null || true
      ;;
    *)
      true
      ;;
  esac
}

store_set() {
  local name="$1"
  local value="$2"
  case "${KEYCHAIN_BACKEND}" in
    secret-tool)
      printf '%s' "${value}" | secret-tool store --label "VERA ${name}" service "${SERVICE_NAME}" account "${name}" app vera >/dev/null
      ;;
    security)
      security add-generic-password -U -s "${SERVICE_NAME}" -a "${name}" -w "${value}" >/dev/null
      ;;
    *)
      return 1
      ;;
  esac
}

store_delete() {
  local name="$1"
  case "${KEYCHAIN_BACKEND}" in
    secret-tool)
      secret-tool clear service "${SERVICE_NAME}" account "${name}" >/dev/null 2>&1 || true
      ;;
    security)
      security delete-generic-password -s "${SERVICE_NAME}" -a "${name}" >/dev/null 2>&1 || true
      ;;
    *)
      return 1
      ;;
  esac
}

normalize_special_value() {
  local name="$1"
  local value="$2"
  local token line

  case "${name}" in
    GITHUB_PERSONAL_ACCESS_TOKEN)
      token="$(printf '%s' "${value}" | sed -n 's/.*\(ghp_[A-Za-z0-9]*\).*/\1/p' | head -n 1)"
      if [ -z "${token}" ]; then
        token="$(printf '%s' "${value}" | sed -n 's/.*\(github_pat_[A-Za-z0-9_]*\).*/\1/p' | head -n 1)"
      fi
      if [ -n "${token}" ]; then
        value="${token}"
      fi
      ;;
    SEARXNG_BASE_URL)
      token="$(printf '%s' "${value}" | grep -oE 'https?://[^[:space:]]+' | tail -n 1 || true)"
      if [ -n "${token}" ]; then
        value="${token}"
      fi
      ;;
    CALLME_NGROK_DOMAIN)
      line="$(printf '%s' "${value}" | grep -i 'Domain:' | head -n 1 || true)"
      if [ -n "${line}" ]; then
        value="${line#*:}"
      fi
      ;;
  esac

  trim_value "${value}"
}

read_creds_value() {
  local name="$1"
  local creds_dir="$2"
  local rel_path path raw normalized

  rel_path="${CREDS_PATHS[${name}]:-}"
  if [ -z "${rel_path}" ]; then
    return 1
  fi

  path="${creds_dir}/${rel_path}"
  if [ ! -f "${path}" ] && [ "${name}" = "BROWSERBASE_PROJECT_ID" ]; then
    path="${creds_dir}/browserbase/browswerbase_project_id"
  fi
  if [ ! -f "${path}" ] && [ "${name}" = "CALLME_NGROK_DOMAIN" ]; then
    path="${creds_dir}/ngrok/domain_and_id"
  fi
  if [ ! -f "${path}" ] && [ "${name}" = "COMPOSIO_API_KEY" ]; then
    path="${creds_dir}/hub/composio_api_key"
  fi
  if [ ! -f "${path}" ] && [ "${name}" = "MCP_HUB_COMMAND" ]; then
    path="${creds_dir}/hub/command"
  fi
  if [ ! -f "${path}" ] && [ "${name}" = "MCP_HUB_ARGS" ]; then
    path="${creds_dir}/hub/args"
  fi

  if [ ! -f "${path}" ]; then
    return 1
  fi

  raw="$(cat "${path}" 2>/dev/null || true)"
  raw="$(printf '%s' "${raw}" | tr -d '\r')"
  raw="$(trim_value "${raw}")"
  if [ -z "${raw}" ]; then
    return 1
  fi

  normalized="$(normalize_special_value "${name}" "${raw}")"
  if [ -z "${normalized}" ]; then
    return 1
  fi
  printf '%s' "${normalized}"
}

cmd_backend() {
  echo "${KEYCHAIN_BACKEND}"
}

cmd_set() {
  local name="${1:-}"
  local value="${2:-}"
  if [ -z "${name}" ] || [ -z "${value}" ]; then
    echo "Usage: scripts/vera_secret_store.sh set <ENV_VAR> <VALUE>" >&2
    exit 1
  fi
  require_backend
  store_set "${name}" "${value}"
}

cmd_get() {
  local name="${1:-}"
  local value
  if [ -z "${name}" ]; then
    echo "Usage: scripts/vera_secret_store.sh get <ENV_VAR>" >&2
    exit 1
  fi
  require_backend
  value="$(store_get "${name}")"
  if [ -z "${value}" ]; then
    exit 1
  fi
  printf '%s\n' "${value}"
}

cmd_delete() {
  local name="${1:-}"
  if [ -z "${name}" ]; then
    echo "Usage: scripts/vera_secret_store.sh delete <ENV_VAR>" >&2
    exit 1
  fi
  require_backend
  store_delete "${name}"
}

cmd_load() {
  local names=("$@")
  local name value loaded_xai=""

  if ! has_backend; then
    return 0
  fi

  if [ "${#names[@]}" -eq 0 ]; then
    names=("${DEFAULT_VARS[@]}")
  fi

  for name in "${names[@]}"; do
    if [ -n "${!name:-}" ]; then
      continue
    fi
    value="$(store_get "${name}")"
    if [ -n "${value}" ]; then
      printf 'export %s=%q\n' "${name}" "${value}"
      if [ "${name}" = "XAI_API_KEY" ]; then
        loaded_xai="${value}"
      fi
    fi
  done

  if [ -z "${API_KEY:-}" ] && [ -n "${loaded_xai}" ]; then
    printf 'export API_KEY=%q\n' "${loaded_xai}"
  fi
}

cmd_status() {
  local names=("$@")
  local name value
  if [ "${#names[@]}" -eq 0 ]; then
    names=("${DEFAULT_VARS[@]}")
  fi
  echo "backend=${KEYCHAIN_BACKEND}"
  if ! has_backend; then
    return 0
  fi
  for name in "${names[@]}"; do
    value="$(store_get "${name}")"
    if [ -n "${value}" ]; then
      echo "${name}=present"
    else
      echo "${name}=missing"
    fi
  done
}

cmd_migrate_creds() {
  local creds_dir="${1:-${DEFAULT_CREDS_DIR}}"
  local name value imported=0 missing=0 failed=0
  require_backend

  for name in "${DEFAULT_VARS[@]}"; do
    if value="$(read_creds_value "${name}" "${creds_dir}")"; then
      if store_set "${name}" "${value}"; then
        imported=$((imported + 1))
        echo "[migrate] ${name} <- ${CREDS_PATHS[${name}]:-custom}"
      else
        failed=$((failed + 1))
        echo "[migrate] failed to store ${name}" >&2
      fi
    else
      missing=$((missing + 1))
    fi
  done

  echo "[migrate] complete: imported=${imported} missing=${missing} failed=${failed} creds_dir=${creds_dir}"
}

COMMAND="${1:-}"
if [ -z "${COMMAND}" ]; then
  print_usage
  exit 1
fi
shift || true

case "${COMMAND}" in
  backend)
    cmd_backend
    ;;
  set)
    cmd_set "$@"
    ;;
  get)
    cmd_get "$@"
    ;;
  delete)
    cmd_delete "$@"
    ;;
  load)
    cmd_load "$@"
    ;;
  status)
    cmd_status "$@"
    ;;
  migrate-creds)
    cmd_migrate_creds "$@"
    ;;
  -h|--help|help)
    print_usage
    ;;
  *)
    echo "Unknown command: ${COMMAND}" >&2
    print_usage
    exit 1
    ;;
esac
