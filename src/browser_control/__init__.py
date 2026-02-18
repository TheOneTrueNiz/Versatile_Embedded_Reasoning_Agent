#!/usr/bin/env python3
"""
Browser Control Module for VERA
=================================

Provides web browser automation capabilities:
- Navigate to URLs
- Click elements
- Fill forms
- Extract page content
- Screenshot pages
- Execute JavaScript

Uses Playwright for async browser automation.
Inspired by LaVague's agent-based web automation.

Requirements:
    pip install playwright
    playwright install  # Install browser binaries

Usage:
    from browser_control import BROWSER_TOOLS, BrowserToolBridge

    # Tool bridge for LLM integration
    bridge = BrowserToolBridge()
    await bridge.launch()

    result = await bridge.execute_tool("browser_goto", {"url": "https://example.com"})
    result = await bridge.execute_tool("browser_click", {"selector": "button.submit"})

    await bridge.close()
"""

from .tools import (
    BROWSER_TOOLS,
    BrowserToolBridge,
    create_browser_bridge,
    get_browser_tool_executor
)

__all__ = [
    'BROWSER_TOOLS',
    'BrowserToolBridge',
    'create_browser_bridge',
    'get_browser_tool_executor',
]
