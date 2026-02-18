#!/usr/bin/env python3
"""
Desktop Control Module for VERA
================================

Provides desktop automation capabilities:
- Mouse control (move, click, drag, scroll)
- Keyboard input (type, hotkeys, special keys)
- Screen capture (screenshots, region capture)
- Cross-platform support via PyAutoGUI

Based on os-ai-computer-use architecture with clean protocol interfaces.

Usage:
    from desktop_control import get_drivers, DesktopController

    # Get platform drivers
    drivers = get_drivers()

    # Use controller for high-level actions
    controller = DesktopController(drivers)
    await controller.click_at(500, 300)
    await controller.type_text("Hello VERA")

    # Use with VERA tool system
    from desktop_control import DESKTOP_TOOLS, DesktopToolBridge
    bridge = DesktopToolBridge()
    result = await bridge.execute_tool("desktop_click", {"x": 500, "y": 300})
"""

from .drivers import get_drivers, PlatformDrivers
from .controller import DesktopController, ActionResult
from .protocols import Mouse, Keyboard, Screen, Size, Point, Capabilities
from .tools import (
    DESKTOP_TOOLS,
    DesktopToolBridge,
    create_desktop_bridge,
    get_desktop_tool_executor
)

__all__ = [
    # Core
    'get_drivers',
    'PlatformDrivers',
    'DesktopController',
    'ActionResult',
    # Protocols
    'Mouse',
    'Keyboard',
    'Screen',
    'Size',
    'Point',
    'Capabilities',
    # Tools
    'DESKTOP_TOOLS',
    'DesktopToolBridge',
    'create_desktop_bridge',
    'get_desktop_tool_executor',
]
