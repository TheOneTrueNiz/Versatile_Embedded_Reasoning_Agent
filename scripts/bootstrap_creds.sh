#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CREDS_DIR="${HOME}/Documents/creds"
ENV_FILE="${ROOT_DIR}/scripts/vera_env.local"
export CREDS_DIR
DEFAULT_REDIRECT_URI="${GOOGLE_OAUTH_REDIRECT_URI:-http://127.0.0.1:8080/oauth2callback}"
USE_GUM=0
CREDS_POINTER="${CREDS_DIR}/.vera_creds_pointer"
BOOTSTRAP_SENTINEL="${CREDS_DIR}/.vera_bootstrap_complete"
THEME_PRIMARY=81
THEME_ACCENT=214
THEME_MUTED=245
THEME_BORDER=31

if command -v gum >/dev/null 2>&1; then
  USE_GUM=1
fi

if [ "${USE_GUM}" != "1" ]; then
  echo "gum is not installed. Falling back to basic prompts."
  echo "Install gum for the full interactive experience:"
  echo "  - Debian/Ubuntu (if available): sudo apt-get install gum"
  echo "  - Homebrew: brew install gum"
  echo "  - Go: go install github.com/charmbracelet/gum@latest"
fi

print_divider() {
  if [ "${USE_GUM}" = "1" ]; then
    gum style --foreground "${THEME_BORDER}" "------------------------------------------------------------"
  else
    printf '%s\n' "------------------------------------------------------------"
  fi
}

print_title() {
  local text="$1"
  if [ "${USE_GUM}" = "1" ]; then
    gum style \
      --border double \
      --border-foreground "${THEME_PRIMARY}" \
      --align center \
      --width 68 \
      --padding "1 2" \
      --foreground 255 \
      --bold \
      "${text}"
  else
    echo "${text}"
  fi
}

print_section() {
  local text="$1"
  if [ "${USE_GUM}" = "1" ]; then
    gum style --foreground "${THEME_PRIMARY}" --bold "${text}"
  else
    echo "${text}"
  fi
}

print_hint() {
  local text="$1"
  if [ "${USE_GUM}" = "1" ]; then
    gum style --foreground "${THEME_MUTED}" "${text}"
  else
    echo "${text}"
  fi
}

print_warn() {
  local text="$1"
  if [ "${USE_GUM}" = "1" ]; then
    gum style --foreground 203 --bold "${text}"
  else
    echo "${text}"
  fi
}

print_success() {
  local text="$1"
  if [ "${USE_GUM}" = "1" ]; then
    gum style --foreground 82 --bold "${text}"
  else
    echo "${text}"
  fi
}

print_card() {
  local text="$1"
  if [ "${USE_GUM}" = "1" ]; then
    printf '%s' "${text}" | gum style \
      --border rounded \
      --border-foreground "${THEME_BORDER}" \
      --padding "1 2" \
      --margin "1 0" \
      --foreground 255
  else
    echo "${text}"
  fi
}

print_markdown() {
  local text="$1"
  if [ "${USE_GUM}" = "1" ]; then
    printf '%s' "${text}" | gum format
  else
    printf '%s\n' "${text}"
  fi
}

prompt_value() {
  local label="$1"
  local secret="${2:-0}"
  local value=""

  if [ "${USE_GUM}" = "1" ]; then
    print_hint "${label}"
    if [ "${secret}" = "1" ]; then
      value="$(gum input --password --prompt "> ")"
    else
      value="$(gum input --prompt "> ")"
    fi
  else
    if [ "${secret}" = "1" ]; then
      read -r -s -p "${label}: " value || true
      echo
    else
      read -r -p "${label}: " value || true
    fi
  fi

  printf '%s' "${value}"
}

confirm_prompt() {
  local message="$1"
  if [ "${USE_GUM}" = "1" ]; then
    gum confirm --affirmative "Continue" --negative "Back" "${message}"
    return $?
  fi
  read -r -p "${message} [y/N]: " reply || true
  case "${reply}" in
    [yY]|[yY][eE][sS]) return 0 ;;
    *) return 1 ;;
  esac
}

