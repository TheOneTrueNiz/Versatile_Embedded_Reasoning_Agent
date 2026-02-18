#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
SERVICE_NAME="vera-followthrough-executor"
TIMER_NAME="${SERVICE_NAME}.timer"
SERVICE_FILE="${UNIT_DIR}/${SERVICE_NAME}.service"
TIMER_FILE="${UNIT_DIR}/${TIMER_NAME}"

INTERVAL_MINUTES="${1:-20}"
BASE_URL="${2:-http://127.0.0.1:8788}"
MAX_RUNS_PER_PASS="${3:-1}"
COOLDOWN_MINUTES="${4:-45}"
GRACE_MINUTES="${5:-30}"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [ ! -x "${PYTHON_BIN}" ]; then
  PYTHON_BIN="python3"
fi

mkdir -p "${UNIT_DIR}"

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=VERA follow-through executor (ledger + autonomy bundle)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${ROOT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash -lc 'cd "${ROOT_DIR}" && "${PYTHON_BIN}" "${ROOT_DIR}/scripts/vera_followthrough_executor.py" --base-url "${BASE_URL}" --vera-root "${ROOT_DIR}" --max-runs-per-pass ${MAX_RUNS_PER_PASS} --attempt-cooldown-minutes ${COOLDOWN_MINUTES} --grace-minutes ${GRACE_MINUTES}'
Nice=10
EOF

cat > "${TIMER_FILE}" <<EOF
[Unit]
Description=Run VERA follow-through executor every ${INTERVAL_MINUTES}m

[Timer]
OnBootSec=6m
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
echo "Interval: every ${INTERVAL_MINUTES} minutes"
echo "Base URL: ${BASE_URL}"
echo "Max runs/pass: ${MAX_RUNS_PER_PASS}"
echo "Cooldown minutes: ${COOLDOWN_MINUTES}"
echo "Grace minutes: ${GRACE_MINUTES}"
echo ""
echo "Status:"
echo "  systemctl --user status ${TIMER_NAME} --no-pager"
echo "Latest ledger:"
echo "  cat ${ROOT_DIR}/tmp/followthrough_state.json"

