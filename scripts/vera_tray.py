#!/usr/bin/env python3
"""
VERA System Tray Controller
============================
Top-level process that manages the VERA runtime lifecycle with a KDE/X11
system tray icon.  Provides visual status feedback, notifications, and
quick-access controls.

Requirements (system):
    sudo apt-get install gir1.2-ayatanaappindicator3-0.1

Requirements (pip):
    pip install pystray Pillow
"""

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from enum import Enum
from pathlib import Path

# Make system PyGObject visible inside the venv so pystray can use the
# AppIndicator3 backend on KDE Plasma 6.
_SYSTEM_DIST = "/usr/lib/python3/dist-packages"
if _SYSTEM_DIST not in sys.path:
    sys.path.insert(0, _SYSTEM_DIST)

import pystray  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

# pystray's Linux GTK backend initializes a DBus notifier by default.
# On some setups, org.freedesktop.Notifications may be slow/unavailable,
# which can crash tray startup. Wrap the notifier so tray icon stays alive.
try:
    from pystray._util import notify_dbus as _notify_dbus  # type: ignore
except Exception:
    _notify_dbus = None

if _notify_dbus is not None:
    _ORIG_NOTIFIER = _notify_dbus.Notifier

    class _SafeNotifier:
        def __init__(self):
            self._inner = None
            try:
                self._inner = _ORIG_NOTIFIER()
            except Exception as exc:
                logging.getLogger("vera_tray").warning(
                    "Tray notifications unavailable; continuing without notifier: %s",
                    exc,
                )

        def notify(self, title, message, icon):
            if self._inner is None:
                return
            try:
                self._inner.notify(title, message, icon)
            except Exception:
                pass

        def hide(self):
            if self._inner is None:
                return
            try:
                self._inner.hide()
            except Exception:
                pass

    _notify_dbus.Notifier = _SafeNotifier
    # Some pystray backends keep a direct reference via _util.gtk.notify_dbus.
    # Patch both module paths so startup doesn't crash on notification bus timeouts.
    try:
        from pystray._util import gtk as _notify_gtk  # type: ignore
        _notify_gtk.notify_dbus.Notifier = _SafeNotifier
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERA_HOST = os.getenv("VERA_API_HOST", "127.0.0.1")
VERA_PORT = int(os.getenv("VERA_API_PORT", "8788"))
VERA_URL = f"http://{VERA_HOST}:{VERA_PORT}"
HEALTH_URL = f"{VERA_URL}/api/health"
EXIT_URL = f"{VERA_URL}/api/exit"

PIDFILE = PROJECT_ROOT / "vera_memory" / "vera_tray.pid"
HALT_FILE = PROJECT_ROOT / "vera_memory" / "manual_halt"
LOG_FILE = PROJECT_ROOT / "logs" / "vera_tray.log"
VERA_LOG_FILE = PROJECT_ROOT / "logs" / "vera_debug.log"
LAUNCHER = PROJECT_ROOT / "scripts" / "run_vera_full.sh"

ICON_SIZE = 64  # Rendered large, KDE scales down for tray
STARTUP_TIMEOUT = 90  # seconds
HEALTH_FAIL_THRESHOLD = 3
AUTO_RESTART_COOLDOWN = max(
    5,
    int(os.getenv("VERA_TRAY_RESTART_COOLDOWN", "20")),
)
FORCE_RECYCLE_GRACE_SECONDS = max(
    0,
    int(os.getenv("VERA_TRAY_FORCE_RECYCLE_GRACE_SECONDS", "45")),
)


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
class State(Enum):
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    STOPPED = "stopped"


STATE_COLORS = {
    State.STARTING: "#FFD700",
    State.RUNNING: "#00C853",
    State.ERROR: "#FF1744",
    State.STOPPED: "#808080",
}