normalize_url() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  if [ -n "${value}" ] && [[ ! "${value}" =~ ^https?:// ]]; then
    value="http://${value}"
  fi
  if [ -n "${value}" ] && [[ ! "${value}" =~ /v1/?$ ]]; then
    value="${value%/}/v1"
  fi
  printf '%s' "${value}"
}

selection_contains() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    if [ "${item}" = "${needle}" ]; then
      return 0
    fi
  done
  return 1
}

write_secret() {
  local path="$1"
  local value="$2"
  if [ -z "${value}" ]; then
    return 0
  fi
  mkdir -p "$(dirname "${path}")"
  printf '%s\n' "${value}" > "${path}"
}

write_env_line() {
  local key="$1"
  local value="$2"
  if [ -z "${key}" ]; then
    return 0
  fi
  mkdir -p "$(dirname "${ENV_FILE}")"
  if [ ! -f "${ENV_FILE}" ]; then
    touch "${ENV_FILE}"
  fi
  if grep -q "^export ${key}=" "${ENV_FILE}"; then
    sed -i "s|^export ${key}=.*|export ${key}=\"${value//\"/\\\"}\"|" "${ENV_FILE}"
  else
    printf 'export %s="%s"\n' "${key}" "${value//\"/\\\"}" >> "${ENV_FILE}"
  fi
}

mkdir -p "${CREDS_DIR}/"{xai,brave,git,searxng,google,local,telegram,whatsapp,discord}
printf 'VERA credentials live at: %s\n' "${CREDS_DIR}" > "${CREDS_POINTER}"

print_title "VERA FIRST-RUN SETUP"
print_card "Credentials are stored outside the repo.\n${CREDS_DIR}\n\nThis wizard configures the minimum required LLM access first."
if [ "${USE_GUM}" != "1" ]; then
  print_warn "Install gum to unlock the full interactive wizard."
fi

XAI_API_KEY="${XAI_API_KEY:-}"
LOCAL_LLM_BASE_URL="${VERA_LLM_BASE_URL:-${LOCAL_LLM_BASE_URL:-}}"
LOCAL_LLM_API_KEY="${VERA_LLM_API_KEY:-${LOCAL_LLM_API_KEY:-}}"
LOCAL_LLM_MODEL_ID="${VERA_MODEL:-${LOCAL_LLM_MODEL_ID:-}}"

print_section "Step 1 of 3 - Core LLM connection"
print_card "Choose XAI or a local OpenAI-compatible endpoint."

while [ -z "${XAI_API_KEY}" ] && [ -z "${LOCAL_LLM_BASE_URL}" ]; do
  choice=""
  if [ "${USE_GUM}" = "1" ]; then
    choice="$(gum choose \
      --header "Select a connection path" \
      --cursor-prefix "> " \
      --selected-prefix "[x] " \
      --height 5 \
      "XAI API key" \
      "Local OpenAI-compatible endpoint")"
  else
    read -r -p "Choose connection path [xai/local]: " choice || true
  fi

  case "${choice}" in
    "XAI API key"|"xai"|"XAI"|"Xai")
      XAI_API_KEY="$(prompt_value "XAI_API_KEY" 1)"
      ;;
    "Local OpenAI-compatible endpoint"|"local"|"LOCAL"|"Local")
      LOCAL_LLM_BASE_URL="$(prompt_value "LOCAL_LLM_BASE_URL (e.g., http://127.0.0.1:8788/v1)")"
      LOCAL_LLM_BASE_URL="$(normalize_url "${LOCAL_LLM_BASE_URL}")"
      ;;
    *)
      ;;
  esac

  if [ -z "${XAI_API_KEY}" ] && [ -z "${LOCAL_LLM_BASE_URL}" ]; then
    print_warn "You must provide either an XAI_API_KEY or a local endpoint."
    if ! confirm_prompt "Try again?"; then
      exit 1
    fi
  fi
done

if [ -n "${XAI_API_KEY}" ]; then
  write_secret "${CREDS_DIR}/xai/xai_api" "${XAI_API_KEY}"
fi

