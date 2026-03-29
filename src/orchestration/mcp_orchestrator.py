#!/usr/bin/env python3
"""
MCP Orchestrator - Lifecycle management for Model Context Protocol servers

Responsibilities:
- Start/stop MCP server processes
- Health monitoring and auto-restart
- Connection pooling
- Request routing
- Configuration management

Based on: INTEGRATION_ARCHITECTURE.md Gap 7
Research: arXiv:2504.21030, 2507.21105, 2505.02279

Improvement #1 (2025-12-26):
- Non-blocking JSON-RPC buffer parser for robust parsing
- Async health monitoring loop
- Handles debug output, partial fragments, multi-line JSON
"""

import asyncio
import json
import os
import select
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
import signal
import logging
logger = logging.getLogger(__name__)


# ============================================================================
# Credential Resolution from Creds Directory
# ============================================================================

# Map environment variable names to their credential file paths (relative to creds dir)
_CRED_FILE_MAP = {
    # Obsidian
    "OBSIDIAN_VAULT_PATH": "obsidian/vault_path",
    # X/Twitter
    "TWITTER_API_KEY": "X/X_API_KEY",
    "TWITTER_API_SECRET": "X/X_API_KEY_SECRET",
    "TWITTER_ACCESS_TOKEN": "X/Access_Token",
    "TWITTER_ACCESS_TOKEN_SECRET": "X/Access_Token_Secret",
    "TWITTER_BEARER_TOKEN": "X/Bearer_Token",
    # Scrapeless
    "SCRAPELESS_KEY": "scrapeless/scrapeless_api",
    # Google / Gemini
    "GEMINI_API_KEY": "google/google_api",
    "GOOGLE_API_KEY": "google/google_api",
}


def _get_creds_dir() -> Path:
    """Get the credentials directory path."""
    return Path(os.getenv("CREDS_DIR", str(Path.home() / "Documents" / "creds")))


def _resolve_credential_from_file(var_name: str) -> Optional[str]:
    """
    Try to resolve a credential from the creds directory.
    Returns the credential value if found, None otherwise.
    """
    if var_name not in _CRED_FILE_MAP:
        return None

    creds_dir = _get_creds_dir()
    cred_file = creds_dir / _CRED_FILE_MAP[var_name]

    if cred_file.exists():
        try:
            value = cred_file.read_text().strip()
            if value:
                logger.debug(f"Resolved {var_name} from creds file: {cred_file}")
                return value
        except Exception as e:
            logger.warning(f"Failed to read credential file {cred_file}: {e}")

    return None


def _resolve_env_or_cred(var_name: str) -> str:
    """
    Resolve an environment variable, falling back to creds directory if not set.
    Returns empty string if neither source has the value.
    """
    # First try environment variable
    value = os.getenv(var_name)
    if value:
        return value

    # Fall back to creds directory
    cred_value = _resolve_credential_from_file(var_name)
    if cred_value:
        return cred_value

    return ""


def _parse_path_list(raw_value: str) -> List[str]:
    """
    Parse a flexible path list from env.

    Accepts comma/semicolon/newline separators, and platform path separators.
    """
    text = str(raw_value or "").strip()
    if not text:
        return []
    candidates: List[str] = []
    for chunk in text.replace("\n", ",").replace(";", ",").split(","):
        item = chunk.strip()
        if not item:
            continue
        if os.pathsep in item:
            for sub_item in item.split(os.pathsep):
                sub_text = sub_item.strip()
                if sub_text:
                    candidates.append(sub_text)
        else:
            candidates.append(item)

    normalized: List[str] = []
    seen: Set[str] = set()
    for entry in candidates:
        try:
            path_obj = Path(entry).expanduser()
            if not path_obj.is_absolute():
                path_obj = (Path.cwd() / path_obj).resolve()
            normalized_path = str(path_obj)
        except Exception:
            normalized_path = entry
        if normalized_path in seen:
            continue
        seen.add(normalized_path)
        normalized.append(normalized_path)
    return normalized


