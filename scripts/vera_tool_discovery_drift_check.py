#!/usr/bin/env python3
"""
Validate tool-name discovery consistency for Doctor/Professor expectations.

Checks expected tool identifiers against:
- /api/tools/list
- /api/tools/defs
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Set, Tuple
from urllib import error, request


EXPECTED: Dict[str, Set[str]] = {
    "native": {"encode_event", "retrieve_memory", "search_archive"},
    "filesystem": {"list_allowed_directories"},
    "memory": {"read_graph"},
    "time": {"time"},
    "sequential-thinking": {"sequentialthinking"},
    "wikipedia-mcp": {"search_wikipedia"},
    "pdf-reader": {"get_pdf_info"},
    "memvid": {"memvid_encode_text"},
    "youtube-transcript": {"search_youtube"},
    "searxng": {"searxng_search"},
    "brave-search": {"brave_web_search"},
    "github": {"list_commits"},
    "google-workspace": {"list_calendars"},
    "obsidian-vault": {"list_allowed_directories"},
    "composio": {"COMPOSIO_SEARCH_TOOLS"},
    "calculator": {"calculate"},
    "stealth-browser": {"list_instances"},
    "x-twitter": {"get_trends"},
    "scrapeless": {"google_search"},
    "marm-memory": {"marm_system_info"},
    "browserbase": {"browserbase_session_create"},
    "call-me": {"send_native_push"},
    "sandbox": {"sandbox_shell_exec"},
}


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _request_json(url: str, timeout: float = 20.0) -> Tuple[bool, Dict[str, Any], str]:
    req = request.Request(url=url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(payload, dict):
                return True, payload, ""
            return False, {}, "non-dict JSON payload"
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, {}, f"HTTP {exc.code}: {body[:500]}"
    except Exception as exc:
        return False, {}, str(exc)


def _extract_defs_tools(payload: Dict[str, Any]) -> Tuple[Dict[str, Set[str]], Set[str]]:
    server_tools: Dict[str, Set[str]] = {}
    for server, entries in payload.get("tools", {}).items():
        names: Set[str] = set()
        if isinstance(entries, list):
            for item in entries:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name:
                        names.add(name)
        server_tools[str(server)] = names

    native: Set[str] = set()
    entries = payload.get("native_tools", [])
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            fn = item.get("function")
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            if isinstance(name, str) and name:
                native.add(name)
    return server_tools, native


def main() -> int:
    parser = argparse.ArgumentParser(description="Check tool-discovery drift for expected Doctor/Professor tools")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    ok_list, payload_list, err_list = _request_json(f"{base}/api/tools/list")
    ok_defs, payload_defs, err_defs = _request_json(f"{base}/api/tools/defs")

    list_tools = payload_list.get("tools", {}) if ok_list else {}
    list_native = set(payload_list.get("native_tools", [])) if ok_list else set()
    defs_tools, defs_native = _extract_defs_tools(payload_defs) if ok_defs else ({}, set())

    checks = []
    total_missing = 0
    for server, expected in sorted(EXPECTED.items()):
        if server == "native":
            missing_list = sorted(expected - list_native)
            missing_defs = sorted(expected - defs_native)
            check = {
                "server": server,
                "expected": sorted(expected),
                "list_missing": missing_list,
                "defs_missing": missing_defs,
                "server_in_list": True,
                "server_in_defs": True,
            }
        else:
            list_set = set(list_tools.get(server, [])) if isinstance(list_tools, dict) else set()
            defs_set = defs_tools.get(server, set())
            missing_list = sorted(expected - list_set)
            missing_defs = sorted(expected - defs_set)
            check = {
                "server": server,
                "expected": sorted(expected),
                "list_missing": missing_list,
                "defs_missing": missing_defs,
                "server_in_list": server in list_tools if isinstance(list_tools, dict) else False,
                "server_in_defs": server in defs_tools,
            }
            if not check["server_in_list"] or not check["server_in_defs"]:
                total_missing += 1

        total_missing += len(missing_list) + len(missing_defs)
        checks.append(check)

    report = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": base,
        "api_ok": {
            "tools_list": ok_list,
            "tools_defs": ok_defs,
        },
        "api_errors": {
            "tools_list": err_list,
            "tools_defs": err_defs,
        },
        "checks": checks,
        "overall_ok": bool(ok_list and ok_defs and total_missing == 0),
        "total_missing": total_missing,
    }

    ts = _utc_ts()
    output = args.output or f"tmp/tool_discovery_drift_check_{ts}.json"
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(output_path)
    print(
        json.dumps(
            {
                "overall_ok": report["overall_ok"],
                "total_missing": report["total_missing"],
            },
            indent=2,
        )
    )
    return 0 if report["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