STATE_TOOLTIPS = {
    State.STARTING: "VERA - Starting...",
    State.RUNNING: "VERA - Running",
    State.ERROR: "VERA - Error",
    State.STOPPED: "VERA - Stopped",
}


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class VERATray:
    def __init__(self):
        self._setup_logging()
        self.state = State.STOPPED
        self.process: subprocess.Popen | None = None
        self.tray: pystray.Icon | None = None
        self.attached = False
        self._stop_event = threading.Event()
        self._browser_opened = False
        self._startup_deadline = 0.0
        self._next_restart_at = 0.0
        self._error_since = 0.0

    # -- Logging -----------------------------------------------------------
    def _setup_logging(self):
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(LOG_FILE),
            ],
        )
        self.log = logging.getLogger("vera_tray")

    # -- Icon generation ---------------------------------------------------
    def _make_icon(self, color: str) -> Image.Image:
        img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
        dc = ImageDraw.Draw(img)
        dc.ellipse([1, 1, ICON_SIZE - 2, ICON_SIZE - 2], fill=color)
        # Draw a white "V" in the center
        cx, cy = ICON_SIZE // 2, ICON_SIZE // 2
        s = ICON_SIZE // 5
        dc.line(
            [(cx - s, cy - s), (cx, cy + s), (cx + s, cy - s)],
            fill="white",
            width=max(2, ICON_SIZE // 16),
        )
        return img

    def _update_icon(self):
        if self.tray:
            self.tray.icon = self._make_icon(STATE_COLORS[self.state])
            self.tray.title = STATE_TOOLTIPS[self.state]
            try:
                self.tray.update_menu()
            except Exception:
                # Some backends don't expose update_menu; safe to ignore.
                pass

    # -- Notifications -----------------------------------------------------
    def _notify(self, title: str, body: str):
        try:
            subprocess.Popen(
                [
                    "dbus-send", "--session", "--type=method_call",
                    "--dest=org.freedesktop.Notifications",
                    "/org/freedesktop/Notifications",
                    "org.freedesktop.Notifications.Notify",
                    "string:VERA",
                    "uint32:0",
                    "string:",
                    f"string:{title}",
                    f"string:{body}",
                    "array:string:",
                    "dict:string:string:",
                    "int32:5000",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            try:
                subprocess.Popen(
                    ["kdialog", "--passivepopup", f"{title}: {body}", "5"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                self.log.warning("Could not send desktop notification")

    # -- Process exit ------------------------------------------------------
    def _force_exit(self, delay: float = 3.0):
        """Schedule a hard exit — workaround for pystray AppIndicator backend
        not reliably unblocking icon.run() on Linux."""
        def _exit():
            time.sleep(delay)
            self.log.warning("Tray did not exit cleanly — forcing exit")
            os._exit(0)
        threading.Thread(target=_exit, daemon=True).start()

    # -- Health checks -----------------------------------------------------
    def _check_health(self) -> bool:
        try:
            req = urllib.request.Request(HEALTH_URL)
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                return data.get("ok", False) is True
        except Exception:
            return False

    def _set_startup_deadline(self):
        self._startup_deadline = time.monotonic() + STARTUP_TIMEOUT

    def _clear_startup_deadline(self):
        self._startup_deadline = 0.0

    def _restart_due(self) -> bool:
        return time.monotonic() >= self._next_restart_at

    def _set_restart_cooldown(self):
        self._next_restart_at = time.monotonic() + AUTO_RESTART_COOLDOWN

    def _mark_error_state(self):
        if self.state != State.ERROR:
            self._error_since = time.monotonic()
        self.state = State.ERROR

    def _maybe_auto_restart(self, reason: str):
        if self._is_halted():
            return
        if not self._restart_due():
            return
        self._set_restart_cooldown()
        # If process is still alive but health endpoint is down, recycle it.
        # This avoids a wedged half-alive backend that never triggers
        # process-exit based recovery.
        if self.process and self.process.poll() is None:
            if FORCE_RECYCLE_GRACE_SECONDS > 0 and self.state == State.ERROR and self._error_since:
                unhealthy_for = time.monotonic() - self._error_since
                if unhealthy_for < FORCE_RECYCLE_GRACE_SECONDS:
                    self.log.info(
                        "Deferring forced recycle (unhealthy_for=%.1fs < grace=%ss): %s",
                        unhealthy_for,
                        FORCE_RECYCLE_GRACE_SECONDS,
                        reason,
                    )
                    return
            self.log.warning("Attempting forced recycle: %s", reason)
            self._restart_vera()
            return

        self.log.warning("Attempting recovery: %s", reason)
        self._start_vera()

    # -- Health monitor thread ---------------------------------------------
    def _health_monitor(self):
        consecutive_failures = 0

        while not self._stop_event.is_set():
            healthy = self._check_health()

            if self.state == State.STARTING:
                if self._startup_deadline == 0.0:
                    self._set_startup_deadline()
                if healthy:
                    self.state = State.RUNNING
                    consecutive_failures = 0
                    self._clear_startup_deadline()
                    self._update_icon()
                    self._notify("VERA", "VERA is ready.")
                    self.log.info("State -> RUNNING")
                    if (
                        not self._browser_opened
                        and os.getenv("VERA_OPEN_BROWSER", "1") == "1"
                    ):
                        self._browser_opened = True
                        threading.Thread(
                            target=webbrowser.open,
                            args=(VERA_URL,),
                            daemon=True,
                        ).start()
                elif time.monotonic() > self._startup_deadline:
                    self._mark_error_state()
                    self._clear_startup_deadline()
                    self._update_icon()
                    self._notify("VERA", "Startup timed out.")
                    self.log.error("Startup timeout. State -> ERROR")

            elif self.state == State.RUNNING:
                if healthy:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= HEALTH_FAIL_THRESHOLD:
                        self._mark_error_state()
                        self._update_icon()
                        self._notify("VERA", "VERA has stopped responding.")
                        self.log.error("Health failures. State -> ERROR")

            elif self.state == State.ERROR:
                if healthy:
                    self.state = State.RUNNING
                    self._error_since = 0.0
                    consecutive_failures = 0
                    self._update_icon()
                    self._notify("VERA", "VERA has recovered.")
                    self.log.info("Recovered. State -> RUNNING")
                else:
                    self._maybe_auto_restart("health unavailable while state=ERROR")

            elif self.state == State.STOPPED:
                # In attach mode, VERA may be restarted externally (outside tray menu).
                # Promote STOPPED -> RUNNING once health endpoint responds again.
                if healthy and not self._is_halted():
                    self.state = State.RUNNING
                    self._error_since = 0.0
                    consecutive_failures = 0
                    self._update_icon()
                    self._notify("VERA", "VERA is running.")
                    self.log.info("Recovered from STOPPED. State -> RUNNING")
                elif not healthy:
                    self._maybe_auto_restart("backend stopped while tray active")

            # Detect subprocess exit
            if self.process and self.process.poll() is not None:
                code = self.process.returncode
                self.log.warning("VERA process exited with code %d", code)
                self.process = None
                if self.state not in (State.STOPPED,):
                    self.state = State.STOPPED
                    self._update_icon()
                    if self._is_halted():
                        self.log.info("VERA stopped (manual halt sentinel present)")
                    else:
                        self._notify("VERA", f"VERA exited unexpectedly (code {code}).")

            # Keep tray persistent in attached mode even when VERA is halted.
            if self.attached and self._is_halted() and not healthy and self.state != State.STOPPED:
                self.state = State.STOPPED
                self._update_icon()

            interval = 2 if self.state == State.STARTING else 5
            self._stop_event.wait(interval)

    # -- Lifecycle ---------------------------------------------------------
    def _start_vera(self):
        if self.process and self.process.poll() is None:
            self.log.info("Start requested but VERA process is already running")
            return
        if self.process and self.process.poll() is not None:
            self.process = None

        if self._is_halted():
            self.log.info("VERA manually halted. Use tray menu to start.")
            self.state = State.STOPPED
            self._clear_startup_deadline()
            self._update_icon()
            return

        if self._check_health():
            self.log.info("VERA already running on port %d, attaching.", VERA_PORT)
            self.attached = True
            self.state = State.RUNNING
            self._clear_startup_deadline()
            self._browser_opened = True
            self._update_icon()
            self._notify("VERA", "Tray attached to running instance.")
            return

        self.log.info("Starting VERA via %s", LAUNCHER)
        self.state = State.STARTING
        self._set_startup_deadline()
        self._update_icon()
        self._browser_opened = False

        log_handle = open(LOG_FILE, "a")
        launch_env = os.environ.copy()
        # Prevent recursive tray launches when backend script starts.
        launch_env.setdefault("VERA_TRAY_ENABLED", "0")
        # Avoid opening browser windows from service-managed tray startup.
        launch_env.setdefault("VERA_OPEN_BROWSER", "0")
        self.process = subprocess.Popen(
            ["bash", str(LAUNCHER), "--logging", "--quiet"],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            preexec_fn=os.setsid,
            env=launch_env,
        )
        self.attached = False
        self.log.info(
            "VERA started (PID %d, PGID %d)",
            self.process.pid,
            os.getpgid(self.process.pid),
        )

    def _stop_vera(self):
        if self.attached:
            self.log.info("Sending /api/exit to attached VERA instance")
            try:
                req = urllib.request.Request(
                    EXIT_URL,
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass
        elif self.process:
            self.log.info("Stopping VERA process group")
            try:
                pgid = os.getpgid(self.process.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.log.warning("Grace period expired, sending SIGKILL")
                    os.killpg(pgid, signal.SIGKILL)
                    self.process.wait(timeout=5)
            except ProcessLookupError:
                pass
            self.process = None

        self.state = State.STOPPED
        self._clear_startup_deadline()
        if self.tray:
            self._update_icon()

    def _restart_vera(self):
        self.log.info("Restarting VERA...")
        self._stop_vera()
        # server.py writes the halt sentinel on /api/exit — clear it for restart
        HALT_FILE.unlink(missing_ok=True)
        time.sleep(2)
        self._start_vera()

    # -- Menu actions ------------------------------------------------------
    def _on_open_ui(self, icon, item):
        webbrowser.open(VERA_URL)

    def _on_restart(self, icon, item):
        threading.Thread(target=self._restart_vera, daemon=True).start()

    def _on_view_logs(self, icon, item):
        log_path = VERA_LOG_FILE if VERA_LOG_FILE.exists() else LOG_FILE
        subprocess.Popen(["xdg-open", str(log_path)])

    def _on_stop(self, icon, item):
        self.log.info("Stop requested — writing manual_halt sentinel")
        HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
        HALT_FILE.write_text(str(time.time()))
        self._stop_vera()
        self._notify("VERA", "VERA stopped. Tray remains active.")

    def _on_quit(self, icon, item):
        self.log.info("Exit requested — stopping tray")
        self._stop_event.set()
        self._cleanup_pid()
        self._force_exit()
        icon.stop()

    def _on_exit_tray(self, icon, item):
        """Exit the tray app via the safe-stop path."""
        self._on_quit(icon, item)

    def _on_start(self, icon, item):
        self.log.info("Start requested — removing manual_halt sentinel")
        HALT_FILE.unlink(missing_ok=True)
        threading.Thread(target=self._start_vera, daemon=True).start()

    def _is_halted(self) -> bool:
        """True when the manual_halt sentinel is present."""
        return HALT_FILE.exists()

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                "Open VERA UI",
                self._on_open_ui,
                default=lambda _: not self._is_halted(),
                visible=lambda _: not self._is_halted(),
            ),
            pystray.MenuItem(
                lambda _: f"Status: {self.state.value.title()}",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start VERA",
                self._on_start,
                visible=lambda _: self._is_halted(),
                default=lambda _: self._is_halted(),
            ),
            pystray.MenuItem(
                "Restart VERA",
                self._on_restart,
                visible=lambda _: not self._is_halted(),
            ),
            pystray.MenuItem(
                "Stop VERA",
                self._on_stop,
                visible=lambda _: not self._is_halted(),
            ),
            pystray.MenuItem("View Logs", self._on_view_logs),
        )

    # -- PID file ----------------------------------------------------------
    def _write_pid(self):
        PIDFILE.parent.mkdir(parents=True, exist_ok=True)
        PIDFILE.write_text(str(os.getpid()))

    def _cleanup_pid(self):
        try:
            PIDFILE.unlink(missing_ok=True)
        except Exception:
            pass

    def _check_existing_tray(self) -> bool:
        if PIDFILE.exists():
            try:
                old_pid = int(PIDFILE.read_text().strip())
                os.kill(old_pid, 0)
                return True
            except (ProcessLookupError, ValueError, PermissionError):
                pass
        return False

    # -- Entry point -------------------------------------------------------
    def run(self, attach_only: bool = False):
        if self._check_existing_tray():
            print("VERA tray is already running. Exiting.")
            sys.exit(0)

        self._write_pid()

        def _signal_handler(signum, frame):
            self.log.info("Received signal %d", signum)
            self._stop_event.set()
            self._cleanup_pid()
            if self.tray:
                self.tray.stop()
            self._force_exit()
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        try:
            if attach_only:
                # Launched by run_vera_full.sh — don't spawn VERA ourselves.
                # Start in STOPPED when manually halted, else STARTING and let
                # the health monitor transition to RUNNING/ERROR.
                self.log.info("Attach mode — waiting for VERA to become healthy")
                self.attached = True
                self.state = State.STOPPED if self._is_halted() else State.STARTING
                if self.state == State.STARTING:
                    self._set_startup_deadline()
            else:
                self._start_vera()

            monitor = threading.Thread(target=self._health_monitor, daemon=True)
            monitor.start()

            self.tray = pystray.Icon(
                "vera",
                self._make_icon(STATE_COLORS[self.state]),
                STATE_TOOLTIPS[self.state],
                menu=self._build_menu(),
            )
            # If state changed before the tray was constructed, refresh now.
            self._update_icon()
            self.tray.run()

        except Exception as e:
            self.log.exception("Fatal error: %s", e)
        finally:
            self._stop_event.set()
            if not attach_only:
                self._stop_vera()
            self._cleanup_pid()


if __name__ == "__main__":
    VERATray().run(attach_only="--attach" in sys.argv)
