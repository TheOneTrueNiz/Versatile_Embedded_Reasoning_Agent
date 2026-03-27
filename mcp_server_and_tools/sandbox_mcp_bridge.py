"""
AIO Sandbox MCP Bridge
========================

Thin MCP server that wraps the AIO Sandbox Docker container REST API
as MCP tools. The sandbox container must be running separately
(see scripts/run_sandbox.sh).

Provides: shell execution, file operations, browser automation,
Jupyter/Python execution, Node.js execution — all sandboxed.
"""

import json
import os
import os
import sys
import logging
from typing import Any, Dict

logger = logging.getLogger("sandbox_mcp")

SANDBOX_URL = os.getenv("SANDBOX_BASE_URL", "http://127.0.0.1:8090")

try:
    import httpx
except ImportError:
    print("Error: httpx required. pip install httpx", file=sys.stderr)
    sys.exit(1)


import time as _time


def _post(endpoint: str, payload: Dict[str, Any], retries: int = 2) -> Dict[str, Any]:
    """Make a POST request to the sandbox API with retry on connection errors."""
    url = f"{SANDBOX_URL}/v1/{endpoint}"
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(url, json=payload, timeout=120.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError as e:
            last_err = e
            if attempt < retries:
                _time.sleep(2 * (attempt + 1))
                continue
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            hint = {
                404: "Endpoint not found — sandbox container may be an older version.",
                500: "Sandbox internal error. Check Docker logs: docker logs aio-sandbox",
                502: "Sandbox proxy error — container may be restarting. Retry in 10s.",
                503: "Sandbox unavailable — container still starting. Wait and retry.",
            }.get(status, "")
            msg = f"Sandbox API error {status}: {e.response.text[:200]}"
            if hint:
                msg += f" | Recovery: {hint}"
            raise RuntimeError(msg) from e
    raise RuntimeError(
        f"Sandbox container not reachable at {SANDBOX_URL} after {retries + 1} attempts. "
        f"Start with: scripts/run_sandbox.sh | Error: {last_err}"
    )


def _get(endpoint: str) -> Dict[str, Any]:
    """Make a GET request to the sandbox API."""
    url = f"{SANDBOX_URL}/v1/{endpoint}"
    resp = httpx.get(url, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


try:
    from mcp.server import Server, InitializationOptions
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent, ServerCapabilities

    server = Server("sandbox")
    _init_options = InitializationOptions(
        server_name="sandbox",
        server_version="1.0.0",
        capabilities=ServerCapabilities(tools={}),
    )

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="sandbox_shell_exec",
                description="Execute a shell command in the isolated Docker sandbox. Use for: running untrusted code, installing packages, system commands. Returns stdout, stderr, exit code. Safe — container is ephemeral and isolated from host.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to execute"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)", "default": 60},
                    },
                    "required": ["command"],
                },
            ),
            Tool(
                name="sandbox_file_read",
                description="Read a file from the sandbox filesystem.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path in the sandbox"},
                    },
                    "required": ["path"],
                },
            ),
            Tool(
                name="sandbox_file_write",
                description="Write content to a file in the sandbox filesystem.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path in the sandbox"},
                        "content": {"type": "string", "description": "Content to write"},
                    },
                    "required": ["path", "content"],
                },
            ),
            Tool(
                name="sandbox_python_exec",
                description="Execute Python code in the sandbox's Jupyter kernel. Use for: data analysis, plotting, running user-provided scripts safely. State persists across calls within a session. Pre-installed: numpy, pandas, matplotlib.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code to execute"},
                    },
                    "required": ["code"],
                },
            ),
            Tool(
                name="sandbox_nodejs_exec",
                description="Execute Node.js/JavaScript code in the sandbox. Use for: running JS scripts, testing npm packages, web scraping scripts. Isolated from host.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "JavaScript code to execute"},
                    },
                    "required": ["code"],
                },
            ),
            Tool(
                name="sandbox_browser_navigate",
                description="Navigate the sandbox browser to a URL. Use for: testing web pages, taking screenshots, verifying deployments. Returns page content/screenshot. Runs in isolated container.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to navigate to"},
                    },
                    "required": ["url"],
                },
            ),
            Tool(
                name="sandbox_file_search",
                description="Search file contents in the sandbox.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Search pattern"},
                        "path": {"type": "string", "description": "Directory to search in", "default": os.path.expanduser("~")},
                    },
                    "required": ["pattern"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "sandbox_shell_exec":
                result = _post("shell/exec", {
                    "command": arguments["command"],
                    "timeout": arguments.get("timeout", 60),
                })
            elif name == "sandbox_file_read":
                result = _post("file/read", {"path": arguments["path"]})
            elif name == "sandbox_file_write":
                result = _post("file/write", {
                    "path": arguments["path"],
                    "content": arguments["content"],
                })
            elif name == "sandbox_python_exec":
                result = _post("jupyter/execute", {"code": arguments["code"]})
            elif name == "sandbox_nodejs_exec":
                result = _post("nodejs/execute", {"code": arguments["code"]})
            elif name == "sandbox_browser_navigate":
                result = _post("browser/action", {
                    "action": "navigate",
                    "url": arguments["url"],
                })
            elif name == "sandbox_file_search":
                result = _post("file/search", {
                    "pattern": arguments["pattern"],
                    "path": arguments.get("path", os.path.expanduser("~")),
                })
            else:
                result = {"error": f"Unknown tool: {name}"}

            return [TextContent(type="text", text=json.dumps(result, default=str))]
        except httpx.ConnectError:
            return [TextContent(type="text", text=json.dumps({
                "error": "Sandbox container not running. Start with: scripts/run_sandbox.sh"
            }))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, _init_options)

    if __name__ == "__main__":
        import asyncio
        asyncio.run(main())

except ImportError:
    try:
        from fastmcp import FastMCP

        mcp = FastMCP("sandbox")

        @mcp.tool()
        def sandbox_shell_exec(command: str, timeout: int = 60) -> str:
            """Execute a shell command in the isolated sandbox container."""
            return json.dumps(_post("shell/exec", {"command": command, "timeout": timeout}), default=str)

        @mcp.tool()
        def sandbox_file_read(path: str) -> str:
            """Read a file from the sandbox filesystem."""
            return json.dumps(_post("file/read", {"path": path}), default=str)

        @mcp.tool()
        def sandbox_file_write(path: str, content: str) -> str:
            """Write content to a file in the sandbox filesystem."""
            return json.dumps(_post("file/write", {"path": path, "content": content}), default=str)

        @mcp.tool()
        def sandbox_python_exec(code: str) -> str:
            """Execute Python code in the sandbox Jupyter kernel."""
            return json.dumps(_post("jupyter/execute", {"code": code}), default=str)

        @mcp.tool()
        def sandbox_nodejs_exec(code: str) -> str:
            """Execute Node.js code in the sandbox."""
            return json.dumps(_post("nodejs/execute", {"code": code}), default=str)

        @mcp.tool()
        def sandbox_browser_navigate(url: str) -> str:
            """Navigate the sandbox browser to a URL."""
            return json.dumps(_post("browser/action", {"action": "navigate", "url": url}), default=str)

        if __name__ == "__main__":
            mcp.run(transport="stdio")

    except ImportError:
        print("Error: Neither 'mcp' nor 'fastmcp' package found.", file=sys.stderr)
        sys.exit(1)
