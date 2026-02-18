#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
SERVICE_NAME="vera-lora-cadence"
TIMER_NAME="${SERVICE_NAME}.timer"
SERVICE_FILE="${UNIT_DIR}/${SERVICE_NAME}.service"
TIMER_FILE="${UNIT_DIR}/${TIMER_NAME}"

INTERVAL_DAYS="${1:-30}"
HOST="${2:-127.0.0.1}"
PORT="${3:-8788}"
TIMEOUT_SECONDS="${4:-300}"
MEMORY_DIR="${5:-vera_memory}"
RANDOM_DELAY_MINUTES="${6:-45}"
RUN_CYCLE_ON_READINESS_FAIL="${7:-0}"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [ ! -x "${PYTHON_BIN}" ]; then
  PYTHON_BIN="python3"
fi

mkdir -p "${UNIT_DIR}"
mkdir -p "${ROOT_DIR}/tmp/lora_cadence"

OPTIONAL_FLAGS=""
if [ "${RUN_CYCLE_ON_READINESS_FAIL}" = "1" ]; then
  OPTIONAL_FLAGS="${OPTIONAL_FLAGS} --run-cycle-on-readiness-fail"
fi

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=VERA periodic LoRA cadence gate (readiness + forced cycle)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${ROOT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash -lc 'cd "${ROOT_DIR}" && TS=\$(date -u +%Y%m%dT%H%M%SZ) && "${PYTHON_BIN}" "${ROOT_DIR}/scripts/lora_cutover_check.py" --compact --memory-dir "${MEMORY_DIR}" --host "${HOST}" --port "${PORT}" --timeout "${TIMEOUT_SECONDS}"${OPTIONAL_FLAGS} > "${ROOT_DIR}/tmp/lora_cadence/lora_cutover_\${TS}.json"'
Nice=10
EOF

cat > "${TIMER_FILE}" <<EOF
[Unit]
Description=Run VERA LoRA cadence gate every ${INTERVAL_DAYS}d

[Timer]
OnBootSec=15m
OnUnitActiveSec=${INTERVAL_DAYS}d
RandomizedDelaySec=${RANDOM_DELAY_MINUTES}m
Persistent=true
Unit=${SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "${TIMER_NAME}"

echo "Installed ${SERVICE_FILE}"
echo "Installed ${TIMER_FILE}"
echo "Enabled timer: ${TIMER_NAME}"
echo "Interval: every ${INTERVAL_DAYS} day(s)"
echo "Host/Port: ${HOST}:${PORT}"
echo "Run-cycle on readiness fail: ${RUN_CYCLE_ON_READINESS_FAIL}"
echo "Output: ${ROOT_DIR}/tmp/lora_cadence/lora_cutover_<timestamp>.json"
echo ""
echo "Status:"
echo "  systemctl --user status ${TIMER_NAME} --no-pager"
echo "Recent runs:"
echo "  ls -1 ${ROOT_DIR}/tmp/lora_cadence | tail -n 10"
