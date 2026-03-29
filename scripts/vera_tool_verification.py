#!/usr/bin/env python3
"""
VERA Tool Verification
======================

End-to-end MCP tool verification for a running VERA API instance.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

_SHUTDOWN_FLAG: Path | None = None
_RESPECT_SHUTDOWN_FLAG = False


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


def _print_status(state: str, label: str, detail: str = "") -> None:
    if detail:
        print(f"[{state}] {label} - {detail}")
    else:
        print(f"[{state}] {label}")


def _wait_for_api(client: httpx.Client, base_url: str, wait_seconds: int) -> bool:
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        ok, data, _ = _request_json(client, "GET", f"{base_url}/api/health")
        if ok and isinstance(data, dict) and data.get("ok") is True:
            return True
        time.sleep(1)
    return False


def _start_servers(client: httpx.Client, base_url: str, servers: List[str]) -> Dict[str, bool]:
    ok, data, err = _request_json(
        client,
        "POST",
        f"{base_url}/api/tools/start",
        json={"servers": servers},
    )
    if not ok:
        _print_status("FAIL", "/api/tools/start", err)
        return {}
    started = data.get("started", {}) if isinstance(data, dict) else {}
    return {name: bool(value) for name, value in started.items()}


def _get_tools_list(client: httpx.Client, base_url: str) -> Dict[str, List[str]]:
    ok, data, err = _request_json(client, "GET", f"{base_url}/api/tools/list")
    if not ok:
        _print_status("FAIL", "/api/tools/list", err)
        return {}
    tools = data.get("tools", {}) if isinstance(data, dict) else {}
    return {name: list(names) for name, names in tools.items()}


def _call_tool(
    client: httpx.Client,
    base_url: str,
    server: str,
    tool: str,
    args: Dict[str, Any],
    timeout: float,
) -> Tuple[bool, str]:
    if _RESPECT_SHUTDOWN_FLAG and _SHUTDOWN_FLAG and _SHUTDOWN_FLAG.exists():
        return False, "shutdown requested"
    ok, data, err = _request_json(
        client,
        "POST",
        f"{base_url}/api/tools/call",
        json={"server": server, "name": tool, "arguments": args},
        timeout=timeout,
    )
    if ok:
        return True, ""
    detail = err or (data if isinstance(data, str) else "")
    return False, detail


def _is_auth_error(detail: str) -> bool:
    lowered = detail.lower()
    return any(token in lowered for token in ("401", "403", "unauthorized", "invalid_grant", "credential", "oauth"))


def _pick_tool(tools: List[str], candidates: List[str]) -> str:
    for candidate in candidates:
        if candidate in tools:
            return candidate
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify VERA MCP tools")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--memvid-timeout", type=float, default=120.0)
    parser.add_argument("--youtube-timeout", type=float, default=60.0)
    parser.add_argument("--youtube-test-url", default="", help="YouTube URL/ID for youtube-transcript verification")
    parser.add_argument("--youtube-search-query", default="", help="Query for youtube-transcript search_youtube verification")
    parser.add_argument("--wait", type=int, default=30, help="Seconds to wait for API readiness")
    parser.add_argument(
        "--respect-shutdown-flag",
        action="store_true",
        help="Honor tmp/shutdown_requested and skip verification when present.",
    )
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    root_dir = Path(__file__).resolve().parents[1]
    global _SHUTDOWN_FLAG
    global _RESPECT_SHUTDOWN_FLAG
    _SHUTDOWN_FLAG = root_dir / "tmp" / "shutdown_requested"
    _RESPECT_SHUTDOWN_FLAG = bool(args.respect_shutdown_flag)
    tmp_dir = root_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    expected_servers = [
        "filesystem",
        "memory",
        "time",
        "sequential-thinking",
        "wikipedia-mcp",
        "pdf-reader",
        "memvid",
        "youtube-transcript",
        "searxng",
        "brave-search",
        "github",
        "google-workspace",
    ]

    failures: List[str] = []
    skipped: List[str] = []
    ok_count = 0

    with httpx.Client(timeout=args.timeout) as client:
        if not _wait_for_api(client, base_url, args.wait):
            _print_status("FAIL", "api", "API not ready")
            return 1

        if _RESPECT_SHUTDOWN_FLAG and _SHUTDOWN_FLAG.exists():
            _print_status("SKIP", "verify", "shutdown requested")
            return 0

        _start_servers(client, base_url, expected_servers)
        tools_map = _get_tools_list(client, base_url)

        def record_ok(label: str) -> None:
            nonlocal ok_count
            ok_count += 1
            _print_status("OK", label)

        def record_skip(label: str, detail: str) -> None:
            skipped.append(label)
            _print_status("SKIP", label, detail)

        def record_fail(label: str, detail: str) -> None:
            if detail == "shutdown requested":
                _print_status("SKIP", label, detail)
                raise SystemExit(0)
            failures.append(label)
            _print_status("FAIL", label, detail)

        # filesystem
        tools = tools_map.get("filesystem", [])
        fs_tool = _pick_tool(tools, ["list_allowed_directories", "list_directory"])
        if fs_tool:
            fs_args = {} if fs_tool == "list_allowed_directories" else {"path": str(root_dir)}
            ok, detail = _call_tool(client, base_url, "filesystem", fs_tool, fs_args, args.timeout)
            record_ok("filesystem") if ok else record_fail("filesystem", detail)
        else:
            record_skip("filesystem", "tool not available")

        # memory
        tools = tools_map.get("memory", [])
        if "read_graph" in tools:
            ok, detail = _call_tool(client, base_url, "memory", "read_graph", {}, args.timeout)
            record_ok("memory") if ok else record_fail("memory", detail)
        else:
            record_skip("memory", "tool not available")

        # time
        tools = tools_map.get("time", [])
        if "time" in tools:
            ok, detail = _call_tool(
                client,
                base_url,
                "time",
                "time",
                {"timezone": "UTC", "format": "iso"},
                args.timeout,
            )
            record_ok("time") if ok else record_fail("time", detail)
        else:
            record_skip("time", "tool not available")

        # sequential-thinking
        tools = tools_map.get("sequential-thinking", [])
        if "sequentialthinking" in tools:
            ok, detail = _call_tool(
                client,
                base_url,
                "sequential-thinking",
                "sequentialthinking",
                {
                    "thought": "diagnostic test",
                    "nextThoughtNeeded": False,
                    "thoughtNumber": 1,
                    "totalThoughts": 1,
                },
                args.timeout,
            )
            record_ok("sequential-thinking") if ok else record_fail("sequential-thinking", detail)
        else:
            record_skip("sequential-thinking", "tool not available")

        # wikipedia
        tools = tools_map.get("wikipedia-mcp", [])
        if "search_wikipedia" in tools:
            ok, detail = _call_tool(
                client,
                base_url,
                "wikipedia-mcp",
                "search_wikipedia",
                {"query": "Vera AI", "limit": 1},
                args.timeout,
            )
            record_ok("wikipedia-mcp") if ok else record_fail("wikipedia-mcp", detail)
        else:
            record_skip("wikipedia-mcp", "tool not available")

        # pdf-reader
        tools = tools_map.get("pdf-reader", [])
        pdf_path = root_dir / "research" / "Skeleton_of_Thought.pdf"
        if "get_pdf_info" in tools and pdf_path.exists():
            ok, detail = _call_tool(
                client,
                base_url,
                "pdf-reader",
                "get_pdf_info",
                {"file_path": str(pdf_path)},
                args.timeout,
            )
            record_ok("pdf-reader") if ok else record_fail("pdf-reader", detail)
        elif "get_pdf_info" in tools:
            record_skip("pdf-reader", f"missing file {pdf_path}")
        else:
            record_skip("pdf-reader", "tool not available")

        # memvid
        tools = tools_map.get("memvid", [])
        if "memvid_encode_text" in tools and "memvid_search" in tools:
            video_path = tmp_dir / "vera_memvid_verify.mp4"
            index_path = tmp_dir / "vera_memvid_verify.index"
            ok, detail = _call_tool(
                client,
                base_url,
                "memvid",
                "memvid_encode_text",
                {
                    "text": "diagnostic memory test",
                    "output_video": str(video_path),
                    "output_index": str(index_path),
                    "chunk_size": 200,
                    "overlap": 20,
                },
                args.memvid_timeout,
            )
            if ok:
                ok, detail = _call_tool(
                    client,
                    base_url,
                    "memvid",
                    "memvid_search",
                    {
                        "query": "diagnostic",
                        "video_path": str(video_path),
                        "index_path": str(index_path),
                        "top_k": 3,
                    },
                    args.memvid_timeout,
                )
                record_ok("memvid") if ok else record_fail("memvid", detail)
            else:
                record_fail("memvid", detail)
        else:
            record_skip("memvid", "tool not available")

        # youtube-transcript
        tools = tools_map.get("youtube-transcript", [])
        if "get_transcript" in tools:
            test_url = args.youtube_test_url.strip() or os.getenv("YOUTUBE_TRANSCRIPT_TEST_URL", "").strip()
            if test_url:
                ok, detail = _call_tool(
                    client,
                    base_url,
                    "youtube-transcript",
                    "get_transcript",
                    {"url": test_url, "lang": "en", "include_timestamps": False, "strip_ads": True},
                    args.youtube_timeout,
                )
                record_ok("youtube-transcript") if ok else record_fail("youtube-transcript", detail)
            else:
                record_skip("youtube-transcript", "set YOUTUBE_TRANSCRIPT_TEST_URL to enable")
        else:
            record_skip("youtube-transcript", "tool not available")

        if "search_youtube" in tools:
            search_query = args.youtube_search_query.strip() or os.getenv("YOUTUBE_TRANSCRIPT_SEARCH_QUERY", "").strip()
            if search_query:
                ok, detail = _call_tool(
                    client,
                    base_url,
                    "youtube-transcript",
                    "search_youtube",
                    {"query": search_query, "max_results": 3},
                    args.youtube_timeout,
                )
                record_ok("youtube-search") if ok else record_fail("youtube-search", detail)
            else:
                record_skip("youtube-search", "set YOUTUBE_TRANSCRIPT_SEARCH_QUERY to enable")
        else:
            record_skip("youtube-search", "tool not available")

        # searxng
        tools = tools_map.get("searxng", [])
        if "searxng_search" in tools:
            ok, detail = _call_tool(
                client,
                base_url,
                "searxng",
                "searxng_search",
                {"query": "Vera AI"},
                args.timeout,
            )
            record_ok("searxng") if ok else record_fail("searxng", detail)
        else:
            record_skip("searxng", "tool not available")

        # brave-search
        tools = tools_map.get("brave-search", [])
        brave_tool = _pick_tool(tools, ["brave_web_search", "brave_local_search"])
        if brave_tool:
            ok, detail = _call_tool(
                client,
                base_url,
                "brave-search",
                brave_tool,
                {"query": "Vera AI"},
                args.timeout,
            )
            record_ok("brave-search") if ok else record_fail("brave-search", detail)
        else:
            record_skip("brave-search", "tool not available")

        # github
        tools = tools_map.get("github", [])
        github_tool = _pick_tool(tools, ["search_repositories", "search_code"])
        if github_tool:
            ok, detail = _call_tool(
                client,
                base_url,
                "github",
                github_tool,
                {"query": "vera"},
                args.timeout,
            )
            record_ok("github") if ok else record_fail("github", detail)
        else:
            record_skip("github", "tool not available")

        # google-workspace
        tools = tools_map.get("google-workspace", [])
        google_tool = _pick_tool(tools, ["list_calendars", "list_drive_items", "list_task_lists"])
        if google_tool:
            ok, detail = _call_tool(
                client,
                base_url,
                "google-workspace",
                google_tool,
                {},
                args.timeout,
            )
            if ok:
                record_ok("google-workspace")
            elif _is_auth_error(detail):
                record_skip("google-workspace", "auth required")
            else:
                record_fail("google-workspace", detail)
        else:
            record_skip("google-workspace", "tool not available")

    print("\nVerification summary:")
    print(f"  OK: {ok_count}")
    print(f"  Skipped: {len(skipped)}")
    print(f"  Failed: {len(failures)}")
    if skipped:
        print(f"  Skipped tools: {', '.join(skipped)}")
    if failures:
        print(f"  Failed tools: {', '.join(failures)}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
