#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ENV_FILE="${ROOT_DIR}/scripts/vera_env.local"
WHEELHOUSE_DIR="${VERA_WHEELHOUSE_DIR:-${ROOT_DIR}/wheelhouse}"
VENV_SEED_ARCHIVE="${WHEELHOUSE_DIR}/venv_seed.tar.gz"
REQ_FILE="${ROOT_DIR}/requirements.txt"
DEPS_CORE_MARKER="${VENV_DIR}/.deps_core"
DEPS_CORE_SHA_FILE="${VENV_DIR}/.deps_core_sha256"

compute_sha256() {
  local file_path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${file_path}" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${file_path}" | awk '{print $1}'
  else
    return 1
  fi
}

prune_preseed_backups() {
  local always_keep_basename="${1:-}"
  local keep_raw keep idx keep_slots
  local old_backup
  local backups=()
  local prune_candidates=()
  local kept_from_candidates=0
  local always_keep_found=0

  if [ "${VERA_KEEP_ALL_PRESEED_BACKUPS:-0}" = "1" ]; then
    echo "[VERA] Keeping all pre-seed backups (VERA_KEEP_ALL_PRESEED_BACKUPS=1)."
    return 0
  fi

  keep_raw="${VERA_PRESEED_BACKUPS_TO_KEEP:-1}"
  if [[ "${keep_raw}" =~ ^[0-9]+$ ]] && [ "${keep_raw}" -ge 1 ]; then
    keep="${keep_raw}"
  else
    keep=1
    echo "[VERA] Invalid VERA_PRESEED_BACKUPS_TO_KEEP='${keep_raw}', defaulting to 1."
  fi

  mapfile -t backups < <(find "${ROOT_DIR}" -maxdepth 1 -mindepth 1 -type d -name '.venv__pre_seed_*' -printf '%f\n' | sort -r)
  if [ "${#backups[@]}" -eq 0 ]; then
    return 0
  fi

  keep_slots="${keep}"
  if [ -n "${always_keep_basename}" ]; then
    for old_backup in "${backups[@]}"; do
      if [ "${old_backup}" = "${always_keep_basename}" ]; then
        always_keep_found=1
        break
      fi
    done
  fi

  if [ "${always_keep_found}" -eq 1 ] && [ "${keep_slots}" -gt 0 ]; then
    keep_slots=$((keep_slots - 1))
  fi

  for old_backup in "${backups[@]}"; do
    if [ -n "${always_keep_basename}" ] && [ "${old_backup}" = "${always_keep_basename}" ]; then
      continue
    fi
    prune_candidates+=("${old_backup}")
  done

  if [ "${#prune_candidates[@]}" -le "${keep_slots}" ]; then
    return 0
  fi

  echo "[VERA] Pruning pre-seed backups: keeping ${keep} total backup(s), pruning $(( ${#prune_candidates[@]} - keep_slots ))."
  if [ "${always_keep_found}" -eq 1 ]; then
    echo "[VERA] Preserving current-run backup: ${ROOT_DIR}/${always_keep_basename}"
  fi
  for ((idx=0; idx<${#prune_candidates[@]}; idx++)); do
    if [ "${kept_from_candidates}" -lt "${keep_slots}" ]; then
      kept_from_candidates=$((kept_from_candidates + 1))
      continue
    fi
    old_backup="${ROOT_DIR}/${prune_candidates[$idx]}"
    rm -rf "${old_backup}"
    echo "[VERA] Pruned pre-seed backup: ${old_backup}"
  done
}

restore_venv_from_seed() {
  local seed_archive="$1"
  local timestamp backup_path

  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup_path=""

  deactivate >/dev/null 2>&1 || true
  if [ -d "${VENV_DIR}" ]; then
    backup_path="${ROOT_DIR}/.venv__pre_seed_${timestamp}"
    mv "${VENV_DIR}" "${backup_path}"
    echo "[VERA] Backed up existing .venv to ${backup_path}"
  fi

  if tar -xzf "${seed_archive}" -C "${ROOT_DIR}"; then
    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"
    if [ -n "${backup_path}" ]; then
      echo "[VERA] Seed restore succeeded; previous venv backup kept at ${backup_path}"
      prune_preseed_backups "$(basename "${backup_path}")"
    else
      prune_preseed_backups
    fi
    return 0
  fi

  echo "[VERA] Seed restore failed from ${seed_archive}" >&2
  rm -rf "${VENV_DIR}"
  if [ -n "${backup_path}" ] && [ -d "${backup_path}" ]; then
    mv "${backup_path}" "${VENV_DIR}"
    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"
    echo "[VERA] Rolled back to pre-seed .venv after restore failure." >&2
  fi
  return 1
}

if [ -f "${ENV_FILE}" ]; then
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
fi

if [ "${VERA_MAX:-0}" = "1" ]; then
  export VERA_VOICE=1
  export VERA_BROWSER=1
  export VERA_DESKTOP=1
  export VERA_PDF=1
  export VERA_MCP_LOCAL=1
fi
if [ "${VERA_MEMVID_ENABLED:-0}" = "1" ] || [ "${VERA_MEMVID_ENABLED:-0}" = "true" ]; then
  echo "[VERA] Memvid fast recall is experimental in VERA 2.0 and disabled by default."
  echo "[VERA] Proceeding because VERA_MEMVID_ENABLED is set."
fi

if [ ! -d "${VENV_DIR}" ]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

REQ_SHA=""
if [ -f "${REQ_FILE}" ]; then
  if ! REQ_SHA="$(compute_sha256 "${REQ_FILE}")"; then
    echo "[VERA] Warning: sha256 tool unavailable; skipping requirements drift check." >&2
    REQ_SHA=""
  fi
fi

NEEDS_CORE_INSTALL=0
if [ "${VERA_FORCE_INSTALL:-0}" = "1" ] || [ ! -f "${DEPS_CORE_MARKER}" ]; then
  NEEDS_CORE_INSTALL=1
elif [ -n "${REQ_SHA}" ]; then
  if [ ! -f "${DEPS_CORE_SHA_FILE}" ]; then
    echo "[VERA] requirements.txt hash stamp missing; reinstalling core deps."
    NEEDS_CORE_INSTALL=1
  else
    STORED_REQ_SHA="$(tr -d '[:space:]' < "${DEPS_CORE_SHA_FILE}")"
    if [ "${STORED_REQ_SHA}" != "${REQ_SHA}" ]; then
      echo "[VERA] requirements.txt changed; reinstalling core deps."
      NEEDS_CORE_INSTALL=1
    fi
  fi
fi

if [ "${NEEDS_CORE_INSTALL}" = "1" ]; then
  WHEEL_COUNT=0
  if [ -d "${WHEELHOUSE_DIR}" ]; then
    WHEEL_COUNT="$(find "${WHEELHOUSE_DIR}" -maxdepth 1 -type f -name '*.whl' | wc -l | tr -d '[:space:]')"
  fi

  if [ "${WHEEL_COUNT}" -gt 0 ]; then
    echo "[VERA] Installing core deps from local wheelhouse: ${WHEELHOUSE_DIR}"
    if ! python -m pip install --no-index --find-links "${WHEELHOUSE_DIR}" -r "${ROOT_DIR}/requirements.txt"; then
      if [ -f "${VENV_SEED_ARCHIVE}" ]; then
        echo "[VERA] Wheelhouse install incomplete; restoring venv seed archive: ${VENV_SEED_ARCHIVE}"
        if ! restore_venv_from_seed "${VENV_SEED_ARCHIVE}"; then
          exit 1
        fi
      else
        echo "[VERA] Offline install failed and no venv seed archive was found at ${VENV_SEED_ARCHIVE}" >&2
        exit 1
      fi
    fi
  elif [ -f "${VENV_SEED_ARCHIVE}" ]; then
    echo "[VERA] Wheelhouse has no .whl files; restoring venv seed archive: ${VENV_SEED_ARCHIVE}"
    if ! restore_venv_from_seed "${VENV_SEED_ARCHIVE}"; then
      exit 1
    fi
  else
    python -m pip install --upgrade pip
    python -m pip install -r "${ROOT_DIR}/requirements.txt"
  fi
  touch "${DEPS_CORE_MARKER}"
  if [ -n "${REQ_SHA}" ]; then
    printf '%s\n' "${REQ_SHA}" > "${DEPS_CORE_SHA_FILE}"
  fi
fi

# Optional extras
if [ "${VERA_VOICE:-0}" = "1" ]; then
  if [ "${VERA_FORCE_INSTALL:-0}" = "1" ] || [ ! -f "${VENV_DIR}/.deps_voice" ]; then
    python -m pip install websockets
    python -m pip install sounddevice numpy scipy || true
    python -m pip install pyaudio || true
    touch "${VENV_DIR}/.deps_voice"
  fi
fi

if [ "${VERA_BROWSER:-0}" = "1" ]; then
  if [ "${VERA_FORCE_INSTALL:-0}" = "1" ] || [ ! -f "${VENV_DIR}/.deps_browser" ]; then
    python -m pip install playwright
    python -m playwright install chromium
    touch "${VENV_DIR}/.deps_browser"
  fi
fi

if [ "${VERA_DESKTOP:-0}" = "1" ]; then
  if [ "${VERA_FORCE_INSTALL:-0}" = "1" ] || [ ! -f "${VENV_DIR}/.deps_desktop" ]; then
    python -m pip install pyautogui
    touch "${VENV_DIR}/.deps_desktop"
  fi
fi

if [ "${VERA_PDF:-0}" = "1" ]; then
  if [ "${VERA_FORCE_INSTALL:-0}" = "1" ] || [ ! -f "${VENV_DIR}/.deps_pdf" ]; then
    python -m pip install aiohttp
    touch "${VENV_DIR}/.deps_pdf"
  fi
fi

if [ "${VERA_MCP_LOCAL:-0}" = "1" ]; then
  if [ -f "${ROOT_DIR}/scripts/run_memvid_mcp.sh" ]; then
    chmod +x "${ROOT_DIR}/scripts/run_memvid_mcp.sh" || true
  fi
  if [ "${VERA_FORCE_INSTALL:-0}" = "1" ] || [ ! -f "${VENV_DIR}/.deps_mcp_local" ]; then
    if [ -f "${ROOT_DIR}/mcp_server_and_tools/mcp_pdf_reader/requirements.txt" ]; then
      python -m pip install -r "${ROOT_DIR}/mcp_server_and_tools/mcp_pdf_reader/requirements.txt"
    fi
    if [ "${VERA_MEMVID_MCP_ENABLED:-0}" = "1" ] || [ "${VERA_MEMVID_MCP_ENABLED:-0}" = "true" ]; then
      if [ -f "${ROOT_DIR}/mcp_server_and_tools/memvid/requirements.txt" ]; then
        python -m pip install -r "${ROOT_DIR}/mcp_server_and_tools/memvid/requirements.txt"
      fi
    else
      echo "[VERA] Skipping memvid MCP deps (set VERA_MEMVID_MCP_ENABLED=1 to enable)."
    fi
    touch "${VENV_DIR}/.deps_mcp_local"
  fi
fi

if [ -z "${XAI_API_KEY:-}" ]; then
  echo "XAI_API_KEY not set. Export it first: export XAI_API_KEY=\"...\""
fi

if [ "${VERA_NO_RUN:-0}" = "1" ]; then
  exit 0
fi

exec python "${ROOT_DIR}/run_vera.py" "$@"
