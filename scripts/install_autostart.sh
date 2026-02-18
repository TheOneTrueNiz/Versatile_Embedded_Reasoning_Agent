#!/usr/bin/env bash
set -euo pipefail
# install_autostart.sh -- Install VERA system tray autostart for KDE/X11

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
AUTOSTART_DIR="${HOME}/.config/autostart"
DESKTOP_FILE="${AUTOSTART_DIR}/vera.desktop"
ICON_PATH="${ROOT_DIR}/ui/minimal-chat/dist/images/web/icon-192.png"

echo "=== VERA Autostart Installer ==="

# 1. System dependency
if ! python3 -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1')" 2>/dev/null; then
  echo "Installing system package: gir1.2-ayatanaappindicator3-0.1"
  sudo apt-get install -y gir1.2-ayatanaappindicator3-0.1
else
  echo "System dependency already installed."
fi

# 2. Python dependencies
if [ ! -f "${VENV_DIR}/.deps_tray" ]; then
  echo "Installing pystray and Pillow..."
  "${VENV_DIR}/bin/python" -m pip install --quiet pystray Pillow
  touch "${VENV_DIR}/.deps_tray"
else
  echo "Python tray dependencies already installed."
fi

# 3. Generate .desktop file
mkdir -p "${AUTOSTART_DIR}"
cat > "${DESKTOP_FILE}" <<EOF
[Desktop Entry]
Type=Application
Name=VERA
Comment=VERA AI Agent - System Tray
Exec=env VERA_TRAY_ENABLED=0 VERA_OPEN_BROWSER=0 ${VENV_DIR}/bin/python ${ROOT_DIR}/scripts/vera_tray.py
Path=${ROOT_DIR}
Icon=${ICON_PATH}
Terminal=false
Categories=Utility;
StartupNotify=false
X-KDE-autostart-after=panel
X-GNOME-Autostart-enabled=true
EOF

chmod 644 "${DESKTOP_FILE}"

echo ""
echo "Installed: ${DESKTOP_FILE}"
echo "VERA will start automatically on next login."
echo ""
echo "To start now:  ${VENV_DIR}/bin/python ${ROOT_DIR}/scripts/vera_tray.py"
echo "To uninstall:  rm ${DESKTOP_FILE}"
