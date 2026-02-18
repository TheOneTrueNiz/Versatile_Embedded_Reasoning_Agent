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

from .protocols import Mouse, Keyboard, Screen, Size, Capabilities

logger = logging.getLogger(__name__)

# Lazy import pyautogui
_pyautogui = None

def _get_pyautogui():
    """Lazy load pyautogui"""
    global _pyautogui
    if _pyautogui is None:
        try:
            import pyautogui
            # Disable fail-safe for automation
            pyautogui.FAILSAFE = False
            _pyautogui = pyautogui
        except ImportError:
            raise ImportError(
                "pyautogui is required for desktop control. "
                "Install with: pip install pyautogui"
            )
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
        pyautogui = _get_pyautogui()
        if region is not None:
            x, y, w, h = region
            return pyautogui.screenshot(region=(int(x), int(y), int(w), int(h)))
        return pyautogui.screenshot()


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
