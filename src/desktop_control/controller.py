#!/usr/bin/env python3
"""
Desktop Controller - High-Level Desktop Automation
===================================================

Provides async-friendly high-level desktop control operations.
Integrates with VERA's tool system.
"""

from __future__ import annotations
import asyncio
import base64
import io
import logging
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime

from .drivers import PlatformDrivers, get_drivers
from .protocols import Size, Point

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Result of a desktop action"""
    success: bool
    action: str
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    screenshot_b64: Optional[str] = None


class DesktopController:
    """
    High-level async desktop controller for VERA.

    Features:
    - Async-friendly wrapper around sync drivers
    - Screenshot capture with base64 encoding
    - Action logging and result tracking
    - Coordinate validation
    """

    def __init__(
        self,
        drivers: Optional[PlatformDrivers] = None,
        capture_screenshots: bool = True,
    ):
        """
        Initialize controller.

        Args:
            drivers: Platform drivers (auto-detected if None)
            capture_screenshots: Whether to capture screenshots after actions
        """
        self.drivers = drivers or get_drivers()
        self.capture_screenshots = capture_screenshots
        self._action_history: List[ActionResult] = []

    @property
    def screen_size(self) -> Size:
        """Get screen size"""
        return self.drivers.screen.size()

    def _validate_coords(self, x: int, y: int) -> Tuple[int, int]:
        """Validate and clamp coordinates to screen bounds"""
        size = self.screen_size
        x = max(0, min(x, size.width - 1))
        y = max(0, min(y, size.height - 1))
        return x, y

    def _capture_screenshot_b64(self) -> Optional[str]:
        """Capture screenshot and return as base64"""
        if not self.capture_screenshots:
            return None
        try:
            img = self.drivers.screen.screenshot()
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            return base64.b64encode(buffer.getvalue()).decode('ascii')
        except Exception as e:
            logger.warning(f"Screenshot capture failed: {e}")
            return None

    def _record_action(self, result: ActionResult) -> None:
        """Record action to history"""
        self._action_history.append(result)
        # Keep last 100 actions
        if len(self._action_history) > 100:
            self._action_history = self._action_history[-100:]

    async def move_to(
        self,
        x: int,
        y: int,
        duration_ms: int = 200
    ) -> ActionResult:
        """
        Move mouse to coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            duration_ms: Animation duration in milliseconds
        """
        x, y = self._validate_coords(x, y)

        try:
            # Run in executor to not block event loop
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.drivers.mouse.move_to(x, y, duration_ms=duration_ms)
            )

            result = ActionResult(
                success=True,
                action="move_to",
                details={"x": x, "y": y, "duration_ms": duration_ms},
            )
        except Exception as e:
            result = ActionResult(
                success=False,
                action="move_to",
                error=str(e),
                details={"x": x, "y": y},
            )

        self._record_action(result)
        return result

    async def click_at(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
    ) -> ActionResult:
        """
        Click at coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            button: Mouse button (left, right, middle)
            clicks: Number of clicks
        """
        x, y = self._validate_coords(x, y)

        try:
            def do_click():
                self.drivers.mouse.move_to(x, y, duration_ms=100)
                self.drivers.mouse.click(button=button, clicks=clicks)

            await asyncio.get_event_loop().run_in_executor(None, do_click)

            screenshot = self._capture_screenshot_b64()

            result = ActionResult(
                success=True,
                action="click",
                details={"x": x, "y": y, "button": button, "clicks": clicks},
                screenshot_b64=screenshot,
            )
        except Exception as e:
            result = ActionResult(
                success=False,
                action="click",
                error=str(e),
                details={"x": x, "y": y, "button": button},
            )

        self._record_action(result)
        return result

    async def type_text(
        self,
        text: str,
        wpm: int = 180
    ) -> ActionResult:
        """
        Type text at current cursor position.

        Args:
            text: Text to type
            wpm: Words per minute typing speed
        """
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.drivers.keyboard.type_text(text, wpm=wpm)
            )

            result = ActionResult(
                success=True,
                action="type_text",
                details={"text_length": len(text), "wpm": wpm},
            )
        except Exception as e:
            result = ActionResult(
                success=False,
                action="type_text",
                error=str(e),
                details={"text_length": len(text)},
            )

        self._record_action(result)
        return result

    async def press_key(self, key: str) -> ActionResult:
        """Press a single key"""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.drivers.keyboard.press_key(key)
            )

            result = ActionResult(
                success=True,
                action="press_key",
                details={"key": key},
            )
        except Exception as e:
            result = ActionResult(
                success=False,
                action="press_key",
                error=str(e),
                details={"key": key},
            )

        self._record_action(result)
        return result

    async def hotkey(self, *keys: str) -> ActionResult:
        """
        Press key combination.

        Args:
            *keys: Keys to press together (e.g., 'ctrl', 'c')
        """
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.drivers.keyboard.press_combo(tuple(keys))
            )

            result = ActionResult(
                success=True,
                action="hotkey",
                details={"keys": list(keys)},
            )
        except Exception as e:
            result = ActionResult(
                success=False,
                action="hotkey",
                error=str(e),
                details={"keys": list(keys)},
            )

        self._record_action(result)
        return result

    async def scroll(
        self,
        dx: int = 0,
        dy: int = 0
    ) -> ActionResult:
        """
        Scroll by delta.

        Args:
            dx: Horizontal scroll amount
            dy: Vertical scroll amount (positive = up)
        """
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.drivers.mouse.scroll(dx=dx, dy=dy)
            )

            result = ActionResult(
                success=True,
                action="scroll",
                details={"dx": dx, "dy": dy},
            )
        except Exception as e:
            result = ActionResult(
                success=False,
                action="scroll",
                error=str(e),
                details={"dx": dx, "dy": dy},
            )

        self._record_action(result)
        return result

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        steps: int = 10,
        delay_ms: int = 10,
    ) -> ActionResult:
        """
        Drag from start to end.

        Args:
            start_x, start_y: Starting coordinates
            end_x, end_y: Ending coordinates
            steps: Number of intermediate steps
            delay_ms: Delay between steps
        """
        start_x, start_y = self._validate_coords(start_x, start_y)
        end_x, end_y = self._validate_coords(end_x, end_y)

        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.drivers.mouse.drag(
                    (start_x, start_y),
                    (end_x, end_y),
                    steps=steps,
                    delay_ms=delay_ms
                )
            )

            screenshot = self._capture_screenshot_b64()

            result = ActionResult(
                success=True,
                action="drag",
                details={
                    "start": [start_x, start_y],
                    "end": [end_x, end_y],
                    "steps": steps,
                },
                screenshot_b64=screenshot,
            )
        except Exception as e:
            result = ActionResult(
                success=False,
                action="drag",
                error=str(e),
                details={
                    "start": [start_x, start_y],
                    "end": [end_x, end_y],
                },
            )

        self._record_action(result)
        return result

    async def screenshot(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> ActionResult:
        """
        Take screenshot.

        Args:
            region: Optional (x, y, width, height) region

        Returns:
            ActionResult with screenshot_b64
        """
        try:
            def do_screenshot():
                img = self.drivers.screen.screenshot(region=region)
                buffer = io.BytesIO()
                img.save(buffer, format='PNG')
                return base64.b64encode(buffer.getvalue()).decode('ascii')

            screenshot_b64 = await asyncio.get_event_loop().run_in_executor(
                None, do_screenshot
            )

            result = ActionResult(
                success=True,
                action="screenshot",
                details={"region": region},
                screenshot_b64=screenshot_b64,
            )
        except Exception as e:
            result = ActionResult(
                success=False,
                action="screenshot",
                error=str(e),
                details={"region": region},
            )

        self._record_action(result)
        return result

    def get_action_history(self, limit: int = 10) -> List[ActionResult]:
        """Get recent action history"""
        return self._action_history[-limit:]


# Convenience function for quick access
async def quick_click(x: int, y: int) -> ActionResult:
    """Quick click at coordinates"""
    controller = DesktopController(capture_screenshots=False)
    return await controller.click_at(x, y)


async def quick_type(text: str) -> ActionResult:
    """Quick type text"""
    controller = DesktopController(capture_screenshots=False)
    return await controller.type_text(text)
