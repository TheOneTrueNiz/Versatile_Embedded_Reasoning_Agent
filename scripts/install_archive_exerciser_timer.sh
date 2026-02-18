#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
SERVICE_NAME="vera-archive-exerciser"
TIMER_NAME="${SERVICE_NAME}.timer"
SERVICE_FILE="${UNIT_DIR}/${SERVICE_NAME}.service"
TIMER_FILE="${UNIT_DIR}/${TIMER_NAME}"

PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
if [ ! -x "${PYTHON_BIN}" ]; then
  PYTHON_BIN="python3"
fi

INTERVAL_MINUTES="${1:-30}"
OUT_DIR="${2:-${ROOT_DIR}/tmp/archive_exerciser}"

mkdir -p "${UNIT_DIR}"
mkdir -p "${OUT_DIR}"

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=VERA Archive Exerciser Probe
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${ROOT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash -lc 'cd "${ROOT_DIR}" && "${ROOT_DIR}/scripts/run_archive_exerciser_once.sh" "${OUT_DIR}"'
Nice=10
EOF

cat > "${TIMER_FILE}" <<EOF
[Unit]
Description=Run VERA archive exerciser every ${INTERVAL_MINUTES}m

[Timer]
OnBootSec=7m
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
echo "Output directory: ${OUT_DIR}"
echo ""
echo "Check timer status:"
echo "  systemctl --user status ${TIMER_NAME} --no-pager"
echo "List recent runs:"
echo "  ls -1 ${OUT_DIR} | tail -n 10"