if [ -n "${LOCAL_LLM_BASE_URL}" ]; then
  write_secret "${CREDS_DIR}/local/llm_base_url" "${LOCAL_LLM_BASE_URL}"
  if [ -z "${LOCAL_LLM_API_KEY}" ]; then
    LOCAL_LLM_API_KEY="$(prompt_value "LOCAL_LLM_API_KEY (optional)" 1)"
  fi
  if [ -n "${LOCAL_LLM_API_KEY}" ]; then
    write_secret "${CREDS_DIR}/local/llm_api_key" "${LOCAL_LLM_API_KEY}"
  fi
  if [ -z "${LOCAL_LLM_MODEL_ID}" ]; then
    LOCAL_LLM_MODEL_ID="$(prompt_value "LOCAL_LLM_MODEL_ID (optional, e.g., llama-3.1-8b-instruct)")"
  fi
  if [ -n "${LOCAL_LLM_MODEL_ID}" ]; then
    write_secret "${CREDS_DIR}/local/model_id" "${LOCAL_LLM_MODEL_ID}"
  fi
fi

OPTIONAL_SELECTED=()
ENABLE_BRAVE=0
ENABLE_GITHUB=0
ENABLE_SEARXNG=0
ENABLE_OBSIDIAN=0
ENABLE_HUB=0
ENABLE_BROWSER=0
ENABLE_TELEGRAM=0
ENABLE_WHATSAPP=0
ENABLE_DISCORD=0
if [ "${USE_GUM}" = "1" ]; then
  print_section "Step 2 of 3 - Optional integrations"
  print_card "Select the integrations to configure right now.\nSpace to toggle, enter to continue."
  selection="$(gum choose --no-limit \
    --header "Select integrations to configure now" \
    --cursor-prefix "> " \
    --selected-prefix "[x] " \
    --unselected-prefix "[ ] " \
    --height 7 \
    "Brave Search" \
    "GitHub" \
    "Searxng" \
    "Obsidian Vault" \
    "Composio Hub" \
    "Browser Automation" \
    "Telegram" \
    "WhatsApp" \
    "Discord" \
    "Skip for now" || true)"
  if [ -n "${selection}" ]; then
    if printf '%s\n' "${selection}" | grep -q "Skip for now"; then
      selection=""
    fi
    mapfile -t OPTIONAL_SELECTED <<< "${selection}"
  fi
  if selection_contains "Brave Search" "${OPTIONAL_SELECTED[@]}"; then ENABLE_BRAVE=1; fi
  if selection_contains "GitHub" "${OPTIONAL_SELECTED[@]}"; then ENABLE_GITHUB=1; fi
  if selection_contains "Searxng" "${OPTIONAL_SELECTED[@]}"; then ENABLE_SEARXNG=1; fi
  if selection_contains "Obsidian Vault" "${OPTIONAL_SELECTED[@]}"; then ENABLE_OBSIDIAN=1; fi
  if selection_contains "Composio Hub" "${OPTIONAL_SELECTED[@]}"; then ENABLE_HUB=1; fi
  if selection_contains "Browser Automation" "${OPTIONAL_SELECTED[@]}"; then ENABLE_BROWSER=1; fi
  if selection_contains "Telegram" "${OPTIONAL_SELECTED[@]}"; then ENABLE_TELEGRAM=1; fi
  if selection_contains "WhatsApp" "${OPTIONAL_SELECTED[@]}"; then ENABLE_WHATSAPP=1; fi
  if selection_contains "Discord" "${OPTIONAL_SELECTED[@]}"; then ENABLE_DISCORD=1; fi
else
  if confirm_prompt "Configure Brave Search now?"; then ENABLE_BRAVE=1; fi
  if confirm_prompt "Configure GitHub now?"; then ENABLE_GITHUB=1; fi
  if confirm_prompt "Configure Searxng now?"; then ENABLE_SEARXNG=1; fi
  if confirm_prompt "Configure Obsidian Vault now?"; then ENABLE_OBSIDIAN=1; fi
  if confirm_prompt "Configure Composio Hub now?"; then ENABLE_HUB=1; fi
  if confirm_prompt "Enable Browser Automation now?"; then ENABLE_BROWSER=1; fi
  if confirm_prompt "Configure Telegram now?"; then ENABLE_TELEGRAM=1; fi
  if confirm_prompt "Configure WhatsApp now?"; then ENABLE_WHATSAPP=1; fi
  if confirm_prompt "Configure Discord now?"; then ENABLE_DISCORD=1; fi
fi

