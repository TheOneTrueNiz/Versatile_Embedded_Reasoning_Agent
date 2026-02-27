#!/usr/bin/env python3
"""
Platform Drivers for Desktop Control
=====================================

PyAutoGUI-based implementations for Linux/Windows/macOS.
Based on os-ai-computer-use driver architecture.
"""

from __future__ import annotations
from typing import Optional, Tuple, Any
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types

from .protocols import Mouse, Keyboard, Screen, Size, Capabilities

logger = logging.getLogger(__name__)

# Lazy import pyautogui
_pyautogui = None
_pyautogui_error: Optional[str] = None

def _get_pyautogui():
    """Lazy load pyautogui"""
    global _pyautogui
    global _pyautogui_error
    if _pyautogui is None:
        if _pyautogui_error:
            raise ImportError(_pyautogui_error)
        try:
            import pyautogui
            # Disable fail-safe for automation
            pyautogui.FAILSAFE = False
            _pyautogui = pyautogui
        except BaseException as exc:
            message = str(exc).strip()

            # Recovery path: some Linux environments without tkinter trigger a
            # mouseinfo SystemExit during pyautogui import. pyautogui only uses
            # mouseinfo for its optional mouseInfo() helper, so we can safely
            # stub it and retry.
            if (
                isinstance(exc, SystemExit)
                and "tkinter" in message.lower()
                and "mouseinfo" in message.lower()
            ):
                try:
                    stub = types.ModuleType("mouseinfo")
                    setattr(stub, "MouseInfoWindow", lambda *args, **kwargs: None)
                    sys.modules["mouseinfo"] = stub
                    import pyautogui

                    pyautogui.FAILSAFE = False
                    _pyautogui = pyautogui
                    _pyautogui_error = None
                    logger.warning(
                        "Desktop control recovered from missing tkinter by stubbing mouseinfo."
                    )
                    return _pyautogui
                except BaseException as retry_exc:
                    exc = retry_exc
                    message = str(retry_exc).strip()

            # Some environments (e.g., missing tkinter on Linux) trigger a
            # SystemExit deep in pyautogui/mouseinfo import. Never let that
            # tear down the entire VERA runtime.
            if not message:
                message = (
                    "pyautogui is required for desktop control. "
                    "Install with: pip install pyautogui"
                )
            _pyautogui_error = (
                "Desktop control unavailable: "
                f"{message}"
            )
            logger.warning(
                "Desktop control import failed (%s): %s",
                exc.__class__.__name__,
                message,
            )
            raise ImportError(_pyautogui_error) from None
    return _pyautogui


class LinuxMouse:
    """Linux mouse driver using PyAutoGUI"""

    def move_to(self, x: int, y: int, *, duration_ms: int = 0) -> None:
        pyautogui = _get_pyautogui()
        dur = max(0.0, float(duration_ms) / 1000.0)
        pyautogui.moveTo(int(x), int(y), duration=dur)

    def click(self, *, button: str = "left", clicks: int = 1) -> None:
        pyautogui = _get_pyautogui()
        pyautogui.click(button=button, clicks=int(clicks), interval=0.05)

    def down(self, *, button: str = "left") -> None:
        pyautogui = _get_pyautogui()
        pyautogui.mouseDown(button=button)

    def up(self, *, button: str = "left") -> None:
        pyautogui = _get_pyautogui()
        pyautogui.mouseUp(button=button)

    def scroll(self, *, dx: int = 0, dy: int = 0) -> None:
        pyautogui = _get_pyautogui()
        if dy:
            pyautogui.scroll(int(dy))
        if dx:
            try:
                pyautogui.hscroll(int(dx))
            except AttributeError:
                # Fallback: shift+scroll for horizontal
                pyautogui.keyDown("shift")
                try:
                    pyautogui.scroll(int(dx))
                finally:
                    pyautogui.keyUp("shift")

    def drag(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int],
        *,
        steps: int = 1,
        delay_ms: int = 0
    ) -> None:
        pyautogui = _get_pyautogui()
        sx, sy = int(start[0]), int(start[1])
        ex, ey = int(end[0]), int(end[1])

        pyautogui.moveTo(sx, sy)
        pyautogui.mouseDown(button="left")

        if steps <= 1:
            pyautogui.moveTo(ex, ey)
        else:
            for i in range(1, int(steps) + 1):
                nx = int(round(sx + (ex - sx) * (i / float(steps))))
                ny = int(round(sy + (ey - sy) * (i / float(steps))))
                pyautogui.moveTo(nx, ny)
                if delay_ms > 0:
                    pyautogui.sleep(max(0.0, float(delay_ms) / 1000.0))

        pyautogui.mouseUp(button="left")


