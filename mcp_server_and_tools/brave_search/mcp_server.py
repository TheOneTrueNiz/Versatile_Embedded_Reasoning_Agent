#!/usr/bin/env python3
"""
Minimal MCP Brave Search Server (stdio JSON-RPC)
================================================

Exposes Brave Search API endpoints beyond basic web search.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Iterable, Optional

import httpx


API_KEY = os.getenv("BRAVE_API_KEY", "").strip()


def _get_base_url() -> str:
    value = os.getenv("BRAVE_API_BASE_URL", "").strip()
    if not value:
        return "https://api.search.brave.com/res/v1"
    return value.rstrip("/")


TOOLS = [
    {
        "name": "brave_web_search",
        "description": (
            "Primary web search — best for commercial queries, product info, recent events, and fact-checking. "
            "Fast and high-quality. Use freshness='day' for breaking news, 'week' for recent developments. "
            "Set summary=true to get a summary_key for follow-up with brave_summarize. "
            "Prefer this over searxng_search for speed; use searxng_search as fallback if rate-limited."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {"type": "integer", "description": "Number of results to return"},
                "offset": {"type": "integer", "description": "Pagination offset"},
                "country": {"type": "string", "description": "Country code (e.g., US)"},
                "search_lang": {"type": "string", "description": "Search language (e.g., en)"},
                "ui_lang": {"type": "string", "description": "UI language (e.g., en-US)"},
                "safesearch": {"type": "string", "description": "off, moderate, or strict"},
                "freshness": {"type": "string", "description": "day, week, month, or year"},
                "result_filter": {"type": "array", "items": {"type": "string"}, "description": "Result filters"},
                "goggles": {"type": "string", "description": "Goggles ID"},
                "summary": {"type": "boolean", "description": "Include summary key"},
                "extra_snippets": {"type": "boolean", "description": "Include extra snippets"},
                "text_decorations": {"type": "boolean", "description": "Enable text decorations"},
                "spellcheck": {"type": "boolean", "description": "Enable spellcheck"},
                "units": {"type": "string", "description": "Units: metric or imperial"},
                "include_raw": {"type": "boolean", "description": "Include raw API response"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "brave_news_search",
        "description": (
            "Search for news articles. Use for: current events, breaking news, 'latest on X', "
            "recent developments, headlines. Supports freshness (day/week/month) to filter by recency. "
            "Returns title, URL, snippet for each news article."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {"type": "integer", "description": "Number of results to return"},
                "offset": {"type": "integer", "description": "Pagination offset"},
                "country": {"type": "string", "description": "Country code (e.g., US)"},
                "search_lang": {"type": "string", "description": "Search language (e.g., en)"},
                "freshness": {"type": "string", "description": "day, week, month, or year"},
                "safesearch": {"type": "string", "description": "off, moderate, or strict"},
                "spellcheck": {"type": "boolean", "description": "Enable spellcheck"},
                "include_raw": {"type": "boolean", "description": "Include raw API response"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "brave_video_search",
        "description": (
            "Search for videos. Use for: 'find videos about X', tutorials, how-to videos, "
            "entertainment content, lectures. Returns video titles, URLs, and descriptions. "
            "Use freshness to find recent uploads."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {"type": "integer", "description": "Number of results to return"},
                "offset": {"type": "integer", "description": "Pagination offset"},
                "country": {"type": "string", "description": "Country code (e.g., US)"},
                "search_lang": {"type": "string", "description": "Search language (e.g., en)"},
                "freshness": {"type": "string", "description": "day, week, month, or year"},
                "safesearch": {"type": "string", "description": "off, moderate, or strict"},
                "include_raw": {"type": "boolean", "description": "Include raw API response"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "brave_image_search",
        "description": (
            "Search for images. Use for: finding pictures, visual references, 'show me X', "
            "image examples, visual inspiration. Returns image URLs and descriptions. "
            "Supports safesearch filtering."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {"type": "integer", "description": "Number of results to return"},
                "offset": {"type": "integer", "description": "Pagination offset"},
                "country": {"type": "string", "description": "Country code (e.g., US)"},
                "search_lang": {"type": "string", "description": "Search language (e.g., en)"},
                "safesearch": {"type": "string", "description": "off, moderate, or strict"},
                "include_raw": {"type": "boolean", "description": "Include raw API response"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "brave_local_search",
        "description": (
            "Search for local places/businesses. Use for: 'restaurants near X', 'find a X nearby', "
            "local businesses, points of interest. Returns POI details with addresses, ratings, hours. "
            "Can include descriptions for richer info."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "ids": {"type": "array", "items": {"type": "string"}, "description": "Location ids from web search"},
                "count": {"type": "integer", "description": "Number of results to return"},
                "offset": {"type": "integer", "description": "Pagination offset"},
                "country": {"type": "string", "description": "Country code (e.g., US)"},
                "search_lang": {"type": "string", "description": "Search language (e.g., en)"},
                "ui_lang": {"type": "string", "description": "UI language (e.g., en-US)"},
                "include_descriptions": {"type": "boolean", "description": "Fetch POI descriptions"},
                "include_raw": {"type": "boolean", "description": "Include raw API response"}
            },
            "required": []
        }
    },
    {
        "name": "brave_suggest",
        "description": (
            "Get search query suggestions/autocomplete. Use for: refining vague queries, "
            "discovering related searches, understanding what people search for. "
            "Helps formulate better search queries."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "country": {"type": "string", "description": "Country code (e.g., US)"},
                "search_lang": {"type": "string", "description": "Search language (e.g., en)"},
                "include_raw": {"type": "boolean", "description": "Include raw API response"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "brave_spellcheck",
        "description": (
            "Check spelling of a query. Use for: correcting misspelled words before searching, "
            "verifying spelling, handling typos. Returns corrected query suggestions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "country": {"type": "string", "description": "Country code (e.g., US)"},
                "search_lang": {"type": "string", "description": "Search language (e.g., en)"},
                "include_raw": {"type": "boolean", "description": "Include raw API response"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "brave_summarize",
        "description": (
            "Get AI-generated summary from search results. REQUIRES summary_key from brave_web_search "
            "(call with summary=true first). Use for: quick overviews, TL;DR of search results, "
            "synthesizing multiple sources into one answer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary_key": {"type": "string", "description": "Summary key from brave_web_search"},
                "include_raw": {"type": "boolean", "description": "Include raw API response"}
            },
            "required": ["summary_key"]
        }
    },
    {
        "name": "brave_ai_grounding",
        "description": (
            "AI-powered Q&A with web grounding — Brave's built-in AI synthesizes an answer from search results. "
            "Best for: complex factual questions, multi-source research, 'explain X' queries. "
            "Returns a single coherent answer. Set enable_research=true ONLY when user explicitly asks for "
            "deep research (triggers multiple searches, slower). Default mode is fast single-search."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "User question (if messages not provided)"},
                "messages": {"type": "array", "items": {"type": "object"}, "description": "OpenAI-style messages"},
                "model": {"type": "string", "description": "Model name (default: brave)"},
                "stream": {"type": "boolean", "description": "Streaming responses (not supported via MCP)"},
                "enable_research": {"type": "boolean", "description": "Enable multi-search research mode (only when explicitly requested)"},
                "enable_citations": {"type": "boolean", "description": "Include citations in the response"},
                "enable_entities": {"type": "boolean", "description": "Enable entity extraction"},
                "country": {"type": "string", "description": "Country code (e.g., US)"},
                "language": {"type": "string", "description": "Language code (e.g., en)"},
                "include_raw": {"type": "boolean", "description": "Include raw API response"}
            },
            "required": []
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


def _bool_to_str(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _clean_params(args: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for arg_key, param_key in mapping.items():
        value = args.get(arg_key)
        if value is None:
            continue
        if isinstance(value, list):
            value = ",".join([str(item) for item in value if item is not None])
            if not value:
                continue
        value = _bool_to_str(value)
        params[param_key] = value
    return params


def _require_api_key() -> None:
    if not API_KEY:
        raise ValueError("BRAVE_API_KEY not set")


def _request_json(endpoint: str, params: Optional[Any] = None,
                  json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    _require_api_key()
    url = f"{_get_base_url()}/{endpoint.lstrip('/')}"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": API_KEY,
        "User-Agent": "vera-brave-mcp/1.0"
    }
    with httpx.Client(timeout=30.0, headers=headers) as client:
        if json_body is None:
            response = client.get(url, params=params)
        else:
            response = client.post(url, params=params, json=json_body)
    if response.status_code >= 400:
        status = response.status_code
        body = response.text[:200]
        hint = {
            401: "Invalid or expired BRAVE_API_KEY. Check ~/Documents/creds/brave/brave_api.",
            403: "API key lacks permission for this endpoint. Verify subscription tier.",
            429: "Rate limited. Wait 10-30s and retry, or switch to searxng_search.",
            500: "Brave API internal error. Retry once, then fall back to searxng_search.",
            503: "Brave API temporarily unavailable. Fall back to searxng_search.",
        }.get(status, "")
        msg = f"Brave API error {status}: {body}"
        if hint:
            msg += f" | Recovery: {hint}"
        raise ValueError(msg)
    return response.json()


def _simplify_results(data: Dict[str, Any], root_key: str) -> Iterable[Dict[str, Any]]:
    payload = data.get(root_key)
    if isinstance(payload, dict):
        items = payload.get("results")
        if isinstance(items, list):
            return items
    if isinstance(payload, list):
        return payload
    if isinstance(data.get("results"), list):
        return data["results"]
    return []


def _format_search_response(data: Dict[str, Any], root_key: str, include_raw: bool) -> Dict[str, Any]:
    simplified = []
    for item in _simplify_results(data, root_key):
        simplified.append({
            "title": item.get("title") or item.get("name") or "",
            "url": item.get("url") or item.get("link") or "",
            "snippet": item.get("description") or item.get("snippet") or item.get("content") or ""
        })

    response: Dict[str, Any] = {"results": simplified}
    summary_block = data.get("summary") or data.get("summarizer")
    if isinstance(summary_block, dict):
        summary_key = summary_block.get("key") or summary_block.get("summary_key")
        if summary_key:
            response["summary_key"] = summary_key
    if include_raw:
        response["raw"] = data
    return response


def _web_search(args: Dict[str, Any]) -> Dict[str, Any]:
    params = _clean_params(args, {
        "query": "q",
        "count": "count",
        "offset": "offset",
        "country": "country",
        "search_lang": "search_lang",
        "ui_lang": "ui_lang",
        "safesearch": "safesearch",
        "freshness": "freshness",
        "result_filter": "result_filter",
        "goggles": "goggles",
        "summary": "summary",
        "extra_snippets": "extra_snippets",
        "text_decorations": "text_decorations",
        "spellcheck": "spellcheck",
        "units": "units"
    })
    if "q" not in params:
        raise ValueError("query is required")
    data = _request_json("web/search", params=params)
    return _format_search_response(data, "web", bool(args.get("include_raw")))


def _news_search(args: Dict[str, Any]) -> Dict[str, Any]:
    params = _clean_params(args, {
        "query": "q",
        "count": "count",
        "offset": "offset",
        "country": "country",
        "search_lang": "search_lang",
        "freshness": "freshness",
        "safesearch": "safesearch",
        "spellcheck": "spellcheck"
    })
    if "q" not in params:
        raise ValueError("query is required")
    data = _request_json("news/search", params=params)
    return _format_search_response(data, "news", bool(args.get("include_raw")))


def _video_search(args: Dict[str, Any]) -> Dict[str, Any]:
    params = _clean_params(args, {
        "query": "q",
        "count": "count",
        "offset": "offset",
        "country": "country",
        "search_lang": "search_lang",
        "freshness": "freshness",
        "safesearch": "safesearch"
    })
    if "q" not in params:
        raise ValueError("query is required")
    data = _request_json("videos/search", params=params)
    return _format_search_response(data, "videos", bool(args.get("include_raw")))


def _image_search(args: Dict[str, Any]) -> Dict[str, Any]:
    params = _clean_params(args, {
        "query": "q",
        "count": "count",
        "offset": "offset",
        "country": "country",
        "search_lang": "search_lang",
        "safesearch": "safesearch"
    })
    if "q" not in params:
        raise ValueError("query is required")
    data = _request_json("images/search", params=params)
    return _format_search_response(data, "images", bool(args.get("include_raw")))


def _extract_poi_ids(pois: Iterable[Dict[str, Any]]) -> str:
    ids = []
    for item in pois:
        for key in ("id", "poi_id", "place_id", "location_id"):
            value = item.get(key)
            if value:
                ids.append(str(value))
                break
    return ",".join(ids)


def _extract_location_ids(data: Dict[str, Any]) -> list[str]:
    locations = data.get("locations")
    if isinstance(locations, dict):
        results = locations.get("results")
        if isinstance(results, list):
            return [item.get("id") for item in results if isinstance(item, dict) and item.get("id")]

    return []


def _ensure_ids(args: Dict[str, Any]) -> list[str]:
    ids = args.get("ids")
    if isinstance(ids, list):
        return [str(item) for item in ids if item]
    if isinstance(ids, str) and ids.strip():
        return [value.strip() for value in ids.split(",") if value.strip()]
    return []


def _limit_ids(ids: list[str], args: Dict[str, Any]) -> list[str]:
    raw_count = args.get("count")
    try:
        max_count = int(raw_count) if raw_count is not None else 20
    except (TypeError, ValueError):
        max_count = 20
    if max_count <= 0:
        max_count = 20
    max_count = min(max_count, 20)

    raw_offset = args.get("offset")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0

    if offset:
        return ids[offset:offset + max_count]
    return ids[:max_count]


def _local_search(args: Dict[str, Any]) -> Dict[str, Any]:
    ids = _ensure_ids(args)
    if not ids:
        params = _clean_params(args, {
            "query": "q",
            "count": "count",
            "offset": "offset",
            "country": "country",
            "search_lang": "search_lang",
            "ui_lang": "ui_lang"
        })
        if "q" not in params:
            raise ValueError("query or ids is required")
        params["result_filter"] = "locations"
        location_data = _request_json("web/search", params=params)
        ids = _extract_location_ids(location_data)
        if not ids:
            raise ValueError("No location ids found in web search results")

    ids = _limit_ids(ids, args)
    query_params = [("ids", value) for value in ids]
    data = _request_json("local/pois", params=query_params)

    include_raw = bool(args.get("include_raw"))
    response: Dict[str, Any] = {"pois": _simplify_results(data, "pois")}
    if include_raw:
        response["raw"] = data

    if args.get("include_descriptions"):
        poi_ids = _extract_poi_ids(response["pois"])
        desc_source = [value for value in poi_ids.split(",") if value] if poi_ids else ids
        if desc_source:
            desc_ids = _limit_ids(desc_source, args)
            response["descriptions"] = _request_json(
                "local/descriptions",
                params=[("ids", value) for value in desc_ids]
            )
        else:
            response["descriptions"] = []
    return response


def _suggest(args: Dict[str, Any]) -> Dict[str, Any]:
    params = _clean_params(args, {
        "query": "q",
        "country": "country",
        "search_lang": "search_lang"
    })
    if "q" not in params:
        raise ValueError("query is required")
    data = _request_json("suggest/search", params=params)

    response: Dict[str, Any] = {"suggestions": data.get("suggestions", data)}
    if args.get("include_raw"):
        response["raw"] = data
    return response


def _spellcheck(args: Dict[str, Any]) -> Dict[str, Any]:
    params = _clean_params(args, {
        "query": "q",
        "country": "country",
        "search_lang": "search_lang"
    })
    if "q" not in params:
        raise ValueError("query is required")
    data = _request_json("spellcheck/search", params=params)

    response: Dict[str, Any] = {"spellcheck": data}
    if args.get("include_raw"):
        response["raw"] = data
    return response


def _summarize(args: Dict[str, Any]) -> Dict[str, Any]:
    key = args.get("summary_key")
    if not key:
        raise ValueError("summary_key is required")
    data = _request_json("summarizer/summary", params={"key": key})

    summary = data.get("summary", data)
    if isinstance(summary, list):
        summary_text = "".join(
            item.get("data", "") for item in summary if isinstance(item, dict)
        )
    else:
        summary_text = summary
    response: Dict[str, Any] = {"summary": summary_text}
    if args.get("include_raw"):
        response["raw"] = data
    return response


def _normalize_grounding_messages(args: Dict[str, Any]) -> list[Dict[str, Any]]:
    messages = args.get("messages")
    if messages is None:
        query = args.get("query") or args.get("prompt")
        if not query:
            raise ValueError("query or messages is required")
        return [{"role": "user", "content": str(query)}]

    if not isinstance(messages, list):
        raise ValueError("messages must be a list")

    normalized = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role") or "user"
        content = item.get("content", "")
        if content is None:
            content = ""
        normalized.append({"role": role, "content": content})

    if not normalized:
        raise ValueError("messages must contain at least one entry")
    return normalized


def _ai_grounding(args: Dict[str, Any]) -> Dict[str, Any]:
    stream = bool(args.get("stream", False))
    if stream:
        raise ValueError("Streaming is not supported via MCP. Set stream=false.")

    payload: Dict[str, Any] = {
        "model": args.get("model") or "brave",
        "messages": _normalize_grounding_messages(args),
        "stream": False,
    }

    if "enable_research" in args:
        payload["enable_research"] = bool(args["enable_research"])
    if "enable_citations" in args:
        if stream:
            payload["enable_citations"] = bool(args["enable_citations"])
        else:
            response_note = "enable_citations requires stream=true; ignored for blocking response."
    if "enable_entities" in args:
        payload["enable_entities"] = bool(args["enable_entities"])
    if args.get("country"):
        payload["country"] = str(args["country"])
    if args.get("language"):
        payload["language"] = str(args["language"])

    data = _request_json("chat/completions", json_body=payload)

    response: Dict[str, Any] = {}
    if "response_note" in locals():
        response["note"] = response_note
    if isinstance(data, dict):
        choices = data.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            response["answer"] = message.get("content")
        if "usage" in data:
            response["usage"] = data["usage"]

    if args.get("include_raw"):
        response["raw"] = data

    if "answer" not in response:
        response["answer"] = data

    return response


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
        try:
            if name == "brave_web_search":
                result = _web_search(args)
            elif name == "brave_news_search":
                result = _news_search(args)
            elif name == "brave_video_search":
                result = _video_search(args)
            elif name == "brave_image_search":
                result = _image_search(args)
            elif name == "brave_local_search":
                result = _local_search(args)
            elif name == "brave_suggest":
                result = _suggest(args)
            elif name == "brave_spellcheck":
                result = _spellcheck(args)
            elif name == "brave_summarize":
                result = _summarize(args)
            elif name == "brave_ai_grounding":
                result = _ai_grounding(args)
            else:
                _send_error(req_id, f"Unknown tool '{name}'", code=-32601)
                return
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
                "serverInfo": {"name": "vera-brave-search", "version": "1.0"},
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