BRAVE_API_KEY="${BRAVE_API_KEY:-}"
if [ "${ENABLE_BRAVE}" = "1" ] && [ -z "${BRAVE_API_KEY}" ]; then
  BRAVE_API_KEY="$(prompt_value "BRAVE_API_KEY" 1)"
fi
write_secret "${CREDS_DIR}/brave/brave_api" "${BRAVE_API_KEY}"

GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PERSONAL_ACCESS_TOKEN:-}"
if [ "${ENABLE_GITHUB}" = "1" ] && [ -z "${GITHUB_PERSONAL_ACCESS_TOKEN}" ]; then
  GITHUB_PERSONAL_ACCESS_TOKEN="$(prompt_value "GITHUB_PERSONAL_ACCESS_TOKEN" 1)"
fi
write_secret "${CREDS_DIR}/git/git_token" "${GITHUB_PERSONAL_ACCESS_TOKEN}"

SEARXNG_BASE_URL="${SEARXNG_BASE_URL:-}"
if [ "${ENABLE_SEARXNG}" = "1" ] && [ -z "${SEARXNG_BASE_URL}" ]; then
  SEARXNG_BASE_URL="$(prompt_value "SEARXNG_BASE_URL (e.g., http://127.0.0.1:8081)")"
fi
write_secret "${CREDS_DIR}/searxng/searxng_url" "${SEARXNG_BASE_URL}"

OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-}"
if [ "${ENABLE_OBSIDIAN}" = "1" ] && [ -z "${OBSIDIAN_VAULT_PATH}" ]; then
  OBSIDIAN_VAULT_PATH="$(prompt_value "OBSIDIAN_VAULT_PATH (e.g., /home/you/Documents/VeraVault)")"
fi
write_secret "${CREDS_DIR}/obsidian/vault_path" "${OBSIDIAN_VAULT_PATH}"
if [ -n "${OBSIDIAN_VAULT_PATH}" ]; then
  write_env_line "OBSIDIAN_VAULT_PATH" "${OBSIDIAN_VAULT_PATH}"
fi

COMPOSIO_API_KEY="${COMPOSIO_API_KEY:-}"
if [ "${ENABLE_HUB}" = "1" ] && [ -z "${COMPOSIO_API_KEY}" ]; then
  COMPOSIO_API_KEY="$(prompt_value "COMPOSIO_API_KEY" 1)"
fi
write_secret "${CREDS_DIR}/composio/composio_api" "${COMPOSIO_API_KEY}"
if [ -n "${COMPOSIO_API_KEY}" ]; then
  write_env_line "COMPOSIO_API_KEY" "${COMPOSIO_API_KEY}"
fi

MCP_HUB_COMMAND="${MCP_HUB_COMMAND:-}"
if [ "${ENABLE_HUB}" = "1" ] && [ -z "${MCP_HUB_COMMAND}" ]; then
  MCP_HUB_COMMAND="$(prompt_value "MCP_HUB_COMMAND (e.g., composio mcp)" "composio mcp")"
fi
write_secret "${CREDS_DIR}/composio/command" "${MCP_HUB_COMMAND}"
if [ -n "${MCP_HUB_COMMAND}" ]; then
  write_env_line "MCP_HUB_COMMAND" "${MCP_HUB_COMMAND}"
fi

MCP_HUB_ARGS="${MCP_HUB_ARGS:-}"
if [ "${ENABLE_HUB}" = "1" ] && [ -z "${MCP_HUB_ARGS}" ]; then
  MCP_HUB_ARGS="$(prompt_value "MCP_HUB_ARGS (e.g., --tools facebook,agentmail,twitter)" "")"
fi
write_secret "${CREDS_DIR}/composio/args" "${MCP_HUB_ARGS}"
if [ -n "${MCP_HUB_ARGS}" ]; then
  write_env_line "MCP_HUB_ARGS" "${MCP_HUB_ARGS}"
fi

if [ "${ENABLE_BROWSER}" = "1" ]; then
  write_env_line "VERA_BROWSER" "1"
fi

TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_ALLOWED_CHATS="${TELEGRAM_ALLOWED_CHATS:-}"
TELEGRAM_ALLOWED_USERS="${TELEGRAM_ALLOWED_USERS:-}"
TELEGRAM_COMMAND_PREFIX="${TELEGRAM_COMMAND_PREFIX:-/}"
if [ "${ENABLE_TELEGRAM}" = "1" ] && [ -z "${TELEGRAM_BOT_TOKEN}" ]; then
  TELEGRAM_BOT_TOKEN="$(prompt_value "TELEGRAM_BOT_TOKEN" 1)"
  TELEGRAM_ALLOWED_CHATS="$(prompt_value "TELEGRAM_ALLOWED_CHATS (comma-separated, optional)")"
  TELEGRAM_ALLOWED_USERS="$(prompt_value "TELEGRAM_ALLOWED_USERS (comma-separated, optional)")"
  TELEGRAM_COMMAND_PREFIX="$(prompt_value "TELEGRAM_COMMAND_PREFIX (default /)")"
fi
if [ -z "${TELEGRAM_COMMAND_PREFIX}" ]; then
  TELEGRAM_COMMAND_PREFIX="/"
fi
write_secret "${CREDS_DIR}/telegram/bot_token" "${TELEGRAM_BOT_TOKEN}"
if [ -n "${TELEGRAM_BOT_TOKEN}" ]; then
  write_env_line "TELEGRAM_BOT_TOKEN" "${TELEGRAM_BOT_TOKEN}"
fi

WHATSAPP_ACCESS_TOKEN="${WHATSAPP_ACCESS_TOKEN:-}"
WHATSAPP_PHONE_NUMBER_ID="${WHATSAPP_PHONE_NUMBER_ID:-}"
WHATSAPP_VERIFY_TOKEN="${WHATSAPP_VERIFY_TOKEN:-}"
WHATSAPP_APP_SECRET="${WHATSAPP_APP_SECRET:-}"
WHATSAPP_ALLOWED_NUMBERS="${WHATSAPP_ALLOWED_NUMBERS:-}"
WHATSAPP_GRAPH_VERSION="${WHATSAPP_GRAPH_VERSION:-v20.0}"
if [ "${ENABLE_WHATSAPP}" = "1" ] && { [ -z "${WHATSAPP_ACCESS_TOKEN}" ] || [ -z "${WHATSAPP_PHONE_NUMBER_ID}" ]; }; then
  WHATSAPP_ACCESS_TOKEN="$(prompt_value "WHATSAPP_ACCESS_TOKEN" 1)"
  WHATSAPP_PHONE_NUMBER_ID="$(prompt_value "WHATSAPP_PHONE_NUMBER_ID")"
  WHATSAPP_VERIFY_TOKEN="$(prompt_value "WHATSAPP_VERIFY_TOKEN (optional)")"
  WHATSAPP_APP_SECRET="$(prompt_value "WHATSAPP_APP_SECRET (optional)")"
  WHATSAPP_ALLOWED_NUMBERS="$(prompt_value "WHATSAPP_ALLOWED_NUMBERS (comma-separated, optional)")"
  WHATSAPP_GRAPH_VERSION="$(prompt_value "WHATSAPP_GRAPH_VERSION (default v20.0)")"
fi
if [ -z "${WHATSAPP_GRAPH_VERSION}" ]; then
  WHATSAPP_GRAPH_VERSION="v20.0"
fi
write_secret "${CREDS_DIR}/whatsapp/access_token" "${WHATSAPP_ACCESS_TOKEN}"
write_secret "${CREDS_DIR}/whatsapp/phone_number_id" "${WHATSAPP_PHONE_NUMBER_ID}"
write_secret "${CREDS_DIR}/whatsapp/verify_token" "${WHATSAPP_VERIFY_TOKEN}"
write_secret "${CREDS_DIR}/whatsapp/app_secret" "${WHATSAPP_APP_SECRET}"
if [ -n "${WHATSAPP_ACCESS_TOKEN}" ]; then
  write_env_line "WHATSAPP_ACCESS_TOKEN" "${WHATSAPP_ACCESS_TOKEN}"
fi
if [ -n "${WHATSAPP_PHONE_NUMBER_ID}" ]; then
  write_env_line "WHATSAPP_PHONE_NUMBER_ID" "${WHATSAPP_PHONE_NUMBER_ID}"
fi
if [ -n "${WHATSAPP_VERIFY_TOKEN}" ]; then
  write_env_line "WHATSAPP_VERIFY_TOKEN" "${WHATSAPP_VERIFY_TOKEN}"
