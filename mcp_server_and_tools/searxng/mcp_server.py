#!/usr/bin/env python3
"""
Minimal MCP SearxNG Server (stdio JSON-RPC)
===========================================

Provides a `searxng_search` tool backed by a SearxNG instance.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional

import httpx


TOOLS = [
    {
        "name": "searxng_search",
        "description": (
            "Privacy-focused web search via local SearxNG metasearch engine. "
            "Aggregates results from 70+ search engines without tracking or rate limits. "
            "Prefer over brave_web_search when: (1) Brave is rate-limited, (2) privacy matters, "
            "(3) you need diverse source coverage, (4) searching niche categories (science, IT, files, music). "
            "Supports category filters: general, images, videos, news, music, files, it, science, social media."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query - be specific for better results"
                },
                "categories": {
                    "type": "string",
                    "description": (
                        "Comma-separated categories: general, images, videos, news, music, files, "
                        "it, science, social media. Default: general"
                    )
                },
                "language": {
                    "type": "string",
                    "description": "Language code (e.g., 'en', 'de', 'fr', 'es'). Default: en"
                },
                "safesearch": {
                    "type": "integer",
                    "description": "Safe search level: 0=off, 1=moderate, 2=strict. Default: 1"
                },
                "time_range": {
                    "type": "string",
                    "description": "Filter by time: 'day', 'week', 'month', 'year'. Omit for all time."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (1-20). Default: 5"
                }
            },
            "required": ["query"]
        }
    }
]


def _send_response(response: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _send_error(req_id: Optional[int], message: str, code: int = -32602) -> None:
    _send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    })


def _search(args: Dict[str, Any]) -> Any:
    query = args.get("query")
    if not query:
        raise ValueError("query is required")

    base_url = os.getenv("SEARXNG_BASE_URL", "").rstrip("/")

    params = {
        "q": query,
        "format": "json"
    }
    if args.get("categories"):
        params["categories"] = args["categories"]
    if args.get("language"):
        params["language"] = args["language"]
    if args.get("safesearch") is not None:
        params["safesearch"] = args["safesearch"]
    if args.get("time_range"):
        params["time_range"] = args["time_range"]

    limit = int(args.get("limit", 5))
    url = f"{base_url}/search"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }

    searx_error: Optional[str] = None
    if base_url:
        try:
            with httpx.Client(timeout=30.0, headers=headers) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError:
            searx_error = (
                "SearxNG service unreachable. Verify it's running: "
                "docker ps | grep searxng."
            )
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 429:
                searx_error = "SearxNG rate limited (upstream engines)."
            else:
                searx_error = f"SearxNG error {status}: {e.response.text[:200]}"
    else:
        searx_error = "SEARXNG_BASE_URL not set"

    if searx_error:
        return _search_brave_fallback(args, searx_error)

    raw_results = data.get("results", [])
    if not raw_results:
        return {
            "results": [],
            "query": params["q"],
            "note": "No results found. Try broader terms, different categories, or remove time_range filter."
        }

    results = []
    for item in raw_results[:limit]:
        results.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "snippet": item.get("content")
        })

    return {"results": results, "query": params["q"]}


def _search_brave_fallback(args: Dict[str, Any], reason: str) -> Dict[str, Any]:
    brave_api_key = os.getenv("BRAVE_API_KEY", "").strip()
    if not brave_api_key:
        raise ValueError(f"{reason} Fall back to brave_web_search.")

    brave_base_url = os.getenv("BRAVE_API_BASE_URL", "https://api.search.brave.com/res/v1").rstrip("/")
    try:
        limit = max(1, min(int(args.get("limit", 5)), 20))
    except (TypeError, ValueError):
        limit = 5

    brave_params: Dict[str, Any] = {"q": args.get("query"), "count": limit}
    if args.get("language"):
        brave_params["search_lang"] = args["language"]
    if args.get("safesearch") is not None:
        brave_params["safesearch"] = {0: "off", 1: "moderate", 2: "strict"}.get(args["safesearch"], "moderate")
    if args.get("time_range"):
        brave_params["freshness"] = args["time_range"]

    brave_headers = {
        "Accept": "application/json",
        "X-Subscription-Token": brave_api_key,
        "User-Agent": "vera-searxng-mcp/1.0",
    }

    try:
        with httpx.Client(timeout=30.0, headers=brave_headers) as client:
            response = client.get(f"{brave_base_url}/web/search", params=brave_params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise ValueError(f"{reason} Brave fallback failed: {exc}") from exc

    web_block = data.get("web", {})
    raw_results = web_block.get("results", []) if isinstance(web_block, dict) else []
    results = []
    for item in raw_results[:limit]:
        results.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "snippet": item.get("description") or item.get("snippet") or item.get("content"),
        })

    return {
        "results": results,
        "query": args.get("query"),
        "fallback": "brave_web_search",
        "note": f"SearxNG unavailable ({reason}) — returned Brave fallback results.",
    }


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
        if name != "searxng_search":
            _send_error(req_id, f"Unknown tool '{name}'", code=-32601)
            return
        try:
            result = _search(args)
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
                "serverInfo": {"name": "vera-searxng", "version": "1.0"},
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
