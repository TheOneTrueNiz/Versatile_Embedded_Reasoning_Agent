#!/usr/bin/env bash
# Install and enable a boot-persistent systemd unit for Vera 2.0.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${1:-vera2}"
SERVICE_USER="${VERA_SERVICE_USER:-$(id -un)}"
SERVICE_GROUP="${VERA_SERVICE_GROUP:-$(id -gn)}"
SERVICE_HOME="${VERA_SERVICE_HOME:-$HOME}"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "Error: systemd/systemctl not available on this host." >&2
  exit 1
fi

sudo tee "${UNIT_PATH}" >/dev/null <<EOF
[Unit]
Description=VERA 2.0 Harness
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${ROOT_DIR}
Environment=HOME=${SERVICE_HOME}
Environment=PYTHONUNBUFFERED=1
Environment=VERA_MCP_AUTOSTART_FORCE=1
ExecStart=/bin/bash -lc 'cd ${ROOT_DIR} && ./scripts/run_vera_full.sh --no-verify --logging --cleanup --no-tray'
ExecStop=/bin/bash -lc 'cd ${ROOT_DIR} && ./scripts/cleanup_vera.sh'
Restart=on-failure
RestartSec=10
TimeoutStartSec=600
TimeoutStopSec=180
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"

echo "Installed ${UNIT_PATH}"
echo "Enabled ${SERVICE_NAME}.service"
echo "Start with: sudo systemctl start ${SERVICE_NAME}.service"
echo "Status with: sudo systemctl status ${SERVICE_NAME}.service --no-pager"