fi
if [ -n "${WHATSAPP_APP_SECRET}" ]; then
  write_env_line "WHATSAPP_APP_SECRET" "${WHATSAPP_APP_SECRET}"
fi
if [ -n "${WHATSAPP_GRAPH_VERSION}" ]; then
  write_env_line "WHATSAPP_GRAPH_VERSION" "${WHATSAPP_GRAPH_VERSION}"
fi

DISCORD_BOT_TOKEN="${DISCORD_BOT_TOKEN:-}"
DISCORD_ALLOWED_GUILDS="${DISCORD_ALLOWED_GUILDS:-}"
DISCORD_ALLOWED_USERS="${DISCORD_ALLOWED_USERS:-}"
DISCORD_COMMAND_PREFIX="${DISCORD_COMMAND_PREFIX:-!}"
if [ "${ENABLE_DISCORD}" = "1" ] && [ -z "${DISCORD_BOT_TOKEN}" ]; then
  DISCORD_BOT_TOKEN="$(prompt_value "DISCORD_BOT_TOKEN" 1)"
  DISCORD_ALLOWED_GUILDS="$(prompt_value "DISCORD_ALLOWED_GUILDS (comma-separated, optional)")"
  DISCORD_ALLOWED_USERS="$(prompt_value "DISCORD_ALLOWED_USERS (comma-separated, optional)")"
  DISCORD_COMMAND_PREFIX="$(prompt_value "DISCORD_COMMAND_PREFIX (default !)")"
fi
if [ -z "${DISCORD_COMMAND_PREFIX}" ]; then
  DISCORD_COMMAND_PREFIX="!"
fi
write_secret "${CREDS_DIR}/discord/bot_token" "${DISCORD_BOT_TOKEN}"
if [ -n "${DISCORD_BOT_TOKEN}" ]; then
  write_env_line "DISCORD_BOT_TOKEN" "${DISCORD_BOT_TOKEN}"
fi

CHANNELS_CONFIG_PATH="${ROOT_DIR}/config/channels.json"
CHANNELS_CONFIG_WRITTEN=0
if [ "${ENABLE_TELEGRAM}" = "1" ] || [ "${ENABLE_WHATSAPP}" = "1" ] || [ "${ENABLE_DISCORD}" = "1" ]; then
  export CHANNELS_CONFIG_PATH
  export ENABLE_TELEGRAM ENABLE_WHATSAPP ENABLE_DISCORD
  export TELEGRAM_ALLOWED_CHATS TELEGRAM_ALLOWED_USERS TELEGRAM_COMMAND_PREFIX
  export WHATSAPP_ALLOWED_NUMBERS WHATSAPP_GRAPH_VERSION
  export DISCORD_ALLOWED_GUILDS DISCORD_ALLOWED_USERS DISCORD_COMMAND_PREFIX
  python - <<'PY'
import json
import os
from pathlib import Path

def parse_list(value: str):
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None

channels = [{"type": "api", "enabled": True}]

if os.environ.get("ENABLE_DISCORD") == "1":
    settings = {
        "token_env": "DISCORD_BOT_TOKEN",
        "command_prefix": os.environ.get("DISCORD_COMMAND_PREFIX", "!") or "!",
    }
    guilds = parse_list(os.environ.get("DISCORD_ALLOWED_GUILDS", ""))
    users = parse_list(os.environ.get("DISCORD_ALLOWED_USERS", ""))
    if guilds:
        settings["allowed_guilds"] = guilds
    if users:
        settings["allowed_users"] = users
    channels.append({"type": "discord", "enabled": True, "settings": settings})

if os.environ.get("ENABLE_TELEGRAM") == "1":
    settings = {
        "token_env": "TELEGRAM_BOT_TOKEN",
        "command_prefix": os.environ.get("TELEGRAM_COMMAND_PREFIX", "/") or "/",
    }
    chats = parse_list(os.environ.get("TELEGRAM_ALLOWED_CHATS", ""))
    users = parse_list(os.environ.get("TELEGRAM_ALLOWED_USERS", ""))
    if chats:
        settings["allowed_chats"] = chats
    if users:
        settings["allowed_users"] = users
    channels.append({"type": "telegram", "enabled": True, "settings": settings})

