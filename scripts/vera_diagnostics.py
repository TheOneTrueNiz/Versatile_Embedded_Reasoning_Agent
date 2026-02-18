#!/usr/bin/env python3
"""
VERA Diagnostics
================

Minimal, repeatable checks for the VERA API + tools.
"""

import argparse
import json
import sys
from typing import Any, Dict, Tuple

import httpx


def _request_json(client: httpx.Client, method: str, url: str, **kwargs) -> Tuple[bool, Any, str]:
    try:
        response = client.request(method, url, **kwargs)
    except Exception as exc:
        return False, None, f"request failed: {exc}"

    if response.status_code >= 400:
        detail = response.text.strip()
        if detail:
            return False, response.text, f"HTTP {response.status_code}: {detail}"
        return False, response.text, f"HTTP {response.status_code}"

    try:
        return True, response.json(), ""
    except Exception:
        return True, response.text, ""


def _print_check(label: str, ok: bool, detail: str = "") -> None:
    status = "OK" if ok else "FAIL"
    if detail:
        print(f"[{status}] {label} - {detail}")
    else:
        print(f"[{status}] {label}")


def run_health(client: httpx.Client, base_url: str) -> bool:
    ok, data, err = _request_json(client, "GET", f"{base_url}/api/health")
    detail = err or (data if isinstance(data, str) else "")
    if ok and isinstance(data, dict) and data.get("ok") is True:
        _print_check("/api/health", True)
        return True
    _print_check("/api/health", False, detail or "unexpected response")
    return False


def run_models(client: httpx.Client, base_url: str) -> bool:
    ok, data, err = _request_json(client, "GET", f"{base_url}/v1/models")
    if ok and isinstance(data, dict) and data.get("data"):
        model_id = data["data"][0].get("id")
        _print_check("/v1/models", True, model_id or "")
        return True
    detail = err or (data if isinstance(data, str) else "")
    _print_check("/v1/models", False, detail or "unexpected response")
    return False


def run_chat(client: httpx.Client, base_url: str, model: str, message: str) -> bool:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
    }
    ok, data, err = _request_json(client, "POST", f"{base_url}/v1/chat/completions", json=payload)
    if ok and isinstance(data, dict):
        choices = data.get("choices") or []
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            preview = (content or "").strip().replace("\n", " ")
            lowered = preview.lower()
            if lowered.startswith("error:") or "client error" in lowered or "bad request" in lowered:
                _print_check("/v1/chat/completions", False, preview[:200])
                return False
            _print_check("/v1/chat/completions", True, preview[:120])
            return True
    detail = err or (data if isinstance(data, str) else "")
    _print_check("/v1/chat/completions", False, detail or "unexpected response")
    return False


def run_tools_status(client: httpx.Client, base_url: str) -> bool:
    ok, data, err = _request_json(client, "GET", f"{base_url}/api/tools")
    if ok and isinstance(data, dict):
        mcp = data.get("mcp", {})
        if isinstance(mcp, dict) and "servers" in mcp and isinstance(mcp["servers"], dict):
            mcp_servers = mcp["servers"]
        elif isinstance(mcp, dict):
            mcp_servers = mcp
        else:
            mcp_servers = {}
        native = data.get("native", {})
        running = 0
        for server in mcp_servers.values():
            if isinstance(server, dict) and server.get("running") is True:
                running += 1
        _print_check("/api/tools", True, f"mcp running {running}, native {len(native.get('tools', []))}")
        return True
    detail = err or (data if isinstance(data, str) else "")
    _print_check("/api/tools", False, detail or "unexpected response")
    return False


def run_tools_list(client: httpx.Client, base_url: str, show_names: bool = False) -> bool:
    ok, data, err = _request_json(client, "GET", f"{base_url}/api/tools/list")
    if ok and isinstance(data, dict):
        tools = data.get("tools", {})
        native_tools = data.get("native_tools", [])
        summary_parts = []
        for name, names in tools.items():
            count = len(names)
            if show_names and names:
                summary_parts.append(f"{name}({count}): " + ", ".join(names))
            else:
                summary_parts.append(f"{name}:{count}")
        if isinstance(native_tools, list):
            summary_parts.append(f"native:{len(native_tools)}")
        _print_check("/api/tools/list", True, "; ".join(summary_parts) or "no tools")
        return True
    detail = err or (data if isinstance(data, str) else "")
    _print_check("/api/tools/list", False, detail or "unexpected response")
    return False


def run_tool_call(
    client: httpx.Client,
    base_url: str,
    tool_name: str,
    server_name: str,
    args: Dict[str, Any],
) -> bool:
    payload: Dict[str, Any] = {"name": tool_name, "arguments": args}
    if server_name:
        payload["server"] = server_name
    ok, data, err = _request_json(client, "POST", f"{base_url}/api/tools/call", json=payload)
    if ok:
        _print_check("/api/tools/call", True, tool_name)
        return True
    detail = err or (data if isinstance(data, str) else "")
    _print_check("/api/tools/call", False, detail or "unexpected response")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="VERA API diagnostics")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--model", default="grok-4-1-fast-reasoning")
    parser.add_argument("--message", default="Hello from diagnostics. Reply with OK.")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds")
    parser.add_argument("--tools", action="store_true", help="Check /api/tools")
    parser.add_argument("--tools-list", action="store_true", help="List MCP tools via /api/tools/list")
    parser.add_argument("--tools-list-names", action="store_true", help="List MCP tools with names")
    parser.add_argument("--call", dest="tool_call", help="Call a tool by name")
    parser.add_argument("--server", default="", help="MCP server name for tool call")
    parser.add_argument("--args", default="{}", help="JSON object for tool args")
    parser.add_argument("--args-file", default="", help="Path to JSON file with tool args")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    if args.args_file:
        try:
            with open(args.args_file, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except OSError as exc:
            print(f"Failed to read --args-file: {exc}")
            return 2
        try:
            tool_args = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON in --args-file: {exc}")
            return 2
    else:
        try:
            tool_args = json.loads(args.args)
        except json.JSONDecodeError as exc:
            print(f"Invalid --args JSON: {exc}")
            return 2
    if not isinstance(tool_args, dict):
        print("--args must be a JSON object")
        return 2

    ok_all = True
    with httpx.Client(timeout=args.timeout) as client:
        ok_all = run_health(client, base_url) and ok_all
        ok_all = run_models(client, base_url) and ok_all
        ok_all = run_chat(client, base_url, args.model, args.message) and ok_all

        if args.tools:
            ok_all = run_tools_status(client, base_url) and ok_all

        if args.tools_list or args.tools_list_names:
            ok_all = run_tools_list(client, base_url, show_names=args.tools_list_names) and ok_all

        if args.tool_call:
            ok_all = run_tool_call(client, base_url, args.tool_call, args.server, tool_args) and ok_all

    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