class LinuxKeyboard:
    """Linux keyboard driver using PyAutoGUI"""

    def press_enter(self) -> None:
        pyautogui = _get_pyautogui()
        pyautogui.press("enter")

    def press_key(self, key: str) -> None:
        pyautogui = _get_pyautogui()
        pyautogui.press(key)

    def press_combo(self, keys: Tuple[str, ...]) -> None:
        pyautogui = _get_pyautogui()
        if not keys:
            return
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)

    def type_text(self, text: str, *, wpm: int = 180) -> None:
        pyautogui = _get_pyautogui()
        # Calculate interval from WPM
        interval = 0.02
        try:
            cps = max(1.0, float(wpm) * 5.0 / 60.0)
            interval = max(0.0, 1.0 / cps)
        except Exception:
            logger.debug("Suppressed Exception in drivers")
            pass
        pyautogui.write(text, interval=interval)


class LinuxScreen:
    """Linux screen driver using PyAutoGUI"""

    def size(self) -> Size:
        pyautogui = _get_pyautogui()
        w, h = pyautogui.size()
        return Size(width=int(w), height=int(h))

    def screenshot(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Any:
        backend = os.getenv("VERA_DESKTOP_SCREENSHOT_BACKEND", "auto").strip().lower()
        if backend in {"auto", "scrot"}:
            try:
                return self._screenshot_via_scrot(region=region)
            except Exception as scrot_exc:
                if backend == "scrot":
                    raise RuntimeError(
                        f"Screenshot failed via configured scrot backend: {scrot_exc}"
                    ) from scrot_exc
                logger.warning("scrot screenshot fallback failed: %s", scrot_exc)

        try:
            pyautogui = _get_pyautogui()
            if region is not None:
                x, y, w, h = region
                return pyautogui.screenshot(region=(int(x), int(y), int(w), int(h)))
            return pyautogui.screenshot()
        except Exception as primary_exc:
            logger.warning(
                "PyAutoGUI screenshot failed; attempting scrot fallback: %s",
                primary_exc,
            )
            try:
                return self._screenshot_via_scrot(region=region)
            except Exception as fallback_exc:
                raise RuntimeError(
                    "Screenshot failed via pyautogui and scrot fallback: "
                    f"{fallback_exc}"
                ) from fallback_exc

    def _screenshot_via_scrot(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> Any:
        scrot_bin = shutil.which("scrot")
        if not scrot_bin:
            raise RuntimeError("scrot is not installed on PATH")

        try:
            from PIL import Image
        except Exception as exc:
            raise RuntimeError("Pillow is required for screenshot fallback") from exc

        temp_dir = Path(tempfile.mkdtemp(prefix="vera_scrot_"))
        output_path = temp_dir / "capture.png"

        cmd = [scrot_bin, "-z"]
        if region is not None:
            x, y, w, h = (int(region[0]), int(region[1]), int(region[2]), int(region[3]))
            if w <= 0 or h <= 0:
                raise RuntimeError(f"invalid screenshot region: {region}")
            cmd.extend(["-a", f"{x},{y},{w},{h}"])
        cmd.append(str(output_path))

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                env=os.environ.copy(),
                check=False,
            )
            if result.returncode != 0:
                stderr = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(
                    f"scrot exited {result.returncode}: {stderr[:300]}"
                )

            target_path = output_path
            if (not target_path.exists()) or target_path.stat().st_size <= 0:
                candidates = sorted(
                    temp_dir.glob("*.png"),
                    key=lambda path: path.stat().st_size if path.exists() else 0,
                    reverse=True,
                )
                if candidates:
                    target_path = candidates[0]

            if (not target_path.exists()) or target_path.stat().st_size <= 0:
                raise RuntimeError("scrot produced no screenshot bytes")

            with Image.open(target_path) as img:
                return img.copy()
        finally:
            for file_path in temp_dir.glob("*.png"):
                try:
                    file_path.unlink(missing_ok=True)
                except Exception:
                    logger.debug("Suppressed Exception in drivers")
            try:
                temp_dir.rmdir()
            except Exception:
                logger.debug("Suppressed Exception in drivers")


@dataclass
class PlatformDrivers:
    """Container for platform-specific drivers"""
    mouse: Mouse
    keyboard: Keyboard
    screen: Screen
    capabilities: Capabilities


def get_drivers() -> PlatformDrivers:
    """
    Get platform drivers for the current OS.

    Returns:
        PlatformDrivers with mouse, keyboard, screen implementations
    """
    import platform
    system = platform.system().lower()

    logger.info(f"Initializing desktop drivers for {system}")

    # All platforms use PyAutoGUI-based drivers
    caps = Capabilities(
        supports_synthetic_input=True,
        supports_smooth_move=True,
        supports_screenshot=True,
        dpi_scale=1.0,
    )

    return PlatformDrivers(
        mouse=LinuxMouse(),
        keyboard=LinuxKeyboard(),
        screen=LinuxScreen(),
        capabilities=caps,
    )
