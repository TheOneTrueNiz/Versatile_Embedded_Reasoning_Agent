#!/usr/bin/env python3
"""
Browser Control Tools for VERA
===============================

Provides tool definitions and handlers for web browser automation.
Uses Playwright for async browser control.

Inspired by LaVague's agent-based web automation approach.

Requirements:
    pip install playwright
    playwright install chromium  # or firefox/webkit

Usage:
    from browser_control.tools import BROWSER_TOOLS, BrowserToolBridge

    bridge = BrowserToolBridge()
    await bridge.launch()

    result = await bridge.execute_tool("browser_goto", {"url": "https://example.com"})

    await bridge.close()
"""

import asyncio
import base64
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Check for playwright availability
_playwright = None
try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext
    _playwright = True
except ImportError:
    _playwright = False


# === Browser Tool Definitions (OpenAI Function Calling Format) ===

BROWSER_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "browser_goto",
            "description": (
                "Navigate to a URL in the browser. "
                "Use for: opening websites, loading web pages, starting web workflows. "
                "Returns: url (final URL after redirects), title (page title). "
                "Tip: Use wait_until='networkidle' for JS-heavy SPAs, 'domcontentloaded' for faster loads. "
                "After navigation, use browser_get_content to extract page data or browser_screenshot to capture it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to navigate to (must include protocol: https://)"
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": ["load", "domcontentloaded", "networkidle"],
                        "description": "Wait until event. 'load': all resources loaded. 'domcontentloaded': DOM ready. 'networkidle': no network activity for 500ms."
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": (
                "Click an element on the page using CSS selector. "
                "Use for: clicking buttons, links, menu items, form submissions. "
                "Returns: selector clicked, current URL (may change after click). "
                "Tip: Use browser_wait first if element loads dynamically. "
                "Common selectors: 'button[type=submit]', '.btn-primary', '#login-button', 'a[href=\"/path\"]'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector for element to click (e.g., '#submit', '.btn', 'button[type=submit]')"
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Max wait time for element in milliseconds (default: 5000)"
                    }
                },
                "required": ["selector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": (
                "Fill text into an input field. "
                "Use for: typing in search boxes, filling forms, entering credentials. "
                "Returns: selector filled, text length. "
                "Tip: Use clear_first=true (default) to replace existing text. "
                "For password fields, the text won't be visible but will be entered. "
                "After filling forms, use browser_click to submit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector for input field (e.g., 'input[name=email]', '#search-box', 'textarea.comment')"
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to fill into the field"
                    },
                    "clear_first": {
                        "type": "boolean",
                        "description": "Clear field before filling (default: true). Set false to append."
                    }
                },
                "required": ["selector", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": (
                "Take a screenshot of the current page. "
                "Use for: visual verification, capturing page state, documenting web content, showing user what the page looks like. "
                "Returns: screenshot_b64 (base64-encoded PNG), full_page flag. "
                "Tip: Use full_page=true for long pages. Use selector to capture specific element. "
                "Screenshot is returned as base64 - can be analyzed visually or saved to file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "full_page": {
                        "type": "boolean",
                        "description": "Capture full scrollable page (default: false, captures viewport only)"
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector to screenshot specific element only (optional)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_content",
            "description": (
                "Extract content from the current page - text, HTML, title, or URL. "
                "Use for: scraping page content, extracting article text, reading page data. "
                "Returns: content_type and content string. "
                "Tip: Use 'text' for readable content (strips HTML). Use 'html' when you need the structure. "
                "Use selector to target specific elements (e.g., '.article-body', '#main-content'). "
                "Long content (>10k chars) is truncated."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content_type": {
                        "type": "string",
                        "enum": ["text", "html", "title", "url"],
                        "description": "'text': visible text only. 'html': full HTML. 'title': page title. 'url': current URL."
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector to extract from specific element only (optional, defaults to whole page)"
                    }
                },
                "required": ["content_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_execute_js",
            "description": (
                "Execute JavaScript code on the page. "
                "Use for: complex interactions, extracting dynamic data, modifying page state, running custom automation logic. "
                "Returns: result of script evaluation (stringified). "
                "Tip: Script runs in page context with access to document, window, etc. "
                "For simple interactions, prefer browser_click/browser_fill. Use this for advanced cases."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "JavaScript code to execute. Return value will be captured. Example: 'return document.querySelectorAll(\".item\").length'"
                    }
                },
                "required": ["script"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait",
            "description": (
                "Wait for an element to reach a specific state. "
                "Use for: waiting for dynamic content to load, waiting for elements to appear/disappear. "
                "Returns: selector and state achieved. "
                "Tip: Use before browser_click/browser_fill when elements load dynamically. "
                "States: 'visible' (on screen), 'hidden' (not visible), 'attached' (in DOM), 'detached' (removed from DOM)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of element to wait for"
                    },
                    "state": {
                        "type": "string",
                        "enum": ["visible", "hidden", "attached", "detached"],
                        "description": "State to wait for. 'visible': element is visible. 'hidden': element is hidden or gone."
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Max wait time in milliseconds (default: 5000). Fails if not achieved."
                    }
                },
                "required": ["selector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": (
                "Scroll the page or scroll an element into view. "
                "Use for: revealing content below the fold, triggering lazy-loaded content, navigating long pages. "
                "Returns: direction scrolled or element scrolled to. "
                "Tip: Use selector to scroll a specific element into view. "
                "Use 'bottom' to load infinite-scroll content. Use 'top' to return to page start."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "top", "bottom"],
                        "description": "'up'/'down': scroll by amount pixels. 'top'/'bottom': scroll to page extremes."
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Pixels to scroll for 'up'/'down' directions (default: 500)"
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of element to scroll into view (overrides direction)"
                    }
                },
                "required": ["direction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_back",
            "description": (
                "Go back in browser history. "
                "Use for: returning to previous page, undoing navigation, multi-step workflows. "
                "Returns: new URL after going back. "
                "Tip: Only works if there's history to go back to. Check browser_status first if unsure."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_forward",
            "description": (
                "Go forward in browser history. "
                "Use for: returning to a page after going back. "
                "Returns: new URL after going forward. "
                "Tip: Only works after browser_back was used."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_refresh",
            "description": (
                "Refresh/reload the current page. "
                "Use for: updating dynamic content, clearing page state, retrying failed loads. "
                "Returns: URL of refreshed page. "
                "Tip: May clear filled form data. Use browser_wait after refresh if needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_status",
            "description": (
                "Get browser status and current page information. "
                "Use for: checking if browser is running, getting current URL/title, debugging browser state. "
                "Returns: launched (bool), url, title, browser_type, headless mode. "
                "Tip: Call this first to check browser state before other operations."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]


@dataclass
class BrowserConfig:
    """Browser configuration."""
    headless: bool = True
    browser_type: str = "chromium"  # chromium, firefox, webkit
    viewport_width: int = 1280
    viewport_height: int = 720
    timeout_ms: int = 30000
    user_agent: Optional[str] = None


class BrowserToolBridge:
    """
    Browser control tool bridge for VERA.

    Provides:
    - Async browser automation via Playwright
    - Tool execution with result tracking
    - Screenshot capture
    - Error handling and logging
    """

    def __init__(self, config: Optional[BrowserConfig] = None):
        """
        Initialize browser tool bridge.

        Args:
            config: Browser configuration
        """
        if not _playwright:
            logger.warning(
                "Playwright not installed. Browser tools will not work. "
                "Install with: pip install playwright && playwright install"
            )

        self.config = config or BrowserConfig()
        self._tools = BROWSER_TOOLS.copy()
        self._custom_handlers: Dict[str, Callable] = {}
        self._history: List[Dict] = []

        # Playwright objects
        self._playwright = None
        self._browser: Optional[Any] = None
        self._context: Optional[Any] = None
        self._page: Optional[Any] = None

    @property
    def tools(self) -> List[Dict[str, Any]]:
        """Get tool definitions for the LLM."""
        return self._tools

    @property
    def is_launched(self) -> bool:
        """Check if browser is launched."""
        return self._page is not None

    async def launch(self):
        """Launch the browser."""
        if not _playwright:
            raise ImportError(
                "Playwright not installed. "
                "Install with: pip install playwright && playwright install"
            )

        self._playwright = await async_playwright().start()

        browser_launcher = getattr(
            self._playwright,
            self.config.browser_type
        )
        self._browser = await browser_launcher.launch(
            headless=self.config.headless
        )

        viewport = {
            "width": self.config.viewport_width,
            "height": self.config.viewport_height
        }
        context_opts = {"viewport": viewport}
        if self.config.user_agent:
            context_opts["user_agent"] = self.config.user_agent

        self._context = await self._browser.new_context(**context_opts)
        self._page = await self._context.new_page()

        logger.info(f"Browser launched ({self.config.browser_type})")

    async def close(self):
        """Close the browser."""
        if self._page:
            await self._page.close()
            self._page = None
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("Browser closed")

    async def __aenter__(self):
        await self.launch()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def register_handler(self, tool_name: str, handler: Callable) -> None:
        """Register a custom handler for a tool."""
        self._custom_handlers[tool_name] = handler

    async def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a browser tool.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Result dictionary with success, result, and error
        """
        logger.info(f"Executing browser tool: {name} with {arguments}")

        call_record = {
            "tool": name,
            "arguments": arguments,
            "timestamp": datetime.now().isoformat(),
            "result": None,
            "error": None
        }

        try:
            # Check if browser is launched
            if not self.is_launched and name != "browser_status":
                return {
                    "success": False,
                    "error": "Browser not launched. Call launch() first."
                }

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

            return result

        except Exception as e:
            logger.error(f"Browser tool error: {e}")
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
    ) -> Dict[str, Any]:
        """Default handlers for browser tools."""

        if name == "browser_goto":
            url = arguments["url"]
            wait_until = arguments.get("wait_until", "load")
            await self._page.goto(url, wait_until=wait_until)
            return {
                "success": True,
                "url": self._page.url,
                "title": await self._page.title()
            }

        elif name == "browser_click":
            selector = arguments["selector"]
            timeout = arguments.get("timeout_ms", 5000)
            await self._page.click(selector, timeout=timeout)
            return {
                "success": True,
                "selector": selector,
                "url": self._page.url
            }

        elif name == "browser_fill":
            selector = arguments["selector"]
            text = arguments["text"]
            clear_first = arguments.get("clear_first", True)
            if clear_first:
                await self._page.fill(selector, text)
            else:
                await self._page.type(selector, text)
            return {
                "success": True,
                "selector": selector,
                "text_length": len(text)
            }

        elif name == "browser_screenshot":
            full_page = arguments.get("full_page", False)
            selector = arguments.get("selector")

            if selector:
                element = await self._page.query_selector(selector)
                if element:
                    screenshot = await element.screenshot()
                else:
                    return {"success": False, "error": f"Element not found: {selector}"}
            else:
                screenshot = await self._page.screenshot(full_page=full_page)

            return {
                "success": True,
                "screenshot_b64": base64.b64encode(screenshot).decode('ascii'),
                "full_page": full_page
            }

        elif name == "browser_get_content":
            content_type = arguments["content_type"]
            selector = arguments.get("selector")

            if content_type == "title":
                content = await self._page.title()
            elif content_type == "url":
                content = self._page.url
            elif content_type == "html":
                if selector:
                    element = await self._page.query_selector(selector)
                    content = await element.inner_html() if element else None
                else:
                    content = await self._page.content()
            elif content_type == "text":
                if selector:
                    element = await self._page.query_selector(selector)
                    content = await element.inner_text() if element else None
                else:
                    content = await self._page.inner_text("body")
            else:
                return {"success": False, "error": f"Unknown content_type: {content_type}"}

            # Truncate if too long
            if content and len(content) > 10000:
                content = content[:10000] + "\n... (truncated)"

            return {
                "success": True,
                "content_type": content_type,
                "content": content
            }

        elif name == "browser_execute_js":
            script = arguments["script"]
            result = await self._page.evaluate(script)
            return {
                "success": True,
                "result": str(result) if result else None
            }

        elif name == "browser_wait":
            selector = arguments["selector"]
            state = arguments.get("state", "visible")
            timeout = arguments.get("timeout_ms", 5000)
            await self._page.wait_for_selector(selector, state=state, timeout=timeout)
            return {
                "success": True,
                "selector": selector,
                "state": state
            }

        elif name == "browser_scroll":
            direction = arguments["direction"]
            amount = arguments.get("amount", 500)
            selector = arguments.get("selector")

            if selector:
                element = await self._page.query_selector(selector)
                if element:
                    await element.scroll_into_view_if_needed()
                    return {"success": True, "scrolled_to": selector}
                else:
                    return {"success": False, "error": f"Element not found: {selector}"}

            if direction == "down":
                await self._page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction == "up":
                await self._page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "top":
                await self._page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            return {"success": True, "direction": direction}

        elif name == "browser_back":
            await self._page.go_back()
            return {"success": True, "url": self._page.url}

        elif name == "browser_forward":
            await self._page.go_forward()
            return {"success": True, "url": self._page.url}

        elif name == "browser_refresh":
            await self._page.reload()
            return {"success": True, "url": self._page.url}

        elif name == "browser_status":
            if not self.is_launched:
                return {
                    "success": True,
                    "launched": False,
                    "message": "Browser not launched"
                }
            return {
                "success": True,
                "launched": True,
                "url": self._page.url,
                "title": await self._page.title(),
                "browser_type": self.config.browser_type,
                "headless": self.config.headless
            }

        else:
            raise NotImplementedError(f"No handler for browser tool: {name}")

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Get recent tool execution history."""
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get tool bridge statistics."""
        return {
            "total_tools": len(self._tools),
            "custom_handlers": len(self._custom_handlers),
            "executions_total": len(self._history),
            "browser_launched": self.is_launched,
            "browser_type": self.config.browser_type
        }


# === Factory Function ===

def create_browser_bridge(
    headless: bool = True,
    browser_type: str = "chromium"
) -> BrowserToolBridge:
    """
    Create a browser tool bridge.

    Args:
        headless: Run browser in headless mode
        browser_type: Browser type (chromium, firefox, webkit)

    Returns:
        Configured BrowserToolBridge
    """
    config = BrowserConfig(headless=headless, browser_type=browser_type)
    return BrowserToolBridge(config=config)


# === Tool Registration Helper ===

def get_browser_tool_executor(bridge: BrowserToolBridge) -> Callable:
    """
    Get tool executor function for AsyncToolExecutor integration.

    Args:
        bridge: BrowserToolBridge instance

    Returns:
        Async callable for tool execution
    """
    async def executor(tool_name: str, params: Dict[str, Any]) -> Any:
        # Only handle browser tools
        if not tool_name.startswith("browser_"):
            raise NotImplementedError(f"Not a browser tool: {tool_name}")
        return await bridge.execute_tool(tool_name, params)

    return executor


# === Self-test ===

if __name__ == "__main__":
    import sys

    async def test_browser_tools():
        """Test browser tool bridge."""
        print("Testing Browser Tool Bridge...")
        print("=" * 50)

        # Test 1: Tool definitions
        print("Test 1: Tool definitions...", end=" ")
        assert len(BROWSER_TOOLS) == 12, f"Expected 12 tools, got {len(BROWSER_TOOLS)}"
        print(f"PASS ({len(BROWSER_TOOLS)} tools)")

        # Test 2: Tool names
        print("Test 2: Tool names...", end=" ")
        tool_names = [t["function"]["name"] for t in BROWSER_TOOLS]
        expected = [
            "browser_goto", "browser_click", "browser_fill",
            "browser_screenshot", "browser_get_content", "browser_execute_js",
            "browser_wait", "browser_scroll", "browser_back",
            "browser_forward", "browser_refresh", "browser_status"
        ]
        assert tool_names == expected
        print("PASS")

        # Test 3: Tool schemas
        print("Test 3: Tool schemas...", end=" ")
        for tool in BROWSER_TOOLS:
            assert "type" in tool
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]
        print("PASS")

        # Test 4: Create bridge
        print("Test 4: Create tool bridge...", end=" ")
        bridge = BrowserToolBridge()
        print("PASS")

        # Test 5: Check status (without launching)
        print("Test 5: Check status (not launched)...", end=" ")
        result = await bridge.execute_tool("browser_status", {})
        assert result["success"]
        assert not result["launched"]
        print("PASS")

        # Test 6: Get stats
        print("Test 6: Get stats...", end=" ")
        stats = bridge.get_stats()
        assert "total_tools" in stats
        assert stats["total_tools"] == 12
        assert not stats["browser_launched"]
        print("PASS")

        # Test 7: Tool executor factory
        print("Test 7: Tool executor factory...", end=" ")
        executor = get_browser_tool_executor(bridge)
        assert callable(executor)
        print("PASS")

        # Test 8: Launch browser (if playwright available)
        print("Test 8: Launch browser...", end=" ")
        if _playwright:
            try:
                await bridge.launch()
                assert bridge.is_launched
                print("PASS")

                # Test 9: Navigate
                print("Test 9: Navigate to URL...", end=" ")
                result = await bridge.execute_tool(
                    "browser_goto",
                    {"url": "https://example.com"}
                )
                assert result["success"]
                assert "Example" in result["title"]
                print("PASS")

                # Test 10: Get content
                print("Test 10: Get page content...", end=" ")
                result = await bridge.execute_tool(
                    "browser_get_content",
                    {"content_type": "text"}
                )
                assert result["success"]
                assert "Example Domain" in result["content"]
                print("PASS")

                # Cleanup
                await bridge.close()
            except Exception as e:
                print(f"SKIP ({e})")
        else:
            print("SKIP (playwright not installed)")

        print("\n" + "=" * 50)
        print("All tests passed!")
        return True

    success = asyncio.run(test_browser_tools())
    sys.exit(0 if success else 1)
