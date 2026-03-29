#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERA_API_HOST="${VERA_API_HOST:-127.0.0.1}"
VERA_API_PORT="${VERA_API_PORT:-8788}"
HALT_FILE="${ROOT_DIR}/vera_memory/manual_halt"

NO_SEARXNG=0
START_ARGS=()
FORCE_DIRECT=0
TRAY_SERVICE_WAS_ACTIVE=0

usage() {
  cat <<'EOF'
Usage: ./scripts/restart_vera.sh [--no-searxng] [--direct] [additional run_vera_full.sh args...]

Deterministic VERA restart helper:
1. writes the manual_halt sentinel
2. runs cleanup_vera.sh --force
3. waits for the API port to close
4. removes manual_halt
5. relaunches VERA

If `vera-tray.service` is active under `systemd --user`, the helper restarts through
that service unless `--direct` is provided.

Defaults passed to run_vera_full.sh when not overridden:
  --logging --quiet --no-verify --no-tray
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --no-searxng)
      NO_SEARXNG=1
      ;;
    --direct)
      FORCE_DIRECT=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      START_ARGS+=("$1")
      ;;
  esac
  shift
done

mkdir -p "${ROOT_DIR}/vera_memory"

if [ "${FORCE_DIRECT}" = "0" ] && command -v systemctl >/dev/null 2>&1; then
  if systemctl --user is-active --quiet vera-tray.service; then
    TRAY_SERVICE_WAS_ACTIVE=1
  fi
fi

: > "${HALT_FILE}"

CLEANUP_ARGS=(--force)
if [ "${NO_SEARXNG}" = "1" ]; then
  CLEANUP_ARGS+=(--no-searxng)
fi

"${ROOT_DIR}/scripts/cleanup_vera.sh" "${CLEANUP_ARGS[@]}"

for _ in $(seq 1 30); do
  if ! curl -fsS "http://${VERA_API_HOST}:${VERA_API_PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

rm -f "${HALT_FILE}"

if [ "${TRAY_SERVICE_WAS_ACTIVE}" = "1" ]; then
  systemctl --user start vera-tray.service
  exit 0
fi

if [ "${#START_ARGS[@]}" -eq 0 ]; then
  START_ARGS=(--logging --quiet --no-verify --no-tray)
fi

exec "${ROOT_DIR}/scripts/run_vera_full.sh" "${START_ARGS[@]}"
