#!/usr/bin/env python3
"""
Server-by-server MCP tool training/verification harness.

This script is designed for "teach Vera her tools" passes:
1) Per tool routing drill via /v1/chat/completions (did the model pick the tool?)
2) Optional direct tool call via /api/tools/call (does the tool execute with sample args?)

By default, side-effect tools are skipped to avoid unintended external actions.
Use --include-side-effects to exercise them.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
TRAINING_TMP_DIR = ROOT_DIR / "tmp"
TRAINING_TEXT_PATH = TRAINING_TMP_DIR / "tool_training.txt"
TRAINING_IMAGE_PATH = TRAINING_TMP_DIR / "tool_training.png"
TRAINING_MEMVID_VIDEO_PATH = TRAINING_TMP_DIR / "tool_training_memvid.mp4"
TRAINING_MEMVID_INDEX_PATH = TRAINING_TMP_DIR / "tool_training_memvid.index"
DEFAULT_OBSIDIAN_VAULT_PATH = (
    Path(os.getenv("OBSIDIAN_VAULT_PATH")).expanduser()
    if os.getenv("OBSIDIAN_VAULT_PATH")
    else (Path.home() / "Documents" / "Veras_Vault")
)
_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX8QAAAAASUVORK5CYII="


SAFE_TOOL_PREFIXES: Tuple[str, ...] = (
    "get_",
    "list_",
    "read_",
    "search_",
    "find_",
    "test_",
    "time",
    "calculate",
    "sequential",
    "open_nodes",
    "read_graph",
    "memvid_search",
)

SIDE_EFFECT_HINTS: Tuple[str, ...] = (
    "create",
    "update",
    "delete",
    "remove",
    "write",
    "edit",
    "move",
    "send",
    "post_",
    "add_",
    "push",
    "initiate_call",
    "merge",
    "fork",
    "upload",
    "insert",
    "replace",
    "launch",
    "start",
    "stop",
    "navigate",
    "click",
    "run_",
    "execute",
    "clear",
    "reset",
    "favorite",
    "bookmark",
    "vote",
    "unfavorite",
)

BLOCKED_ERROR_HINTS: Tuple[str, ...] = (
    "option is not subscribed in the plan",
    "too many requests",
    "rate limit",
    "unauthorized",
    "authentication",
    "api key",
    "permission denied",
    "when authenticating requests to the twitter api v2 endpoints",
    "subset of x api v2 endpoints",
    "google chat app",
    "google docs api",
    "google sheets api",
    "google drive api",
    "tool-training-id",
    "does not match the pattern",
    "instance not found",
    "tool call timed out after",
    "timed out after",
    "invalid tools/call result",
    "unexpected keyword argument 'service'",
    "eisdir",
    "is a directory",
    "[object object]",
)

TOOL_ARG_OVERRIDES: Dict[str, Dict[str, Any]] = {
    # Brave local/grounding endpoints accept optional query but require it in practice.
    "brave_local_search": {"query": "coffee near downtown", "country": "US"},
    "brave_ai_grounding": {"query": "What is model context protocol?", "language": "en", "country": "US"},
    # Memvid tools need concrete files/paths.
    "memvid_encode_file": {
        "file_path": str(TRAINING_TEXT_PATH),
        "output_video": str(TRAINING_MEMVID_VIDEO_PATH),
        "output_index": str(TRAINING_MEMVID_INDEX_PATH),
        "chunk_size": 200,
        "overlap": 20,
    },
    "memvid_search": {
        "query": "tool training",
        "video_path": str(TRAINING_MEMVID_VIDEO_PATH),
        "index_path": str(TRAINING_MEMVID_INDEX_PATH),
        "top_k": 3,
    },
    # Calculator conversion checks need concrete units accepted by this tool.
    "convert_units": {"value": 1, "from_unit": "m", "to_unit": "cm"},
    # Grokipedia expects canonical slugs.
    "get_page": {"slug": "Artificial_intelligence"},
    "get_page_content": {"slug": "Artificial_intelligence"},
    "get_page_citations": {"slug": "Artificial_intelligence"},
    "get_related_pages": {"slug": "Artificial_intelligence"},
    "get_page_section": {"slug": "Artificial_intelligence", "section_header": "Artificial intelligence"},
    "get_page_sections": {"slug": "Artificial_intelligence"},
    # YouTube transcript parser expects a real YouTube URL/ID pattern.
    "get_transcript": {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "lang": "en"},
    # GitHub read-only baseline repository/targets.
    "get_file_contents": {"owner": "openai", "repo": "openai-python", "path": "README.md"},
    "list_commits": {"owner": "openai", "repo": "openai-python"},
    "list_issues": {"owner": "openai", "repo": "openai-python", "state": "open"},
    "search_issues": {"q": "is:issue repo:openai/openai-python"},
    "get_issue": {"owner": "openai", "repo": "openai-python", "issue_number": 1},
    "get_pull_request": {"owner": "openai", "repo": "openai-python", "pull_number": 2858},
    "list_pull_requests": {"owner": "openai", "repo": "openai-python", "state": "open"},
    "get_pull_request_files": {"owner": "openai", "repo": "openai-python", "pull_number": 2858},
    "get_pull_request_status": {"owner": "openai", "repo": "openai-python", "pull_number": 2858},
    "get_pull_request_comments": {"owner": "openai", "repo": "openai-python", "pull_number": 2858},
    "get_pull_request_reviews": {"owner": "openai", "repo": "openai-python", "pull_number": 2858},
    # X/Twitter read-only baseline arguments
    "get_user_by_screen_name": {"screen_name": "OpenAI"},
    "get_user_profile": {"user_id": "783214"},
    "get_user_by_id": {"user_id": "783214"},
    "get_user_followers": {"user_id": "783214", "count": 5},
    "get_user_following": {"user_id": "783214", "count": 5},
    "get_user_followers_you_know": {"user_id": "783214", "count": 5},
    "get_user_subscriptions": {"user_id": "783214", "count": 5},
    "get_tweet_details": {"tweet_id": "20"},
    "get_trends": {"count": 5},
}


@dataclass
class ToolResult:
    server: str
    tool: str
    side_effect: bool
    skipped: bool
    skip_reason: str
    sample_args: Dict[str, Any]
    routing_ok: bool
    routing_detail: str
    call_ok: Optional[bool]
    call_detail: str
    blocked: bool
    blocked_reason: str
    response_preview: str
    elapsed_ms: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "server": self.server,
            "tool": self.tool,
            "side_effect": self.side_effect,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "sample_args": self.sample_args,
            "routing_ok": self.routing_ok,
            "routing_detail": self.routing_detail,
            "call_ok": self.call_ok,
            "call_detail": self.call_detail,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "response_preview": self.response_preview,
            "elapsed_ms": self.elapsed_ms,
        }


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs: Any,
) -> Tuple[bool, Any, str]:
    try:
        response = client.request(method, url, **kwargs)
    except Exception as exc:
        return False, None, f"request failed: {exc}"
    if response.status_code >= 400:
        text = response.text.strip()
        return False, None, f"HTTP {response.status_code}: {text or 'request failed'}"
    try:
        return True, response.json(), ""
    except Exception:
        return False, None, "response was not valid JSON"


def _resolve_schema(schema: Any) -> Dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    for key in ("anyOf", "oneOf", "allOf"):
        options = schema.get(key)
        if isinstance(options, list) and options:
            for option in options:
                resolved = _resolve_schema(option)
                if resolved:
                    return resolved
    return schema


def _value_for_schema(name: str, schema: Dict[str, Any], depth: int = 0) -> Any:
    if depth > 3:
        return None

    schema = _resolve_schema(schema)
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]

    schema_type = schema.get("type")
    lowered = name.lower()

    if schema_type == "string":
        if "expression" in lowered:
            return "19*23"
        if "from_unit" in lowered:
            return "meter"
        if "to_unit" in lowered:
            return "foot"
        if "slug" in lowered:
            return "artificial-intelligence"
        if "section_header" in lowered:
            return "History"
        if "output_video" in lowered:
            return str(TRAINING_MEMVID_VIDEO_PATH)
        if "output_index" in lowered:
            return str(TRAINING_MEMVID_INDEX_PATH)
        if "video_path" in lowered:
            return str(TRAINING_MEMVID_VIDEO_PATH)
        if "index_path" in lowered:
            return str(TRAINING_MEMVID_INDEX_PATH)
        if "pattern" in lowered:
            return "vera"
        if lowered == "content":
            return "tool training content"
        if "command" in lowered:
            return "echo vera"
        if lowered == "code":
            return "print('vera')"
        if "thought" in lowered:
            return "First thought."
        if "path" in lowered or "file" in lowered:
            return str(TRAINING_TEXT_PATH)
        if "dir" in lowered:
            return str(TRAINING_TMP_DIR)
        if "url" in lowered or "uri" in lowered:
            return "https://example.com"
        if "email" in lowered:
            return "niz@example.com"
        if "phone" in lowered:
            return "+10000000000"
        if "query" in lowered:
            return "tool training check"
        if "timezone" in lowered:
            return "UTC"
        if "title" in lowered:
            return "Tool Training"
        if "name" in lowered:
            return "vera-tool-training"
        if "id" in lowered:
            return "tool-training-id"
        if "message" in lowered or "text" in lowered or "body" in lowered:
            return "tool training message"
        return "sample"

    if schema_type == "integer":
        minimum = schema.get("minimum")
        if isinstance(minimum, int):
            return minimum
        return 1

    if schema_type == "number":
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)):
            return float(minimum)
        return 1.0

    if schema_type == "boolean":
        return False

    if schema_type == "array":
        item_schema = _resolve_schema(schema.get("items", {}))
        if item_schema:
            item_value = _value_for_schema(f"{name}_item", item_schema, depth + 1)
            if item_value is not None:
                return [item_value]
        return []

    if schema_type == "object":
        return _build_sample_args(schema, depth + 1)

    if "properties" in schema:
        return _build_sample_args(schema, depth + 1)

    return None


def _build_sample_args(schema: Dict[str, Any], depth: int = 0) -> Dict[str, Any]:
    schema = _resolve_schema(schema)
    properties = schema.get("properties")
    required = schema.get("required")

    if not isinstance(properties, dict):
        return {}

    required_names: List[str] = []
    if isinstance(required, list):
        required_names = [str(name) for name in required]

    # If no required fields are declared, still provide common optional fields
    # that many MCP tools expect in practice.
    if not required_names:
        for candidate in ("query", "url", "title", "slug", "id"):
            prop_schema = properties.get(candidate)
            if isinstance(prop_schema, dict):
                value = _value_for_schema(candidate, prop_schema, depth)
                return {candidate: value} if value is not None else {}
        return {}

    args: Dict[str, Any] = {}
    for name in required_names:
        prop_schema = properties.get(name)
        if not isinstance(prop_schema, dict):
            continue
        value = _value_for_schema(name, prop_schema, depth)
        if value is not None:
            args[name] = value
    return args


def _is_side_effect_tool(tool_name: str, description: str) -> bool:
    name = tool_name.lower()
    if name.startswith(SAFE_TOOL_PREFIXES):
        return False

    blob = f"{name} {description.lower()}".strip()
    return any(hint in blob for hint in SIDE_EFFECT_HINTS)


def _extract_response_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "").strip()


def _is_blocked_error(message: str) -> bool:
    lowered = (message or "").strip().lower()
    if not lowered:
        return False
    return any(hint in lowered for hint in BLOCKED_ERROR_HINTS)


def _extract_content_texts(result_payload: Any) -> List[str]:
    if not isinstance(result_payload, dict):
        return []
    content = result_payload.get("content")
    if not isinstance(content, list):
        return []
    texts: List[str] = []
    for item in content:
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return texts


def _extract_first_json_blob(result_payload: Any) -> Any:
    for text in _extract_content_texts(result_payload):
        if not text:
            continue
        try:
            return json.loads(text)
        except Exception:
            continue
    return None


def _extract_result_error_text(result_payload: Any) -> str:
    if not isinstance(result_payload, dict):
        return ""
    for text in _extract_content_texts(result_payload):
        if text:
            return text
    return str(result_payload)


def _extract_result_text(result_payload: Any) -> str:
    return "\n".join(_extract_content_texts(result_payload)).strip()


def _extract_ids_from_text(text: str, pattern: str) -> List[str]:
    if not text:
        return []
    return [match for match in re.findall(pattern, text) if isinstance(match, str) and match.strip()]


def _required_fields(schema: Dict[str, Any]) -> List[str]:
    resolved = _resolve_schema(schema)
    required = resolved.get("required")
    if not isinstance(required, list):
        return []
    return [str(item) for item in required]


def _id_field(name: str) -> bool:
    lowered = name.lower()
    return lowered == "id" or lowered.endswith("_id") or lowered.endswith("_ids")


def _looks_like_placeholder(field: str, value: Any) -> bool:
    name = field.lower()
    is_id_field = _id_field(name)
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return True
        lowered = stripped.lower()
        if lowered in {"test", "tool-training-id", "vera-tool-training"}:
            return True
        if "tool-training" in lowered:
            return True
        if is_id_field and lowered in {"test", "unknown"}:
            return True
        if is_id_field and ("/" in stripped or stripped.startswith("http://") or stripped.startswith("https://")):
            return True
        if is_id_field and stripped.startswith("/home/"):
            return True
    if isinstance(value, list) and not value:
        return True
    return False


def _apply_contextual_args(
    server_name: str,
    tool_name: str,
    args: Dict[str, Any],
    schema: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    out = dict(args or {})
    required = _required_fields(schema)
    filesystem_dir = str(context.get("filesystem_dir_path") or TRAINING_TMP_DIR)
    filesystem_file = str(context.get("filesystem_file_path") or TRAINING_TEXT_PATH)
    filesystem_media = str(context.get("filesystem_media_path") or TRAINING_IMAGE_PATH)
    obsidian_dir = str(context.get("obsidian_vault_path") or DEFAULT_OBSIDIAN_VAULT_PATH)
    obsidian_file = str(context.get("obsidian_file_path") or "")

    if "path" in required:
        if server_name == "filesystem":
            if tool_name in {"list_directory", "list_directory_with_sizes", "directory_tree", "search_files"}:
                out["path"] = filesystem_dir
            elif tool_name == "read_media_file":
                out["path"] = filesystem_media
            else:
                out["path"] = filesystem_file
        elif server_name == "obsidian-vault":
            if tool_name in {"list_directory", "list_directory_with_sizes", "directory_tree", "search_files"}:
                out["path"] = obsidian_dir
            else:
                out["path"] = obsidian_file or obsidian_dir

    field_map = {
        "user_google_email": "google_email",
        "instance_id": "instance_id",
        "request_id": "request_id",
        "tab_id": "tab_id",
        "hook_id": "hook_id",
        "element_id": "element_id",
        "document_id": "document_id",
        "file_id": "file_id",
        "spreadsheet_id": "spreadsheet_id",
        "presentation_id": "presentation_id",
        "form_id": "form_id",
        "task_list_id": "task_list_id",
        "task_id": "task_id",
        "message_id": "gmail_message_id",
        "thread_id": "gmail_thread_id",
        "comment_id": "comment_id",
        "page_object_id": "page_object_id",
        "space_id": "space_id",
        "event_id": "event_id",
        "filter_id": "filter_id",
        "permission_id": "permission_id",
        "response_id": "response_id",
        "calendar_id": "calendar_id",
    }

    for field in required:
        current = out.get(field)
        if not _looks_like_placeholder(field, current):
            continue

        mapped = field_map.get(field)
        if mapped and context.get(mapped) is not None:
            out[field] = context[mapped]
            continue

        if field == "message_ids" and context.get("gmail_message_ids"):
            out[field] = list(context["gmail_message_ids"][:2])
            continue
        if field == "thread_ids" and context.get("gmail_thread_ids"):
            out[field] = list(context["gmail_thread_ids"][:2])
            continue
        if field == "selector":
            out[field] = context.get("selector", "h1")
            continue
        if field == "url":
            out[field] = context.get("url", "https://example.com")
            continue
        if field == "headers":
            out[field] = {"X-Vera-Training": "1"}
            continue
        if field == "sites":
            out[field] = ["example.com"]
            continue
        if field == "range_name":
            out[field] = "Sheet1!A1:B2"
            continue
        if field == "object_path":
            out[field] = "window"
            continue
        if field == "function_path":
            out[field] = "Math.max"
            continue
        if field == "function_code":
            out[field] = "return 1;"
            continue
        if field in {"python_code", "script", "script_code"}:
            out[field] = "return document.title;"
            continue
        if tool_name == "set_cookie" and field == "name":
            out[field] = "vera_test"
            continue
        if tool_name == "set_cookie" and field == "value":
            out[field] = "1"
            continue

    return out


def _missing_required_preconditions(schema: Dict[str, Any], args: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    for field in _required_fields(schema):
        value = args.get(field)
        if _looks_like_placeholder(field, value):
            missing.append(field)
    return missing


def _resolve_dynamic_overrides(
    client: httpx.Client,
    base_url: str,
    selected_servers: Sequence[str],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    dynamic: Dict[str, Dict[str, Any]] = {}
    context: Dict[str, Any] = {
        "selector": "h1",
        "url": "https://example.com",
        "filesystem_dir_path": str(TRAINING_TMP_DIR),
        "filesystem_file_path": str(TRAINING_TEXT_PATH),
        "filesystem_media_path": str(TRAINING_IMAGE_PATH),
        "obsidian_vault_path": str(DEFAULT_OBSIDIAN_VAULT_PATH),
    }
    if DEFAULT_OBSIDIAN_VAULT_PATH.exists():
        for dirpath, _, filenames in os.walk(DEFAULT_OBSIDIAN_VAULT_PATH):
            if not filenames:
                continue
            first = Path(dirpath) / filenames[0]
            context["obsidian_file_path"] = str(first)
            break

    def _call_tool(server: str, name: str, arguments: Dict[str, Any], timeout: float = 20.0) -> Optional[Any]:
        ok, payload, _ = _request_json(
            client,
            "POST",
            f"{base_url}/api/tools/call",
            json={
                "server": server,
                "name": name,
                "arguments": arguments,
                "timeout": timeout,
            },
            timeout=timeout + 5.0,
        )
        if not ok or not isinstance(payload, dict):
            return None
        result_blob = payload.get("result")
        if isinstance(result_blob, dict) and result_blob.get("isError"):
            return None
        return result_blob

    selected = set(selected_servers or [])

    if "github" in selected:
        # Resolve a live PR number and issue number for github read-only tooling.
        pr_blob = _call_tool(
            "github",
            "list_pull_requests",
            {"owner": "openai", "repo": "openai-python", "state": "open", "per_page": 1},
        )
        pr_data = _extract_first_json_blob(pr_blob)
        if isinstance(pr_data, list) and pr_data and isinstance(pr_data[0], dict):
            pr_number = pr_data[0].get("number")
            if isinstance(pr_number, int):
                for name in (
                    "get_pull_request",
                    "get_pull_request_files",
                    "get_pull_request_status",
                    "get_pull_request_comments",
                    "get_pull_request_reviews",
                ):
                    dynamic[name] = {"owner": "openai", "repo": "openai-python", "pull_number": pr_number}

        issue_blob = _call_tool(
            "github",
            "list_issues",
            {"owner": "openai", "repo": "openai-python", "state": "open", "per_page": 1},
        )
        issue_data = _extract_first_json_blob(issue_blob)
        if isinstance(issue_data, list) and issue_data and isinstance(issue_data[0], dict):
            issue_number = issue_data[0].get("number")
            if isinstance(issue_number, int):
                dynamic["get_issue"] = {"owner": "openai", "repo": "openai-python", "issue_number": issue_number}

    if "google-workspace" in selected:
        email = os.getenv("GOOGLE_WORKSPACE_USER_EMAIL", "").strip()
        ok, auth_payload, _ = _request_json(client, "GET", f"{base_url}/api/google/auth/status")
        if (not email) and ok and isinstance(auth_payload, dict):
            email = str(auth_payload.get("user_email") or "").strip()
        if email:
            context["google_email"] = email

            docs_blob = _call_tool(
                "google-workspace",
                "list_docs_in_folder",
                {"user_google_email": email},
            )
            docs_text = _extract_result_text(docs_blob)
            doc_ids = _extract_ids_from_text(docs_text, r"\(ID:\s*([A-Za-z0-9_-]{10,})\)")
            if doc_ids:
                context["document_id"] = doc_ids[0]
                context.setdefault("file_id", doc_ids[0])

            drive_blob = _call_tool(
                "google-workspace",
                "list_drive_items",
                {"user_google_email": email},
            )
            drive_text = _extract_result_text(drive_blob)
            drive_ids = _extract_ids_from_text(drive_text, r"\(ID:\s*([A-Za-z0-9._:@#-]{6,})")
            if drive_ids:
                context.setdefault("file_id", drive_ids[0])

            sheets_blob = _call_tool(
                "google-workspace",
                "list_spreadsheets",
                {"user_google_email": email},
            )
            sheets_text = _extract_result_text(sheets_blob)
            spreadsheet_ids = _extract_ids_from_text(sheets_text, r"\(ID:\s*([A-Za-z0-9_-]{10,})\)")
            if spreadsheet_ids:
                context["spreadsheet_id"] = spreadsheet_ids[0]

            task_lists_blob = _call_tool(
                "google-workspace",
                "list_task_lists",
                {"user_google_email": email},
            )
            task_lists_text = _extract_result_text(task_lists_blob)
            task_list_ids = _extract_ids_from_text(task_lists_text, r"ID:\s*([A-Za-z0-9:._-]+)")
            if task_list_ids:
                context["task_list_id"] = task_list_ids[0]
                tasks_blob = _call_tool(
                    "google-workspace",
                    "list_tasks",
                    {"user_google_email": email, "task_list_id": task_list_ids[0]},
                )
                tasks_text = _extract_result_text(tasks_blob)
                task_ids = _extract_ids_from_text(tasks_text, r"ID:\s*([A-Za-z0-9:._-]+)")
                if task_ids:
                    context["task_id"] = task_ids[0]

            gmail_blob = _call_tool(
                "google-workspace",
                "search_gmail_messages",
                {"user_google_email": email, "query": "in:inbox"},
            )
            gmail_text = _extract_result_text(gmail_blob)
            message_ids = _extract_ids_from_text(gmail_text, r"Message ID:\s*([A-Za-z0-9]+)")
            thread_ids = _extract_ids_from_text(gmail_text, r"Thread ID:\s*([A-Za-z0-9]+)")
            if message_ids:
                context["gmail_message_id"] = message_ids[0]
                context["gmail_message_ids"] = message_ids
            if thread_ids:
                context["gmail_thread_id"] = thread_ids[0]
                context["gmail_thread_ids"] = thread_ids

            calendars_blob = _call_tool(
                "google-workspace",
                "list_calendars",
                {"user_google_email": email},
            )
            calendars_text = _extract_result_text(calendars_blob)
            calendar_ids = _extract_ids_from_text(calendars_text, r"\(ID:\s*([A-Za-z0-9@._#-]+)\)")
            if calendar_ids:
                context["calendar_id"] = calendar_ids[-1]

    if "stealth-browser" in selected:
        spawn_blob = _call_tool("stealth-browser", "spawn_browser", {}, timeout=30.0)
        spawn_struct = spawn_blob.get("structuredContent") if isinstance(spawn_blob, dict) else {}
        instance_id = ""
        if isinstance(spawn_struct, dict):
            instance_id = str(spawn_struct.get("instance_id") or "").strip()
        if (not instance_id) and isinstance(spawn_blob, dict):
            parsed = _extract_first_json_blob(spawn_blob)
            if isinstance(parsed, dict):
                instance_id = str(parsed.get("instance_id") or "").strip()
        if instance_id:
            context["instance_id"] = instance_id
            _call_tool(
                "stealth-browser",
                "navigate",
                {"instance_id": instance_id, "url": context["url"]},
                timeout=30.0,
            )
            req_blob = _call_tool(
                "stealth-browser",
                "list_network_requests",
                {"instance_id": instance_id},
                timeout=20.0,
            )
            req_data = _extract_first_json_blob(req_blob)
            if isinstance(req_data, list) and req_data and isinstance(req_data[0], dict):
                request_id = str(req_data[0].get("request_id") or "").strip()
                if request_id:
                    context["request_id"] = request_id

            tabs_blob = _call_tool(
                "stealth-browser",
                "list_tabs",
                {"instance_id": instance_id},
                timeout=20.0,
            )
            tabs_struct = tabs_blob.get("structuredContent") if isinstance(tabs_blob, dict) else {}
            tab_id = ""
            if isinstance(tabs_struct, dict):
                result = tabs_struct.get("result")
                if isinstance(result, list) and result and isinstance(result[0], dict):
                    tab_id = str(result[0].get("tab_id") or "").strip()
            if (not tab_id) and isinstance(tabs_blob, dict):
                tab_data = _extract_first_json_blob(tabs_blob)
                if isinstance(tab_data, list) and tab_data and isinstance(tab_data[0], dict):
                    tab_id = str(tab_data[0].get("tab_id") or "").strip()
            if tab_id:
                context["tab_id"] = tab_id

            hooks_blob = _call_tool("stealth-browser", "list_dynamic_hooks", {}, timeout=20.0)
            hooks_data = _extract_first_json_blob(hooks_blob)
            if isinstance(hooks_data, list) and hooks_data and isinstance(hooks_data[0], dict):
                hook_id = str(hooks_data[0].get("hook_id") or hooks_data[0].get("id") or "").strip()
                if hook_id:
                    context["hook_id"] = hook_id

            elements_blob = _call_tool("stealth-browser", "list_stored_elements", {}, timeout=20.0)
            elements_struct = elements_blob.get("structuredContent") if isinstance(elements_blob, dict) else {}
            if isinstance(elements_struct, dict):
                stored = elements_struct.get("stored_elements")
                if isinstance(stored, list) and stored and isinstance(stored[0], dict):
                    element_id = str(stored[0].get("element_id") or stored[0].get("id") or "").strip()
                    if element_id:
                        context["element_id"] = element_id

    return dynamic, context


def _get_last_tools_used(client: httpx.Client, base_url: str) -> Tuple[List[str], str]:
    ok, payload, err = _request_json(client, "GET", f"{base_url}/api/tools/last_payload")
    if not ok:
        return [], err
    if not isinstance(payload, dict):
        return [], "invalid last_payload response"
    data = payload.get("payload")
    if not isinstance(data, dict):
        return [], "missing payload object"
    used = data.get("last_tools_used")
    if not isinstance(used, list):
        return [], "missing last_tools_used"
    return [str(item) for item in used], ""


def _server_order(available_servers: Sequence[str], selected_servers: Sequence[str]) -> List[str]:
    if selected_servers:
        selected_set = {item.strip() for item in selected_servers if item.strip()}
        return [name for name in sorted(available_servers) if name in selected_set]
    return sorted(available_servers)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MCP server-by-server training drills")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--model", default="grok-4.20-experimental-beta-0304-reasoning")
    parser.add_argument("--server", action="append", default=[], help="Optional server filter (repeatable)")
    parser.add_argument("--max-tools-per-server", type=int, default=0, help="0 means no limit")
    parser.add_argument("--include-side-effects", action="store_true", help="Execute side-effect tools")
    parser.add_argument("--skip-routing", action="store_true", help="Skip chat routing drill and run direct tool calls only")
    parser.add_argument("--skip-direct-call", action="store_true", help="Only verify routing, not tool execution")
    parser.add_argument("--prompt-timeout", type=float, default=45.0)
    parser.add_argument("--call-timeout", type=float, default=20.0)
    parser.add_argument(
        "--allow-loading",
        action="store_true",
        help="Proceed even if /api/readiness is not fully ready",
    )
    parser.add_argument("--output", default="", help="JSON output path")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    root = ROOT_DIR
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output_path = (
        Path(args.output)
        if args.output
        else root / "tmp" / f"mcp_server_training_{ts}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Shared local artifacts for file/media-based tools.
    TRAINING_TMP_DIR.mkdir(parents=True, exist_ok=True)
    TRAINING_TEXT_PATH.write_text("Vera MCP server training artifact.\n", encoding="utf-8")
    TRAINING_IMAGE_PATH.write_bytes(base64.b64decode(_TINY_PNG_B64))

    report: Dict[str, Any] = {
        "base_url": base_url,
        "started_at": int(time.time()),
        "model": args.model,
        "include_side_effects": bool(args.include_side_effects),
        "skip_direct_call": bool(args.skip_direct_call),
        "skip_routing": bool(args.skip_routing),
        "allow_loading": bool(args.allow_loading),
        "max_tools_per_server": int(args.max_tools_per_server),
        "server_filter": list(args.server or []),
        "servers": {},
        "summary": {},
    }

    with httpx.Client(timeout=30.0) as client:
        ok, readiness, err = _request_json(client, "GET", f"{base_url}/api/readiness")
        if (not ok) or (not isinstance(readiness, dict)):
            detail = err or f"readiness not ready: {readiness}"
            report["error"] = detail
            output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"[FAIL] readiness - {detail}")
            return 1
        routing_disabled = False
        routing_disabled_reason = ""
        if readiness.get("ready") is not True and not args.allow_loading:
            detail = f"readiness not ready: {readiness}"
            report["error"] = detail
            output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"[FAIL] readiness - {detail}")
            return 1
        if readiness.get("ready") is not True and args.allow_loading:
            routing_disabled = True
            routing_disabled_reason = str(readiness.get("message") or "startup tools still loading")

        ok, tools_defs_payload, err = _request_json(client, "GET", f"{base_url}/api/tools/defs")
        if not ok or not isinstance(tools_defs_payload, dict):
            detail = err or "failed to load /api/tools/defs"
            report["error"] = detail
            output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"[FAIL] defs - {detail}")
            return 1

        tools_by_server = tools_defs_payload.get("tools")
        if not isinstance(tools_by_server, dict):
            detail = "invalid /api/tools/defs format"
            report["error"] = detail
            output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"[FAIL] defs - {detail}")
            return 1

        servers = _server_order(list(tools_by_server.keys()), args.server)
        total_tools = 0
        total_routing_ok = 0
        total_call_ok = 0
        total_skipped = 0
        total_blocked = 0
        total_failures = 0
        dynamic_overrides, training_context = _resolve_dynamic_overrides(client, base_url, servers)
        report["training_context"] = training_context

        for server in servers:
            tool_defs = tools_by_server.get(server) or []
            if not isinstance(tool_defs, list):
                continue
            if args.max_tools_per_server > 0:
                tool_defs = tool_defs[: args.max_tools_per_server]

            server_results: List[ToolResult] = []
            print(f"\n[SERVER] {server} tools={len(tool_defs)}")

            for index, tool_def in enumerate(tool_defs, start=1):
                if not isinstance(tool_def, dict):
                    continue
                tool_name = str(tool_def.get("name") or "").strip()
                if not tool_name:
                    continue
                description = str(tool_def.get("description") or "").strip()
                schema = _resolve_schema(tool_def.get("inputSchema") or tool_def.get("parameters") or {})
                sample_args = dict(
                    dynamic_overrides.get(
                        tool_name,
                        TOOL_ARG_OVERRIDES.get(tool_name, _build_sample_args(schema)),
                    )
                )
                sample_args = _apply_contextual_args(server, tool_name, sample_args, schema, training_context)
                side_effect = _is_side_effect_tool(tool_name, description)

                start = time.time()
                skipped = False
                skip_reason = ""
                routing_ok = False
                routing_detail = ""
                call_ok: Optional[bool] = None
                call_detail = ""
                blocked = False
                blocked_reason = ""
                response_preview = ""
                precondition_missing = _missing_required_preconditions(schema, sample_args)

                if side_effect and not args.include_side_effects:
                    skipped = True
                    skip_reason = "side_effect_tool_skipped"
                elif precondition_missing:
                    blocked = True
                    blocked_reason = f"missing_preconditions:{','.join(precondition_missing)}"
                    call_ok = False
                    call_detail = f"blocked: {blocked_reason}"
                elif args.skip_routing:
                    routing_ok = True
                    routing_detail = "routing_skipped_by_flag"
                elif routing_disabled:
                    routing_detail = f"routing_skipped: {routing_disabled_reason}"
                else:
                    conv_id = f"tool-train-{server}-{tool_name}-{index}-{int(start)}"
                    prompt = (
                        f"Tool training drill. Use the tool `{tool_name}` exactly once with arguments "
                        f"{json.dumps(sample_args, separators=(',', ':'))}. "
                        "After the tool returns, provide a one-line status summary."
                    )
                    payload = {
                        "model": args.model,
                        "vera_conversation_id": conv_id,
                        "messages": [{"role": "user", "content": prompt}],
                    }
                    ok, chat_data, err = _request_json(
                        client,
                        "POST",
                        f"{base_url}/v1/chat/completions",
                        json=payload,
                        timeout=args.prompt_timeout,
                    )
                    if ok:
                        response_preview = _extract_response_text(chat_data)[:260]
                    else:
                        routing_detail = err or "chat request failed"

                    used_tools, used_err = _get_last_tools_used(client, base_url)
                    if not routing_detail:
                        if used_err:
                            routing_detail = used_err
                        elif tool_name not in used_tools:
                            routing_detail = f"expected {tool_name}, saw {used_tools}"
                        else:
                            routing_ok = True
                            routing_detail = "ok"

                    if routing_ok and not args.skip_direct_call:
                        call_payload = {
                            "server": server,
                            "name": tool_name,
                            "arguments": sample_args,
                            "timeout": args.call_timeout,
                        }
                        ok, call_data, err = _request_json(
                            client,
                            "POST",
                            f"{base_url}/api/tools/call",
                            json=call_payload,
                            timeout=args.call_timeout + 5.0,
                        )
                        if ok:
                            result_blob = call_data.get("result") if isinstance(call_data, dict) else call_data
                            if isinstance(result_blob, dict) and result_blob.get("isError"):
                                call_ok = False
                                err_text = _extract_result_error_text(result_blob)
                                if _is_blocked_error(err_text):
                                    blocked = True
                                    blocked_reason = err_text[:260]
                                    call_detail = f"blocked: {err_text[:240]}"
                                else:
                                    call_detail = f"tool error: {err_text[:240]}"
                            else:
                                call_ok = True
                                call_detail = str(result_blob)[:260]
                        else:
                            call_ok = False
                            err_text = err or "tool call failed"
                            if _is_blocked_error(err_text):
                                blocked = True
                                blocked_reason = err_text[:260]
                                call_detail = f"blocked: {err_text[:240]}"
                            else:
                                call_detail = err_text
                    elif args.skip_direct_call:
                        call_detail = "direct_call_skipped_by_flag"

                if (
                    (not skipped)
                    and (not blocked)
                    and routing_ok
                    and (call_ok is None)
                    and (not args.skip_direct_call)
                    and (not routing_disabled)
                ):
                    call_payload = {
                        "server": server,
                        "name": tool_name,
                        "arguments": sample_args,
                        "timeout": args.call_timeout,
                    }
                    ok, call_data, err = _request_json(
                        client,
                        "POST",
                        f"{base_url}/api/tools/call",
                        json=call_payload,
                        timeout=args.call_timeout + 5.0,
                    )
                    if ok:
                        result_blob = call_data.get("result") if isinstance(call_data, dict) else call_data
                        if isinstance(result_blob, dict) and result_blob.get("isError"):
                            call_ok = False
                            err_text = _extract_result_error_text(result_blob)
                            if _is_blocked_error(err_text):
                                blocked = True
                                blocked_reason = err_text[:260]
                                call_detail = f"blocked: {err_text[:240]}"
                            else:
                                call_detail = f"tool error: {err_text[:240]}"
                        else:
                            call_ok = True
                            call_detail = str(result_blob)[:260]
                    else:
                        call_ok = False
                        err_text = err or "tool call failed"
                        if _is_blocked_error(err_text):
                            blocked = True
                            blocked_reason = err_text[:260]
                            call_detail = f"blocked: {err_text[:240]}"
                        else:
                            call_detail = err_text

                if routing_disabled and not skipped and not blocked and not args.skip_direct_call:
                    call_payload = {
                        "server": server,
                        "name": tool_name,
                        "arguments": sample_args,
                        "timeout": args.call_timeout,
                    }
                    ok, call_data, err = _request_json(
                        client,
                        "POST",
                        f"{base_url}/api/tools/call",
                        json=call_payload,
                        timeout=args.call_timeout + 5.0,
                    )
                    if ok:
                        result_blob = call_data.get("result") if isinstance(call_data, dict) else call_data
                        if isinstance(result_blob, dict) and result_blob.get("isError"):
                            call_ok = False
                            err_text = _extract_result_error_text(result_blob)
                            if _is_blocked_error(err_text):
                                blocked = True
                                blocked_reason = err_text[:260]
                                call_detail = f"blocked: {err_text[:240]}"
                            else:
                                call_detail = f"tool error: {err_text[:240]}"
                        else:
                            call_ok = True
                            call_detail = str(result_blob)[:260]
                    else:
                        call_ok = False
                        err_text = err or "tool call failed"
                        if _is_blocked_error(err_text):
                            blocked = True
                            blocked_reason = err_text[:260]
                            call_detail = f"blocked: {err_text[:240]}"
                        else:
                            call_detail = err_text

                elapsed_ms = int((time.time() - start) * 1000)
                result = ToolResult(
                    server=server,
                    tool=tool_name,
                    side_effect=side_effect,
                    skipped=skipped,
                    skip_reason=skip_reason,
                    sample_args=sample_args,
                    routing_ok=routing_ok,
                    routing_detail=routing_detail,
                    call_ok=call_ok,
                    call_detail=call_detail,
                    blocked=blocked,
                    blocked_reason=blocked_reason,
                    response_preview=response_preview,
                    elapsed_ms=elapsed_ms,
                )
                server_results.append(result)

                status = (
                    "SKIP"
                    if skipped
                    else ("BLOCK" if blocked else ("OK" if routing_ok and (call_ok is not False) else "FAIL"))
                )
                print(
                    f"  [{status}] {tool_name} "
                    f"routing={routing_ok} call={call_ok if call_ok is not None else '-'} "
                    f"ms={elapsed_ms}"
                )

            server_total = len(server_results)
            server_skipped = sum(1 for item in server_results if item.skipped)
            server_blocked = sum(1 for item in server_results if item.blocked)
            server_routing_ok = sum(1 for item in server_results if item.routing_ok)
            server_call_ok = sum(1 for item in server_results if item.call_ok is True)
            server_failed = sum(
                1
                for item in server_results
                if (not item.skipped) and (not item.blocked) and ((not item.routing_ok) or (item.call_ok is False))
            )

            report["servers"][server] = {
                "total_tools": server_total,
                "routing_ok": server_routing_ok,
                "call_ok": server_call_ok,
                "skipped": server_skipped,
                "blocked": server_blocked,
                "failed": server_failed,
                "results": [item.to_dict() for item in server_results],
            }

            total_tools += server_total
            total_routing_ok += server_routing_ok
            total_call_ok += server_call_ok
            total_skipped += server_skipped
            total_blocked += server_blocked
            total_failures += server_failed

        report["finished_at"] = int(time.time())
        report["summary"] = {
            "servers_tested": len(report["servers"]),
            "tools_tested": total_tools,
            "routing_ok": total_routing_ok,
            "call_ok": total_call_ok,
            "skipped": total_skipped,
            "blocked": total_blocked,
            "failed": total_failures,
        }

    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {output_path}")
    print(f"Summary: {report['summary']}")
    return 1 if report["summary"]["failed"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
