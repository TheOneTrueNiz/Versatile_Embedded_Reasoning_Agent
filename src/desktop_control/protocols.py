#!/usr/bin/env python3
"""
Desktop Control Protocol Interfaces
====================================

Abstract interfaces for desktop control operations.
Based on os-ai-computer-use ports architecture.
"""

from __future__ import annotations
from typing import Protocol, Tuple, Optional, Any, NamedTuple


class Size(NamedTuple):
    """Screen or region size"""
    width: int
    height: int


class Point(NamedTuple):
    """Screen coordinate"""
    x: int
    y: int


class Capabilities(NamedTuple):
    """Platform capabilities"""
    supports_synthetic_input: bool = True
    supports_smooth_move: bool = True
    supports_screenshot: bool = True
    dpi_scale: float = 1.0


class Mouse(Protocol):
    """Mouse control protocol"""

    def move_to(self, x: int, y: int, *, duration_ms: int = 0) -> None:
        """Move mouse to coordinates"""
        ...

    def click(self, *, button: str = "left", clicks: int = 1) -> None:
        """Click at current position"""
        ...

    def down(self, *, button: str = "left") -> None:
        """Press mouse button down"""
        ...

    def up(self, *, button: str = "left") -> None:
        """Release mouse button"""
        ...

    def scroll(self, *, dx: int = 0, dy: int = 0) -> None:
        """Scroll by delta"""
        ...

    def drag(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int],
        *,
        steps: int = 1,
        delay_ms: int = 0
    ) -> None:
        """Drag from start to end"""
        ...


class Keyboard(Protocol):
    """Keyboard control protocol"""

    def press_enter(self) -> None:
        """Press enter key"""
        ...

    def press_key(self, key: str) -> None:
        """Press a single key"""
        ...

    def press_combo(self, keys: Tuple[str, ...]) -> None:
        """Press key combination (e.g., ctrl+c)"""
        ...

    def type_text(self, text: str, *, wpm: int = 180) -> None:
        """Type text at specified words-per-minute"""
        ...


class Screen(Protocol):
    """Screen capture protocol"""

    def size(self) -> Size:
        """Get screen size"""
        ...

    def screenshot(
        self,
        region: Optional[Tuple[int, int, int, int]] = None
    ) -> Any:
        """Take screenshot, optionally of region (x, y, w, h)"""
        ...
