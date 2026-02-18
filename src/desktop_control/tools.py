#!/usr/bin/env python3
"""
Desktop Control Tools for VERA
===============================

Provides tool definitions and handlers for desktop automation.
Integrates with VERA's tool system for LLM-driven desktop control.

Based on os-ai-computer-use architecture adapted for VERA.

Usage:
    from desktop_control.tools import DESKTOP_TOOLS, DesktopToolBridge

    # Get tool definitions
    tools = DESKTOP_TOOLS

    # Create bridge and execute
    bridge = DesktopToolBridge()
    result = await bridge.execute_tool("desktop_click", {"x": 500, "y": 300})
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from .controller import DesktopController, ActionResult
from .drivers import get_drivers

logger = logging.getLogger(__name__)


# === Desktop Tool Definitions (OpenAI Function Calling Format) ===

DESKTOP_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "desktop_click",
            "description": (
                "Click at screen coordinates. "
                "Use for: clicking buttons, icons, menu items, desktop shortcuts, any clickable UI element. "
                "Returns: success, action performed, screenshot_b64 (if capture enabled). "
                "Tip: Use desktop_screenshot first to identify coordinates. "
                "Use clicks=2 for double-click (open files, select words). "
                "Use button='right' for context menus."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "X coordinate on screen (pixels from left edge)"
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate on screen (pixels from top edge)"
                    },
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "'left': normal click. 'right': context menu. 'middle': special actions."
                    },
                    "clicks": {
                        "type": "integer",
                        "description": "1=single click (select), 2=double click (open/activate)"
                    }
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_type",
            "description": (
                "Type text at the current cursor position. "
                "Use for: filling text fields, typing in editors, entering data, writing messages. "
                "Returns: success, action performed. "
                "Tip: Click on a text field first with desktop_click to focus it. "
                "Use desktop_hotkey(['ctrl', 'a']) to select all existing text before typing to replace. "
                "WPM controls typing speed - lower for applications that can't keep up."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to type. Newlines (\\n) will be typed as Enter key."
                    },
                    "wpm": {
                        "type": "integer",
                        "description": "Typing speed in words per minute (default: 180). Lower for slow applications."
                    }
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_hotkey",
            "description": (
                "Press a keyboard shortcut (multiple keys simultaneously). "
                "Use for: copy (ctrl+c), paste (ctrl+v), save (ctrl+s), undo (ctrl+z), select all (ctrl+a), find (ctrl+f), etc. "
                "Returns: success, action performed. "
                "Tip: Common shortcuts: ['ctrl', 'c'] copy, ['ctrl', 'v'] paste, ['ctrl', 'z'] undo, "
                "['ctrl', 'shift', 's'] save as, ['alt', 'f4'] close window, ['alt', 'tab'] switch window. "
                "On macOS, use 'command' instead of 'ctrl'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keys to press together. Modifiers: 'ctrl', 'alt', 'shift', 'command' (Mac). Letters: 'c', 'v', etc."
                    }
                },
                "required": ["keys"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_press_key",
            "description": (
                "Press a single key. "
                "Use for: Enter to confirm, Escape to cancel, Tab to move focus, arrow keys to navigate. "
                "Returns: success, action performed. "
                "Tip: Key names: 'enter', 'escape', 'tab', 'backspace', 'delete', "
                "'up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown', "
                "'f1'-'f12' function keys, 'space'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key to press: 'enter', 'escape', 'tab', 'up', 'down', 'left', 'right', 'backspace', 'delete', 'space', 'f1'-'f12'"
                    }
                },
                "required": ["key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_screenshot",
            "description": (
                "Capture a screenshot of the entire screen or a specific region. "
                "Use for: seeing what's on screen, identifying click targets, verifying actions, documenting state. "
                "Returns: success, screenshot_b64 (base64-encoded PNG image). "
                "Tip: Use before clicking to identify coordinates. Use region to capture specific area. "
                "The screenshot can be analyzed visually to find UI elements."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer", "description": "Left edge X coordinate"},
                            "y": {"type": "integer", "description": "Top edge Y coordinate"},
                            "width": {"type": "integer", "description": "Width in pixels"},
                            "height": {"type": "integer", "description": "Height in pixels"}
                        },
                        "description": "Capture specific region only. Omit for full screen."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_scroll",
            "description": (
                "Scroll the screen vertically or horizontally. "
                "Use for: scrolling through documents, web pages, lists, revealing hidden content. "
                "Returns: success, action performed. "
                "Tip: Click on the target area first to ensure it receives scroll events. "
                "Positive dy scrolls up (content moves down), negative dy scrolls down (content moves up). "
                "Typical scroll: dy=3 (small up) or dy=-3 (small down)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dx": {
                        "type": "integer",
                        "description": "Horizontal scroll clicks. Positive=right, negative=left."
                    },
                    "dy": {
                        "type": "integer",
                        "description": "Vertical scroll clicks. Positive=up, negative=down. Typical: 3 or -3."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_drag",
            "description": (
                "Drag from one position to another (click-hold-move-release). "
                "Use for: drag-and-drop files/items, selecting text by dragging, resizing windows, drawing. "
                "Returns: success, action performed, screenshot_b64 (if capture enabled). "
                "Tip: Use more steps for smoother drag. Some applications require slow drags to register properly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_x": {"type": "integer", "description": "Starting X coordinate (where to click)"},
                    "start_y": {"type": "integer", "description": "Starting Y coordinate (where to click)"},
                    "end_x": {"type": "integer", "description": "Ending X coordinate (where to release)"},
                    "end_y": {"type": "integer", "description": "Ending Y coordinate (where to release)"},
                    "steps": {
                        "type": "integer",
                        "description": "Intermediate movement steps (default: 10). More steps = smoother but slower."
                    }
                },
                "required": ["start_x", "start_y", "end_x", "end_y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_move",
            "description": (
                "Move the mouse cursor to coordinates without clicking. "
                "Use for: hovering to reveal tooltips/menus, positioning before other actions, triggering hover effects. "
                "Returns: success, action performed. "
                "Tip: Some UI elements only appear on hover - use this to trigger them before clicking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Target X coordinate"},
                    "y": {"type": "integer", "description": "Target Y coordinate"},
                    "duration_ms": {
                        "type": "integer",
                        "description": "Movement animation time in milliseconds (default: 200). 0 for instant."
                    }
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "desktop_screen_size",
            "description": (
                "Get the screen dimensions (width and height in pixels). "
                "Use for: understanding screen bounds, calculating positions, centering windows. "
                "Returns: width and height in pixels. "
                "Tip: Call this first to understand the coordinate space before clicking or moving."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


class DesktopToolBridge:
    """
    Bridges desktop control to VERA's tool system.

    Provides:
    - Tool execution with ActionResult tracking
    - Screenshot capture after visual actions
    - Error handling and logging
    - Action history for debugging
    """

    def __init__(
        self,
        controller: Optional[DesktopController] = None,
        capture_screenshots: bool = True
    ):
        """
        Initialize the desktop tool bridge.

        Args:
            controller: DesktopController instance (created if None)
            capture_screenshots: Whether to capture screenshots after actions
        """
        self.controller = controller or DesktopController(
            capture_screenshots=capture_screenshots
        )
        self._tools = DESKTOP_TOOLS.copy()
        self._custom_handlers: Dict[str, Callable] = {}
        self._history: List[Dict] = []

    @property
    def tools(self) -> List[Dict[str, Any]]:
        """Get tool definitions for the LLM."""
        return self._tools

    def register_handler(self, tool_name: str, handler: Callable) -> None:
        """Register a custom handler for a tool."""
        self._custom_handlers[tool_name] = handler

    async def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a desktop tool.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Result dictionary with success, result, and optional screenshot
        """
        logger.info(f"Executing desktop tool: {name} with {arguments}")

        call_record = {
            "tool": name,
            "arguments": arguments,
            "timestamp": datetime.now().isoformat(),
            "result": None,
            "error": None
        }

        try:
            # Check for custom handler
            if name in self._custom_handlers:
                handler = self._custom_handlers[name]
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(**arguments)
                else:
                    result = handler(**arguments)
            else:
                result = await self._default_handler(name, arguments)

            call_record["result"] = result
            self._history.append(call_record)

            # Convert ActionResult to dict if needed
            if isinstance(result, ActionResult):
                return {
                    "success": result.success,
                    "action": result.action,
                    "details": result.details,
                    "error": result.error,
                    "screenshot_b64": result.screenshot_b64,
                    "timestamp": result.timestamp.isoformat()
                }

            return {
                "success": True,
                "result": result
            }

        except Exception as e:
            logger.error(f"Desktop tool error: {e}")
            call_record["error"] = str(e)
            self._history.append(call_record)

            return {
                "success": False,
                "error": str(e)
            }

    async def _default_handler(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> ActionResult:
        """Default handlers for desktop tools."""

        if name == "desktop_click":
            return await self.controller.click_at(
                x=arguments["x"],
                y=arguments["y"],
                button=arguments.get("button", "left"),
                clicks=arguments.get("clicks", 1)
            )

        elif name == "desktop_type":
            return await self.controller.type_text(
                text=arguments["text"],
                wpm=arguments.get("wpm", 180)
            )

        elif name == "desktop_hotkey":
            keys = arguments["keys"]
            return await self.controller.hotkey(*keys)

        elif name == "desktop_press_key":
            return await self.controller.press_key(arguments["key"])

        elif name == "desktop_screenshot":
            region = arguments.get("region")
            if region:
                region_tuple = (
                    region["x"], region["y"],
                    region["width"], region["height"]
                )
                return await self.controller.screenshot(region=region_tuple)
            return await self.controller.screenshot()

        elif name == "desktop_scroll":
            return await self.controller.scroll(
                dx=arguments.get("dx", 0),
                dy=arguments.get("dy", 0)
            )

        elif name == "desktop_drag":
            return await self.controller.drag(
                start_x=arguments["start_x"],
                start_y=arguments["start_y"],
                end_x=arguments["end_x"],
                end_y=arguments["end_y"],
                steps=arguments.get("steps", 10)
            )

        elif name == "desktop_move":
            return await self.controller.move_to(
                x=arguments["x"],
                y=arguments["y"],
                duration_ms=arguments.get("duration_ms", 200)
            )

        elif name == "desktop_screen_size":
            size = self.controller.screen_size
            return ActionResult(
                success=True,
                action="screen_size",
                details={"width": size.width, "height": size.height}
            )

        else:
            raise NotImplementedError(f"No handler for desktop tool: {name}")

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Get recent tool execution history."""
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get tool bridge statistics."""
        action_history = self.controller.get_action_history()

        return {
            "total_tools": len(self._tools),
            "custom_handlers": len(self._custom_handlers),
            "executions_total": len(self._history),
            "controller_actions": len(action_history),
            "screen_size": {
                "width": self.controller.screen_size.width,
                "height": self.controller.screen_size.height
            }
        }


# === Factory Function ===

def create_desktop_bridge(
    capture_screenshots: bool = True
) -> DesktopToolBridge:
    """
    Create a desktop tool bridge.

    Args:
        capture_screenshots: Whether to capture screenshots after actions

    Returns:
        Configured DesktopToolBridge
    """
    return DesktopToolBridge(capture_screenshots=capture_screenshots)


# === Tool Registration Helper ===

def get_desktop_tool_executor(bridge: DesktopToolBridge) -> Callable:
    """
    Get tool executor function for AsyncToolExecutor integration.

    Args:
        bridge: DesktopToolBridge instance

    Returns:
        Async callable for tool execution
    """
    async def executor(tool_name: str, params: Dict[str, Any]) -> Any:
        # Only handle desktop tools
        if not tool_name.startswith("desktop_"):
            raise NotImplementedError(f"Not a desktop tool: {tool_name}")
        return await bridge.execute_tool(tool_name, params)

    return executor


# === Self-test ===

if __name__ == "__main__":
    import sys

    async def test_desktop_tools():
        """Test desktop tool bridge (without actual execution)."""
        print("Testing Desktop Tool Bridge...")
        print("=" * 50)

        # Test 1: Tool definitions
        print("Test 1: Tool definitions...", end=" ")
        assert len(DESKTOP_TOOLS) == 9, f"Expected 9 tools, got {len(DESKTOP_TOOLS)}"
        print(f"PASS ({len(DESKTOP_TOOLS)} tools)")

        # Test 2: Tool names
        print("Test 2: Tool names...", end=" ")
        tool_names = [t["function"]["name"] for t in DESKTOP_TOOLS]
        expected = [
            "desktop_click", "desktop_type", "desktop_hotkey",
            "desktop_press_key", "desktop_screenshot", "desktop_scroll",
            "desktop_drag", "desktop_move", "desktop_screen_size"
        ]
        assert tool_names == expected
        print("PASS")

        # Test 3: Tool schemas
        print("Test 3: Tool schemas...", end=" ")
        for tool in DESKTOP_TOOLS:
            assert "type" in tool
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]
        print("PASS")

        # Test 4: Create bridge (requires pyautogui)
        print("Test 4: Create tool bridge...", end=" ")
        try:
            bridge = DesktopToolBridge(capture_screenshots=False)
            print("PASS")
        except ImportError as e:
            print(f"SKIP (pyautogui not installed)")
            print("\n" + "=" * 50)
            print("Basic tests passed! Install pyautogui for full functionality:")
            print("  pip install pyautogui")
            return True

        # Test 5: Screen size (safe to execute)
        print("Test 5: Get screen size...", end=" ")
        result = await bridge.execute_tool("desktop_screen_size", {})
        if not result.get("success", ""):
            if "pyautogui" in str(result.get("error", "")):
                print("SKIP (pyautogui not installed)")
                print("\n" + "=" * 50)
                print("Basic tests passed! Install pyautogui for full functionality:")
                print("  pip install pyautogui")
                return True
            else:
                raise AssertionError(f"Failed: {result.get('error')}")
        assert "width" in result.get("details", "")
        assert "height" in result.get("details", "")
        print(f"PASS ({result.get('details', '')['width']}x{result.get('details', '')['height']})")

        # Test 6: Get stats
        print("Test 6: Get stats...", end=" ")
        stats = bridge.get_stats()
        assert "total_tools" in stats
        assert stats["total_tools"] == 9
        print("PASS")

        # Test 7: History
        print("Test 7: Execution history...", end=" ")
        history = bridge.get_history()
        assert len(history) >= 1
        print("PASS")

        # Test 8: Tool executor factory
        print("Test 8: Tool executor factory...", end=" ")
        executor = get_desktop_tool_executor(bridge)
        assert callable(executor)
        print("PASS")

        print("\n" + "=" * 50)
        print("All tests passed!")
        return True

    success = asyncio.run(test_desktop_tools())
    sys.exit(0 if success else 1)