if os.environ.get("ENABLE_WHATSAPP") == "1":
    settings = {
        "token_env": "WHATSAPP_ACCESS_TOKEN",
        "phone_number_id_env": "WHATSAPP_PHONE_NUMBER_ID",
        "verify_token_env": "WHATSAPP_VERIFY_TOKEN",
        "app_secret_env": "WHATSAPP_APP_SECRET",
        "graph_version": os.environ.get("WHATSAPP_GRAPH_VERSION", "v20.0") or "v20.0",
    }
    numbers = parse_list(os.environ.get("WHATSAPP_ALLOWED_NUMBERS", ""))
    if numbers:
        settings["allowed_numbers"] = numbers
    channels.append({"type": "whatsapp", "enabled": True, "settings": settings})

path = Path(os.environ["CHANNELS_CONFIG_PATH"])
path.parent.mkdir(parents=True, exist_ok=True)
payload = {"channels": channels}
path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"Saved channels config to {path}")
PY
  CHANNELS_CONFIG_WRITTEN=1
fi

GOOGLE_WORKSPACE_USER_EMAIL="${GOOGLE_WORKSPACE_USER_EMAIL:-}"
while [ -z "${GOOGLE_WORKSPACE_USER_EMAIL}" ]; do
  print_section "Workspace email (required)"
  GOOGLE_WORKSPACE_USER_EMAIL="$(prompt_value "GOOGLE_WORKSPACE_USER_EMAIL (e.g., you@gmail.com)")"
  if [ -z "${GOOGLE_WORKSPACE_USER_EMAIL}" ]; then
    print_warn "Workspace email is required to start Vera."
  fi
done
write_secret "${CREDS_DIR}/google/user_email" "${GOOGLE_WORKSPACE_USER_EMAIL}"

GOOGLE_OAUTH_CLIENT_ID="${GOOGLE_OAUTH_CLIENT_ID:-${GOOGLE_CLIENT_ID:-}}"
GOOGLE_OAUTH_CLIENT_SECRET="${GOOGLE_OAUTH_CLIENT_SECRET:-${GOOGLE_CLIENT_SECRET:-}}"
if [ -z "${GOOGLE_OAUTH_CLIENT_ID}" ] || [ -z "${GOOGLE_OAUTH_CLIENT_SECRET}" ]; then
  if confirm_prompt "Configure Google OAuth now?"; then
    if [ -z "${GOOGLE_OAUTH_CLIENT_ID}" ]; then
      GOOGLE_OAUTH_CLIENT_ID="$(prompt_value "GOOGLE_OAUTH_CLIENT_ID" 1)"
    fi
    if [ -z "${GOOGLE_OAUTH_CLIENT_SECRET}" ]; then
      GOOGLE_OAUTH_CLIENT_SECRET="$(prompt_value "GOOGLE_OAUTH_CLIENT_SECRET" 1)"
    fi
  fi
fi

GOOGLE_OAUTH_REDIRECT_URI="${GOOGLE_OAUTH_REDIRECT_URI:-${GOOGLE_REDIRECT_URI:-${DEFAULT_REDIRECT_URI}}}"

if [ -n "${GOOGLE_OAUTH_CLIENT_ID}" ] && [ -n "${GOOGLE_OAUTH_CLIENT_SECRET}" ]; then
  GOOGLE_OAUTH_JSON_PATH="${CREDS_DIR}/google/client_secret_generated.json"
  export GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET GOOGLE_OAUTH_REDIRECT_URI GOOGLE_OAUTH_JSON_PATH
  python - <<'PY'
import json
import os
from pathlib import Path

client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "")
path = Path(os.environ["GOOGLE_OAUTH_JSON_PATH"]).expanduser()
payload = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    }
}
if redirect_uri:
    payload["installed"]["redirect_uris"] = [redirect_uri]
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2, ensure_ascii=True))
print(f"Saved Google OAuth client config to {path}")
PY
fi

print_section "Step 3 of 3 - Summary"
summary_lines=()
if [ -n "${XAI_API_KEY}" ]; then
  summary_lines+=("LLM: XAI API key set")
else
  summary_lines+=("LLM: Local endpoint ${LOCAL_LLM_BASE_URL:-missing}")
fi
if [ -n "${LOCAL_LLM_MODEL_ID}" ]; then
  summary_lines+=("Local model id: ${LOCAL_LLM_MODEL_ID}")