def _truthy_env(name: str, default: str = "0") -> bool:
    value = str(os.getenv(name, default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _default_filesystem_roots() -> List[str]:
    """
    Return broad but user-scoped filesystem roots for day-to-day operation.

    These defaults expand Desktop/Documents access without granting raw system
    roots like /etc, /proc, or /.
    """
    home = Path.home()
    candidates = [
        home,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        Path("/media"),
        Path("/mnt"),
        Path("/tmp"),
    ]
    roots: List[str] = []
    seen: Set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.expanduser().resolve())
        except Exception:
            continue
        if resolved in seen or not Path(resolved).exists():
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


# ============================================================================
# JSON-RPC Buffer Parser (Improvement #1)
# ============================================================================

class JSONRPCBufferParser:
    """
    Robust JSON-RPC frame parser that handles:
    - Non-JSON debug output from servers
    - Partial JSON fragments
    - Multi-line JSON
    - Binary/non-UTF8 data

    Instead of line-based readline(), accumulates data and scans
    for valid JSON-RPC frames using bracket matching.
    """

    def __init__(self, max_buffer_size: int = 10 * 1024 * 1024):  # 10MB max
        """
        Initialize buffer parser.

        Args:
            max_buffer_size: Maximum buffer size before discarding old data
        """
        self._buffer = b""
        self._max_buffer_size = max_buffer_size
        self._debug_lines: List[str] = []  # Capture non-JSON debug output

    def feed(self, data: bytes) -> None:
        """
        Feed raw bytes into the buffer.

        Args:
            data: Raw bytes from stdout
        """
        self._buffer += data

        # Prevent unbounded memory growth
        if len(self._buffer) > self._max_buffer_size:
            # Discard first half of buffer
            discard_point = len(self._buffer) // 2
            self._buffer = self._buffer[discard_point:]

    def try_extract_json_rpc(self) -> Optional[Dict]:
        """
        Attempt to extract a complete JSON-RPC message from buffer.

        Uses bracket matching to find complete JSON objects, handling:
        - Leading non-JSON debug output (discarded)
        - Partial JSON (kept in buffer for next call)

        Returns:
            Parsed JSON dict if found, None if no complete message yet
        """
        if not self._buffer:
            return None

        # Try to decode as UTF-8, skipping invalid bytes
        try:
            text = self._buffer.decode('utf-8', errors='replace')
        except Exception:
            # If all else fails, try latin-1
            text = self._buffer.decode('latin-1', errors='replace')

        # Find the start of a JSON object
        json_start = self._find_json_start(text)

        if json_start == -1:
            # No JSON found - buffer contains only non-JSON data
            # Save as debug output and clear buffer
            if text.strip():
                self._capture_debug_lines(text)
            self._buffer = b""
            return None

        # If there's text before JSON, capture it as debug output
        if json_start > 0:
            prefix = text[:json_start]
            if prefix.strip():
                self._capture_debug_lines(prefix)
            # Update buffer to start from JSON
            self._buffer = text[json_start:].encode('utf-8')
            text = text[json_start:]

        # Try to parse JSON from the start
        json_obj, end_pos = self._try_parse_json(text)

        if json_obj is not None:
            # Successfully parsed - remove from buffer
            self._buffer = text[end_pos:].encode('utf-8')
            return json_obj

        # JSON is incomplete - keep buffer for next read
        return None

    def _find_json_start(self, text: str) -> int:
        """
        Find the start of a JSON object or array.

        Args:
            text: Text to search

        Returns:
            Index of '{' or '[' that starts JSON, or -1 if not found
        """
        # Look for opening brace that could be JSON-RPC
        for i, char in enumerate(text):
            if char == '{':
                # Check if this looks like JSON-RPC (has "jsonrpc" key nearby)
                remaining = text[i:i+100]  # Look ahead 100 chars
                if '"jsonrpc"' in remaining or '"result"' in remaining or '"error"' in remaining:
                    return i
            elif char == '[':
                # Could be a batch response - must be followed by { or [
                # to distinguish from log output like "[INFO]" or "[DEBUG]"
                if i + 1 < len(text):
                    next_char = text[i + 1]
                    # Valid JSON array start: [{ or [[ or [ followed by whitespace then { or [
                    if next_char == '{' or next_char == '[':
                        return i
                    # Check for whitespace followed by { or [
                    j = i + 1
                    while j < len(text) and text[j] in ' \t\n\r':
                        j += 1
                    if j < len(text) and text[j] in '{[':
                        return i

        # Fallback: just find first { that looks like JSON start
        # Don't use [ fallback as it catches log prefixes like [INFO]
        brace_pos = text.find('{')
        return brace_pos

    def _try_parse_json(self, text: str) -> Tuple[Optional[Dict], int]:
        """
        Try to parse a complete JSON object from the start of text.

        Uses bracket matching to handle multi-line JSON properly.

        Args:
            text: Text starting with JSON object

        Returns:
            Tuple of (parsed_json or None, end_position)
        """
        if not text or text[0] not in '{[':
            return None, 0

        # Track bracket depth
        depth = 0
        in_string = False
        escape_next = False
        start_char = text[0]
        end_char = '}' if start_char == '{' else ']'

        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue

            if char == '\\' and in_string:
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == start_char or (char == '{' and start_char == '[') or (char == '[' and start_char == '['):
                if char == start_char or char == '{':
                    depth += 1
            elif char == end_char or (char == '}' and start_char == '[') or (char == ']' and start_char == '['):
                if char == end_char or char == '}':
                    depth -= 1

            if depth == 0:
                # Found complete JSON
                json_text = text[:i + 1]
                try:
                    return json.loads(json_text), i + 1
                except json.JSONDecodeError:
                    # Invalid JSON despite matching brackets - skip this char
                    return None, 0

        # Incomplete JSON
        return None, 0

    def _capture_debug_lines(self, text: str) -> None:
        """Capture non-JSON text as debug output"""
        for line in text.split('\n'):
            line = line.strip()
            if line and not line.startswith('{'):
                self._debug_lines.append(line)
                # Keep only last 100 debug lines
                if len(self._debug_lines) > 100:
                    self._debug_lines.pop(0)

    def get_debug_output(self) -> List[str]:
        """Get captured debug output lines"""
        return list(self._debug_lines)

    def clear_debug_output(self) -> None:
        """Clear captured debug output"""
        self._debug_lines.clear()

    def reset(self) -> None:
        """Reset parser state"""
        self._buffer = b""
        self._debug_lines.clear()


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server"""
    name: str
    command: str
    args: List[str]
    env: Optional[Dict[str, str]] = None
    auto_start: bool = True
    startup_grace: int = 1  # seconds to wait before first health check
    health_check_interval: int = 30  # seconds
    tool_timeout: float = 30.0  # seconds for tool calls
    max_restart_attempts: int = 3
    restart_backoff: int = 5  # seconds
    required_env: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    description: str = ""

    def __post_init__(self):
        if self.env is None:
            self.env = {}


@dataclass
class MCPServerProcess:
    """Running MCP server process information"""
    name: str
    process: subprocess.Popen
    config: MCPServerConfig
    started_at: datetime
    last_health_check: Optional[datetime] = None
    health_status: str = "unknown"  # unknown, healthy, unhealthy
    restart_count: int = 0


class MCPConnection:
    """
    Connection to an MCP server via stdio

    MCP protocol communicates over stdin/stdout using JSON-RPC

    Improvement #1: Uses JSONRPCBufferParser for robust parsing that handles
    debug output, partial fragments, and multi-line JSON without blocking.
    """

    # Default timeouts (seconds)
    DEFAULT_TIMEOUT = 30.0
    PING_TIMEOUT = 5.0
    LIST_TOOLS_TIMEOUT = 10.0

    def __init__(self, stdin, stdout, server_name: str, stderr=None) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr  # Optional stderr for debug output
        self.server_name = server_name
        self._request_id = 0
        self._parser = JSONRPCBufferParser()
        self._pending_requests: Dict[int, float] = {}  # request_id -> sent_timestamp
        self._response_cache: Dict[int, Dict] = {}  # request_id -> response
        self._io_lock = threading.Lock()

    def _next_id(self) -> int:
        """Generate next request ID"""
        self._request_id += 1
        return self._request_id

    def _read_with_timeout(self, timeout: float, chunk_size: int = 4096) -> Optional[bytes]:
        """
        Non-blocking read from stdout with timeout using select.

        Args:
            timeout: Maximum seconds to wait for data
            chunk_size: Bytes to read per chunk

        Returns:
            Bytes read, or None if timeout/no data
        """
        try:
            # Use select to check if data is available
            fd = self.stdout.fileno()
            readable, _, _ = select.select([fd], [], [], timeout)

            if fd in readable:
                # Data available - read without blocking for full chunk
                data = os.read(fd, chunk_size)
                return data if data else None
            else:
                # Timeout - no data available
                return None

        except Exception as e:
            # Handle broken pipe, closed fd, etc.
            return None

    def _wait_for_response(self, request_id: int, timeout: float) -> Dict:
        """
        Wait for a specific JSON-RPC response using the buffer parser.

        Handles:
        - Debug output mixed with JSON-RPC
        - Partial JSON fragments
        - Multi-line JSON
        - Timeout

        Args:
            request_id: ID of the request to wait for
            timeout: Maximum seconds to wait

        Returns:
            Parsed JSON-RPC response dict

        Raises:
            TimeoutError: If no response within timeout
            Exception: If invalid response received
        """
        cached = self._response_cache.pop(request_id, None)
        if cached:
            return cached

        start_time = time.time()
        poll_interval = 0.1  # Check every 100ms

        while True:
            elapsed = time.time() - start_time
            remaining = timeout - elapsed

            if remaining <= 0:
                # Capture any debug output for diagnostics
                debug_output = self._parser.get_debug_output()
                self._parser.clear_debug_output()
                debug_str = "; ".join(debug_output[-5:]) if debug_output else "none"
                raise TimeoutError(
                    f"MCP response timeout ({timeout}s) for request {request_id} "
                    f"on {self.server_name}. Debug output: {debug_str}"
                )

            # Try to read new data
            data = self._read_with_timeout(min(poll_interval, remaining))

            if data:
                # Feed data to parser
                self._parser.feed(data)

            # Try to extract a complete JSON-RPC message
            response = self._parser.try_extract_json_rpc()

            if response:
                # Check if this is the response we're waiting for
                resp_id = response.get("id")

                if resp_id == request_id:
                    return response
                elif resp_id is not None:
                    # Response for a different request - log and continue
                    # This shouldn't happen with sequential calls, but handle it
                    self._response_cache[resp_id] = response
                    print(f"⚠️  {self.server_name}: Got response for request {resp_id}, waiting for {request_id}")
                    continue
                else:
                    # Notification (no id) or invalid response
                    # Check for error
                    if "error" in response:
                        raise Exception(f"MCP error: {response['error']}")
                    continue

    def _send_request(self, method: str, params: Optional[Dict] = None) -> int:
        """
        Send a JSON-RPC request.

        Args:
            method: RPC method name
            params: Optional method parameters

        Returns:
            Request ID
        """
        request_id = self._next_id()
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method
        }
        if params is not None:
            request["params"] = params

        request_json = json.dumps(request) + "\n"
        self.stdin.write(request_json.encode())
        self.stdin.flush()

        self._pending_requests[request_id] = time.time()
        return request_id

    def _send_notification(self, method: str, params: Optional[Dict] = None) -> None:
        """
        Send a JSON-RPC notification (no id).
        """
        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            notification["params"] = params
        notification_json = json.dumps(notification) + "\n"
        self.stdin.write(notification_json.encode())
        self.stdin.flush()

    def call_tool(self, tool_name: str, params: Dict, timeout: Optional[float] = None) -> str:
        """
        Call tool on MCP server via JSON-RPC

        Request format:
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "tool_name",
                "arguments": {...}
            }
        }

        Args:
            tool_name: Name of the tool to call
            params: Tool arguments
            timeout: Optional timeout override (default: DEFAULT_TIMEOUT)

        Returns:
            Tool result as string

        Raises:
            TimeoutError: If no response within timeout
            Exception: If tool call fails
        """
        timeout = timeout or self.DEFAULT_TIMEOUT

        with self._io_lock:
            # Send request
            request_id = self._send_request(
                "tools/call",
                {"name": tool_name, "arguments": params}
            )

            # Wait for response
            try:
                response = self._wait_for_response(request_id, timeout)
            finally:
                # Clean up pending request tracking
                self._pending_requests.pop(request_id, None)

        if "error" in response:
            error = response["error"]
            error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise Exception(f"MCP tool call error: {error_msg}")

        return response.get("result", "")

    def ping(self, timeout: Optional[float] = None) -> str:
        """
        Health check ping with proper timeout handling.

        Args:
            timeout: Optional timeout override (default: PING_TIMEOUT)

        Returns:
            "pong" if successful, "timeout" or "error" on failure
        """
        timeout = timeout or self.PING_TIMEOUT

        try:
            with self._io_lock:
                request_id = self._send_request("ping")

                try:
                    response = self._wait_for_response(request_id, timeout)
                finally:
                    self._pending_requests.pop(request_id, None)

                if "error" in response:
                    return f"error: {response['error']}"
                return "pong"

        except TimeoutError:
            return "timeout"
        except Exception as e:
            return f"error: {e}"

    def list_tools(self, timeout: Optional[float] = None, strict: bool = False) -> List[str]:
        """
        List available tools from MCP server

        Args:
            timeout: Optional timeout override (default: LIST_TOOLS_TIMEOUT)

        Returns:
            List of tool names
        """
        timeout = timeout or self.LIST_TOOLS_TIMEOUT

        try:
            with self._io_lock:
                request_id = self._send_request("tools/list")

                try:
                    response = self._wait_for_response(request_id, timeout)
                finally:
                    self._pending_requests.pop(request_id, None)

            if "error" in response:
                error = response["error"]
                error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                if strict:
                    raise Exception(error_msg)
                print(f"⚠️  Failed to list tools from {self.server_name}: {error_msg}")
                return []

            if "result" in response and "tools" in response["result"]:
                return [tool["name"] for tool in response["result"]["tools"]]

            return []

        except TimeoutError:
            if strict:
                raise
            print(f"⚠️  Timeout listing tools from {self.server_name}")
            return []
        except Exception as e:
            print(f"⚠️  Failed to list tools from {self.server_name}: {e}")
            return []

    def list_tool_defs(self, timeout: Optional[float] = None, strict: bool = False) -> List[Dict[str, Any]]:
        """
        List tool definitions from MCP server.

        Returns a list of tool objects (name, description, inputSchema when available).
        """
        timeout = timeout or self.LIST_TOOLS_TIMEOUT

        try:
            with self._io_lock:
                request_id = self._send_request("tools/list")

                try:
                    response = self._wait_for_response(request_id, timeout)
                finally:
                    self._pending_requests.pop(request_id, None)

            if "error" in response:
                error = response["error"]
                error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                if strict:
                    raise Exception(error_msg)
                print(f"⚠️  Failed to list tools from {self.server_name}: {error_msg}")
                return []

            tool_entries = response.get("result", {}).get("tools", [])
            tool_defs: List[Dict[str, Any]] = []
            for tool in tool_entries:
                if isinstance(tool, dict):
                    name = tool.get("name")
                    if not name:
                        continue
                    tool_defs.append(tool)
                elif isinstance(tool, str):
                    tool_defs.append({"name": tool})
            return tool_defs

        except TimeoutError:
            if strict:
                raise
            print(f"⚠️  Timeout listing tools from {self.server_name}")
            return []
        except Exception as e:
            print(f"⚠️  Failed to list tools from {self.server_name}: {e}")
            return []

    def initialize(self, timeout: Optional[float] = None) -> bool:
        """
        Send MCP initialize handshake if supported by the server.

        Returns True on success, False otherwise.
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        notified = False
        try:
            with self._io_lock:
                request_id = self._send_request("initialize", {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "clientInfo": {"name": "vera", "version": "1.0"},
                    "capabilities": {}
                })
                try:
                    response = self._wait_for_response(request_id, timeout)
                finally:
                    self._pending_requests.pop(request_id, None)

            if "error" in response:
                return False
            # Notify server initialization completed
            self._send_notification("notifications/initialized", {})
            notified = True
            return True
        except Exception as exc:
            logger.warning("MCP initialization handshake failed: %s", exc)
            return False
        finally:
            if not notified:
                # Best-effort notification to avoid blocking servers that require it.
                try:
                    self._send_notification("notifications/initialized", {})
                except Exception as exc:
                    logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def get_debug_output(self) -> List[str]:
        """Get any debug output captured during parsing"""
        return self._parser.get_debug_output()

    def clear_debug_output(self) -> None:
        """Clear captured debug output"""
        self._parser.clear_debug_output()

    def reset_parser(self) -> None:
        """Reset parser state (useful after connection issues)"""
        self._parser.reset()
        self._pending_requests.clear()


