#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
SERVICE_NAME="vera-doctor-professor-trigger"
TIMER_NAME="${SERVICE_NAME}.timer"
SERVICE_FILE="${UNIT_DIR}/${SERVICE_NAME}.service"
TIMER_FILE="${UNIT_DIR}/${TIMER_NAME}"

INTERVAL_MINUTES="${1:-5}"
COOLDOWN_MINUTES="${2:-60}"
TARGET_RUNNING_MCP="${3:-23}"
CRITICAL_RUNNING_MCP="${4:-20}"
STARTUP_GRACE_MINUTES="${5:-12}"
WARNING_STREAK="${6:-2}"
CLEAR_HEALTHY_STREAK="${7:-2}"
MAX_TRIGGERS_PER_DAY="${8:-6}"

mkdir -p "${UNIT_DIR}"

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Trigger Doctor/Professor CI diagnostics on Vera failures
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${ROOT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash -lc 'cd "${ROOT_DIR}" && python3 "${ROOT_DIR}/scripts/vera_doctor_professor_failure_trigger.py" --base-url http://127.0.0.1:8788 --target-running-mcp ${TARGET_RUNNING_MCP} --critical-running-mcp ${CRITICAL_RUNNING_MCP} --startup-grace-minutes ${STARTUP_GRACE_MINUTES} --warning-consecutive-failures ${WARNING_STREAK} --clear-healthy-streak ${CLEAR_HEALTHY_STREAK} --cooldown-minutes ${COOLDOWN_MINUTES} --max-triggers-per-day ${MAX_TRIGGERS_PER_DAY}'
Nice=10
EOF

cat > "${TIMER_FILE}" <<EOF
[Unit]
Description=Check Vera health every ${INTERVAL_MINUTES}m and trigger Doctor/Professor diagnostics on failures

[Timer]
OnBootSec=3m
OnUnitActiveSec=${INTERVAL_MINUTES}m
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
echo "Check interval: every ${INTERVAL_MINUTES} minutes"
echo "Trigger cooldown: ${COOLDOWN_MINUTES} minutes"
echo "MCP target floor: < ${TARGET_RUNNING_MCP} (warning)"
echo "MCP critical floor: < ${CRITICAL_RUNNING_MCP} (critical)"
echo "Startup grace: ${STARTUP_GRACE_MINUTES} minutes"
echo "Warning streak required: ${WARNING_STREAK}"
echo "Healthy clears required: ${CLEAR_HEALTHY_STREAK}"
echo "Max triggers per day: ${MAX_TRIGGERS_PER_DAY}"
echo ""
echo "Status:"
echo "  systemctl --user status ${TIMER_NAME} --no-pager"
echo "Latest trigger state:"
echo "  cat ${ROOT_DIR}/tmp/doctor_professor_failure_trigger_state.json"