fi
if [ -n "${BRAVE_API_KEY}" ]; then
  summary_lines+=("Brave: configured")
else
  summary_lines+=("Brave: missing")
fi
if [ -n "${GITHUB_PERSONAL_ACCESS_TOKEN}" ]; then
  summary_lines+=("GitHub: configured")
else
  summary_lines+=("GitHub: missing")
fi
if [ -n "${SEARXNG_BASE_URL}" ]; then
  summary_lines+=("Searxng: configured")
else
  summary_lines+=("Searxng: missing")
fi
if [ -n "${OBSIDIAN_VAULT_PATH}" ]; then
  summary_lines+=("Obsidian vault: configured")
else
  summary_lines+=("Obsidian vault: missing")
fi
if [ -n "${MCP_HUB_COMMAND}" ]; then
  summary_lines+=("Composio hub: configured")
else
  summary_lines+=("Composio hub: missing")
fi
if [ "${ENABLE_TELEGRAM}" = "1" ]; then
  summary_lines+=("Telegram: enabled")
else
  summary_lines+=("Telegram: skipped")
fi
if [ "${ENABLE_WHATSAPP}" = "1" ]; then
  summary_lines+=("WhatsApp: enabled")
else
  summary_lines+=("WhatsApp: skipped")
fi
if [ "${ENABLE_DISCORD}" = "1" ]; then
  summary_lines+=("Discord: enabled")
else
  summary_lines+=("Discord: skipped")
fi
if [ "${CHANNELS_CONFIG_WRITTEN}" = "1" ]; then
  summary_lines+=("Channels config: ${CHANNELS_CONFIG_PATH}")
fi
if [ -n "${VERA_BROWSER:-}" ]; then
  summary_lines+=("Browser automation: enabled")
else
  summary_lines+=("Browser automation: disabled")
fi
if [ -n "${GOOGLE_WORKSPACE_USER_EMAIL}" ] && [ -n "${GOOGLE_OAUTH_CLIENT_ID}" ] && [ -n "${GOOGLE_OAUTH_CLIENT_SECRET}" ]; then
  summary_lines+=("Google Workspace: configured")
else
  summary_lines+=("Google Workspace: missing")
fi
summary_text="$(printf '%s\n' "${summary_lines[@]}")"
print_card "${summary_text}"
print_divider

MISSING_FEATURES=()
if [ -z "${BRAVE_API_KEY}" ]; then
  MISSING_FEATURES+=("Brave Search tools")
fi
if [ -z "${GITHUB_PERSONAL_ACCESS_TOKEN}" ]; then
  MISSING_FEATURES+=("GitHub tools")
fi
if [ -z "${SEARXNG_BASE_URL}" ]; then
  MISSING_FEATURES+=("Searxng web search")
fi
if [ -z "${OBSIDIAN_VAULT_PATH}" ]; then
  MISSING_FEATURES+=("Obsidian vault memory")
fi
if [ -z "${MCP_HUB_COMMAND}" ]; then
  MISSING_FEATURES+=("Composio hub integrations")
fi
if [ "${ENABLE_TELEGRAM}" != "1" ] && [ "${ENABLE_WHATSAPP}" != "1" ] && [ "${ENABLE_DISCORD}" != "1" ]; then
  MISSING_FEATURES+=("Messaging channels (Telegram, WhatsApp, Discord)")
fi
if [ -z "${GOOGLE_WORKSPACE_USER_EMAIL}" ] || [ -z "${GOOGLE_OAUTH_CLIENT_ID}" ] || [ -z "${GOOGLE_OAUTH_CLIENT_SECRET}" ]; then
  MISSING_FEATURES+=("Google Workspace tools (Gmail, Calendar, Drive)")
fi

if [ "${#MISSING_FEATURES[@]}" -gt 0 ]; then
  print_warn "Optional integrations skipped:"
  for item in "${MISSING_FEATURES[@]}"; do
    print_hint "  - ${item}"
  done
  print_hint "You can add these later in Settings > Configuration > API Connections."
  if ! confirm_prompt "Continue without these integrations?"; then
    exit 1
  fi
fi

printf 'complete\n' > "${BOOTSTRAP_SENTINEL}"
print_success "Credentials saved under ${CREDS_DIR}."
