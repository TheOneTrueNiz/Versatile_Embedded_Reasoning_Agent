#!/usr/bin/env python3
"""
Minimal MCP Time Server (stdio JSON-RPC)
========================================

Provides a small, dependency-free MCP server that exposes a `time` tool.
This replaces the npm-based server-time package for environments where
`npx @modelcontextprotocol/server-time` is unavailable.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None


TOOLS = [
    {
        "name": "time",
        "description": (
            "Get the current time and date. Use for 'what time is it', 'current time in X', "
            "'what's the date', time zone conversions, and scheduling context. "
            "Returns ISO timestamp, unix epoch, formatted date/time, and UTC offset. "
            "Common timezones: America/New_York (ET), America/Chicago (CT), America/Denver (MT), "
            "America/Los_Angeles (PT), Europe/London (GMT/BST), Europe/Paris (CET), "
            "Asia/Tokyo (JST), Asia/Shanghai (CST), Australia/Sydney (AEST), UTC."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "IANA timezone name (e.g., 'America/New_York', 'Europe/London', 'Asia/Tokyo') "
                        "or 'UTC' or 'local' for system time. Default: local."
                    )
                },
                "format": {
                    "type": "string",
                    "enum": ["iso", "unix", "human"],
                    "description": (
                        "Output format: 'iso' returns full object with all fields (default), "
                        "'unix' returns epoch seconds only, 'human' returns readable string only."
                    )
                },
            },
        },
    }
]


def _resolve_timezone(tz_name: Optional[str]) -> tuple[timezone, str]:
    if not tz_name or tz_name.lower() in ("local", "system"):
        local = datetime.now().astimezone()
        tzinfo = local.tzinfo or timezone.utc
        label = local.tzname() or "local"
        return tzinfo, label

    if tz_name.upper() == "UTC":
        return timezone.utc, "UTC"

    if ZoneInfo is None:
        raise ValueError("zoneinfo not available; use 'UTC' or 'local'")

    return ZoneInfo(tz_name), tz_name


def _build_time_payload(args: Dict[str, Any]) -> Any:
    tz_name = args.get("timezone")
    fmt = args.get("format", "iso")
    tzinfo, label = _resolve_timezone(tz_name)
    now = datetime.now(tzinfo)
    offset = now.utcoffset()
    offset_minutes = int(offset.total_seconds() / 60) if offset else 0

    payload = {
        "iso": now.isoformat(),
        "unix": int(now.timestamp()),
        "timezone": label,
        "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
        "offset_minutes": offset_minutes,
    }

    if fmt == "unix":
        return payload["unix"]
    if fmt == "human":
        return payload["formatted"]
    return payload


def _send_response(response: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _send_error(req_id: Optional[int], message: str, code: int = -32602) -> None:
    _send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    })


def _handle_request(request: Dict[str, Any]) -> None:
    req_id = request.get("id")
    method = request.get("method")

    if method == "notifications/initialized":
        return

    if method == "ping":
        _send_response({"jsonrpc": "2.0", "id": req_id, "result": "pong"})
        return

    if method == "tools/list":
        _send_response({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        return

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name != "time":
            _send_error(req_id, f"Unknown tool '{name}'", code=-32601)
            return
        try:
            result = _build_time_payload(args)
        except Exception as exc:
            _send_error(req_id, str(exc))
            return
        _send_response({"jsonrpc": "2.0", "id": req_id, "result": result})
        return

    if method == "initialize":
        _send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "serverInfo": {"name": "vera-time", "version": "1.0"},
                "capabilities": {"tools": {}},
            },
        })
        return

    if method == "shutdown":
        _send_response({"jsonrpc": "2.0", "id": req_id, "result": "ok"})
        sys.exit(0)

    _send_error(req_id, f"Unknown method '{method}'", code=-32601)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        _handle_request(request)


if __name__ == "__main__":
    main()