class MCPOrchestrator:
    """
    MCP Server Lifecycle Manager

    Manages multiple MCP servers, handling:
    - Starting/stopping processes
    - Health monitoring
    - Auto-restart on failure
    - Connection pooling
    - Configuration management
    """

    def __init__(self, config_file: Optional[Path] = None) -> None:
        """
        Initialize MCP Orchestrator

        Args:
            config_file: Path to mcp_servers.json configuration file
        """
        self.servers: Dict[str, MCPServerProcess] = {}
        self.connections: Dict[str, MCPConnection] = {}
        self.config_file = config_file or Path(__file__).parent.parent / "mcp_servers.json"
        self.configs: Dict[str, MCPServerConfig] = {}
        self._stderr_threads: Dict[str, threading.Thread] = {}
        self._log_dir = Path(os.getenv("VERA_MCP_LOG_DIR", "logs/mcp"))
        self._shutdown_requested = False
        self._health_monitor_running = False
        self._autostart_retry_after: Dict[str, float] = {}
        self._starting_servers: Set[str] = set()

        # Load configurations
        if self.config_file.exists():
            self._load_configs()

    def _augment_filesystem_args(self, args: List[str]) -> List[str]:
        """Add env-configured filesystem roots without clobbering configured defaults."""
        source_label = "VERA_FILESYSTEM_EXTRA_ROOTS"
        extra_roots = _parse_path_list(os.getenv("VERA_FILESYSTEM_EXTRA_ROOTS", ""))
        if not extra_roots and _truthy_env("VERA_FILESYSTEM_AUTO_EXPAND_HOME", "1"):
            extra_roots = _default_filesystem_roots()
            source_label = "auto-expanded defaults"

        if not extra_roots:
            return list(args or [])

        augmented = list(args or [])
        marker = "@modelcontextprotocol/server-filesystem"
        root_start = 0
        if marker in augmented:
            root_start = augmented.index(marker) + 1
        existing_roots = set(str(item) for item in augmented[root_start:] if isinstance(item, str))

        appended = 0
        for root in extra_roots:
            if root in existing_roots:
                continue
            if not Path(root).exists():
                logger.warning("Skipping VERA_FILESYSTEM_EXTRA_ROOTS path that does not exist: %s", root)
                continue
            augmented.append(root)
            existing_roots.add(root)
            appended += 1

        if appended > 0:
            print(f"📁 Filesystem MCP: appended {appended} extra root(s) from {source_label}")
        return augmented

    def _load_configs(self):
        """Load server configurations from JSON file"""
        try:
            with open(self.config_file, 'r') as f:
                configs_dict = json.load(f)

            for name, config_data in configs_dict.items():
                if not isinstance(config_data, dict):
                    continue
                if "command" not in config_data:
                    continue
                config_args = list(config_data.get("args", []) or [])
                if name == "filesystem":
                    config_args = self._augment_filesystem_args(config_args)
                # Expand environment variables in env dict
                env = config_data.get("env", {})
                expanded_env = {}
                for key, value in env.items():
                    # Expand ${VAR_NAME} patterns (check env first, then creds dir)
                    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                        var_name = value[2:-1]
                        expanded_env[key] = _resolve_env_or_cred(var_name)
                    else:
                        expanded_env[key] = value

                self.configs[name] = MCPServerConfig(
                    name=name,
                    command=config_data.get("command", ""),
                    args=config_args,
                    env=expanded_env,
                    auto_start=config_data.get("auto_start", True),
                    startup_grace=config_data.get("startup_grace", 1),
                    health_check_interval=config_data.get("health_check_interval", 30),
                    tool_timeout=config_data.get("tool_timeout", 30.0),
                    max_restart_attempts=config_data.get("max_restart_attempts", 3),
                    restart_backoff=config_data.get("restart_backoff", 5),
                    required_env=config_data.get("required_env", []),
                    categories=config_data.get("categories", []) or [],
                    description=config_data.get("description", "") or ""
                )

            print(f"✅ Loaded {len(self.configs)} MCP server configurations")

        except FileNotFoundError:
            print(f"⚠️  MCP config file not found: {self.config_file}")
            print("   No MCP servers will be started. Create mcp_servers.json to configure servers.")
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in MCP config file: {e}")
        except Exception as e:
            print(f"❌ Failed to load MCP configs: {e}")

    @staticmethod
    def _load_server_runtime_status(server_name: str) -> Dict[str, Any]:
        if server_name != "call-me":
            return {}
        status_path = Path(os.getenv("CALLME_RUNTIME_STATUS_PATH", "vera_memory/callme_runtime_status.json"))
        try:
            if not status_path.exists():
                return {}
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            logger.warning("Failed to load runtime status for %s: %s", server_name, exc)
            return {}

    @staticmethod
    def _extract_tool_error_text(result: Any) -> str:
        """Best-effort extraction of MCP tool error text."""
        if isinstance(result, dict):
            parts: List[str] = []
            content = result.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            parts.append(text.strip())
            structured = result.get("structuredContent")
            if isinstance(structured, dict):
                text = structured.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            if parts:
                return " | ".join(parts)
        return str(result or "")

    @staticmethod
    def _path_within_root(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False

    def _filesystem_allowed_roots(self) -> List[Path]:
        config = self.configs.get("filesystem")
        if not config:
            return []
        args = list(config.args or [])
        marker = "@modelcontextprotocol/server-filesystem"
        root_start = 0
        if marker in args:
            root_start = args.index(marker) + 1

        roots: List[Path] = []
        for item in args[root_start:]:
            if not isinstance(item, str):
                continue
            try:
                root = Path(item).expanduser().resolve()
            except Exception:
                continue
            if root.exists():
                roots.append(root)
        return roots

    def _path_allowed_for_filesystem(self, path: Path) -> bool:
        roots = self._filesystem_allowed_roots()
        if not roots:
            return False
        return any(self._path_within_root(path, root) for root in roots)

    def _fallback_move_file_cross_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback for EXDEV move_file errors: copy + verify + delete."""
        source_raw = str(params.get("source", "")).strip()
        destination_raw = str(params.get("destination", "")).strip()
        if not source_raw or not destination_raw:
            return {
                "content": [{"type": "text", "text": "move_file fallback failed: source and destination are required"}],
                "isError": True,
            }

        source = Path(source_raw).expanduser()
        destination = Path(destination_raw).expanduser()
        if not source.is_absolute():
            source = (Path.cwd() / source).resolve()
        else:
            source = source.resolve()
        if not destination.is_absolute():
            destination = (Path.cwd() / destination).resolve()
        else:
            destination = destination.resolve()

        if not source.exists():
            return {
                "content": [{"type": "text", "text": f"move_file fallback failed: source not found ({source})"}],
                "isError": True,
            }

        dest_parent = destination.parent.resolve()
        if not dest_parent.exists():
            return {
                "content": [{"type": "text", "text": f"move_file fallback failed: destination parent does not exist ({dest_parent})"}],
                "isError": True,
            }

        if not self._path_allowed_for_filesystem(source):
            return {
                "content": [{"type": "text", "text": f"move_file fallback denied: source outside allowed roots ({source})"}],
                "isError": True,
            }
        if not self._path_allowed_for_filesystem(destination):
            return {
                "content": [{"type": "text", "text": f"move_file fallback denied: destination outside allowed roots ({destination})"}],
                "isError": True,
            }

        size_before = source.stat().st_size if source.is_file() else None
        try:
            moved_path = Path(shutil.move(str(source), str(destination))).resolve()
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"move_file fallback failed during copy/delete: {exc}"}],
                "isError": True,
            }

        verified = moved_path.exists() and not source.exists()
        if verified and size_before is not None and moved_path.is_file():
            verified = moved_path.stat().st_size == size_before

        if not verified:
            return {
                "content": [{"type": "text", "text": "move_file fallback copy/delete could not be verified"}],
                "isError": True,
            }

        return {
            "content": [{
                "type": "text",
                "text": f"Moved {source} -> {moved_path} (fallback: cross-device copy+delete)"
            }],
            "structuredContent": {
                "source": str(source),
                "destination": str(destination),
                "moved_path": str(moved_path),
                "fallback": "copy_delete",
                "verified": True,
            },
        }

    def _get_missing_env(self, config: MCPServerConfig) -> List[str]:
        """Return list of missing required env keys for a config."""
        missing = []
        for key in config.required_env:
            value = config.env.get(key) if config.env is not None else os.getenv(key)
            if not value:
                missing.append(key)
        return missing

    def reload_configs(self) -> None:
        """Reload MCP server configurations from disk."""
        self.configs = {}
        if self.config_file and self.config_file.exists():
            self._load_configs()

    def start_server(self, server_name: str) -> bool:
        """
        Start an MCP server process

        Args:
            server_name: Name of server from configuration

        Returns:
            True if started successfully, False otherwise
        """
        if self._shutdown_requested:
            print(f"⚠️  MCP shutdown requested; skipping start for {server_name}")
            return False
        if server_name not in self.configs:
            print(f"❌ Unknown MCP server: {server_name}")
            return False

        if server_name in self.servers:
            print(f"⚠️  MCP server {server_name} already running")
            return True
        if server_name in self._starting_servers:
            print(f"⚠️  MCP server {server_name} is already starting")
            return False

        config = self.configs[server_name]
        missing_env = self._get_missing_env(config)
        if missing_env:
            print(f"⚠️  Skipping MCP server {server_name}: missing env {', '.join(missing_env)}")
            return False
        print(f"🚀 Starting MCP server: {server_name}")
        self._starting_servers.add(server_name)

        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self._log_dir / f"{server_name}.log"

            # Prepare environment
            env = os.environ.copy()
            env.update(config.env)

            # Use the current interpreter for local python servers
            command = config.command
            if command in {"python", "python3"}:
                command = os.getenv("VERA_MCP_PYTHON") or sys.executable

            # Start process (isolate into its own process group/session)
            popen_kwargs: Dict[str, Any] = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "env": env,
                "text": False,  # Binary mode for JSON-RPC
            }
            if os.name == "posix":
                popen_kwargs["start_new_session"] = True
            elif os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

            process = subprocess.Popen([command] + config.args, **popen_kwargs)

            # Store process info
            server_process = MCPServerProcess(
                name=server_name,
                process=process,
                config=config,
                started_at=datetime.now()
            )
            self.servers[server_name] = server_process

            # Create connection with buffer parser for robust JSON-RPC handling
            connection = MCPConnection(
                stdin=process.stdin,
                stdout=process.stdout,
                server_name=server_name,
                stderr=process.stderr  # Capture stderr for debugging
            )
            self.connections[server_name] = connection

            # Best-effort initialize handshake (some servers require it)
            try:
                connection.initialize(timeout=self._compute_initialize_timeout(config))
            except Exception as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

            if self._shutdown_requested:
                print(f"⏹️  MCP startup interrupted during shutdown: {server_name}")
                self._cleanup_server(server_name)
                return False

            # Stream stderr to log file in background
            if process.stderr:
                thread = threading.Thread(
                    target=self._stream_stderr,
                    args=(server_name, process.stderr, log_path),
                    daemon=True,
                    name=f"MCPStderr-{server_name}"
                )
                thread.start()
                self._stderr_threads[server_name] = thread

            # Initial health check with bounded warm-up polling.
            if not self._interruptible_sleep(float(config.startup_grace)):
                print(f"⏹️  MCP startup interrupted during shutdown: {server_name}")
                self._cleanup_server(server_name)
                return False
            if self._shutdown_requested:
                print(f"⏹️  MCP startup interrupted during shutdown: {server_name}")
                self._cleanup_server(server_name)
                return False
            health_deadline = time.time() + self._compute_list_tools_timeout(config, connection)
            while True:
                if self._health_check(server_name):
                    print(f"✅ MCP server {server_name} started successfully (PID: {process.pid})")
                    return True
                if self._shutdown_requested:
                    print(f"⏹️  MCP startup interrupted during shutdown: {server_name}")
                    self._cleanup_server(server_name)
                    return False
                if time.time() >= health_deadline:
                    print(f"⚠️  MCP server {server_name} started but failed health check")
                    self._cleanup_server(server_name)
                    return False
                if not self._interruptible_sleep(1.0):
                    print(f"⏹️  MCP startup interrupted during shutdown: {server_name}")
                    self._cleanup_server(server_name)
                    return False

        except Exception as e:
            print(f"❌ Failed to start MCP server {server_name}: {e}")
            # Cleanup if process was created
            if server_name in self.servers:
                self._cleanup_server(server_name)
            return False
        finally:
            self._starting_servers.discard(server_name)

    def _ordered_autostart_servers(self, auto_start_servers: List[str]) -> List[str]:
        """Return auto-start servers with startup-critical servers prioritized first."""
        raw = os.getenv("VERA_STARTUP_CRITICAL_SERVERS", "")
        critical = [item.strip() for item in raw.split(",") if item.strip()]
        ordered: List[str] = []

        for server_name in critical:
            if server_name in auto_start_servers and server_name not in ordered:
                ordered.append(server_name)
        for server_name in auto_start_servers:
            if server_name not in ordered:
                ordered.append(server_name)
        return ordered

    def _interruptible_sleep(self, seconds: float, poll_interval: float = 0.25) -> bool:
        """Sleep in short intervals so shutdown can interrupt long startup grace windows."""
        duration = max(0.0, float(seconds))
        if duration <= 0.0:
            return not self._shutdown_requested
        deadline = time.time() + duration
        while True:
            if self._shutdown_requested:
                return False
            remaining = deadline - time.time()
            if remaining <= 0:
                return True
            time.sleep(min(max(0.05, poll_interval), remaining))

    @staticmethod
    def _compute_initialize_timeout(config: MCPServerConfig) -> float:
        """Compute a per-server initialize handshake timeout."""
        tool_timeout = max(5.0, float(getattr(config, "tool_timeout", 30.0) or 30.0))
        startup_grace = max(0.0, float(getattr(config, "startup_grace", 1) or 1.0))
        return max(10.0, min(tool_timeout, startup_grace + 20.0))

    @staticmethod
    def _compute_list_tools_timeout(config: Optional[MCPServerConfig], connection: MCPConnection) -> float:
        """Compute a per-server list-tools timeout."""
        base = float(getattr(connection, "LIST_TOOLS_TIMEOUT", 10.0) or 10.0)
        if config is None:
            return base
        tool_timeout = max(base, float(getattr(config, "tool_timeout", base) or base))
        startup_grace = max(0.0, float(getattr(config, "startup_grace", 1) or 1.0))
        return max(base, min(tool_timeout, startup_grace + 20.0))

    def _start_server_with_timeout(self, server_name: str, timeout_seconds: float) -> bool:
        """Start a server with a hard timeout so one hung start does not block all autostarts."""
        done = threading.Event()
        result = {"ok": False}

        def _runner() -> None:
            try:
                result["ok"] = self.start_server(server_name)
            finally:
                done.set()

        thread = threading.Thread(
            target=_runner,
            daemon=True,
            name=f"MCPStart-{server_name}",
        )
        thread.start()

        deadline = time.time() + max(1.0, timeout_seconds)
        while not done.wait(timeout=0.25):
            if self._shutdown_requested:
                print(f"⏹️  MCP startup interrupted during shutdown: {server_name}")
                return False
            if time.time() >= deadline:
                break
        if done.is_set():
            return bool(result["ok"])

        print(
            f"⚠️  MCP server {server_name} startup timed out after "
            f"{timeout_seconds:.0f}s; continuing startup sequence"
        )
        self._autostart_retry_after[server_name] = time.time() + 60.0
        return False

    def stop_server(self, server_name: str, timeout: int = 5) -> bool:
        """
        Stop an MCP server gracefully

        Args:
            server_name: Name of server to stop
            timeout: Seconds to wait for graceful shutdown

        Returns:
            True if stopped successfully
        """
        if server_name not in self.servers:
            print(f"⚠️  MCP server {server_name} not running")
            return True

        server = self.servers[server_name]
        process = server.process
        print(f"🛑 Stopping MCP server: {server_name} (PID: {process.pid})")

        try:
            # Try graceful termination first (prefer process group/session)
            if os.name == "posix":
                try:
                    pgid = os.getpgid(process.pid)
                    os.killpg(pgid, signal.SIGTERM)
                except Exception as exc:
                    logger.debug("killpg SIGTERM failed (%s), falling back to terminate()", exc)
                    process.terminate()
            else:
                process.terminate()

            try:
                process.wait(timeout=timeout)
                print(f"✅ MCP server {server_name} stopped gracefully")
            except subprocess.TimeoutExpired:
                # Force kill if graceful shutdown failed
                print(f"⚠️  MCP server {server_name} did not stop gracefully, force killing...")
                if os.name == "posix":
                    try:
                        pgid = os.getpgid(process.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except Exception as exc:
                        logger.debug("killpg SIGKILL failed (%s), falling back to kill()", exc)
                        process.kill()
                else:
                    process.kill()
                process.wait()
                print(f"✅ MCP server {server_name} force killed")

            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception as exc:
                    logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

            self._cleanup_server(server_name)
            return True

        except Exception as e:
            print(f"❌ Failed to stop MCP server {server_name}: {e}")
            return False

    def restart_server(self, server_name: str) -> bool:
        """Restart a server by stopping then starting it."""
        if self._shutdown_requested:
            print(f"⚠️  MCP shutdown requested; skipping restart for {server_name}")
            return False
        self.stop_server(server_name)
        return self.start_server(server_name)

    def _cleanup_server(self, server_name: str):
        """Terminate server process, close pipes, and remove from tracking."""
        if server_name in self.servers:
            proc = self.servers[server_name].process
            # Terminate process if still running
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            except OSError as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
            # Close all pipes
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if stream:
                        stream.close()
                except OSError as exc:
                    logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
            del self.servers[server_name]
        if server_name in self.connections:
            del self.connections[server_name]
        if server_name in self._stderr_threads:
            thread = self._stderr_threads.pop(server_name)
            try:
                thread.join(timeout=2)
            except Exception:
                pass  # Thread may already be dead

    def _stream_stderr(self, server_name: str, stream, log_path: Path) -> None:
        """Stream MCP stderr to a log file for diagnostics."""
        try:
            with open(log_path, "ab") as f:
                while True:
                    data = stream.readline()
                    if not data:
                        break
                    f.write(data)
                    f.flush()
        except Exception as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def _health_check(self, server_name: str) -> bool:
        """
        Perform health check on server using non-blocking ping.

        Returns:
            True if healthy, False otherwise
        """
        if server_name not in self.servers:
            return False

        server = self.servers[server_name]
        connection = self.connections.get(server_name)

        if not connection:
            return False

        # Check if process is still running
        if server.process.poll() is not None:
            server.health_status = "unhealthy"
            print(f"⚠️  MCP server {server_name} process died (exit code: {server.process.returncode})")
            return False

        # Try to ping server using non-blocking parser
        response = connection.ping()

        if response == "pong":
            server.health_status = "healthy"
            server.last_health_check = datetime.now()
            return True
        if response.startswith("error:") and "Unknown method 'ping'" in response:
            server.health_status = "healthy"
            server.last_health_check = datetime.now()
            return True
        elif response == "timeout":
            # Non-blocking timeout - server may be slow or unresponsive
            try:
                connection.list_tools(
                    timeout=self._compute_list_tools_timeout(server.config, connection),
                    strict=True,
                )
                server.health_status = "healthy"
                server.last_health_check = datetime.now()
                return True
            except Exception:
                print(f"⚠️  MCP server {server_name} ping timeout")
                server.health_status = "unhealthy"
                return False
        else:
            # Error response (starts with "error:")
            print(f"⚠️  Health check failed for {server_name}: {response}")
            server.health_status = "unhealthy"
            return False

    def _restart_server(self, server_name: str) -> bool:
        """
        Restart a failed server

        Returns:
            True if restarted successfully
        """
        if server_name not in self.servers:
            return False

        server = self.servers[server_name]

        # Check restart attempt limit
        if server.restart_count >= server.config.max_restart_attempts:
            print(f"❌ Max restart attempts reached for {server_name}, giving up")
            return False

        print(f"🔄 Restarting MCP server: {server_name} (attempt {server.restart_count + 1}/{server.config.max_restart_attempts})")

        # Stop the server
        self.stop_server(server_name)

        # Wait backoff period
        time.sleep(server.config.restart_backoff)

        # Start the server
        success = self.start_server(server_name)

        if success:
            # Increment restart count (re-fetch to avoid stale reference)
            self.servers[server_name].restart_count += 1
            return True
        else:
            return False

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        params: Dict,
        timeout_override: Optional[float] = None,
    ) -> str:
        """
        Call a tool on an MCP server

        Handles:
        - Connection failures (auto-reconnect)
        - Server crashes (auto-restart)
        - Timeouts

        Args:
            server_name: Name of MCP server
            tool_name: Name of tool to call
            params: Tool parameters

        Returns:
            Tool result as string

        Raises:
            Exception if tool call fails
        """
        if server_name not in self.connections:
            raise Exception(f"MCP server {server_name} not running")

        connection = self.connections[server_name]
        timeout = None
        server = self.servers.get(server_name)
        if server:
            timeout = server.config.tool_timeout
        if timeout_override is not None:
            try:
                override = float(timeout_override)
                if override > 0:
                    timeout = override
            except Exception:
                logger.debug("Ignoring invalid timeout_override for %s.%s", server_name, tool_name)

        if server_name == "google-workspace" and "user_google_email" not in params:
            user_email = (
                os.getenv("GOOGLE_WORKSPACE_USER_EMAIL")
                or os.getenv("USER_GOOGLE_EMAIL")
                or os.getenv("GOOGLE_USER_EMAIL")
                or ""
            ).strip()
            if user_email:
                params = {**params, "user_google_email": user_email.lower()}

        try:
            # Call tool
            result = connection.call_tool(tool_name, params, timeout=timeout)
            if server_name == "filesystem" and tool_name == "move_file":
                error_text = self._extract_tool_error_text(result).lower()
                if isinstance(result, dict) and result.get("isError") and (
                    "exdev" in error_text or "cross-device link" in error_text
                ):
                    logger.info("Applying filesystem move_file EXDEV fallback (copy+delete)")
                    return self._fallback_move_file_cross_device(params)
            return result

        except Exception as e:
            err_str = str(e).lower()

            if server_name == "filesystem" and tool_name == "move_file" and (
                "exdev" in err_str or "cross-device link" in err_str
            ):
                logger.info("Applying filesystem move_file EXDEV exception fallback (copy+delete)")
                return self._fallback_move_file_cross_device(params)

            if self._shutdown_requested:
                raise Exception(f"MCP shutdown in progress ({server_name}.{tool_name})") from e

            # Classify error for better user/agent feedback
            if "timeout" in err_str or "timed out" in err_str:
                timeout_display = f"{timeout}s" if timeout else "the configured timeout"
                hint = (
                    f"Tool {server_name}.{tool_name} timed out after {timeout_display}. "
                    "Consider using a smaller file path, narrower query, or "
                    "splitting the operation."
                )
                raise Exception(hint) from e

            if "permission" in err_str or "access denied" in err_str or "EACCES" in err_str:
                hint = (
                    f"Permission denied for {server_name}.{tool_name}. "
                    "The requested path may be outside the allowed directory or "
                    "the file may not be readable."
                )
                raise Exception(hint) from e

            if "not found" in err_str or "ENOENT" in err_str or "no such file" in err_str:
                hint = (
                    f"File or directory not found ({server_name}.{tool_name}). "
                    "Verify the path exists and is spelled correctly."
                )
                raise Exception(hint) from e

            # Check if server crashed
            if server_name in self.servers:
                server = self.servers[server_name]
                if server.process.poll() is not None:
                    # Server died, try to restart
                    print(f"⚠️  MCP server {server_name} crashed during tool call, attempting restart...")
                    if self._restart_server(server_name):
                        # Retry once after restart
                        return self.connections[server_name].call_tool(tool_name, params, timeout=timeout)

            # Re-raise exception if restart failed or other error
            raise Exception(f"MCP tool call failed ({server_name}.{tool_name}): {e}")

    def start_all(self) -> None:
        """Start all configured MCP servers with auto_start=True.

        Launches all servers in parallel threads for fast startup.
        Critical servers (from VERA_STARTUP_CRITICAL_SERVERS) are started
        first and waited on before the rest launch concurrently.
        """
        auto_start_servers = [
            name for name, config in self.configs.items()
            if config.auto_start
        ]

        if not auto_start_servers:
            print("No MCP servers configured for auto-start")
            return

        # Pre-flight: warn about missing required env vars
        for server_name in auto_start_servers:
            config = self.configs[server_name]
            missing = self._get_missing_env(config)
            if missing:
                print(f"⚠️  {server_name}: missing env vars: {', '.join(missing)} — server may fail to start")

        ordered_servers = self._ordered_autostart_servers(auto_start_servers)
        print(f"Starting {len(ordered_servers)} MCP servers (parallel)...")

        default_timeout = float(os.getenv("VERA_MCP_START_TIMEOUT_SECONDS", "90"))

        # Separate critical (must finish first) from the rest
        raw_critical = os.getenv("VERA_STARTUP_CRITICAL_SERVERS", "")
        critical_set = {s.strip() for s in raw_critical.split(",") if s.strip()}

        critical_servers = [s for s in ordered_servers if s in critical_set]
        other_servers = [s for s in ordered_servers if s not in critical_set]

        t_start = time.time()

        def _launch_batch(servers: list[str]) -> dict[str, bool]:
            """Launch a batch of servers in parallel and wait for all."""
            results: dict[str, bool] = {}
            threads: list[tuple[str, threading.Thread, threading.Event, dict]] = []

            for server_name in servers:
                if self._shutdown_requested:
                    break
                config = self.configs.get(server_name)
                grace = float(config.startup_grace) if config else 0.0
                timeout_seconds = max(default_timeout, grace + 20.0)

                done_event = threading.Event()
                result_box = {"ok": False}

                def _runner(sn=server_name, rb=result_box, ev=done_event):
                    try:
                        rb["ok"] = self.start_server(sn)
                    finally:
                        ev.set()

                t = threading.Thread(target=_runner, daemon=True,
                                     name=f"MCPParaStart-{server_name}")
                t.start()
                threads.append((server_name, t, done_event, result_box))

            # Wait for all threads with per-server timeouts
            for server_name, t, done_event, result_box in threads:
                config = self.configs.get(server_name)
                grace = float(config.startup_grace) if config else 0.0
                timeout_seconds = max(default_timeout, grace + 20.0)
                deadline = time.time() + max(1.0, timeout_seconds)
                timed_out = False
                interrupted = False
                while not done_event.wait(timeout=0.25):
                    if self._shutdown_requested:
                        interrupted = True
                        break
                    if time.time() >= deadline:
                        timed_out = True
                        break

                if done_event.is_set():
                    results[server_name] = bool(result_box["ok"])
                    continue
                if interrupted:
                    print(f"⏹️  MCP startup interrupted during shutdown: {server_name}")
                    results[server_name] = False
                    continue

                print(f"⚠️  MCP server {server_name} startup timed out after "
                      f"{timeout_seconds:.0f}s (parallel batch)")
                self._autostart_retry_after[server_name] = time.time() + 60.0
                results[server_name] = False

            return results

        # Phase 1: critical servers (if any) — start and wait first
        if critical_servers:
            print(f"  Phase 1: {len(critical_servers)} critical servers: {', '.join(critical_servers)}")
            _launch_batch(critical_servers)

        # Phase 2: everything else — all in parallel
        if other_servers:
            print(f"  Phase 2: {len(other_servers)} servers in parallel")
            _launch_batch(other_servers)

        elapsed = time.time() - t_start
        running = sum(1 for s in ordered_servers if s in self.servers)
        print(f"MCP startup complete: {running}/{len(ordered_servers)} servers in {elapsed:.1f}s")

    def stop_all(self) -> None:
        """Stop all running MCP servers"""
        self._shutdown_requested = True
        self.stop_health_monitor()
        server_names = list(self.servers.keys())

        if not server_names:
            print("No MCP servers running")
            return

        print(f"Stopping {len(server_names)} MCP servers...")

        for server_name in server_names:
            self.stop_server(server_name)

    def request_shutdown(self) -> None:
        """Signal orchestrator shutdown to prevent restarts."""
        self._shutdown_requested = True
        self.stop_health_monitor()

    def get_available_tools(self) -> Dict[str, List[str]]:
        """
        Get all tools available across all running servers

        Returns:
            Dict mapping server_name → list of tool names
        """
        tools = {}

        for server_name, connection in list(self.connections.items()):
            try:
                server = self.servers.get(server_name)
                if server is None or server.process.poll() is not None:
                    tools[server_name] = []
                    continue
                if str(getattr(server, "health_status", "") or "").strip().lower() not in {"healthy", "unknown"}:
                    tools[server_name] = []
                    continue
                timeout = None
                config = self.configs.get(server_name)
                if config and config.tool_timeout:
                    timeout = max(connection.LIST_TOOLS_TIMEOUT, float(config.tool_timeout))
                    timeout = min(timeout, 30.0)
                tools[server_name] = connection.list_tools(timeout=timeout)
            except Exception as e:
                print(f"⚠️  Failed to list tools from {server_name}: {e}")
                tools[server_name] = []

        return tools

    def get_available_tool_defs(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get tool definitions across all running servers.

        Returns:
            Dict mapping server_name → list of tool definition dicts
        """
        tools: Dict[str, List[Dict[str, Any]]] = {}

        for server_name, connection in list(self.connections.items()):
            try:
                tools[server_name] = connection.list_tool_defs()
            except Exception as e:
                print(f"⚠️  Failed to list tools from {server_name}: {e}")
                tools[server_name] = []

        return tools

    def get_status(self) -> Dict[str, Any]:
        """
        Get status of all MCP servers

        Returns:
            Status dictionary with server info
        """
        status = {
            "total_configured": len(self.configs),
            "total_running": len(self.servers),
            "servers": {}
        }

        for server_name, config in self.configs.items():
            server = self.servers.get(server_name)
            is_starting = server_name in self._starting_servers
            is_alive = server is not None and server.process.poll() is None
            uptime = (datetime.now() - server.started_at).total_seconds() if server else 0.0
            missing_env = self._get_missing_env(config)
            runtime_status = self._load_server_runtime_status(server_name)
            health = server.health_status if server else ("starting" if is_starting else "stopped")
            effective_health = health
            health_source = "mcp"
            warning = ""
            if runtime_status.get("degraded"):
                tunnel_kind = str(runtime_status.get("tunnel_kind") or "").strip()
                degraded_reason = str(runtime_status.get("degraded_reason") or "").strip()
                if tunnel_kind:
                    warning = f"{server_name} running in degraded tunnel mode via {tunnel_kind}"
                    if degraded_reason:
                        warning += f" ({degraded_reason})"
            if (
                server_name == "call-me"
                and runtime_status.get("connected") is True
                and str(runtime_status.get("phase") or "").strip().lower() == "ready"
                and str(health or "").strip().lower() in {"unknown", "starting"}
            ):
                effective_health = "healthy"
                health_source = "runtime_status"

            status["servers"][server_name] = {
                "running": is_alive,
                "pid": server.process.pid if is_alive else None,
                "health": health,
                "effective_health": effective_health,
                "health_source": health_source,
                "uptime_seconds": uptime if is_alive else 0.0,
                "restart_count": server.restart_count if server else 0,
                "last_health_check": server.last_health_check.isoformat() if server and server.last_health_check else None,
                "auto_start": config.auto_start,
                "starting": is_starting,
                "required_env": list(config.required_env),
                "missing_env": missing_env,
                "categories": list(config.categories or []),
                "description": config.description or "",
                "runtime_status": runtime_status,
                "warning": warning,
            }

        return status

    def get_stats(self) -> Dict[str, Any]:
        """
        Compatibility wrapper for older callers expecting summary stats.
        """
        status = self.get_status()
        healthy = sum(
            1 for info in status["servers"].values()
            if info.get("health") == "healthy"
        )
        return {
            "configured_servers": status["total_configured"],
            "running_servers": status["total_running"],
            "healthy_servers": healthy,
            "total_requests": 0,
        }

    def health_monitor_loop(self, interval: int = 30) -> None:
        """
        Blocking health monitoring loop (legacy).

        Args:
            interval: Seconds between health checks

        Note: This is a blocking call. Prefer start_health_monitor() for
        non-blocking background monitoring.
        """
        print(f"🏥 Starting health monitor loop (interval: {interval}s)")
        self._health_monitor_running = True

        while self._health_monitor_running:
            self._run_health_checks()
            time.sleep(interval)

    def _run_health_checks(self) -> Dict[str, bool]:
        """
        Run health checks on all servers.

        Returns:
            Dict mapping server_name -> is_healthy
        """
        if self._shutdown_requested:
            return {}
        results = {}
        for server_name in list(self.servers.keys()):
            if server_name in self._starting_servers:
                continue
            config = self.configs.get(server_name)
            if config and config.health_check_interval <= 0:
                results[server_name] = True
                continue
            is_healthy = self._health_check(server_name)
            results[server_name] = is_healthy

            if not is_healthy:
                # Try to restart unhealthy server
                print(f"⚠️  Server {server_name} unhealthy, attempting restart...")
                self._restart_server(server_name)

        # Self-heal: retry configured auto-start servers that never came up.
        now = time.time()
        for server_name, config in self.configs.items():
            if not config.auto_start:
                continue
            if server_name in self.servers:
                continue
            if server_name in self._starting_servers:
                continue
            if self._shutdown_requested:
                break
            retry_after = self._autostart_retry_after.get(server_name, 0.0)
            if retry_after > now:
                continue
            missing_env = self._get_missing_env(config)
            if missing_env:
                continue
            print(f"🔁 Auto-start reconcile: attempting start for missing server {server_name}")
            started = self.start_server(server_name)
            results[server_name] = started
            if started:
                self._autostart_retry_after.pop(server_name, None)
            else:
                # Back off retries to avoid tight restart churn for persistent failures.
                self._autostart_retry_after[server_name] = now + 60.0

        return results

    def start_health_monitor(self, interval: int = 30) -> threading.Thread:
        """
        Start health monitor in a background thread (non-blocking).

        Args:
            interval: Seconds between health checks

        Returns:
            The monitoring thread (can be joined to wait for shutdown)
        """
        self._health_monitor_running = True

        def monitor_thread() -> None:
            print(f"🏥 Starting background health monitor (interval: {interval}s)")
            while self._health_monitor_running:
                try:
                    self._run_health_checks()
                except Exception as e:
                    print(f"⚠️  Health monitor error: {e}")
                time.sleep(interval)
            print("🏥 Health monitor stopped")

        thread = threading.Thread(target=monitor_thread, daemon=True, name="MCP-HealthMonitor")
        thread.start()
        return thread

    def stop_health_monitor(self) -> None:
        """Stop the background health monitor."""
        self._health_monitor_running = False

    async def async_health_monitor_loop(self, interval: int = 30):
        """
        Async health monitoring loop for use with asyncio.

        This version is non-blocking and integrates with asyncio event loops.

        Args:
            interval: Seconds between health checks
        """
        print(f"🏥 Starting async health monitor (interval: {interval}s)")
        self._health_monitor_running = True

        while self._health_monitor_running:
            try:
                # Run health checks in executor to avoid blocking event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._run_health_checks)
            except Exception as e:
                print(f"⚠️  Async health monitor error: {e}")

            await asyncio.sleep(interval)

        print("🏥 Async health monitor stopped")


# ============================================================================
# CLI Interface (for testing and standalone use)
# ============================================================================

def main() -> None:
    """CLI for managing MCP servers"""
    import sys

    orchestrator = MCPOrchestrator()

    if len(sys.argv) < 2:
        print("Usage: python mcp_orchestrator.py <command> [args]")
        print("\nCommands:")
        print("  start <server>   - Start a specific server")
        print("  stop <server>    - Stop a specific server")
        print("  start-all        - Start all auto-start servers")
        print("  stop-all         - Stop all running servers")
        print("  status           - Show status of all servers")
        print("  list-tools       - List tools from all servers")
        print("  health-monitor   - Run health monitoring loop")
        sys.exit(1)

    command = sys.argv[1]

    if command == "start" and len(sys.argv) >= 3:
        server_name = sys.argv[2]
        orchestrator.start_server(server_name)

    elif command == "stop" and len(sys.argv) >= 3:
        server_name = sys.argv[2]
        orchestrator.stop_server(server_name)

    elif command == "start-all":
        orchestrator.start_all()

    elif command == "stop-all":
        orchestrator.stop_all()

    elif command == "status":
        status = orchestrator.get_status()
        print(json.dumps(status, indent=2))

    elif command == "list-tools":
        tools = orchestrator.get_available_tools()
        print(json.dumps(tools, indent=2))

    elif command == "health-monitor":
        try:
            orchestrator.start_all()
            orchestrator.health_monitor_loop()
        except KeyboardInterrupt:
            print("\nStopping health monitor...")
            orchestrator.stop_all()

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
try:
    from mcp.types import LATEST_PROTOCOL_VERSION
except Exception:
    LATEST_PROTOCOL_VERSION = "2025-11-25"
