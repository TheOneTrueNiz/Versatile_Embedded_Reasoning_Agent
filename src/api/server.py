#!/usr/bin/env python3
"""
VERA API Server
===============

OpenAI-compatible HTTP API + WebSocket stream for the VERA runtime.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from aiohttp import web
from quorum.premade_quorums import PREMADE_QUORUMS, QUORUM_PRIORITY_ORDER
from quorum.custom_quorums import (
    list_custom_quorum_specs,
    save_custom_quorum_spec,
    delete_custom_quorum,
    build_quorum_from_spec,
)
from core.atomic_io import atomic_json_write, safe_json_read
from observability.self_improvement_budget import (
    DEFAULT_BUDGET_PATH,
    DEFAULT_CONFIG_PATH,
    BudgetConfig,
    budget_config_to_dict,
    load_budget_config,
    load_budget_state,
    reset_budget_state,
)
from core.services.self_improvement_runner import SelfImprovementRunner
from core.runtime.genome_config import (
    DEFAULT_GENOME_PATH,
    apply_genome_patch,
    load_genome_config,
)
from core.runtime.autonomy_runplane import ack_required_delivery_channels, run_requires_ack
from observability.git_context import GitContext
from core.services.push_notifications import PushNotificationService
from core.services.native_push_notifications import NativePushNotificationService

# Observable thinking stream
try:
    from core.runtime.thinking_stream import get_thinking_stream, ThinkingEvent
    THINKING_AVAILABLE = True
except ImportError:
    THINKING_AVAILABLE = False
    def get_thinking_stream(): return None

logger = logging.getLogger(__name__)


def _startup_critical_servers() -> List[str]:
    # Keep core productivity online even if telephony (call-me) is still warming up.
    # Operators can opt back into strict call-me startup gating via:
    #   VERA_STARTUP_CRITICAL_SERVERS=call-me,google-workspace,time
    raw = os.getenv("VERA_STARTUP_CRITICAL_SERVERS", "google-workspace,time")
    servers = [item.strip() for item in raw.split(",") if item.strip()]
    return servers or ["google-workspace", "time"]


def _parse_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _parse_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _parse_server_concurrency(raw: str) -> Dict[str, int]:
    limits: Dict[str, int] = {}
    for token in (raw or "").split(","):
        part = token.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        server = name.strip()
        if not server:
            continue
        try:
            parsed = int(value.strip())
        except ValueError:
            continue
        if parsed > 0:
            limits[server] = parsed
    return limits


def _default_server_concurrency() -> Dict[str, int]:
    raw = os.getenv(
        "VERA_MCP_SERVER_CONCURRENCY",
        "call-me=1,memvid=2,google-workspace=2",
    )
    return _parse_server_concurrency(raw)


def _readiness_max_wait_seconds() -> float:
    return _parse_float_env("VERA_STARTUP_CRITICAL_MAX_WAIT_SECONDS", 180.0, minimum=5.0)


def _csv_values(raw: str) -> List[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _extract_tool_choice_name(tool_choice: Any) -> str:
    if isinstance(tool_choice, str):
        cleaned = tool_choice.strip()
        if cleaned and cleaned.lower() != "auto":
            return cleaned
        return ""
    if not isinstance(tool_choice, dict):
        return ""
    function_obj = tool_choice.get("function")
    if isinstance(function_obj, dict):
        name = function_obj.get("name")
        if isinstance(name, str):
            return name.strip()
    name = tool_choice.get("name")
    if isinstance(name, str):
        return name.strip()
    return ""


def _allow_loading_bypass_for_tool(readiness: Dict[str, Any], tool_choice: Any) -> bool:
    enabled = str(os.getenv("VERA_READINESS_LOADING_TOOL_BYPASS", "1")).strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False

    phase = str(readiness.get("phase") or "").strip().lower()
    if phase != "loading":
        return False

    blocked = readiness.get("blocked_servers") or []
    missing = readiness.get("missing_servers") or []
    if blocked or missing:
        return False

    tool_name = _extract_tool_choice_name(tool_choice).lower()
    if not tool_name:
        return False

    allow_tools = {
        item.lower()
        for item in _csv_values(os.getenv("VERA_READINESS_LOADING_ALLOW_TOOLS", ""))
    }
    if tool_name in allow_tools:
        return True

    allow_prefixes = [
        prefix.lower()
        for prefix in _csv_values(
            os.getenv("VERA_READINESS_LOADING_ALLOW_PREFIXES", "desktop_,editor_")
        )
    ]
    return any(tool_name.startswith(prefix) for prefix in allow_prefixes if prefix)


def _evaluate_tools_readiness(app: web.Application) -> Dict[str, Any]:
    vera = app.get("vera")
    started_at = app.get("started_at", time.time())
    checked_at = datetime.utcnow().isoformat() + "Z"
    if not vera:
        return {
            "ready": False,
            "phase": "initializing",
            "message": "Stand by while Vera initializes.",
            "critical_servers": _startup_critical_servers(),
            "pending_servers": [],
            "missing_servers": [],
            "blocked_servers": [],
            "checked_at": checked_at,
            "uptime_seconds": max(0.0, time.time() - started_at),
        }

    try:
        mcp_status = vera.mcp.get_status()
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc)
        return {
            "ready": False,
            "phase": "error",
            "message": "Stand by while Vera reconnects tool services.",
            "critical_servers": _startup_critical_servers(),
            "pending_servers": [],
            "missing_servers": [],
            "blocked_servers": [],
            "checked_at": checked_at,
            "uptime_seconds": max(0.0, time.time() - started_at),
        }

    servers = mcp_status.get("servers", {})
    critical_servers = _startup_critical_servers()
    pending_servers: List[str] = []
    missing_servers: List[str] = []
    blocked_servers: List[str] = []
    unknown_health_grace = float(os.getenv("VERA_STARTUP_UNKNOWN_HEALTH_GRACE_SECONDS", "15"))
    critical_wait_cap = _readiness_max_wait_seconds()
    app_uptime_seconds = max(0.0, time.time() - started_at)
    warnings: List[Dict[str, Any]] = []

    for name in critical_servers:
        info = servers.get(name)
        if not info:
            missing_servers.append(name)
            continue

        if info.get("missing_env"):
            blocked_servers.append(name)
            continue

        running = bool(info.get("running"))
        health = (info.get("health") or "unknown").strip().lower()
        uptime_seconds = float(info.get("uptime_seconds") or 0.0)
        if not running:
            if app_uptime_seconds >= critical_wait_cap:
                blocked_servers.append(name)
                continue
            pending_servers.append(name)
            continue
        if health == "healthy":
            continue
        if health == "unknown" and uptime_seconds >= unknown_health_grace:
            continue
        if health in {"starting", "initializing"} and uptime_seconds >= unknown_health_grace:
            continue
        if uptime_seconds >= critical_wait_cap:
            blocked_servers.append(name)
            continue
        pending_servers.append(name)

    for name, info in servers.items():
        warning = str(info.get("warning") or "").strip()
        if not warning:
            continue
        warnings.append(
            {
                "server": name,
                "message": warning,
                "runtime_status": info.get("runtime_status") or {},
            }
        )

    ready = len(pending_servers) == 0
    degraded_servers = sorted({*blocked_servers, *missing_servers})
    if not ready:
        phase = "loading"
        pending = ", ".join(pending_servers[:3])
        suffix = f" ({pending})" if pending else ""
        message = f"Stand by please while my tools are loading{suffix}."
    elif degraded_servers:
        phase = "degraded"
        limited = ", ".join(degraded_servers[:3])
        suffix = f" ({limited})" if limited else ""
        message = f"Vera is online with limited tool availability{suffix}."
    else:
        phase = "ready"
        message = "Tools have been fully loaded. Vera is online and ready."

    return {
        "ready": ready,
        "phase": phase,
        "message": message,
        "critical_servers": critical_servers,
        "pending_servers": pending_servers,
        "missing_servers": missing_servers,
        "blocked_servers": blocked_servers,
        "checked_at": checked_at,
        "uptime_seconds": max(0.0, time.time() - started_at),
        "warnings": warnings,
        "mcp": {
            "total_configured": mcp_status.get("total_configured", 0),
            "total_running": mcp_status.get("total_running", 0),
        },
    }


async def _chat_text_response(
    request: web.Request,
    text: str,
    model: str,
    stream: bool = False,
) -> web.StreamResponse:
    if stream:
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        chunk = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion.chunk",
            "choices": [{
                "index": 0,
                "delta": {"content": text},
                "finish_reason": "stop"
            }],
            "model": model
        }
        await response.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

    return web.json_response({
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }]
    })


def _get_creds_dir() -> Path:
    creds_root = os.getenv("CREDS_DIR")
    if creds_root:
        return Path(creds_root).expanduser()
    return Path.home() / "Documents" / "creds"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def _persist_tool_keys(keys: Dict[str, str]) -> Tuple[Dict[str, str], List[str]]:
    creds_dir = _get_creds_dir()
    env_updates: Dict[str, str] = {}
    persisted: List[str] = []

    if keys:
        for subdir in ("xai", "brave", "git", "searxng", "google", "obsidian", "hub"):
            (creds_dir / subdir).mkdir(parents=True, exist_ok=True)

    def _set_env(name: str, value: Optional[str]) -> None:
        if value:
            env_updates[name] = value

    def _write_value(subdir: str, filename: str, value: Optional[str]) -> None:
        if not value:
            return
        target = creds_dir / subdir / filename
        _atomic_write(target, f"{value}\n")
        persisted.append(str(target))

    xai_key = keys.get("XAI_API_KEY") or keys.get("API_KEY")
    if xai_key:
        _write_value("xai", "xai_api", xai_key)
        _set_env("XAI_API_KEY", xai_key)
        _set_env("API_KEY", xai_key)

    brave_key = keys.get("BRAVE_API_KEY")
    if brave_key:
        _write_value("brave", "brave_api", brave_key)
        _set_env("BRAVE_API_KEY", brave_key)

    git_key = keys.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    if git_key:
        _write_value("git", "git_token", git_key)
        _set_env("GITHUB_PERSONAL_ACCESS_TOKEN", git_key)

    searxng_url = keys.get("SEARXNG_BASE_URL")
    if searxng_url:
        _write_value("searxng", "searxng_url", searxng_url)
        _set_env("SEARXNG_BASE_URL", searxng_url)

    obsidian_path = keys.get("OBSIDIAN_VAULT_PATH")
    if obsidian_path:
        _write_value("obsidian", "vault_path", obsidian_path)
        _set_env("OBSIDIAN_VAULT_PATH", obsidian_path)

    composio_key = keys.get("COMPOSIO_API_KEY")
    if composio_key:
        _write_value("composio", "composio_api", composio_key)
        _set_env("COMPOSIO_API_KEY", composio_key)

    hub_command = keys.get("MCP_HUB_COMMAND")
    if hub_command:
        _write_value("composio", "command", hub_command)
        _set_env("MCP_HUB_COMMAND", hub_command)

    hub_args = keys.get("MCP_HUB_ARGS")
    if hub_args:
        _write_value("composio", "args", hub_args)
        _set_env("MCP_HUB_ARGS", hub_args)

    user_email = (
        keys.get("GOOGLE_WORKSPACE_USER_EMAIL")
        or keys.get("USER_GOOGLE_EMAIL")
        or keys.get("GOOGLE_USER_EMAIL")
    )
    if user_email:
        _write_value("google", "user_email", user_email)
        _set_env("GOOGLE_WORKSPACE_USER_EMAIL", user_email)
        _set_env("USER_GOOGLE_EMAIL", user_email)
        _set_env("GOOGLE_USER_EMAIL", user_email)

    google_client_id = keys.get("GOOGLE_OAUTH_CLIENT_ID") or keys.get("GOOGLE_CLIENT_ID")
    google_client_secret = keys.get("GOOGLE_OAUTH_CLIENT_SECRET") or keys.get("GOOGLE_CLIENT_SECRET")
    google_redirect_uri = keys.get("GOOGLE_OAUTH_REDIRECT_URI") or keys.get("GOOGLE_REDIRECT_URI")

    if google_client_id:
        _set_env("GOOGLE_OAUTH_CLIENT_ID", google_client_id)
        _set_env("GOOGLE_CLIENT_ID", google_client_id)
    if google_client_secret:
        _set_env("GOOGLE_OAUTH_CLIENT_SECRET", google_client_secret)
        _set_env("GOOGLE_CLIENT_SECRET", google_client_secret)
    if google_redirect_uri:
        _set_env("GOOGLE_OAUTH_REDIRECT_URI", google_redirect_uri)
        _set_env("GOOGLE_REDIRECT_URI", google_redirect_uri)

    if google_client_id and google_client_secret:
        oauth_path = creds_dir / "google" / "client_secret_generated.json"
        payload = {
            "installed": {
                "client_id": google_client_id,
                "client_secret": google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            }
        }
        if google_redirect_uri:
            payload["installed"]["redirect_uris"] = [google_redirect_uri]
        _atomic_write(oauth_path, json.dumps(payload, indent=2, ensure_ascii=True))
        persisted.append(str(oauth_path))
        _set_env("GOOGLE_CLIENT_SECRET_PATH", str(oauth_path))

    return env_updates, persisted


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _resolve_workspace_user_email() -> str:
    for key in ("GOOGLE_WORKSPACE_USER_EMAIL", "USER_GOOGLE_EMAIL", "GOOGLE_USER_EMAIL"):
        value = os.getenv(key, "").strip()
        if value:
            normalized = _normalize_email(value)
            os.environ["GOOGLE_WORKSPACE_USER_EMAIL"] = normalized
            os.environ["USER_GOOGLE_EMAIL"] = normalized
            os.environ["GOOGLE_USER_EMAIL"] = normalized
            return normalized
    user_path = _get_creds_dir() / "google" / "user_email"
    if user_path.is_file():
        normalized = _normalize_email(user_path.read_text(encoding="utf-8"))
        if normalized:
            os.environ["GOOGLE_WORKSPACE_USER_EMAIL"] = normalized
            os.environ["USER_GOOGLE_EMAIL"] = normalized
            os.environ["GOOGLE_USER_EMAIL"] = normalized
        return normalized
    return ""


def _resolve_workspace_user_email_with_source() -> Tuple[str, str]:
    for key in ("GOOGLE_WORKSPACE_USER_EMAIL", "USER_GOOGLE_EMAIL", "GOOGLE_USER_EMAIL"):
        value = os.getenv(key, "").strip()
        if value:
            normalized = _normalize_email(value)
            os.environ["GOOGLE_WORKSPACE_USER_EMAIL"] = normalized
            os.environ["USER_GOOGLE_EMAIL"] = normalized
            os.environ["GOOGLE_USER_EMAIL"] = normalized
            return normalized, f"env:{key}"
    user_path = _get_creds_dir() / "google" / "user_email"
    if user_path.is_file():
        normalized = _normalize_email(user_path.read_text(encoding="utf-8"))
        if normalized:
            os.environ["GOOGLE_WORKSPACE_USER_EMAIL"] = normalized
            os.environ["USER_GOOGLE_EMAIL"] = normalized
            os.environ["GOOGLE_USER_EMAIL"] = normalized
        return normalized, f"file:{user_path}"
    return "", ""


def _parse_budget_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"Invalid boolean for {field}")


def _parse_budget_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(float(value.strip()))
    raise ValueError(f"Invalid integer for {field}")


def _parse_budget_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        return float(value.strip())
    raise ValueError(f"Invalid number for {field}")


def _apply_budget_overrides(config: BudgetConfig, payload: Dict[str, Any]) -> BudgetConfig:
    if "enabled" in payload:
        config.enabled = _parse_budget_bool(payload.get("enabled"), "enabled")
    if "daily_budget_usd" in payload:
        value = _parse_budget_float(payload.get("daily_budget_usd"), "daily_budget_usd")
        if value < -1:
            raise ValueError("daily_budget_usd must be >= -1")
        config.daily_budget_usd = value
    if "daily_token_budget" in payload:
        value = _parse_budget_int(payload.get("daily_token_budget"), "daily_token_budget")
        if value < -1:
            raise ValueError("daily_token_budget must be >= -1")
        config.daily_token_budget = value
    if "daily_call_budget" in payload:
        value = _parse_budget_int(payload.get("daily_call_budget"), "daily_call_budget")
        if value < -1:
            raise ValueError("daily_call_budget must be >= -1")
        config.daily_call_budget = value
    if "max_tokens_per_call" in payload:
        value = _parse_budget_int(payload.get("max_tokens_per_call"), "max_tokens_per_call")
        if value < -1:
            raise ValueError("max_tokens_per_call must be >= -1")
        config.max_tokens_per_call = value
    return config


def _get_google_credentials_dir() -> Path:
    env_dir = os.getenv("GOOGLE_MCP_CREDENTIALS_DIR") or os.getenv("CREDENTIALS_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    creds_dir = _get_creds_dir() / "google" / "credentials"
    if creds_dir.exists():
        return creds_dir
    root_dir = Path(__file__).resolve().parents[2]
    return root_dir / "vera_memory" / "google_workspace" / "credentials"


def _extract_auth_url(message: str) -> str:
    if not message:
        return ""
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
                elif isinstance(item, str):
                    parts.append(item)
            if parts:
                message = "\n".join(parts)
        elif isinstance(content, str) and content:
            message = content
        if isinstance(message, dict):
            message = message.get("result") or message
        if isinstance(message, dict):
            for key in ("auth_url", "authorization_url", "url", "authUrl", "authorizationUrl"):
                value = message.get(key)
                if value:
                    return str(value)
            message = message.get("message") or message.get("detail") or message.get("error") or message
    if not isinstance(message, str):
        try:
            message = json.dumps(message)
        except TypeError:
            message = str(message)

    match = re.search(r"Authorization URL:\s*(https?://\S+)", message)
    if match:
        return match.group(1).rstrip(")")
    match = re.search(r"https?://[^\s)]+", message)
    if match:
        return match.group(0)
    return ""


def _read_google_client_secret(path: Path) -> Dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    block = data.get("installed") or data.get("web") or {}
    redirect_uris = block.get("redirect_uris") or []
    redirect_uri = redirect_uris[0] if redirect_uris else ""
    return {
        "client_id": block.get("client_id", ""),
        "client_secret": block.get("client_secret", ""),
        "redirect_uri": redirect_uri,
    }


def _resolve_google_oauth_config(creds_dir: Path) -> Dict[str, str]:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or ""
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET") or ""
    redirect_uri = (
        os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
        or os.getenv("GOOGLE_REDIRECT_URI")
        or os.getenv("REDIRECT_URL")
        or ""
    )
    client_secret_path = os.getenv("GOOGLE_CLIENT_SECRET_PATH", "").strip()

    google_dir = creds_dir / "google"
    if not client_secret_path:
        generated = google_dir / "client_secret_generated.json"
        if generated.exists():
            client_secret_path = str(generated)
        else:
            try:
                client_secret_path = next(google_dir.glob("*.json")).as_posix()
            except StopIteration:
                client_secret_path = ""

    if client_secret_path:
        path_obj = Path(client_secret_path).expanduser()
        if path_obj.exists():
            parsed = _read_google_client_secret(path_obj)
            if parsed.get("client_id") and not client_id:
                client_id = parsed["client_id"]
            if parsed.get("client_secret") and not client_secret:
                client_secret = parsed["client_secret"]
            if parsed.get("redirect_uri") and not redirect_uri:
                redirect_uri = parsed["redirect_uri"]
        else:
            client_secret_path = ""

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "client_secret_path": client_secret_path,
    }



def _normalize_content(content: Any, include_image_placeholder: bool = True) -> str:
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif item.get("type") == "image_url" and include_image_placeholder:
                parts.append("[image]")
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    return str(content)


def _normalize_messages(raw_messages: List[Any], include_image_placeholder: bool = True) -> Tuple[List[Dict[str, Any]], str]:
    messages: List[Dict[str, Any]] = []
    system_chunks: List[str] = []

    for msg in raw_messages or []:
        if isinstance(msg, str):
            content = msg.strip()
            if content:
                messages.append({"role": "user", "content": content})
            continue
        if not isinstance(msg, dict):
            continue

        role = str(msg.get("role") or "").strip().lower()
        if role not in {"system", "user", "assistant", "tool"}:
            # Compatibility path for legacy payloads that omitted `role`.
            if "content" in msg:
                role = "user"
            else:
                continue

        content = _normalize_content(
            msg.get("content"),
            include_image_placeholder=include_image_placeholder,
        )
        if role == "system":
            if content:
                system_chunks.append(content)
            continue
        messages.append({"role": role, "content": content})

    return messages, "\n".join(system_chunks).strip()

def _get_last_user_text(raw_messages: List[Any]) -> str:
    for msg in reversed(raw_messages or []):
        if isinstance(msg, str):
            text = msg.strip()
            if text:
                return text
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text") or ""
                    if text.strip():
                        return text.strip()
    return ""


def _needs_temporal_scheduling_guard(user_text: str) -> bool:
    text = str(user_text or "").strip().lower()
    if not text:
        return False

    has_scheduling_intent = any(
        token in text
        for token in (
            "calendar",
            "event",
            "reminder",
            "schedule",
            "meeting",
            "appointment",
            "task",
            "to-do",
            "todo",
        )
    )
    if not has_scheduling_intent:
        return False

    return bool(
        re.search(
            r"\b(today|tonight|tomorrow|next week|next month|this morning|this afternoon|this evening|in \d+ (minute|minutes|hour|hours|day|days|week|weeks))\b",
            text,
        )
    )


def _build_temporal_scheduling_directive(now_local: datetime) -> str:
    anchor = now_local.astimezone().isoformat(timespec="seconds")
    return (
        "Temporal Scheduling Directive:\n"
        f"- Current local datetime anchor: {anchor}\n"
        "- For this request, resolve all relative time phrases (today/tomorrow/in N hours) against this anchor.\n"
        "- Convert relative phrases to explicit RFC3339 datetimes with timezone before calling calendar/task tools.\n"
        "- Do not use historical years unless the partner explicitly requests a past date."
    )


def _resolve_workspace_google_auth_context() -> Tuple[str, bool]:
    user_email = _resolve_workspace_user_email()
    if not user_email:
        return "", False
    credentials_dir = _get_google_credentials_dir()
    credentials_file = credentials_dir / f"{user_email}.json"
    return user_email, credentials_file.exists()


def _build_workspace_email_autofill_directive(user_email: str, authenticated: bool) -> str:
    normalized_email = str(user_email or "").strip().lower()
    if normalized_email and authenticated:
        return (
            "Workspace Identity Directive:\n"
            f"- Default Google Workspace account is onboarded and authenticated: {normalized_email}.\n"
            "- For Google Workspace tool calls, do not ask for email; use the onboarded account."
        )
    if normalized_email:
        return (
            "Workspace Identity Directive:\n"
            f"- Default Google Workspace account is onboarded: {normalized_email} (auth pending).\n"
            "- Reuse this email for auth/setup calls.\n"
            "- Ask for an email only if no onboarded workspace account exists."
        )
    return (
        "Workspace Identity Directive:\n"
        "- No onboarded Google Workspace account is available.\n"
        "- Ask for email only when a Google Workspace action requires it."
    )


def _extract_last_image_content(raw_messages: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    for msg in reversed(raw_messages or []):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") in {"image_url", "image"}:
                return content
    return None


def _extract_session_link_id(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in (
        "session_link_id",
        "vera_session_link_id",
        "session_link",
        "link_id",
        "partner_id",
        "vera_partner_id",
        "unified_user_id",
        "user_id",
    ):
        value = payload.get(key)
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            return cleaned
    return ""


def _prepare_api_session_key(
    vera: Any,
    conversation_id: Optional[str],
    *,
    sender_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    session_link_id: Optional[str] = None,
) -> Optional[str]:
    from sessions.keys import derive_link_session_key, derive_session_key
    from sessions.types import SessionScope

    convo_id = (conversation_id or "").strip()
    channel = str(channel_id or "api").strip() or "api"
    sender = str(sender_id or "").strip()
    link_id = str(session_link_id or "").strip()
    link_session_key = derive_link_session_key(link_id)

    if not sender:
        sender = convo_id
    if not sender and not convo_id and not link_session_key:
        return None

    derived_sender_key = derive_session_key(
        channel_id=channel,
        sender_id=sender or "api_client",
        scope=SessionScope.PER_SENDER,
    )
    base_key = convo_id or derived_sender_key
    canonical_key = link_session_key or base_key

    if getattr(vera, "session_store", None) is None:
        return canonical_key or None

    session_store = vera.session_store
    if not convo_id:
        convo_id = base_key
    try:
        if hasattr(session_store, "link_session_keys"):
            alias_candidates = [base_key, derived_sender_key]
            if convo_id:
                alias_candidates.append(convo_id)
            session_store.link_session_keys(canonical_key, *alias_candidates)
            canonical_key = session_store.resolve_session_key(canonical_key)

        session = session_store.get_or_create(
            session_key=canonical_key,
            channel_id=channel,
            sender_id=sender or convo_id,
        )
        session.metadata["last_activity_at"] = time.time()
        session.metadata["api_channel_id"] = channel
        session.metadata["api_base_session_key"] = base_key
        if convo_id:
            session.metadata["api_conversation_id"] = convo_id
        if link_id:
            session.metadata["session_link_id"] = link_id
        return canonical_key
    except Exception:
        logger.debug("Suppressed Exception in server")
        return canonical_key or None


def _should_hydrate_api_history(messages: List[Dict[str, Any]]) -> bool:
    if len(messages) != 1:
        return False
    only_msg = messages[0]
    if only_msg.get("role") != "user":
        return False
    return bool(str(only_msg.get("content") or "").strip())


def _hydrate_messages_from_session_history(
    vera: Any,
    session_key: Optional[str],
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not session_key or not _should_hydrate_api_history(messages):
        return messages
    session_store = getattr(vera, "session_store", None)
    if session_store is None:
        return messages
    try:
        history = session_store.get_history(session_key)
    except Exception:
        logger.debug("Suppressed Exception in server")
        return messages
    if not history:
        return messages

    hydrated = list(history)
    incoming_user = messages[0]
    incoming_text = str(incoming_user.get("content") or "").strip()
    if not hydrated:
        hydrated.append(incoming_user)
        return hydrated

    last = hydrated[-1]
    last_role = str(last.get("role") or "")
    last_text = str(last.get("content") or "").strip()
    if last_role != "user" or last_text != incoming_text:
        hydrated.append(incoming_user)
    return hydrated


def _last_history_message(vera: Any, session_key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not session_key:
        return None
    session_store = getattr(vera, "session_store", None)
    if session_store is None:
        return None
    try:
        history = session_store.get_history(session_key, max_messages=1)
    except Exception:
        logger.debug("Suppressed Exception in server")
        return None
    if not history:
        return None
    return history[-1]


async def _record_api_message_if_new(
    vera: Any,
    session_key: Optional[str],
    role: str,
    content: str,
) -> None:
    if not session_key:
        return
    text = str(content or "").strip()
    if not text:
        return
    session_store = getattr(vera, "session_store", None)
    if session_store is None:
        return

    last = _last_history_message(vera, session_key)
    if last:
        last_role = str(last.get("role") or "")
        last_content = str(last.get("content") or "").strip()
        if last_role == role and last_content == text:
            return

    try:
        await session_store.record_message(
            session_key=session_key,
            role=role,
            content=text,
        )
        session = session_store.get(session_key)
        if session:
            session.metadata["last_activity_at"] = time.time()
    except Exception:
        logger.debug("Suppressed Exception in server")


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_generation_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    temperature = _coerce_float(payload.get("temperature"))
    if temperature is not None:
        config["temperature"] = temperature

    top_p = _coerce_float(payload.get("top_p"))
    if top_p is None:
        top_p = _coerce_float(payload.get("top_P"))
    if top_p is not None:
        config["top_p"] = top_p

    max_tokens = _coerce_int(payload.get("max_tokens"))
    if max_tokens is None:
        max_tokens = _coerce_int(payload.get("max_output_tokens"))
    if max_tokens is not None:
        config["max_tokens"] = max_tokens

    frequency_penalty = _coerce_float(payload.get("frequency_penalty"))
    if frequency_penalty is None:
        frequency_penalty = _coerce_float(payload.get("repetition_penalty"))
    if frequency_penalty is not None:
        config["frequency_penalty"] = frequency_penalty

    presence_penalty = _coerce_float(payload.get("presence_penalty"))
    if presence_penalty is not None:
        config["presence_penalty"] = presence_penalty

    return config


def _is_reasoning_model(model: str) -> bool:
    name = (model or "").strip().lower()
    if not name:
        return False
    if "non-reasoning" in name:
        return False
    if "reasoning" in name:
        return True
    return name.startswith(("grok-3", "grok-4"))


def _filter_generation_config_for_model(model: str, config: Dict[str, Any]) -> Dict[str, Any]:
    if not config:
        return {}
    if not _is_reasoning_model(model):
        return config
    filtered = dict(config)
    for key in ("presence_penalty", "frequency_penalty", "stop"):
        filtered.pop(key, None)
    return filtered


def _mark_shutdown_requested(app: web.Application) -> None:
    shutdown_event = app.get("shutdown_event")
    if shutdown_event and not shutdown_event.is_set():
        shutdown_event.set()

    shutdown_state = app.get("shutdown_state")
    if isinstance(shutdown_state, dict):
        shutdown_state["handled"] = False

    try:
        vera = app.get("vera")
        if vera and getattr(vera, "mcp", None):
            vera.mcp.request_shutdown()
    except Exception:
        logger.debug("Suppressed Exception in server")
        pass

    try:
        root_dir = Path(__file__).resolve().parents[2]
        flag_path = root_dir / "tmp" / "shutdown_requested"
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text(str(time.time()))
    except Exception:
        logger.debug("Suppressed Exception in server")
        pass

    # Write manual_halt sentinel so the tray/launcher won't auto-restart
    try:
        root_dir = Path(__file__).resolve().parents[2]
        halt_path = root_dir / "vera_memory" / "manual_halt"
        halt_path.parent.mkdir(parents=True, exist_ok=True)
        halt_path.write_text(str(time.time()))
    except Exception:
        logger.debug("Suppressed Exception writing manual_halt sentinel")
        pass


async def _fetch_vision_summary(content: List[Dict[str, Any]]) -> str:
    api_key = os.getenv("XAI_VISION_API_KEY") or os.getenv("XAI_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        return ""
    model = os.getenv("XAI_VISION_MODEL", "grok-4")
    base_url = _validate_base_url(os.getenv("XAI_VISION_BASE_URL", ""), "https://api.x.ai/v1")
    system_prompt = (
        "You are a vision analyzer. Describe the image accurately and concisely. "
        "If the user asked a specific question, answer it directly based only on the image."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "max_tokens": 512,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
    except Exception as exc:
        logger = logging.getLogger(__name__)
        logger.warning("Vision summary failed: %s", exc)
        return ""


def _is_auth_error(detail: str) -> bool:
    lowered = detail.lower()
    return any(token in lowered for token in ("401", "403", "unauthorized", "invalid_grant", "credential", "oauth"))


def _voice_enabled() -> bool:
    value = os.getenv("VERA_VOICE", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _client_ip(request: web.Request) -> str:
    """Extract client IP, only trusting X-Forwarded-For from trusted proxies."""
    trusted_proxies = os.getenv("VERA_TRUSTED_PROXIES", "").strip()
    remote = request.remote or "unknown"
    if trusted_proxies and remote != "unknown":
        trusted_set = {p.strip() for p in trusted_proxies.split(",") if p.strip()}
        if remote in trusted_set:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                first = forwarded.split(",", 1)[0].strip()
                if first:
                    return first
    return remote


# ---------------------------------------------------------------------------
# Base URL validation (SSRF prevention)
# ---------------------------------------------------------------------------
_SAFE_API_HOSTS = frozenset({
    "api.x.ai", "api.anthropic.com", "api.openai.com",
    "generativelanguage.googleapis.com", "api.together.xyz",
    "api.groq.com", "openrouter.ai",
})


def _validate_base_url(url: str, fallback: str) -> str:
    """Validate an env-sourced base URL to prevent SSRF.

    Allows known API hosts, localhost for dev, and rejects private/internal IPs.
    Returns fallback if the URL is invalid.
    """
    if not url or not url.strip():
        return fallback

    url = url.strip().rstrip("/")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
    except Exception:
        logger.warning("Invalid base URL rejected: %s", url)
        return fallback

    hostname = (parsed.hostname or "").lower()
    scheme = (parsed.scheme or "").lower()

    if not hostname or scheme not in ("http", "https"):
        logger.warning("Base URL rejected (bad scheme/host): %s", url)
        return fallback

    # Allow known API hosts
    if hostname in _SAFE_API_HOSTS:
        return url

    # Allow localhost/loopback for local dev proxies
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return url

    # Allow custom hosts only over HTTPS
    if scheme == "https":
        # Block private/internal IP ranges
        import ipaddress
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_reserved or addr.is_link_local or addr.is_loopback:
                logger.warning("Base URL rejected (private IP): %s", url)
                return fallback
        except ValueError:
            pass  # hostname, not IP — allow over HTTPS
        return url

    # HTTP to non-localhost, non-safe host — reject
    logger.warning("Base URL rejected (HTTP to external host): %s", url)
    return fallback


def _anthropic_messages_endpoint() -> str:
    base_url = _validate_base_url(os.getenv("ANTHROPIC_BASE_URL", ""), "https://api.anthropic.com")
    if base_url.endswith("/v1"):
        return f"{base_url}/messages"
    return f"{base_url}/v1/messages"


def _get_secret_env(var_name: str) -> str:
    value = (os.getenv(var_name) or "").strip()
    if value:
        return value

    try:
        from core.services.dev_secrets import read_secret_from_keychain
    except Exception:
        return ""

    value = read_secret_from_keychain(var_name).strip()
    if value:
        os.environ[var_name] = value
        if var_name == "XAI_API_KEY" and not os.getenv("API_KEY"):
            os.environ["API_KEY"] = value
    return value


def _check_anthropic_proxy_rate_limit(app: web.Application, client_ip: str) -> Tuple[bool, int]:
    max_requests = _parse_int_env("VERA_ANTHROPIC_PROXY_MAX_REQUESTS", 30, minimum=1)
    window_seconds = _parse_float_env("VERA_ANTHROPIC_PROXY_WINDOW_SECONDS", 60.0, minimum=1.0)
    now = time.time()
    cutoff = now - window_seconds

    buckets = app.setdefault("anthropic_proxy_rate_limit", {})
    history = buckets.setdefault(client_ip, [])

    while history and history[0] < cutoff:
        history.pop(0)

    if len(history) >= max_requests:
        retry_after = max(1, int(window_seconds - (now - history[0])))
        return False, retry_after

    history.append(now)
    return True, 0


@web.middleware
async def cors_middleware(request: web.Request, handler):
    origin = os.getenv("VERA_CORS_ORIGIN", "*")
    if request.method == "OPTIONS":
        return web.Response(
            status=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                "Access-Control-Max-Age": "3600",
            },
        )
    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------
_AUTH_SKIP_PREFIXES = ("/api/health", "/api/readiness")
_AUTH_SKIP_EXACT = frozenset({"/", "/favicon.ico"})


@web.middleware
async def auth_middleware(request, handler):
    if request.method == "OPTIONS":
        return await handler(request)
    api_key = request.app.get("vera_api_key", "")
    if not api_key:  # Auth disabled when key not set
        return await handler(request)
    path = request.path
    if path in _AUTH_SKIP_EXACT:
        return await handler(request)
    for prefix in _AUTH_SKIP_PREFIXES:
        if path.startswith(prefix):
            return await handler(request)
    if not path.startswith("/api/") and not path.startswith("/v1/") and not path.startswith("/ws"):
        return await handler(request)  # Static UI assets
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:].strip() == api_key:
        return await handler(request)
    return web.json_response(
        {"error": "Unauthorized. Provide Authorization: Bearer <VERA_API_KEY>."},
        status=401,
        headers={"WWW-Authenticate": 'Bearer realm="vera"'},
    )


# ---------------------------------------------------------------------------
# General rate-limit helpers
# ---------------------------------------------------------------------------
_RATE_LIMIT_CLEANUP_INTERVAL = 300  # seconds between stale-IP sweeps
_rate_limit_last_cleanup: float = 0.0


def _check_rate_limit(app, bucket_name, client_ip, max_requests, window_seconds):
    """Generic sliding-window rate limiter. Returns (allowed, retry_after)."""
    global _rate_limit_last_cleanup
    now = time.time()
    cutoff = now - window_seconds
    buckets = app.setdefault(bucket_name, {})

    # Periodic sweep of stale IPs to prevent unbounded memory growth
    if now - _rate_limit_last_cleanup > _RATE_LIMIT_CLEANUP_INTERVAL:
        _rate_limit_last_cleanup = now
        stale_keys = [k for k, v in buckets.items() if not v or v[-1] < cutoff]
        for k in stale_keys:
            del buckets[k]

    history = buckets.setdefault(client_ip, [])
    while history and history[0] < cutoff:
        history.pop(0)
    if len(history) >= max_requests:
        retry_after = max(1, int(window_seconds - (now - history[0])))
        return False, retry_after
    history.append(now)
    return True, 0


_RATE_LIMIT_SKIP_PREFIXES = ("/api/health", "/api/readiness")
_RATE_LIMIT_POLL_PREFIXES = (
    "/api/editor",
    "/api/tools",
    "/api/memory/stats",
    "/api/session/activity",
    "/api/session/links",
    "/api/channels/status",
    "/api/channels/local/outbox",
    "/api/confirmations/sync",
    "/api/innerlife/status",
)


def _resolve_rate_limit_bucket(request: web.Request) -> Tuple[str, int, float]:
    path = request.path
    method = (request.method or "GET").upper()

    # Tool execution can be bursty during exams and background checks.
    if path.startswith("/api/tools/call"):
        return (
            "tools_call_rate_limit",
            _parse_int_env("VERA_RATE_LIMIT_TOOLS_CALL_MAX", 600, minimum=1),
            _parse_float_env("VERA_RATE_LIMIT_TOOLS_CALL_WINDOW", 60.0, minimum=1.0),
        )

    # UI polling should not consume the same budget as chat/tool mutations.
    if method == "GET" and any(path.startswith(prefix) for prefix in _RATE_LIMIT_POLL_PREFIXES):
        return (
            "poll_rate_limit",
            _parse_int_env("VERA_RATE_LIMIT_POLL_MAX", 600, minimum=1),
            _parse_float_env("VERA_RATE_LIMIT_POLL_WINDOW", 60.0, minimum=1.0),
        )

    return (
        "global_rate_limit",
        _parse_int_env("VERA_RATE_LIMIT_MAX", 60, minimum=1),
        _parse_float_env("VERA_RATE_LIMIT_WINDOW", 60.0, minimum=1.0),
    )


@web.middleware
async def rate_limit_middleware(request, handler):
    if os.getenv("VERA_RATE_LIMIT", "1") == "0":
        return await handler(request)
    path = request.path
    for prefix in _RATE_LIMIT_SKIP_PREFIXES:
        if path.startswith(prefix):
            return await handler(request)
    if not path.startswith("/api/") and not path.startswith("/v1/") and not path.startswith("/ws"):
        return await handler(request)
    bucket_name, max_req, window = _resolve_rate_limit_bucket(request)
    ip = _client_ip(request)
    allowed, retry_after = _check_rate_limit(
        request.app, bucket_name, ip, max_req, window
    )
    if not allowed:
        return web.json_response(
            {"error": {"message": "Rate limit exceeded."}},
            status=429,
            headers={"Retry-After": str(retry_after)},
        )
    return await handler(request)


async def health(request: web.Request) -> web.Response:
    readiness = _evaluate_tools_readiness(request.app)
    vera = request.app.get("vera")
    bridge = getattr(vera, "_llm_bridge", None) if vera else None
    model = getattr(bridge, "model", None) or os.getenv("VERA_MODEL", "grok-4.20-experimental-beta-0304-reasoning")
    status = "ok" if readiness.get("ready") else ("degraded" if readiness.get("phase") == "degraded" else "error")
    return web.json_response({
        "ok": True,
        "status": status,
        "model": model,
        "readiness": readiness,
    })


async def readiness(request: web.Request) -> web.Response:
    return web.json_response(_evaluate_tools_readiness(request.app))


async def list_models(request: web.Request) -> web.Response:
    primary = os.getenv("VERA_MODEL", "grok-4.20-experimental-beta-0304-reasoning")
    models_env = os.getenv("VERA_MODELS", "")
    if models_env:
        models = [item.strip() for item in models_env.split(",") if item.strip()]
        if primary and primary not in models:
            models.insert(0, primary)
    else:
        models = [primary]
    return web.json_response({
        "object": "list",
        "data": [{"id": model, "name": model, "object": "model"} for model in models]
    })


async def chat_completions(request: web.Request) -> web.StreamResponse:
    vera = request.app["vera"]
    payload = await request.json()
    conversation_id = payload.get("vera_conversation_id") or payload.get("conversation_id")
    if conversation_id is not None:
        conversation_id = str(conversation_id)
    sender_id = payload.get("sender_id") or payload.get("client_id")
    if sender_id is not None:
        sender_id = str(sender_id)
    channel_id = payload.get("channel_id") or payload.get("source_channel") or "api"
    if channel_id is not None:
        channel_id = str(channel_id)
    session_link_id = _extract_session_link_id(payload)

    raw_messages = payload.get("messages", [])
    if isinstance(raw_messages, dict):
        raw_messages = [raw_messages]
    elif isinstance(raw_messages, str):
        raw_messages = [raw_messages]
    elif not isinstance(raw_messages, list):
        raw_messages = [str(raw_messages)]
    last_user_text_raw = _get_last_user_text(raw_messages)
    last_user_text = last_user_text_raw.lower()
    model = payload.get("model") or os.getenv("VERA_MODEL", "grok-4.20-experimental-beta-0304-reasoning")
    stream = bool(payload.get("stream", False))
    tool_choice_override = payload.get("tool_choice")
    if last_user_text in {"/exit", "/quit", "/shutdown"}:
        _mark_shutdown_requested(request.app)
        text = "Excuse me while I clean things up a bit before I go."
        return await _chat_text_response(request, text, model, stream)

    readiness_payload = _evaluate_tools_readiness(request.app)
    if not readiness_payload.get("ready"):
        if not _allow_loading_bypass_for_tool(readiness_payload, tool_choice_override):
            standby_text = readiness_payload.get("message") or "Stand by while I finish loading my tools."
            return await _chat_text_response(request, standby_text, model, stream)
        logger.info(
            "Readiness loading bypass allowed for tool_choice=%s pending=%s",
            _extract_tool_choice_name(tool_choice_override),
            readiness_payload.get("pending_servers") or [],
        )

    image_content = _extract_last_image_content(raw_messages)
    vision_summary = ""
    vision_model = os.getenv("XAI_VISION_MODEL", "grok-4")
    if image_content:
        vision_summary = await _fetch_vision_summary(image_content)

    include_image_placeholder = not bool(vision_summary)
    messages, system_override = _normalize_messages(raw_messages, include_image_placeholder=include_image_placeholder)
    if not messages:
        return web.json_response({"error": {"message": "No messages provided."}}, status=400)
    session_key = _prepare_api_session_key(
        vera,
        conversation_id,
        sender_id=sender_id,
        channel_id=channel_id,
        session_link_id=session_link_id,
    )
    runtime_conversation_id = session_key or conversation_id or "default"
    messages = _hydrate_messages_from_session_history(vera, session_key, messages)

    generation_config = _extract_generation_config(payload)
    generation_config = _filter_generation_config_for_model(model, generation_config)

    # Speaker recognition: detect self-identification, track conversations
    _is_title_gen = "5 words or less" in last_user_text
    if not _is_title_gen and hasattr(vera, 'speaker_memory') and vera.speaker_memory:
        try:
            from core.runtime.speaker_memory import SpeakerMemory
            _speaker_sid = sender_id or runtime_conversation_id
            _speaker_name = SpeakerMemory.detect_self_identification(last_user_text_raw)
            if _speaker_name:
                vera.speaker_memory.identify_speaker(
                    name=_speaker_name,
                    sender_id=_speaker_sid,
                    channel_id=channel_id,
                )
            # Track new conversation starts (first message in session)
            _session_obj = (
                vera.session_store.get(session_key)
                if session_key and getattr(vera, "session_store", None)
                else None
            )
            if _session_obj and _session_obj.message_count == 0:
                vera.speaker_memory.start_conversation(_speaker_sid)
            vera.speaker_memory.record_interaction(
                sender_id=_speaker_sid,
                channel_id=channel_id,
            )
        except Exception:
            logger.debug("Suppressed Exception in speaker recognition")

    system_prompt_addenda: List[str] = []
    if system_override:
        system_prompt_addenda.append(f"User System Prompt:\n{system_override}")
    if vision_summary:
        system_prompt_addenda.append(f"Image analysis ({vision_model}):\n{vision_summary}")
    if _needs_temporal_scheduling_guard(last_user_text_raw):
        system_prompt_addenda.append(
            _build_temporal_scheduling_directive(datetime.now().astimezone())
        )
    workspace_email, workspace_authenticated = _resolve_workspace_google_auth_context()
    system_prompt_addenda.append(
        _build_workspace_email_autofill_directive(workspace_email, workspace_authenticated)
    )

    manual_summary = ""
    manual_quorum = payload.get("vera_quorum")
    manual_swarm = payload.get("vera_swarm")
    if manual_quorum or manual_swarm:
        mode = "swarm" if manual_swarm else "quorum"
        params: Dict[str, Any] = {}
        if isinstance(manual_quorum, dict):
            params.update(manual_quorum)
        if isinstance(manual_swarm, dict):
            params.update(manual_swarm)
        if mode == "quorum":
            params.setdefault("question", last_user_text_raw)
        else:
            params.setdefault("action", last_user_text_raw)
        manual_summary = await vera._run_quorum_tool(mode, params, manual=True, trigger="manual")
        if manual_summary:
            system_prompt_addenda.append(manual_summary)

    # Pass only additive directives. Core identity/self-model prompt construction
    # remains centralized inside LLMBridge._get_system_prompt.
    runtime_system_override = "\n\n".join(part for part in system_prompt_addenda if part).strip() or None

    # Set up thinking stream to broadcast to WebSocket clients
    thinking_task = None
    clients = request.app.get("ws_clients", set())
    if THINKING_AVAILABLE and clients:
        thinking_stream = get_thinking_stream()
        if thinking_stream:
            thinking_stream.clear()
            thinking_queue = thinking_stream.create_async_queue()

            async def broadcast_thinking():
                """Broadcast thinking events to all connected WebSocket clients."""
                try:
                    while True:
                        try:
                            event = await asyncio.wait_for(thinking_queue.get(), timeout=0.1)
                            event_data = event.to_dict()
                            for ws in list(clients):
                                if ws.closed:
                                    clients.discard(ws)
                                    continue
                                try:
                                    await ws.send_json(event_data)
                                except Exception:
                                    clients.discard(ws)
                        except asyncio.TimeoutError:
                            continue
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug("Thinking broadcast error: %s", e)

            thinking_task = asyncio.create_task(broadcast_thinking())

    if stream:
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)

        await _record_api_message_if_new(vera, session_key, "user", last_user_text_raw)
        text = await vera.process_messages(
            messages,
            system_override=runtime_system_override,
            model=model,
            generation_config=generation_config,
            conversation_id=runtime_conversation_id,
            tool_choice=tool_choice_override,
        )
        await _record_api_message_if_new(vera, session_key, "assistant", text)

        await _broadcast_confirmation_events(clients, vera)

        # Stop thinking broadcast and drain remaining events
        if thinking_task:
            thinking_task.cancel()
            try:
                await thinking_task
            except asyncio.CancelledError:
                logger.debug("Suppressed Exception in server")
                pass
            if THINKING_AVAILABLE:
                thinking_stream = get_thinking_stream()
                if thinking_stream:
                    for event in thinking_stream.drain():
                        event_data = event.to_dict()
                        for ws in list(clients):
                            if ws.closed:
                                clients.discard(ws)
                                continue
                            try:
                                await ws.send_json(event_data)
                            except Exception:
                                clients.discard(ws)

        # Use actual model from bridge if available (may differ from requested)
        actual_model = model
        _bridge_ref = getattr(vera, "_llm_bridge", None)
        if _bridge_ref and getattr(_bridge_ref, "last_model_used", None):
            actual_model = _bridge_ref.last_model_used
        chunk = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion.chunk",
            "choices": [{
                "index": 0,
                "delta": {"content": text},
                "finish_reason": "stop"
            }],
            "model": actual_model
        }
        await response.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        if clients:
            bridge = getattr(vera, "_llm_bridge", None)
            if bridge and getattr(bridge, "get_last_tool_payload", None):
                payload_data = bridge.get_last_tool_payload()
                for ws in list(clients):
                    if ws.closed:
                        clients.discard(ws)
                        continue
                    try:
                        await ws.send_json({"type": "tool_payload", "data": payload_data})
                    except Exception:
                        clients.discard(ws)
        return response

    await _record_api_message_if_new(vera, session_key, "user", last_user_text_raw)
    text = await vera.process_messages(
        messages,
        system_override=runtime_system_override,
        model=model,
        generation_config=generation_config,
        conversation_id=runtime_conversation_id,
        tool_choice=tool_choice_override,
    )
    await _record_api_message_if_new(vera, session_key, "assistant", text)

    await _broadcast_confirmation_events(clients, vera)

    # Stop thinking broadcast and drain remaining events
    if thinking_task:
        thinking_task.cancel()
        try:
            await thinking_task
        except asyncio.CancelledError:
            logger.debug("Suppressed Exception in server")
            pass
        if THINKING_AVAILABLE:
            thinking_stream = get_thinking_stream()
            if thinking_stream:
                for event in thinking_stream.drain():
                    event_data = event.to_dict()
                    for ws in list(clients):
                        if ws.closed:
                            clients.discard(ws)
                            continue
                        try:
                            await ws.send_json(event_data)
                        except Exception:
                            clients.discard(ws)
    clients = request.app.get("ws_clients", set())
    if clients:
        bridge = getattr(vera, "_llm_bridge", None)
        if bridge and getattr(bridge, "get_last_tool_payload", None):
            payload_data = bridge.get_last_tool_payload()
            for ws in list(clients):
                if ws.closed:
                    clients.discard(ws)
                    continue
                try:
                    await ws.send_json({"type": "tool_payload", "data": payload_data})
                except Exception:
                    clients.discard(ws)
    # Use actual model from bridge if available (may differ from requested)
    actual_model = model
    _bridge_ref = getattr(vera, "_llm_bridge", None)
    if _bridge_ref and getattr(_bridge_ref, "last_model_used", None):
        actual_model = _bridge_ref.last_model_used
    return web.json_response({
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": actual_model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop"
        }]
    })


async def voice_chat_completions(request: web.Request) -> web.Response:
    """Low-latency chat endpoint for voice calls (no tool routing)."""
    vera = request.app["vera"]
    payload = await request.json()
    raw_messages = payload.get("messages", [])

    messages, system_override = _normalize_messages(raw_messages, include_image_placeholder=False)
    extra_system = os.getenv("VERA_VOICE_SYSTEM_PROMPT", "").strip()
    if extra_system:
        system_override = f"{extra_system}\n\n{system_override}" if system_override else extra_system
    if system_override:
        messages.insert(0, {"role": "system", "content": system_override})

    if not messages:
        return web.json_response({"error": {"message": "No messages provided."}}, status=400)

    model = (
        payload.get("model")
        or os.getenv("VERA_CALLME_MODEL")
        or os.getenv("VERA_VOICE_MODEL")
        or os.getenv("VERA_MODEL", "grok-4.20-experimental-beta-0304-reasoning")
    )
    generation_config = _extract_generation_config(payload)
    generation_config = _filter_generation_config_for_model(model, generation_config)

    bridge = getattr(vera, "_llm_bridge", None)
    if bridge is None and getattr(vera, "llm_router", None):
        bridge = vera.llm_router.create_bridge()
        vera._llm_bridge = bridge

    if bridge is None:
        return web.json_response(
            {"error": {"message": "LLM bridge unavailable."}},
            status=503,
        )

    try:
        data = await bridge._call_chat(  # pylint: disable=protected-access
            messages,
            tools=None,
            generation_config=generation_config,
            model_override=model,
        )
    except Exception as exc:
        logger.exception("Voice chat completion failed: %s", exc)
        return web.json_response(
            {"error": {"message": "Voice chat completion failed."}},
            status=500,
        )

    model_used = data.get("model") or model
    response_payload = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_used,
        "choices": data.get("choices", []),
    }
    if "usage" in data:
        response_payload["usage"] = data["usage"]
    return web.json_response(response_payload)


def _resolve_conversation_ids(vera: Any, conversation_ids: List[Any]) -> List[str]:
    normalized: List[str] = []
    seen: set = set()
    session_store = getattr(vera, "session_store", None)

    for raw in conversation_ids:
        convo_id = str(raw).strip()
        if not convo_id:
            continue
        if convo_id not in seen:
            normalized.append(convo_id)
            seen.add(convo_id)

        if session_store and hasattr(session_store, "resolve_session_key"):
            try:
                canonical = str(session_store.resolve_session_key(convo_id) or "").strip()
            except Exception:
                canonical = ""
            if canonical and canonical not in seen:
                normalized.append(canonical)
                seen.add(canonical)

    return normalized


async def confirmations_clear(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    payload = await request.json()
    conversation_id = payload.get("conversation_id")
    conversation_ids = payload.get("conversation_ids") or []
    if conversation_id is not None:
        conversation_ids = [conversation_id] + list(conversation_ids)
    if not conversation_ids:
        return web.json_response({"ok": False, "error": "conversation_id required"}, status=400)
    resolved_ids = _resolve_conversation_ids(vera, conversation_ids)
    removed = vera.clear_pending_tool_confirmations(resolved_ids, reason="ui_clear")
    return web.json_response({"ok": True, "removed": removed})


async def confirmations_sync(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    payload = await request.json()
    conversation_ids = payload.get("conversation_ids") or []
    if not isinstance(conversation_ids, list):
        return web.json_response({"ok": False, "error": "conversation_ids must be a list"}, status=400)
    resolved_ids = _resolve_conversation_ids(vera, conversation_ids)
    removed = vera.sync_pending_tool_confirmations(resolved_ids, reason="ui_sync")
    return web.json_response({"ok": True, "removed": removed})


async def session_activity(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    payload = {}
    try:
        payload = await request.json()
    except (json.JSONDecodeError, Exception):
        payload = {}  # Optional body — empty is fine

    conversation_id = payload.get("conversation_id") or payload.get("vera_conversation_id") or "default"
    convo_id = str(conversation_id)
    sender_id = payload.get("sender_id")
    if sender_id is not None:
        sender_id = str(sender_id)
    channel_id = payload.get("channel_id") or "ui"
    if channel_id is not None:
        channel_id = str(channel_id)
    session_link_id = _extract_session_link_id(payload)
    now = time.time()

    resolved_conversation_id = _prepare_api_session_key(
        vera,
        convo_id,
        sender_id=sender_id or "browser",
        channel_id=channel_id,
        session_link_id=session_link_id,
    ) or convo_id
    if getattr(vera, "session_store", None):
        try:
            session = vera.session_store.get(resolved_conversation_id)
            if session:
                session.touch()
                session.metadata["last_activity_at"] = now
        except Exception:
            logger.debug("Suppressed Exception in server")
            pass

    event_bus = getattr(vera, "event_bus", None)
    if event_bus:
        try:
            event_bus.publish(
                "session.activity",
                payload={
                    "conversation_id": resolved_conversation_id,
                    "channel_id": channel_id,
                    "sender_id": sender_id,
                    "trigger": payload.get("trigger"),
                    "timestamp": now,
                },
                source="api",
            )
        except Exception:
            logger.debug("Suppressed Exception in server")
            pass

    ack_run_id = _maybe_proxy_ack_on_session_activity(
        request,
        {
            **(payload if isinstance(payload, dict) else {}),
            "conversation_id": resolved_conversation_id,
            "channel_id": channel_id,
        },
    )

    response_payload: Dict[str, Any] = {"ok": True, "conversation_id": resolved_conversation_id}
    if ack_run_id:
        response_payload["ack_run_id"] = ack_run_id
    return web.json_response(response_payload)


def _session_link_map_path() -> Path:
    raw_path = os.getenv("VERA_SESSION_LINK_MAP_PATH", "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return Path("vera_memory") / "session_link_map.json"


def _normalize_session_link_rule(raw_rule: Any) -> str:
    if isinstance(raw_rule, str):
        rule = raw_rule.strip()
        if rule and "=" in rule and ":" in rule:
            return rule
        return ""
    if isinstance(raw_rule, dict):
        channel = str(raw_rule.get("channel") or raw_rule.get("channel_id") or "").strip()
        sender = str(raw_rule.get("sender") or raw_rule.get("sender_id") or "").strip()
        link_id = str(raw_rule.get("link_id") or raw_rule.get("session_link_id") or "").strip()
        if channel and sender and link_id:
            return f"{channel}:{sender}={link_id}"
    return ""


def _load_session_link_map_rules() -> List[str]:
    path = _session_link_map_path()
    payload = safe_json_read(path, default={}) or {}
    rules: List[str] = []

    def _append(raw_rule: Any) -> None:
        normalized = _normalize_session_link_rule(raw_rule)
        if normalized:
            rules.append(normalized)

    if isinstance(payload, dict):
        raw_rules = payload.get("rules")
        if isinstance(raw_rules, list):
            for raw_rule in raw_rules:
                _append(raw_rule)
        raw_map = payload.get("map")
        if isinstance(raw_map, dict):
            for identity, link_id in raw_map.items():
                _append(f"{str(identity).strip()}={str(link_id).strip()}")
    elif isinstance(payload, list):
        for raw_rule in payload:
            _append(raw_rule)

    deduped: List[str] = []
    seen = set()
    for rule in rules:
        if rule not in seen:
            seen.add(rule)
            deduped.append(rule)
    return deduped


async def session_link_map(request: web.Request) -> web.Response:
    path = _session_link_map_path()
    env_rules_raw = str(os.getenv("VERA_SESSION_LINK_MAP", "") or "").strip()
    env_rules = [
        rule for rule in (
            _normalize_session_link_rule(raw_rule)
            for raw_rule in env_rules_raw.split(",")
        )
        if rule
    ] if env_rules_raw else []

    return web.json_response({
        "ok": True,
        "path": str(path),
        "file_exists": path.exists(),
        "rules": _load_session_link_map_rules(),
        "env_rules": env_rules,
        "env_override_active": bool(env_rules_raw),
    })


async def session_link_map_update(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid or missing JSON body."}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"error": "Invalid payload"}, status=400)

    append = bool(payload.get("append", False))
    clear = bool(payload.get("clear", False))

    incoming_rules: List[str] = []
    single_rule = payload.get("rule")
    if single_rule is not None:
        normalized = _normalize_session_link_rule(single_rule)
        if normalized:
            incoming_rules.append(normalized)

    raw_rules = payload.get("rules")
    if isinstance(raw_rules, list):
        for raw_rule in raw_rules:
            normalized = _normalize_session_link_rule(raw_rule)
            if normalized:
                incoming_rules.append(normalized)

    inline_rule = _normalize_session_link_rule(payload)
    if inline_rule:
        incoming_rules.append(inline_rule)

    current_rules: List[str] = [] if clear else _load_session_link_map_rules()
    if append:
        combined = current_rules + incoming_rules
    else:
        combined = incoming_rules if incoming_rules or clear else current_rules

    deduped: List[str] = []
    seen = set()
    for rule in combined:
        if rule not in seen:
            seen.add(rule)
            deduped.append(rule)

    target_path = _session_link_map_path()
    atomic_json_write(
        target_path,
        {
            "version": 1,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "rules": deduped,
        },
        indent=2,
        sort_keys=True,
    )

    return web.json_response({
        "ok": True,
        "path": str(target_path),
        "rules": deduped,
        "count": len(deduped),
        "append": append,
        "clear": clear,
    })


async def session_links(request: web.Request) -> web.Response:
    """Inspect cross-channel session linking state."""
    vera = request.app.get("vera")
    if not vera:
        return web.json_response({"error": "VERA unavailable"}, status=503)
    store = getattr(vera, "session_store", None)
    if not store:
        return web.json_response({"error": "Session store unavailable"}, status=503)

    session_key = (
        request.query.get("session_key")
        or request.query.get("conversation_id")
        or request.query.get("alias")
    )
    if session_key:
        key = str(session_key).strip()
        canonical = str(store.resolve_session_key(key) or key)
        session = store.get(canonical)
        return web.json_response({
            "session_key": key,
            "canonical_session_key": canonical,
            "aliases": store.aliases_for(canonical),
            "session_exists": bool(session),
            "message_count": getattr(session, "message_count", 0) if session else 0,
            "last_active_at": getattr(session, "last_active_at", None) if session else None,
            "metadata": getattr(session, "metadata", {}) if session else {},
        })

    sessions = store.list_sessions()
    return web.json_response({
        "count": len(sessions),
        "sessions": sessions,
        "alias_map": store.alias_map() if hasattr(store, "alias_map") else {},
    })


async def session_link(request: web.Request) -> web.Response:
    """Create or update a canonical cross-channel session link."""
    vera = request.app.get("vera")
    if not vera:
        return web.json_response({"error": "VERA unavailable"}, status=503)
    store = getattr(vera, "session_store", None)
    if not store:
        return web.json_response({"error": "Session store unavailable"}, status=503)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid or missing JSON body."}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"error": "Invalid payload"}, status=400)

    from sessions.keys import derive_link_session_key

    session_link_id = _extract_session_link_id(payload)
    canonical_session_key = str(payload.get("canonical_session_key") or payload.get("session_key") or "").strip()
    if session_link_id:
        canonical_session_key = derive_link_session_key(session_link_id) or canonical_session_key

    alias_keys: List[str] = []
    for multi_key in ("alias_keys", "aliases", "conversation_ids", "session_keys"):
        values = payload.get(multi_key)
        if not isinstance(values, list):
            continue
        for raw_value in values:
            cleaned = str(raw_value or "").strip()
            if cleaned:
                alias_keys.append(cleaned)

    for single_key in ("alias", "conversation_id", "source_session_key", "channel_session_key"):
        cleaned = str(payload.get(single_key) or "").strip()
        if cleaned:
            alias_keys.append(cleaned)

    if not canonical_session_key and alias_keys:
        canonical_session_key = alias_keys.pop(0)

    if not canonical_session_key:
        return web.json_response(
            {"error": "Provide canonical_session_key, session_key, or session_link_id"},
            status=400,
        )

    canonical = store.link_session_keys(canonical_session_key, *alias_keys)
    canonical = store.resolve_session_key(canonical)

    channel_id = str(payload.get("channel_id") or "link").strip() or "link"
    sender_id = str(payload.get("sender_id") or session_link_id or "linked").strip() or "linked"
    session = store.get_or_create(canonical, channel_id=channel_id, sender_id=sender_id)
    session.touch()
    session.metadata["last_activity_at"] = time.time()
    if session_link_id:
        session.metadata["session_link_id"] = session_link_id

    return web.json_response({
        "ok": True,
        "canonical_session_key": canonical,
        "aliases": store.aliases_for(canonical),
        "session_link_id": session_link_id,
    })


def _core_identity_threshold_default() -> float:
    raw = str(os.getenv("VERA_PREF_PROMOTION_THRESHOLD", "0.9") or "").strip()
    try:
        value = float(raw) if raw else 0.9
    except Exception:
        value = 0.9
    return max(0.0, min(1.0, value))


def _partner_model_threshold_default() -> float:
    raw = str(os.getenv("VERA_PARTNER_PREF_PROMOTION_THRESHOLD", "0.9") or "").strip()
    try:
        value = float(raw) if raw else 0.9
    except Exception:
        value = 0.9
    return max(0.0, min(1.0, value))


def _get_preferences_manager(request: web.Request) -> Optional[Any]:
    vera = request.app.get("vera")
    if not vera:
        return None
    manager = getattr(vera, "preferences", None)
    return manager


async def partner_model_status(request: web.Request) -> web.Response:
    prefs = _get_preferences_manager(request)
    if not prefs:
        return web.json_response({"error": "Preference manager unavailable"}, status=503)

    try:
        max_items = int(request.query.get("max_items", "12"))
    except Exception:
        max_items = 12
    max_items = max(1, min(100, max_items))

    try:
        audit_limit = int(request.query.get("audit_limit", "80"))
    except Exception:
        audit_limit = 80
    audit_limit = max(1, min(300, audit_limit))

    threshold_default = _partner_model_threshold_default()
    confidence_raw = str(request.query.get("confidence_min", "") or "").strip()
    try:
        confidence_min = float(confidence_raw) if confidence_raw else threshold_default
    except Exception:
        confidence_min = threshold_default
    confidence_min = max(0.0, min(1.0, confidence_min))

    vera = request.app.get("vera")
    notes: Dict[str, Any] = {}
    partner_id = "partner"
    last_learning_answer = ""
    if vera:
        inner_life = getattr(vera, "inner_life", None)
        personality = getattr(inner_life, "personality", None) if inner_life else None
        raw_notes = getattr(personality, "relationship_notes", {}) if personality else {}
        if isinstance(raw_notes, dict):
            notes = raw_notes
            partner_id = str(notes.get("partner_id") or "partner")
            last_learning_answer = str(notes.get("last_learning_answer") or "")

    categories = (
        "preferences",
        "goals",
        "frustrations",
        "working_style",
        "long_term_projects",
    )

    category_counts: Dict[str, int] = {}
    high_confidence_facts: List[Dict[str, Any]] = []
    for category in categories:
        raw_items = notes.get(category, [])
        if not isinstance(raw_items, list):
            category_counts[category] = 0
            continue
        category_counts[category] = len(raw_items)
        for item in reversed(raw_items):
            if not isinstance(item, dict):
                continue
            fact = " ".join(str(item.get("fact") or "").strip().split())
            if not fact:
                continue
            try:
                confidence = float(item.get("confidence", 0.0) or 0.0)
            except Exception:
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
            if confidence < confidence_min:
                continue
            high_confidence_facts.append(
                {
                    "category": category,
                    "fact": fact[:220],
                    "confidence": confidence,
                    "evidence": str(item.get("evidence") or "")[:180],
                    "source": str(item.get("source") or "")[:24],
                    "updated_at": str(item.get("updated_at") or "")[:64],
                }
            )
            if len(high_confidence_facts) >= max_items:
                break
        if len(high_confidence_facts) >= max_items:
            break

    active_promotions = prefs.list_core_identity_promotions(active_only=True)
    partner_promotions = [
        dict(entry)
        for entry in active_promotions
        if isinstance(entry, dict) and str(entry.get("category") or "") == "partner_model"
    ][:max_items]
    partner_commitments = [
        str(entry.get("commitment") or "").strip()
        for entry in partner_promotions
        if str(entry.get("commitment") or "").strip()
    ]

    raw_audit = prefs.get_core_identity_audit(limit=audit_limit)
    partner_audit = [
        dict(event)
        for event in raw_audit
        if isinstance(event, dict)
        and str(event.get("pref_key") or "").startswith("partner_model.")
    ]
    if len(partner_audit) > audit_limit:
        partner_audit = partner_audit[-audit_limit:]

    return web.json_response(
        {
            "ok": True,
            "threshold_default": threshold_default,
            "confidence_min": confidence_min,
            "partner_id": partner_id[:80],
            "last_learning_answer": last_learning_answer[:240],
            "category_counts": category_counts,
            "high_confidence_fact_count": len(high_confidence_facts),
            "high_confidence_facts": high_confidence_facts,
            "partner_identity_promotion_count": len(partner_promotions),
            "partner_identity_promotions": partner_promotions,
            "partner_identity_commitments": partner_commitments,
            "partner_identity_audit": partner_audit,
        }
    )


async def core_identity_status(request: web.Request) -> web.Response:
    prefs = _get_preferences_manager(request)
    if not prefs:
        return web.json_response({"error": "Preference manager unavailable"}, status=503)

    try:
        audit_limit = int(request.query.get("audit_limit", "50"))
    except Exception:
        audit_limit = 50
    audit_limit = max(1, min(300, audit_limit))

    promotions = prefs.list_core_identity_promotions(active_only=True)
    return web.json_response({
        "ok": True,
        "threshold_default": _core_identity_threshold_default(),
        "active_count": len(promotions),
        "promotions": promotions,
        "prompt_block": prefs.export_core_identity_prompt(max_items=6),
        "audit": prefs.get_core_identity_audit(limit=audit_limit),
    })


async def core_identity_refresh(request: web.Request) -> web.Response:
    prefs = _get_preferences_manager(request)
    if not prefs:
        return web.json_response({"error": "Preference manager unavailable"}, status=503)

    try:
        payload = await request.json()
    except Exception:
        payload = {}  # Optional body — defaults used when absent
    if not isinstance(payload, dict):
        payload = {}

    threshold_raw = payload.get("threshold", _core_identity_threshold_default())
    max_items_raw = payload.get("max_items", 8)
    prompt_items_raw = payload.get("prompt_max_items", 6)
    try:
        threshold = float(threshold_raw)
    except Exception:
        threshold = _core_identity_threshold_default()
    threshold = max(0.0, min(1.0, threshold))
    try:
        max_items = int(max_items_raw)
    except Exception:
        max_items = 8
    max_items = max(1, min(50, max_items))
    try:
        prompt_max_items = int(prompt_items_raw)
    except Exception:
        prompt_max_items = 6
    prompt_max_items = max(1, min(20, prompt_max_items))

    stats = prefs.refresh_core_identity_promotions(
        threshold=threshold,
        max_items=max_items,
    )
    promotions = prefs.list_core_identity_promotions(active_only=True)
    return web.json_response({
        "ok": True,
        "stats": stats,
        "active_count": len(promotions),
        "promotions": promotions,
        "prompt_block": prefs.export_core_identity_prompt(max_items=prompt_max_items),
        "audit": prefs.get_core_identity_audit(limit=50),
    })


async def core_identity_revert(request: web.Request) -> web.Response:
    prefs = _get_preferences_manager(request)
    if not prefs:
        return web.json_response({"error": "Preference manager unavailable"}, status=503)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid or missing JSON body."}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"error": "Invalid payload"}, status=400)

    category = str(payload.get("category") or "").strip()
    key = str(payload.get("key") or "").strip()
    reason = str(payload.get("reason") or "manual_revert").strip()
    if not category or not key:
        return web.json_response({"error": "category and key are required"}, status=400)

    reverted = prefs.revert_core_identity_preference(
        category=category,
        key=key,
        reason=reason,
    )
    if not reverted:
        return web.json_response({"error": "core identity preference not active"}, status=404)

    promotions = prefs.list_core_identity_promotions(active_only=True)
    return web.json_response({
        "ok": True,
        "reverted": {"category": category, "key": key, "reason": reason},
        "active_count": len(promotions),
        "promotions": promotions,
        "audit": prefs.get_core_identity_audit(limit=50),
    })


async def api_exit(request: web.Request) -> web.Response:
    _mark_shutdown_requested(request.app)
    return web.json_response({
        "status": "shutting_down",
        "message": "Excuse me while I clean things up a bit before I go."
    })


async def file_read(request: web.Request) -> web.Response:
    """Read a file from the local filesystem for the code editor."""
    try:
        payload = await request.json()
        path = payload.get("path", "").strip()
        if not path:
            return web.json_response({"error": "Path is required"}, status=400)

        # Expand and resolve to catch traversal
        resolved = Path(os.path.expanduser(path)).resolve()

        # Block dangerous paths
        if _is_path_blocked(resolved):
            return web.json_response({"error": "Access denied: protected path"}, status=403)

        if not resolved.exists():
            return web.json_response({"error": "File not found"}, status=404)

        if not resolved.is_file():
            return web.json_response({"error": "Not a file"}, status=400)

        # Check file size (limit to 10MB)
        size = resolved.stat().st_size
        if size > 10 * 1024 * 1024:
            return web.json_response({"error": "File too large (max 10MB)"}, status=400)

        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        return web.json_response({
            "path": str(resolved),
            "content": content,
            "size": size
        })
    except Exception as e:
        logging.getLogger(__name__).error("File read error: %s", e)
        return web.json_response({"error": "Internal error reading file."}, status=500)


# Editor canvas state (shared between frontend and VERA)
_editor_lock = asyncio.Lock()
_editor_state = {
    "content": "",
    "file_path": "",              # Relative to working_directory when set
    "language": "javascript",
    "is_open": False,
    "working_directory": "",      # Absolute path to project root (sandbox)
}

# Undo stack for editor (stores previous states)
_editor_undo_stack: list = []
_EDITOR_MAX_UNDO = 50  # Maximum undo history


def _editor_push_undo():
    """Push current editor state to undo stack before making changes.

    Callers should hold _editor_lock (asyncio.Lock) when modifying
    _editor_state and calling this helper so that the snapshot is consistent.
    """
    # Only save if there's actual content to undo
    state_snapshot = {
        "content": _editor_state["content"],
        "file_path": _editor_state["file_path"],
        "language": _editor_state["language"],
    }
    # Don't push duplicate states
    if _editor_undo_stack and _editor_undo_stack[-1] == state_snapshot:
        return
    _editor_undo_stack.append(state_snapshot)
    # Limit stack size
    while len(_editor_undo_stack) > _EDITOR_MAX_UNDO:
        _editor_undo_stack.pop(0)


# Dangerous paths that are always blocked (safety)
_BLOCKED_PATHS = {
    "/", "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64",
    "/boot", "/dev", "/proc", "/sys", "/root", "/var",
    os.path.expanduser("~/.ssh"),
    os.path.expanduser("~/.gnupg"),
    os.path.expanduser("~/.bashrc"),
    os.path.expanduser("~/.bash_profile"),
    os.path.expanduser("~/.profile"),
}

# Dangerous file patterns that require extra caution
_PROTECTED_PATTERNS = [
    "run_vera.py", "vera.py", "config.py", "safety_validator.py",
    "dangerous_patterns.json", ".env", "*.key", "*.pem", "id_rsa*",
]


def _is_path_blocked(path: Path) -> bool:
    """Check if path is in the global blocklist for safety."""
    path_str = str(path.resolve())

    for blocked in _BLOCKED_PATHS:
        # Always resolve — avoids symlink bypass when blocked path doesn't exist yet
        blocked_resolved = str(Path(blocked).resolve())
        if path_str == blocked_resolved or path_str.startswith(blocked_resolved + "/"):
            return True

    return False


def _validate_sandbox_path(requested_path: str, allow_absolute: bool = False) -> Path:
    """
    Validate that requested_path is within the working directory sandbox.
    Returns the resolved absolute Path if valid.
    Raises ValueError if path is outside sandbox or no working directory is set.

    Safety checks:
    - Path must be within working directory (sandbox)
    - Path must not be in global blocklist
    - Path traversal attacks are blocked
    """
    working_dir = _editor_state.get("working_directory", "").strip()
    if not working_dir:
        raise ValueError("No working directory set. Please set a project directory first.")

    base = Path(working_dir).resolve()
    if not base.exists():
        raise ValueError(f"Working directory does not exist: {working_dir}")

    # Safety check: working directory itself must not be blocked
    if _is_path_blocked(base):
        raise ValueError(f"Cannot use {working_dir} as working directory (protected path)")

    # Handle absolute vs relative paths
    requested = Path(requested_path)
    if requested.is_absolute():
        if not allow_absolute:
            raise ValueError("Absolute paths not allowed. Use paths relative to working directory.")
        target = requested.resolve()
    else:
        target = (base / requested_path).resolve()

    # Check for path traversal
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"Path traversal blocked: {requested_path} is outside the sandbox")

    # Safety check: target must not be blocked
    if _is_path_blocked(target):
        raise ValueError(f"Access denied: {requested_path} is a protected system path")

    return target


def _list_directory(dir_path: Path, pattern: str = None) -> list:
    """List files and directories, optionally filtered by glob pattern."""
    import fnmatch

    result = []
    try:
        for entry in sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            # Skip hidden files and common ignore patterns
            if entry.name.startswith('.'):
                continue
            if entry.name in ('__pycache__', 'node_modules', '.git', 'venv', '.venv'):
                continue

            if pattern and not fnmatch.fnmatch(entry.name, pattern):
                continue

            item = {
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
            }
            if entry.is_file():
                try:
                    item["size"] = entry.stat().st_size
                except OSError:
                    item["size"] = 0
            result.append(item)
    except PermissionError:
        logger.debug("Suppressed PermissionError in server")
        pass

    return result


async def editor_get(request: web.Request) -> web.Response:
    """Get the current code editor state for VERA to read."""
    return web.json_response(_editor_state)


async def editor_set(request: web.Request) -> web.Response:
    """Set the code editor content - used by VERA to write code."""
    try:
        payload = await request.json()
        async with _editor_lock:
            # Push to undo stack if content is changing
            if "content" in payload and payload["content"] != _editor_state["content"]:
                _editor_push_undo()
            if "content" in payload:
                _editor_state["content"] = payload["content"]
            if "file_path" in payload:
                _editor_state["file_path"] = payload["file_path"]
            if "language" in payload:
                _editor_state["language"] = payload["language"]
            if "is_open" in payload:
                _editor_state["is_open"] = payload["is_open"]
            if "working_directory" in payload:
                wd = payload["working_directory"].strip()
                if wd:
                    resolved = Path(os.path.expanduser(wd)).resolve()
                    if _is_path_blocked(resolved):
                        return web.json_response({
                            "error": f"Cannot use {wd} as working directory (protected path)"
                        }, status=403)
                    if not resolved.exists() or not resolved.is_dir():
                        return web.json_response({
                            "error": f"Invalid directory: {wd}"
                        }, status=400)
                    _editor_state["working_directory"] = str(resolved)
                else:
                    _editor_state["working_directory"] = ""

        # Broadcast to WebSocket clients so frontend updates
        app = request.app
        ws_clients = app.get("ws_clients", set())
        msg = {
            "type": "editor_update",
            "data": _editor_state
        }
        for ws in list(ws_clients):
            try:
                await ws.send_json(msg)
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass

        return web.json_response({"success": True, "state": _editor_state})
    except Exception as e:
        logger.error("Editor update error: %s", e)
        return web.json_response({"error": "Internal server error."}, status=500)


async def editor_save(request: web.Request) -> web.Response:
    """Save the current editor content to a file within the sandbox."""
    try:
        payload = await request.json()
        rel_path = payload.get("path") or _editor_state.get("file_path")
        content = payload.get("content") or _editor_state.get("content", "")

        if not rel_path:
            return web.json_response({"error": "No file path specified"}, status=400)

        # Validate path is within sandbox
        working_dir = _editor_state.get("working_directory", "").strip()
        if working_dir:
            try:
                target = _validate_sandbox_path(rel_path)
            except ValueError as e:
                logger.warning("Sandbox path validation failed: %s", e)
                return web.json_response({"error": "Path not allowed."}, status=403)
            abs_path = str(target)
        else:
            # No sandbox set - use legacy behavior but warn
            abs_path = os.path.expanduser(rel_path)
            # Safety check: don't allow writes to blocked paths
            if _is_path_blocked(Path(abs_path)):
                return web.json_response({
                    "error": f"Cannot write to protected path: {rel_path}"
                }, status=403)

        # Create directory if needed
        dir_path = os.path.dirname(abs_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        # Atomic write via random temp file (prevents symlink TOCTOU)
        import tempfile
        fd, temp_path = tempfile.mkstemp(
            dir=os.path.dirname(abs_path) or ".", suffix=".vera_tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, abs_path)
        except Exception:
            os.unlink(temp_path)
            raise

        async with _editor_lock:
            _editor_state["file_path"] = rel_path
            _editor_state["content"] = content

        return web.json_response({
            "success": True,
            "path": rel_path,
            "absolute_path": abs_path,
            "size": len(content.encode("utf-8"))
        })
    except Exception as e:
        logging.getLogger(__name__).error("Editor save error: %s", e)
        return web.json_response({"error": "Internal server error."}, status=500)


async def editor_undo(request: web.Request) -> web.Response:
    """Undo the last editor change, restoring previous content."""
    try:
        async with _editor_lock:
            if not _editor_undo_stack:
                return web.json_response({
                    "success": False,
                    "error": "Nothing to undo",
                    "undo_available": False
                })

            # Pop the previous state
            prev_state = _editor_undo_stack.pop()

            # Restore state
            _editor_state["content"] = prev_state["content"]
            _editor_state["file_path"] = prev_state["file_path"]
            _editor_state["language"] = prev_state["language"]

        # Broadcast to WebSocket clients (outside lock)
        app = request.app
        ws_clients = app.get("ws_clients", set())
        msg = {
            "type": "editor_update",
            "data": _editor_state
        }
        for ws in list(ws_clients):
            try:
                await ws.send_json(msg)
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass

        return web.json_response({
            "success": True,
            "state": _editor_state,
            "undo_remaining": len(_editor_undo_stack)
        })
    except Exception as e:
        logging.getLogger(__name__).error("Editor undo error: %s", e)
        return web.json_response({"error": "Internal server error."}, status=500)


async def workspace_get(request: web.Request) -> web.Response:
    """Get the current workspace (working directory) and its files."""
    try:
        working_dir = _editor_state.get("working_directory", "")

        result = {
            "working_directory": working_dir,
            "files": [],
        }

        if working_dir:
            base = Path(working_dir)
            if base.exists() and base.is_dir():
                result["files"] = _list_directory(base)

        return web.json_response(result)
    except Exception as e:
        logging.getLogger(__name__).error("Workspace get error: %s", e)
        return web.json_response({"error": "Internal server error."}, status=500)


async def workspace_set(request: web.Request) -> web.Response:
    """Set the working directory (sandbox) for file operations."""
    try:
        payload = await request.json()
        path = payload.get("path", "").strip()

        if not path:
            return web.json_response({"error": "Path is required"}, status=400)

        # Expand user home directory
        path = os.path.expanduser(path)
        resolved = Path(path).resolve()

        # Safety check: cannot use blocked paths
        if _is_path_blocked(resolved):
            return web.json_response({
                "error": f"Cannot use {path} as working directory (protected system path)"
            }, status=403)

        # Verify path exists and is a directory
        if not resolved.exists():
            return web.json_response({
                "error": f"Directory does not exist: {path}"
            }, status=404)

        if not resolved.is_dir():
            return web.json_response({
                "error": f"Path is not a directory: {path}"
            }, status=400)

        # Set the working directory
        async with _editor_lock:
            _editor_state["working_directory"] = str(resolved)

        # Return the workspace with file list
        files = _list_directory(resolved)

        return web.json_response({
            "success": True,
            "working_directory": str(resolved),
            "files": files
        })
    except Exception as e:
        logging.getLogger(__name__).error("Workspace set error: %s", e)
        return web.json_response({"error": "Internal server error."}, status=500)


async def workspace_files(request: web.Request) -> web.Response:
    """List files in a subdirectory of the working directory."""
    try:
        working_dir = _editor_state.get("working_directory", "").strip()
        if not working_dir:
            return web.json_response({
                "error": "No working directory set"
            }, status=400)

        # Get query parameters
        subpath = request.query.get("path", "")
        pattern = request.query.get("pattern", None)

        # Validate and resolve path
        if subpath:
            try:
                target = _validate_sandbox_path(subpath)
            except ValueError as e:
                logger.warning("Sandbox path validation failed: %s", e)
                return web.json_response({"error": "Path not allowed."}, status=403)
        else:
            target = Path(working_dir)

        if not target.exists():
            return web.json_response({
                "error": f"Path does not exist: {subpath}"
            }, status=404)

        if not target.is_dir():
            return web.json_response({
                "error": f"Path is not a directory: {subpath}"
            }, status=400)

        files = _list_directory(target, pattern)

        return web.json_response({
            "path": subpath or "",
            "working_directory": working_dir,
            "files": files
        })
    except Exception as e:
        logging.getLogger(__name__).error("Workspace files error: %s", e)
        return web.json_response({"error": "Internal server error."}, status=500)


async def workspace_open_file(request: web.Request) -> web.Response:
    """Open a file from the workspace into the editor canvas."""
    try:
        payload = await request.json()
        rel_path = payload.get("path", "").strip()

        if not rel_path:
            return web.json_response({"error": "Path is required"}, status=400)

        # Validate and resolve path within sandbox
        try:
            target = _validate_sandbox_path(rel_path)
        except ValueError as e:
            logger.warning("Sandbox path validation failed: %s", e)
            return web.json_response({"error": "Path not allowed."}, status=403)

        if not target.exists():
            return web.json_response({
                "error": f"File does not exist: {rel_path}"
            }, status=404)

        if not target.is_file():
            return web.json_response({
                "error": f"Path is not a file: {rel_path}"
            }, status=400)

        # Check file size (10MB limit)
        file_size = target.stat().st_size
        if file_size > 10 * 1024 * 1024:
            return web.json_response({
                "error": f"File too large ({file_size} bytes). Maximum is 10MB."
            }, status=400)

        # Read file content
        content = target.read_text(encoding="utf-8", errors="replace")

        # Detect language from extension
        ext_to_lang = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "javascript", ".tsx": "typescript", ".json": "json",
            ".html": "html", ".htm": "html", ".css": "css", ".scss": "css",
            ".md": "markdown", ".yaml": "yaml", ".yml": "yaml",
            ".sh": "shell", ".bash": "shell", ".sql": "sql", ".xml": "xml",
            ".rs": "rust", ".go": "go", ".java": "java", ".cpp": "cpp",
            ".c": "c", ".h": "c", ".vue": "html",
        }
        ext = target.suffix.lower()
        language = ext_to_lang.get(ext, "plaintext")

        # Update editor state
        async with _editor_lock:
            _editor_state["content"] = content
            _editor_state["file_path"] = rel_path
            _editor_state["language"] = language
            _editor_state["is_open"] = True

        # Broadcast to WebSocket clients
        app = request.app
        ws_clients = app.get("ws_clients", set())
        msg = {"type": "editor_update", "data": _editor_state}
        for ws in list(ws_clients):
            try:
                await ws.send_json(msg)
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass

        return web.json_response({
            "success": True,
            "path": rel_path,
            "language": language,
            "size": file_size
        })
    except Exception as e:
        logging.getLogger(__name__).error("Workspace open file error: %s", e)
        return web.json_response({"error": "Internal server error."}, status=500)


# === Git Status API ===

async def git_status(request: web.Request) -> web.Response:
    """Get git repository status for the current workspace."""
    try:
        path = request.query.get("path", _editor_state.get("working_directory", ""))
        if not path:
            path = os.getcwd()
        path = os.path.expanduser(path)

        def get_status():
            git = GitContext(Path(path))
            status = git.get_repo_status()
            last_commit = None
            if status.last_commit:
                last_commit = {
                    "hash": status.last_commit.hash,
                    "short_hash": status.last_commit.short_hash,
                    "author": status.last_commit.author,
                    "date": status.last_commit.date,
                    "message": status.last_commit.message,
                }
            return {
                "is_repo": status.is_repo,
                "branch": status.branch,
                "is_clean": status.is_clean,
                "ahead": status.ahead,
                "behind": status.behind,
                "staged_count": status.staged_count,
                "modified_count": status.modified_count,
                "untracked_count": status.untracked_count,
                "has_stash": status.has_stash,
                "last_commit": last_commit,
            }

        result = await asyncio.to_thread(get_status)
        return web.json_response(result)
    except Exception as e:
        logger.error("Git status error: %s", e)
        return web.json_response({"error": "Internal server error."}, status=500)


async def git_files(request: web.Request) -> web.Response:
    """Get list of uncommitted files in the git repository."""
    try:
        path = request.query.get("path", _editor_state.get("working_directory", ""))
        if not path:
            path = os.getcwd()
        path = os.path.expanduser(path)

        def get_files():
            git = GitContext(Path(path))
            uncommitted = git.get_uncommitted_files()
            files = []
            for f in uncommitted:
                files.append({
                    "path": f.path,
                    "status": f.status.value,
                    "is_dirty": f.is_dirty,
                    "staged": f.staged_changes,
                    "message": f.message,
                    "diff_preview": f.diff_preview,
                })
            return {"files": files}

        result = await asyncio.to_thread(get_files)
        return web.json_response(result)
    except Exception as e:
        logger.error("Git files error: %s", e)
        return web.json_response({"error": "Internal server error."}, status=500)


async def file_write(request: web.Request) -> web.Response:
    """Write a file to the local filesystem from the code editor."""
    try:
        payload = await request.json()
        path = payload.get("path", "").strip()
        content = payload.get("content", "")

        if not path:
            return web.json_response({"error": "Path is required"}, status=400)

        # Expand and resolve to catch traversal
        resolved = Path(os.path.expanduser(path)).resolve()

        # Block dangerous paths
        if _is_path_blocked(resolved):
            return web.json_response({"error": "Access denied: protected path"}, status=403)

        # Block writing to protected file patterns
        fname = resolved.name
        for pattern in _PROTECTED_PATTERNS:
            if "*" in pattern:
                import fnmatch
                if fnmatch.fnmatch(fname, pattern):
                    return web.json_response({"error": "Access denied: protected file"}, status=403)
            elif fname == pattern:
                return web.json_response({"error": "Access denied: protected file"}, status=403)

        # Create directory if it doesn't exist
        dir_path = resolved.parent
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)

        # Atomic write via random temp file (prevents symlink TOCTOU)
        import tempfile
        fd, temp_path = tempfile.mkstemp(
            dir=str(dir_path), suffix=".vera_tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, str(resolved))
        except Exception:
            os.unlink(temp_path)
            raise

        return web.json_response({
            "path": str(resolved),
            "size": len(content.encode("utf-8")),
            "success": True
        })
    except Exception as e:
        logging.getLogger(__name__).error("File write error: %s", e)
        return web.json_response({"error": "Internal error writing file."}, status=500)


async def image_generations(request: web.Request) -> web.Response:
    payload = await request.json()
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return web.json_response({"error": {"message": "Prompt is required."}}, status=400)

    api_key = os.getenv("XAI_IMAGE_API_KEY") or os.getenv("XAI_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        return web.json_response({"error": {"message": "XAI_IMAGE_API_KEY or XAI_API_KEY is required."}}, status=400)

    model = payload.get("model") or os.getenv("XAI_IMAGE_MODEL", "grok-imagine-image-pro")
    size = payload.get("size") or os.getenv("XAI_IMAGE_SIZE", "1024x1024")
    response_format = payload.get("response_format")
    n = payload.get("n") or 1
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 1
    n = max(1, min(n, 4))

    base_url = _validate_base_url(os.getenv("XAI_IMAGE_BASE_URL", ""), "https://api.x.ai/v1")
    is_xai = "api.x.ai" in base_url
    request_payload = {
        "model": model,
        "prompt": prompt,
        "n": n,
    }
    if not is_xai and size:
        request_payload["size"] = size
    if response_format and not is_xai:
        request_payload["response_format"] = response_format

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url}/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )
            response.raise_for_status()
            return web.json_response(response.json())
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        logging.getLogger(__name__).warning("Image generation error %s: %s", exc.response.status_code, detail)
        return web.json_response({"error": {"message": detail}}, status=exc.response.status_code)
    except Exception as exc:
        logger.error("Image generation failed: %s", exc)
        return web.json_response({"error": {"message": "Internal server error."}}, status=500)


async def video_generations(request: web.Request) -> web.Response:
    payload = await request.json()
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return web.json_response({"error": {"message": "Prompt is required."}}, status=400)

    api_key = os.getenv("XAI_VIDEO_API_KEY") or os.getenv("XAI_IMAGE_API_KEY") or os.getenv("XAI_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        return web.json_response({"error": {"message": "XAI_VIDEO_API_KEY or XAI_API_KEY is required."}}, status=400)

    model = payload.get("model") or os.getenv("XAI_VIDEO_MODEL", "grok-imagine-video")
    n = payload.get("n") or 1
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 1
    n = max(1, min(n, 2))

    base_url = _validate_base_url(
        os.getenv("XAI_VIDEO_BASE_URL", "") or os.getenv("XAI_IMAGE_BASE_URL", ""),
        "https://api.x.ai/v1",
    )
    request_payload = dict(payload or {})
    request_payload["model"] = model
    request_payload["prompt"] = prompt
    request_payload["n"] = n

    logger = logging.getLogger(__name__)
    poll_interval = _parse_float_env("VERA_XAI_VIDEO_POLL_INTERVAL_SECONDS", 3.0, minimum=0.5)
    poll_timeout = _parse_float_env("VERA_XAI_VIDEO_POLL_TIMEOUT_SECONDS", 210.0, minimum=5.0)

    async def _poll_video_completion(
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        request_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        deadline = time.time() + poll_timeout
        poll_url = f"{base_url}/videos/{request_id}"

        while time.time() < deadline:
            await asyncio.sleep(poll_interval)
            poll_response = await client.get(poll_url, headers=headers)

            if poll_response.status_code == 202:
                continue

            if poll_response.status_code >= 400:
                return None, poll_response.text

            try:
                poll_data = poll_response.json()
            except ValueError:
                return None, poll_response.text

            status = str(poll_data.get("status", "")).strip().lower()
            video_obj = poll_data.get("video")
            if status == "done":
                return poll_data, None
            if status in {"expired", "failed", "rejected"}:
                return poll_data, f"Video generation {status}."
            if isinstance(video_obj, dict) and video_obj.get("url"):
                return poll_data, None

        return None, f"Video generation timed out after {int(poll_timeout)}s."

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=max(120.0, poll_timeout + 30.0)) as client:
            response = await client.post(
                f"{base_url}/videos/generations",
                headers=headers,
                json=request_payload,
            )
            response.raise_for_status()
            init_data = response.json()

            request_id = (
                str(init_data.get("request_id") or "").strip()
                or str(init_data.get("response_id") or "").strip()
            )
            final_data = init_data
            if request_id:
                logger.info("Video generation queued (request_id=%s). Polling for completion.", request_id)
                polled_data, poll_error = await _poll_video_completion(client, headers, request_id)
                if poll_error and not polled_data:
                    logger.warning("Video generation polling failed: %s", poll_error)
                    return web.json_response(
                        {"error": {"message": poll_error}, "request_id": request_id},
                        status=504,
                    )
                if polled_data:
                    final_data = polled_data

            if not isinstance(final_data, dict):
                return web.json_response(final_data)

            video_obj = final_data.get("video")
            urls: List[str] = []
            if isinstance(video_obj, dict):
                video_url = video_obj.get("url")
                if isinstance(video_url, str) and video_url.strip():
                    urls.append(video_url.strip())
            for item in final_data.get("data", []) if isinstance(final_data.get("data"), list) else []:
                if isinstance(item, dict):
                    item_url = item.get("url")
                    if isinstance(item_url, str) and item_url.strip():
                        urls.append(item_url.strip())

            if urls and not final_data.get("data"):
                final_data["data"] = [{"url": url} for url in urls]

            return web.json_response(final_data)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        logger.warning("Video generation error %s: %s", exc.response.status_code, detail)
        return web.json_response({"error": {"message": detail}}, status=exc.response.status_code)
    except Exception as exc:
        logger.exception("Unhandled video generation exception")
        return web.json_response({"error": {"message": "Internal server error."}}, status=500)


async def anthropic_messages_proxy(request: web.Request) -> web.StreamResponse:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": {"message": "Invalid JSON payload."}}, status=400)

    if not isinstance(payload, dict):
        return web.json_response({"error": {"message": "JSON body must be an object."}}, status=400)

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return web.json_response({"error": {"message": "messages must be a non-empty array."}}, status=400)
    if len(messages) > 200:
        return web.json_response({"error": {"message": "messages array is too large."}}, status=400)

    stream_value = payload.get("stream", False)
    if not isinstance(stream_value, bool):
        return web.json_response({"error": {"message": "stream must be a boolean."}}, status=400)

    model = payload.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        return web.json_response({"error": {"message": "model must be a non-empty string."}}, status=400)

    client_ip = _client_ip(request)
    allowed, retry_after = _check_anthropic_proxy_rate_limit(request.app, client_ip)
    if not allowed:
        return web.json_response(
            {"error": {"message": "Rate limit exceeded. Please retry shortly."}},
            status=429,
            headers={"Retry-After": str(retry_after)},
        )

    api_key = _get_secret_env("ANTHROPIC_API_KEY")
    if not api_key:
        return web.json_response(
            {"error": {"message": "ANTHROPIC_API_KEY is not configured on the server."}},
            status=503,
        )

    upstream_url = _anthropic_messages_endpoint()
    timeout_seconds = _parse_float_env("VERA_ANTHROPIC_PROXY_TIMEOUT_SECONDS", 120.0, minimum=1.0)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            if stream_value:
                async with client.stream("POST", upstream_url, headers=headers, json=payload) as upstream:
                    if upstream.status_code >= 400:
                        raw_error = await upstream.aread()
                        text_error = raw_error.decode("utf-8", errors="replace").strip()
                        try:
                            parsed_error = json.loads(text_error) if text_error else {"error": {"message": "Upstream error"}}
                        except json.JSONDecodeError:
                            parsed_error = {"error": {"message": text_error or "Upstream error"}}
                        return web.json_response(parsed_error, status=upstream.status_code)

                    response = web.StreamResponse(
                        status=upstream.status_code,
                        headers={
                            "Content-Type": upstream.headers.get("content-type", "text/event-stream"),
                            "Cache-Control": "no-cache",
                        },
                    )
                    await response.prepare(request)
                    async for chunk in upstream.aiter_bytes():
                        if chunk:
                            await response.write(chunk)
                    await response.write_eof()
                    return response

            upstream = await client.post(upstream_url, headers=headers, json=payload)
            if upstream.status_code >= 400:
                try:
                    parsed_error = upstream.json()
                except ValueError:
                    parsed_error = {"error": {"message": upstream.text or "Upstream error"}}
                return web.json_response(parsed_error, status=upstream.status_code)

            try:
                parsed = upstream.json()
            except ValueError:
                return web.Response(
                    text=upstream.text,
                    status=upstream.status_code,
                    content_type=upstream.headers.get("content-type", "text/plain"),
                )
            return web.json_response(parsed, status=upstream.status_code)
    except httpx.HTTPError as exc:
        logger.warning("Anthropic proxy request failed: %s", exc)
        return web.json_response({"error": {"message": f"Upstream request failed: {exc}"}}, status=502)


async def tools_status(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    mcp_status = vera.mcp.get_status()
    return web.json_response({
        "mcp": mcp_status,
        "native": {
            "tools": sorted(vera._native_tool_handlers.keys()),
            "errors": vera._native_tool_errors
        }
    })


def _channel_capabilities_payload(capabilities) -> Dict[str, Any]:
    if not capabilities:
        return {}
    return {
        "chat_types": [chat_type.value for chat_type in (capabilities.chat_types or [])],
        "reactions": capabilities.reactions,
        "threads": capabilities.threads,
        "media": capabilities.media,
        "polls": capabilities.polls,
        "native_commands": capabilities.native_commands,
        "text_chunk_limit": capabilities.text_chunk_limit,
    }


async def channels_status(request: web.Request) -> web.Response:
    vera = request.app.get("vera")
    dock = getattr(vera, "channel_dock", None)
    channels: List[Dict[str, Any]] = []

    if dock:
        for meta in dock.list_channels():
            adapter = dock.get(meta.id)
            status = "registered"
            if adapter is not None:
                if hasattr(adapter, "running"):
                    status = "running" if getattr(adapter, "running") else "stopped"
                elif hasattr(adapter, "is_running"):
                    status = "running" if getattr(adapter, "is_running") else "stopped"
            channels.append({
                "id": meta.id,
                "label": meta.label,
                "blurb": meta.blurb,
                "order": meta.order,
                "status": status,
                "capabilities": _channel_capabilities_payload(getattr(adapter, "capabilities", None)),
            })

    try:
        from channels.loader import get_channel_config_snapshot
        configured = get_channel_config_snapshot()
    except Exception as exc:
        logger.debug("Failed to read channel config snapshot: %s", exc)
        configured = {
            "source": "unknown",
            "config_path": str(Path("config") / "channels.json"),
            "config_exists": False,
            "specs": [],
        }

    return web.json_response({
        "active": channels,
        "configured": configured,
    })


def _get_whatsapp_adapter(vera) -> Optional[Any]:
    dock = getattr(vera, "channel_dock", None)
    if not dock:
        return None
    adapter = dock.get("whatsapp")
    if adapter and hasattr(adapter, "handle_webhook"):
        return adapter
    return None


async def whatsapp_webhook_verify(request: web.Request) -> web.Response:
    vera = request.app.get("vera")
    adapter = _get_whatsapp_adapter(vera)
    if not adapter:
        return web.Response(status=503, text="WhatsApp adapter not configured")

    mode = request.query.get("hub.mode", "")
    token = request.query.get("hub.verify_token", "")
    challenge = request.query.get("hub.challenge", "")

    if mode == "subscribe" and hasattr(adapter, "verify_webhook"):
        try:
            if adapter.verify_webhook(token):
                return web.Response(text=challenge or "")
        except Exception:
            logger.debug("Suppressed Exception in server")
            pass

    return web.Response(status=403, text="Verification failed")


async def whatsapp_webhook_receive(request: web.Request) -> web.Response:
    vera = request.app.get("vera")
    adapter = _get_whatsapp_adapter(vera)
    if not adapter:
        return web.json_response({"error": "WhatsApp adapter not configured"}, status=503)

    raw_body = await request.read()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON payload"}, status=400)

    try:
        result = adapter.handle_webhook(payload, dict(request.headers), raw_body)
        if asyncio.iscoroutine(result):
            result = await result
        return web.json_response(result or {"ok": True})
    except Exception as exc:
        logger.warning("WhatsApp webhook error: %s", exc)
        return web.json_response({"error": "Webhook handler error"}, status=500)


def _get_local_loopback_adapter(vera) -> Optional[Any]:
    dock = getattr(vera, "channel_dock", None)
    if not dock:
        return None
    adapter = dock.get("local-loopback")
    if adapter and hasattr(adapter, "inject_inbound") and hasattr(adapter, "outbox_snapshot"):
        return adapter
    return None


async def local_loopback_inbound(request: web.Request) -> web.Response:
    vera = request.app.get("vera")
    adapter = _get_local_loopback_adapter(vera)
    if not adapter:
        return web.json_response({"error": "Local loopback adapter not configured"}, status=503)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid or missing JSON body."}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"error": "Invalid payload."}, status=400)

    text = str(payload.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "Field 'text' is required."}, status=400)
    wait_for_handler = bool(payload.get("wait", True))
    raw_timeout = payload.get("timeout_seconds")
    timeout_seconds: Optional[float] = None
    if raw_timeout is not None:
        try:
            timeout_seconds = max(0.1, min(float(raw_timeout), 120.0))
        except Exception:
            timeout_seconds = None

    try:
        result = await adapter.inject_inbound(
            text=text,
            sender_id=str(payload.get("sender_id") or "loopback-user").strip() or "loopback-user",
            sender_name=(str(payload.get("sender_name")).strip() if payload.get("sender_name") is not None else None),
            conversation_id=(str(payload.get("conversation_id")).strip() if payload.get("conversation_id") is not None else None),
            session_link_id=(str(payload.get("session_link_id")).strip() if payload.get("session_link_id") is not None else None),
            chat_type=str(payload.get("chat_type") or "direct").strip().lower() or "direct",
            thread_id=(str(payload.get("thread_id")).strip() if payload.get("thread_id") is not None else None),
            reply_to_id=(str(payload.get("reply_to_id")).strip() if payload.get("reply_to_id") is not None else None),
            raw=payload if isinstance(payload, dict) else {},
            wait_for_handler=wait_for_handler,
            timeout_seconds=timeout_seconds,
        )
        return web.json_response({
            "ok": True,
            "result": result,
        })
    except asyncio.TimeoutError:
        return web.json_response({
            "ok": False,
            "result": {
                "status": "timeout",
                "channel": adapter.channel_id,
                "background": False,
                "timeout_seconds": timeout_seconds,
            },
        }, status=202)
    except Exception as exc:
        logger.warning("Local loopback inbound error: %s", exc)
        return web.json_response({"error": "Loopback handler error"}, status=500)


async def local_loopback_outbox(request: web.Request) -> web.Response:
    vera = request.app.get("vera")
    adapter = _get_local_loopback_adapter(vera)
    if not adapter:
        return web.json_response({"error": "Local loopback adapter not configured"}, status=503)
    raw_limit = str(request.query.get("limit") or "20").strip()
    try:
        limit = int(raw_limit) if raw_limit else 20
    except Exception:
        limit = 20
    rows = await adapter.outbox_snapshot(limit=limit)
    return web.json_response({
        "ok": True,
        "count": len(rows),
        "messages": rows,
    })


async def local_loopback_outbox_clear(request: web.Request) -> web.Response:
    vera = request.app.get("vera")
    adapter = _get_local_loopback_adapter(vera)
    if not adapter:
        return web.json_response({"error": "Local loopback adapter not configured"}, status=503)
    cleared = await adapter.clear_outbox()
    return web.json_response({"ok": True, "cleared": int(cleared)})


def _get_push_service(request: web.Request) -> Optional[PushNotificationService]:
    service = request.app.get("push_service")
    if isinstance(service, PushNotificationService):
        return service
    return None


def _get_native_push_service(request: web.Request) -> Optional[NativePushNotificationService]:
    service = request.app.get("native_push_service")
    if isinstance(service, NativePushNotificationService):
        return service
    return None


_PUSH_ACK_ALLOWED_TYPES = {
    "received",
    "displayed",
    "opened",
    "clicked",
    "dismissed",
    "action",
}


def _normalize_push_ack_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _PUSH_ACK_ALLOWED_TYPES:
        return normalized
    return "opened"


def _push_ack_log_path() -> Path:
    raw = str(os.getenv("VERA_PUSH_ACK_LOG_PATH", "vera_memory/push_user_ack.jsonl") or "").strip()
    path = Path(raw).expanduser() if raw else (Path("vera_memory") / "push_user_ack.jsonl")
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _append_jsonl_row(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _build_push_ack_row(
    *,
    run_id: str,
    ack_type: str,
    channel: str,
    source: str,
    device_id: str = "",
    event_type: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "run_id": str(run_id or "").strip()[:128],
        "ack_type": _normalize_push_ack_type(ack_type),
        "channel": str(channel or "").strip().lower()[:64] or "unknown",
        "source": str(source or "").strip().lower()[:64] or "unknown",
    }
    if device_id:
        row["device_id"] = str(device_id).strip()[:256]
    if event_type:
        row["event_type"] = str(event_type).strip()[:96]
    if isinstance(metadata, dict) and metadata:
        compact: Dict[str, Any] = {}
        for key, value in metadata.items():
            skey = str(key).strip()
            if not skey:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                compact[skey] = value
            else:
                compact[skey] = str(value)
            if len(compact) >= 32:
                break
        if compact:
            row["metadata"] = compact
    return row


def _append_push_ack(row: Dict[str, Any]) -> Tuple[bool, str]:
    run_id = str(row.get("run_id") or "").strip()
    if not run_id:
        return False, "missing_run_id"
    path = _push_ack_log_path()
    try:
        _append_jsonl_row(path, row)
    except Exception as exc:
        logger.warning("Failed to record push ack: %s", exc)
        return False, "ack_log_write_failed"
    return True, str(path)


def _expected_reachout_ack_channels(app: web.Application, delivered_to: List[str]) -> List[str]:
    channels: List[str] = list(ack_required_delivery_channels(delivered_to))
    normalized = [str(item).strip().lower() for item in delivered_to if str(item).strip()]
    if "api" not in normalized:
        return channels

    seen = set(channels)

    push_service = app.get("push_service")
    try:
        if getattr(push_service, "enabled", False) and callable(getattr(push_service, "list_subscriptions", None)):
            if push_service.list_subscriptions():
                if "web_push" not in seen:
                    channels.append("web_push")
                    seen.add("web_push")
    except Exception:
        logger.debug("Failed to inspect web push state for reach-out ack expectation")

    native_push_service = app.get("native_push_service")
    try:
        if (
            getattr(native_push_service, "enabled", False)
            and getattr(native_push_service, "configured", False)
            and callable(getattr(native_push_service, "list_devices", None))
        ):
            if native_push_service.list_devices():
                if "fcm" not in seen:
                    channels.append("fcm")
                    seen.add("fcm")
    except Exception:
        logger.debug("Failed to inspect native push state for reach-out ack expectation")

    return channels


def _effective_reachout_delivery_channels(app: web.Application, delivered_to: List[str]) -> List[str]:
    normalized = [str(item).strip().lower() for item in delivered_to if str(item).strip()]
    effective: List[str] = []
    seen = set()

    def _append(channel: str) -> None:
        cleaned = str(channel or "").strip().lower()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        effective.append(cleaned)

    api_present = "api" in normalized
    for channel in normalized:
        if channel == "api":
            continue
        _append(channel)

    if api_present:
        for channel in _expected_reachout_ack_channels(app, delivered_to):
            _append(channel)

    if not effective:
        for channel in normalized:
            _append(channel)

    return effective


def _ack_runplane_if_available(
    request: web.Request,
    *,
    run_id: str,
    ack_type: str,
    source: str,
) -> Dict[str, Any]:
    target_run_id = str(run_id or "").strip()
    if not target_run_id:
        return {"ok": False, "reason": "missing_run_id"}
    try:
        vera = request.app.get("vera")
        proactive = getattr(vera, "proactive_manager", None) if vera else None
        runplane = getattr(proactive, "runplane", None) if proactive else None
        if not runplane or not hasattr(runplane, "ack_run"):
            return {"ok": False, "reason": "runplane_unavailable"}
        return runplane.ack_run(
            target_run_id,
            ack_type=_normalize_push_ack_type(ack_type),
            source=str(source or "unknown").strip().lower() or "unknown",
        )
    except Exception as exc:
        logger.warning("Failed to ingest runplane ack for %s: %s", target_run_id, exc)
        return {"ok": False, "reason": "runplane_ack_failed"}


def _ack_exists_for_run_id(run_id: str, max_scan_lines: int = 200) -> bool:
    path = _push_ack_log_path()
    if not path.exists():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return False
    for line in reversed(lines[-max_scan_lines:]):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict) and str(row.get("run_id") or "").strip() == run_id:
            return True
    return False


def _close_superseded_reachout_runs(
    app: web.Application,
    *,
    current_run_id: str,
    max_to_close: int = 8,
) -> int:
    run_id = str(current_run_id or "").strip()
    if not run_id:
        return 0
    vera = app.get("vera")
    proactive = getattr(vera, "proactive_manager", None) if vera else None
    runplane = getattr(proactive, "runplane", None) if proactive else None
    if not runplane or not hasattr(runplane, "list_runs") or not hasattr(runplane, "mark_run_status"):
        return 0

    closed = 0
    candidate_rows: List[Dict[str, Any]] = []
    for status in ("delivered", "escalated"):
        try:
            rows = runplane.list_runs(limit=200, status_filter=status)
        except Exception:
            logger.debug("Failed to inspect runplane for superseded reachouts")
            return closed
        if isinstance(rows, list):
            candidate_rows.extend(row for row in rows if isinstance(row, dict))

    for row in candidate_rows:
        if closed >= max_to_close:
            break
        row_run_id = str(row.get("run_id") or "").strip()
        if not row_run_id or row_run_id == run_id:
            continue
        if str(row.get("kind") or "").strip().lower() != "delivery_reachout":
            continue
        if not run_requires_ack(row):
            continue
        mark = runplane.mark_run_status(
            run_id=row_run_id,
            status="closed",
            source="reachout_superseded",
            note=f"superseded_by:{run_id}",
        )
        if mark.get("ok"):
            closed += 1
    return closed


def _parse_utc_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromtimestamp(float(text), tz=timezone.utc)
    except Exception:
        pass
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _maybe_proxy_ack_on_native_register(
    request: web.Request,
    payload: Dict[str, Any],
    token: str,
) -> Optional[str]:
    explicit_run_id = str(payload.get("run_id") or payload.get("ack_run_id") or "").strip()[:128]
    explicit_ack_type = str(payload.get("ack_type") or "opened")
    if explicit_run_id:
        if _ack_exists_for_run_id(explicit_run_id):
            _ack_runplane_if_available(
                request,
                run_id=explicit_run_id,
                ack_type=explicit_ack_type,
                source="native_register_explicit_existing",
            )
            return explicit_run_id
        row = _build_push_ack_row(
            run_id=explicit_run_id,
            ack_type=explicit_ack_type,
            channel="fcm",
            source="native_register_explicit",
            device_id=token,
            event_type="innerlife.reached_out",
            metadata={"path": "native_register"},
        )
        ok, _ = _append_push_ack(row)
        if ok:
            _ack_runplane_if_available(
                request,
                run_id=explicit_run_id,
                ack_type=explicit_ack_type,
                source="native_register_explicit",
            )
        return explicit_run_id if ok else None

    window_seconds = _parse_int_env("VERA_PUSH_REGISTER_ACK_WINDOW_SECONDS", 180, minimum=30)
    last_reachout = request.app.get("last_reachout_event")
    if not isinstance(last_reachout, dict):
        return None
    run_id = str(last_reachout.get("run_id") or "").strip()[:128]
    timestamp = _parse_utc_timestamp(str(last_reachout.get("timestamp") or ""))
    if not run_id or not timestamp:
        return None
    age_seconds = (datetime.now(timestamp.tzinfo) - timestamp).total_seconds()
    if age_seconds < 0 or age_seconds > float(window_seconds):
        return None
    if _ack_exists_for_run_id(run_id):
        return run_id
    row = _build_push_ack_row(
        run_id=run_id,
        ack_type="opened",
        channel="fcm",
        source="native_register_proxy",
        device_id=token,
        event_type="innerlife.reached_out",
        metadata={
            "path": "native_register_proxy",
            "window_seconds": window_seconds,
            "age_seconds": round(age_seconds, 3),
        },
    )
    ok, _ = _append_push_ack(row)
    if ok:
        _ack_runplane_if_available(
            request,
            run_id=run_id,
            ack_type="opened",
            source="native_register_proxy",
        )
    return run_id if ok else None


def _maybe_proxy_ack_on_session_activity(
    request: web.Request,
    payload: Dict[str, Any],
) -> Optional[str]:
    window_seconds = _parse_int_env("VERA_SESSION_ACTIVITY_ACK_WINDOW_SECONDS", 900, minimum=30)
    last_reachout = request.app.get("last_reachout_event")
    if not isinstance(last_reachout, dict):
        return None
    run_id = str(last_reachout.get("run_id") or "").strip()[:128]
    timestamp = _parse_utc_timestamp(str(last_reachout.get("timestamp") or ""))
    if not run_id or not timestamp:
        return None
    age_seconds = (datetime.now(timestamp.tzinfo) - timestamp).total_seconds()
    if age_seconds < 0 or age_seconds > float(window_seconds):
        return None
    if _ack_exists_for_run_id(run_id):
        _ack_runplane_if_available(
            request,
            run_id=run_id,
            ack_type="opened",
            source="session_activity_proxy_existing",
        )
        return run_id

    channel_id = str(payload.get("channel_id") or "ui").strip().lower()[:64] or "ui"
    conversation_id = str(payload.get("conversation_id") or "").strip()[:128]
    trigger = str(payload.get("trigger") or "").strip()[:128]
    row = _build_push_ack_row(
        run_id=run_id,
        ack_type="opened",
        channel=channel_id,
        source="session_activity_proxy",
        event_type="innerlife.reached_out",
        metadata={
            "path": "session_activity_proxy",
            "window_seconds": window_seconds,
            "age_seconds": round(age_seconds, 3),
            "conversation_id": conversation_id,
            "trigger": trigger,
        },
    )
    ok, _ = _append_push_ack(row)
    if ok:
        _ack_runplane_if_available(
            request,
            run_id=run_id,
            ack_type="opened",
            source="session_activity_proxy",
        )
    return run_id if ok else None


async def push_vapid(request: web.Request) -> web.Response:
    service = _get_push_service(request)
    if not service:
        return web.json_response({"enabled": False, "reason": "push_service_unavailable"})
    if not service.enabled:
        return web.json_response({"enabled": False, "reason": "vapid_not_configured"})
    return web.json_response({
        "enabled": True,
        "public_key": service.vapid_public_key,
        "subject": service.subject,
    })


async def push_subscribe(request: web.Request) -> web.Response:
    service = _get_push_service(request)
    if not service or not service.enabled:
        return web.json_response({"ok": False, "error": "push_not_configured"}, status=400)
    payload = await request.json()
    subscription = payload.get("subscription") if isinstance(payload, dict) else None
    if subscription is None:
        subscription = payload
    ok, detail = service.add_subscription(subscription if isinstance(subscription, dict) else {})
    if not ok:
        return web.json_response({"ok": False, "error": detail}, status=400)
    return web.json_response({"ok": True, "endpoint": detail})


async def push_unsubscribe(request: web.Request) -> web.Response:
    service = _get_push_service(request)
    if not service:
        return web.json_response({"ok": False, "error": "push_service_unavailable"}, status=400)
    payload = await request.json()
    endpoint = ""
    if isinstance(payload, dict):
        endpoint = payload.get("endpoint") or payload.get("subscription", {}).get("endpoint", "")
    if not endpoint:
        return web.json_response({"ok": False, "error": "missing_endpoint"}, status=400)
    removed = service.remove_subscription(endpoint)
    return web.json_response({"ok": True, "removed": removed})


async def push_test(request: web.Request) -> web.Response:
    service = _get_push_service(request)
    if not service or not service.enabled:
        return web.json_response({"ok": False, "error": "push_not_configured"}, status=400)
    payload = await request.json()
    title = payload.get("title") or "VERA"
    body = payload.get("body") or "Push notifications are active."
    data = payload.get("data") or {}
    message = {
        "title": title,
        "body": body,
        "icon": payload.get("icon") or "/assets/icon-192.png",
        "badge": payload.get("badge") or "/assets/icon-192.png",
        "data": data,
    }
    result = await service.broadcast(message)
    return web.json_response({"ok": True, **result})


async def push_native_status(request: web.Request) -> web.Response:
    service = _get_native_push_service(request)
    if not service:
        return web.json_response({"ok": False, "error": "native_push_service_unavailable"}, status=503)
    return web.json_response({"ok": True, **service.status()})


async def push_native_register(request: web.Request) -> web.Response:
    service = _get_native_push_service(request)
    if not service:
        return web.json_response({"ok": False, "error": "native_push_service_unavailable"}, status=503)
    payload = await request.json()
    device = payload.get("device") if isinstance(payload, dict) else None
    if device is None:
        device = payload
    if not isinstance(device, dict):
        return web.json_response({"ok": False, "error": "invalid_payload"}, status=400)
    ok, detail = service.register_device(device)
    if not ok:
        return web.json_response({"ok": False, "error": detail}, status=400)
    ack_run_id = _maybe_proxy_ack_on_native_register(request, device, detail)
    response_payload: Dict[str, Any] = {"ok": True, "token": detail}
    if ack_run_id:
        response_payload["ack_run_id"] = ack_run_id
    return web.json_response(response_payload)


async def push_native_unregister(request: web.Request) -> web.Response:
    service = _get_native_push_service(request)
    if not service:
        return web.json_response({"ok": False, "error": "native_push_service_unavailable"}, status=503)
    payload = await request.json()
    token = ""
    provider = "fcm"
    if isinstance(payload, dict):
        token = str(payload.get("token") or payload.get("device_token") or "").strip()
        provider = str(payload.get("provider") or "fcm").strip().lower() or "fcm"
    if not token:
        return web.json_response({"ok": False, "error": "missing_token"}, status=400)
    removed = service.unregister_device(token, provider=provider)
    return web.json_response({"ok": True, "removed": removed})


async def push_native_test(request: web.Request) -> web.Response:
    service = _get_native_push_service(request)
    if not service:
        return web.json_response({"ok": False, "error": "native_push_service_unavailable"}, status=503)
    payload = await request.json()
    if not isinstance(payload, dict):
        payload = {}
    title = payload.get("title") or "Vera"
    body = payload.get("body") or payload.get("message") or "Native push test from Vera."
    data = payload.get("data") or {}
    provider = str(payload.get("provider") or "fcm").strip().lower() or "fcm"
    platforms_raw = payload.get("platforms") or []
    tags_raw = payload.get("tags") or []
    platforms = [str(item) for item in platforms_raw] if isinstance(platforms_raw, list) else []
    tags = [str(item) for item in tags_raw] if isinstance(tags_raw, list) else []

    result = await service.broadcast(
        {
            "title": str(title),
            "body": str(body),
            "data": data if isinstance(data, dict) else {},
        },
        provider=provider,
        platforms=platforms,
        tags=tags,
    )
    if not result.get("ok"):
        return web.json_response(result, status=400)
    return web.json_response(result)


async def push_native_ack(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "invalid_payload"}, status=400)

    run_id = str(payload.get("run_id") or "").strip()[:128]
    if not run_id:
        return web.json_response({"ok": False, "error": "missing_run_id"}, status=400)

    ack_type = _normalize_push_ack_type(payload.get("ack_type") or payload.get("type") or "opened")
    channel = str(payload.get("channel") or payload.get("provider") or "").strip().lower()[:64] or "unknown"
    source = str(payload.get("source") or "").strip().lower()[:64] or "unknown"
    device_id = str(payload.get("device_id") or payload.get("token") or "").strip()[:256]
    event_type = str(payload.get("event_type") or "").strip()[:96]

    metadata_raw = payload.get("metadata")
    if not isinstance(metadata_raw, dict):
        metadata_raw = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    metadata: Dict[str, Any] = {}
    for key, value in metadata_raw.items():
        skey = str(key).strip()
        if not skey:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[skey] = value
        else:
            metadata[skey] = str(value)
        if len(metadata) >= 32:
            break

    row = _build_push_ack_row(
        run_id=run_id,
        ack_type=ack_type,
        channel=channel,
        source=source,
        device_id=device_id,
        event_type=event_type,
        metadata=metadata,
    )
    ok, path = _append_push_ack(row)
    if not ok:
        return web.json_response({"ok": False, "error": path}, status=500)
    runplane_ack = _ack_runplane_if_available(
        request,
        run_id=run_id,
        ack_type=ack_type,
        source=source or "native_ack",
    )

    return web.json_response(
        {
            "ok": True,
            "run_id": run_id,
            "ack_type": ack_type,
            "log_path": path,
            "runplane_ack": runplane_ack,
        }
    )


async def push_native_targets(request: web.Request) -> web.Response:
    service = _get_native_push_service(request)
    if not service:
        return web.json_response({"ok": False, "error": "native_push_service_unavailable"}, status=503)

    payload: Dict[str, Any] = {}
    if request.can_read_body:
        try:
            maybe_payload = await request.json()
            if isinstance(maybe_payload, dict):
                payload = maybe_payload
        except Exception:
            payload = {}

    provider = str(payload.get("provider") or request.query.get("provider") or "fcm").strip().lower() or "fcm"
    platforms_raw = payload.get("platforms")
    tags_raw = payload.get("tags")
    if platforms_raw is None:
        query_platforms = request.query.get("platforms", "").strip()
        if query_platforms:
            platforms_raw = [part.strip() for part in query_platforms.split(",")]
    if tags_raw is None:
        query_tags = request.query.get("tags", "").strip()
        if query_tags:
            tags_raw = [part.strip() for part in query_tags.split(",")]
    platforms = [str(item) for item in platforms_raw] if isinstance(platforms_raw, list) else []
    tags = [str(item) for item in tags_raw] if isinstance(tags_raw, list) else []

    result = service.preview_targets(provider=provider, platforms=platforms, tags=tags)
    if not result.get("ok"):
        return web.json_response(result, status=400)
    return web.json_response(result)


async def google_auth_status(request: web.Request) -> web.Response:
    debug = request.query.get("debug", "").lower() in {"1", "true", "yes", "on"}
    user_email, email_source = _resolve_workspace_user_email_with_source()
    credentials_dir = _get_google_credentials_dir()
    checked_at = datetime.now().isoformat()
    oauth_config = _resolve_google_oauth_config(_get_creds_dir())
    credentials_file = credentials_dir / f"{user_email}.json" if user_email else None
    credentials_present = bool(credentials_file and credentials_file.exists())
    oauth_secret_path_exists = bool(
        oauth_config["client_secret_path"]
        and Path(oauth_config["client_secret_path"]).expanduser().exists()
    )

    server_info = {}
    missing_env = []
    vera = request.app.get("vera")
    if vera and getattr(vera, "mcp", None):
        status = vera.mcp.get_status()
        server_info = status.get("servers", {}).get("google-workspace", {}) or {}
        missing_env = server_info.get("missing_env") or []

    oauth_ready = bool(oauth_config["client_id"] and oauth_config["client_secret"]) or bool(
        oauth_config["client_secret_path"]
    )
    if not user_email:
        payload = {
            "status": "unauthorized",
            "reason": "missing_user_email",
            "reasons": ["missing_user_email"],
            "user_email": user_email,
            "credentials_dir": str(credentials_dir),
            "credentials_file": str(credentials_file) if credentials_file else "",
            "oauth_client_id": oauth_config["client_id"],
            "oauth_redirect_uri": oauth_config["redirect_uri"],
            "oauth_client_secret_path": oauth_config["client_secret_path"],
            "oauth_ready": oauth_ready,
            "missing_env": missing_env,
            "server_running": server_info.get("running"),
            "server_health": server_info.get("health"),
            "checked_at": checked_at,
        }
        if debug:
            payload["debug"] = {
                "email_source": email_source,
                "credentials_dir_exists": credentials_dir.exists(),
                "credentials_file_exists": credentials_present,
                "credentials_dir_files": sorted(
                    [path.name for path in credentials_dir.glob("*.json")]
                ) if credentials_dir.exists() else [],
                "oauth_client_secret_path_exists": oauth_secret_path_exists,
                "resolved_credentials_dir": str(credentials_dir),
            }
        return web.json_response(payload)

    if credentials_present:
        payload = {
            "status": "authorized",
            "reason": "",
            "warnings": [reason for reason in (
                "missing_oauth_env" if missing_env else "",
                "missing_oauth_client" if not oauth_ready else "",
                "missing_redirect_uri" if not oauth_config["redirect_uri"] else "",
            ) if reason],
            "user_email": user_email,
            "credentials_dir": str(credentials_dir),
            "credentials_file": str(credentials_file),
            "oauth_client_id": oauth_config["client_id"],
            "oauth_redirect_uri": oauth_config["redirect_uri"],
            "oauth_client_secret_path": oauth_config["client_secret_path"],
            "oauth_ready": oauth_ready,
            "missing_env": missing_env,
            "server_running": server_info.get("running"),
            "server_health": server_info.get("health"),
            "checked_at": checked_at,
        }
        if debug:
            payload["debug"] = {
                "email_source": email_source,
                "credentials_dir_exists": credentials_dir.exists(),
                "credentials_file_exists": credentials_present,
                "credentials_dir_files": sorted(
                    [path.name for path in credentials_dir.glob("*.json")]
                ) if credentials_dir.exists() else [],
                "oauth_client_secret_path_exists": oauth_secret_path_exists,
                "resolved_credentials_dir": str(credentials_dir),
            }
        return web.json_response(payload)

    missing_reasons = []
    if missing_env:
        missing_reasons.append("missing_oauth_env")
    if not oauth_ready:
        missing_reasons.append("missing_oauth_client")
    if not oauth_config["redirect_uri"]:
        missing_reasons.append("missing_redirect_uri")
    if missing_reasons:
        payload = {
            "status": "unauthorized",
            "reason": missing_reasons[0],
            "reasons": missing_reasons,
            "user_email": user_email,
            "credentials_dir": str(credentials_dir),
            "credentials_file": str(credentials_file) if credentials_file else "",
            "oauth_client_id": oauth_config["client_id"],
            "oauth_redirect_uri": oauth_config["redirect_uri"],
            "oauth_client_secret_path": oauth_config["client_secret_path"],
            "oauth_ready": oauth_ready,
            "missing_env": missing_env,
            "server_running": server_info.get("running"),
            "server_health": server_info.get("health"),
            "checked_at": checked_at,
        }
        if debug:
            payload["debug"] = {
                "email_source": email_source,
                "credentials_dir_exists": credentials_dir.exists(),
                "credentials_file_exists": credentials_present,
                "credentials_dir_files": sorted(
                    [path.name for path in credentials_dir.glob("*.json")]
                ) if credentials_dir.exists() else [],
                "oauth_client_secret_path_exists": oauth_secret_path_exists,
                "resolved_credentials_dir": str(credentials_dir),
            }
        return web.json_response(payload)

    payload = {
        "status": "unauthorized",
        "reason": "missing_credentials_file",
        "reasons": ["missing_credentials_file"],
        "user_email": user_email,
        "credentials_dir": str(credentials_dir),
        "credentials_file": str(credentials_file) if credentials_file else "",
        "oauth_client_id": oauth_config["client_id"],
        "oauth_redirect_uri": oauth_config["redirect_uri"],
        "oauth_client_secret_path": oauth_config["client_secret_path"],
        "oauth_ready": oauth_ready,
        "missing_env": missing_env,
        "server_running": server_info.get("running"),
        "server_health": server_info.get("health"),
        "checked_at": checked_at,
    }
    if debug:
        payload["debug"] = {
            "email_source": email_source,
            "credentials_dir_exists": credentials_dir.exists(),
            "credentials_file_exists": credentials_present,
            "credentials_dir_files": sorted(
                [path.name for path in credentials_dir.glob("*.json")]
            ) if credentials_dir.exists() else [],
            "oauth_client_secret_path_exists": oauth_secret_path_exists,
            "resolved_credentials_dir": str(credentials_dir),
        }
    return web.json_response(payload)


async def google_auth_start(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    payload = await request.json()
    service_name = payload.get("service_name") or "Gmail"
    user_email = payload.get("user_google_email") or _resolve_workspace_user_email()

    if not user_email:
        return web.json_response(
            {"error": "Missing GOOGLE_WORKSPACE_USER_EMAIL."},
            status=400,
        )

    status = vera.mcp.get_status()
    server_info = status.get("servers", {}).get("google-workspace")
    if not server_info:
        return web.json_response({"error": "google-workspace MCP not configured."}, status=404)
    if server_info.get("missing_env"):
        return web.json_response(
            {"error": "Missing required env for google-workspace MCP.", "missing_env": server_info["missing_env"]},
            status=400,
        )
    if not server_info.get("running"):
        started = await asyncio.to_thread(vera.mcp.start_server, "google-workspace")
        if not started:
            return web.json_response({"error": "Failed to start google-workspace MCP."}, status=500)

    try:
        message = await asyncio.wait_for(
            asyncio.to_thread(
                vera.mcp.call_tool,
                "google-workspace",
                "start_google_auth",
                {"service_name": service_name, "user_google_email": user_email},
                60.0,
            ),
            timeout=65.0,
        )
    except Exception as exc:
        logger.error("Google auth failed: %s", exc)
        return web.json_response({"error": "Internal server error."}, status=500)

    auth_url = _extract_auth_url(message)
    return web.json_response(
        {
            "ok": True,
            "user_email": user_email,
            "auth_url": auth_url,
            "message": message,
        }
    )


async def tools_start(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    payload = await request.json()
    servers = payload.get("servers")
    start_timeout = _parse_float_env("VERA_MCP_MANUAL_START_TIMEOUT_SECONDS", 20.0, minimum=1.0)

    def _start_server(name: str) -> bool:
        starter = getattr(vera.mcp, "start_server_with_timeout", None)
        if callable(starter):
            return bool(starter(name, start_timeout))
        bounded = getattr(vera.mcp, "_start_server_with_timeout", None)
        if callable(bounded):
            return bool(bounded(name, start_timeout))
        return bool(vera.mcp.start_server(name))

    if servers:
        results = {}
        for name in servers:
            results[name] = await asyncio.to_thread(_start_server, name)
        return web.json_response({"started": results})

    await asyncio.to_thread(vera.mcp.start_all)
    return web.json_response({"started": "all"})


async def tools_restart(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    payload = await request.json()
    servers = payload.get("servers", [])
    results = {}
    for name in servers:
        results[name] = await asyncio.to_thread(vera.mcp.restart_server, name)
    return web.json_response({"restarted": results})


async def tools_list(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    tools = vera.mcp.get_available_tools()
    native_tools = sorted(getattr(vera, "_native_tool_handlers", {}).keys())
    return web.json_response({
        "tools": tools,
        "native_tools": native_tools,
    })


async def tools_defs(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    tool_defs = vera.mcp.get_available_tool_defs()
    native_defs = list(getattr(vera, "_native_tool_defs", []))
    return web.json_response({
        "tools": tool_defs,
        "native_tools": native_defs,
    })


async def tools_last_payload(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    bridge = getattr(vera, "_llm_bridge", None)
    payload = {}
    if bridge and getattr(bridge, "get_last_tool_payload", None):
        payload = bridge.get_last_tool_payload()
    return web.json_response({"payload": payload})


async def tools_preview(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    bridge = getattr(vera, "_llm_bridge", None)
    if bridge is None and getattr(vera, "llm_router", None):
        bridge = vera.llm_router.create_bridge()
        vera._llm_bridge = bridge
    if not bridge or not getattr(bridge, "_build_tool_schemas", None):
        return web.json_response({"ok": False, "error": "LLM bridge unavailable"}, status=503)

    payload: Dict[str, Any] = {}
    if request.can_read_body:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

    context = str(payload.get("context") or "").strip()
    if not context:
        return web.json_response({"ok": False, "error": "context is required"}, status=400)

    try:
        tools, tool_choice, explicit = await bridge._build_tool_schemas(context=context)
        preview_payload = bridge.get_last_tool_payload() if getattr(bridge, "get_last_tool_payload", None) else {}
        return web.json_response(
            {
                "ok": True,
                "tool_count": len(tools or []),
                "tool_choice": tool_choice,
                "explicit_tools": list(explicit or []),
                "payload": preview_payload,
            }
        )
    except Exception as exc:
        logger.exception("tools_preview failed")
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def tools_history(request: web.Request) -> web.Response:
    limit = int(request.query.get("limit", "50"))
    vera = request.app["vera"]
    bridge = getattr(vera, "_llm_bridge", None)
    history = getattr(bridge, "tool_execution_history", []) if bridge else []
    logger.info("tools_history: bridge=%s entries=%d", bridge is not None, len(history))
    return web.json_response({"history": history[-limit:], "count": len(history)})


async def tools_history_clear(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    bridge = getattr(vera, "_llm_bridge", None)
    if bridge and hasattr(bridge, "tool_execution_history"):
        bridge.tool_execution_history = []
    return web.json_response({"ok": True})


async def quorum_status(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    return web.json_response(vera.get_quorum_status())


async def quorum_list(request: web.Request) -> web.Response:
    quorums = []
    ordered_names = list(QUORUM_PRIORITY_ORDER)
    for name in PREMADE_QUORUMS.keys():
        if name not in ordered_names:
            ordered_names.append(name)
    for name in ordered_names:
        quorum = PREMADE_QUORUMS.get(name)
        if not quorum:
            continue
        quorums.append({
            "name": quorum.name,
            "purpose": quorum.purpose,
            "agents": quorum.get_agent_names(),
            "consensus": quorum.consensus_algorithm.value,
            "lead_agent": quorum.get_lead_agent(),
            "veto_agent": quorum.get_veto_agent(),
            "tool_access": list(quorum.tool_access),
            "description": quorum.description.strip(),
            "is_swarm": quorum.name.lower() == "swarm",
            "source": "built_in",
        })
    for spec in list_custom_quorum_specs():
        try:
            custom_quorum = build_quorum_from_spec(spec)
        except Exception as exc:
            logger.warning("Skipping custom quorum %s: %s", spec.get("name"), exc)
            continue
        quorums.append({
            "name": custom_quorum.name,
            "purpose": custom_quorum.purpose,
            "agents": custom_quorum.get_agent_names(),
            "consensus": custom_quorum.consensus_algorithm.value,
            "lead_agent": custom_quorum.get_lead_agent(),
            "veto_agent": custom_quorum.get_veto_agent(),
            "tool_access": list(custom_quorum.tool_access),
            "description": custom_quorum.description.strip(),
            "is_swarm": bool(spec.get("is_swarm", False)),
            "source": "custom",
        })
    return web.json_response({"quorums": quorums})


async def quorum_settings(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    payload = await request.json()
    quorum_auto = payload.get("quorum_auto_enabled")
    swarm_auto = payload.get("swarm_auto_enabled")
    updated = vera.update_quorum_settings(quorum_auto, swarm_auto)
    return web.json_response({"settings": updated})


async def quorum_custom_create(request: web.Request) -> web.Response:
    payload = await request.json()
    try:
        custom = save_custom_quorum_spec(payload)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Failed to save custom quorum")
        return web.json_response({"error": "Internal server error."}, status=500)
    return web.json_response({"status": "ok", "quorum": custom})


async def quorum_custom_delete(request: web.Request) -> web.Response:
    payload = await request.json()
    name = (payload.get("name") or "").strip()
    if not name:
        return web.json_response({"error": "Missing quorum name"}, status=400)
    removed = delete_custom_quorum(name)
    return web.json_response({"status": "ok", "removed": removed})


async def memory_stats(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    memory = getattr(vera, "memory", None)
    if not memory:
        return web.json_response({"error": "Memory service unavailable."}, status=503)
    try:
        raw_stats = memory.get_stats()
        safe_stats = json.loads(json.dumps(raw_stats, default=str))
        return web.json_response(safe_stats)
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to fetch memory stats")
        return web.json_response({"error": "Internal server error."}, status=500)


async def learning_loop_status(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    learning_loop = getattr(vera, "learning_loop", None)
    if not learning_loop:
        return web.json_response({"error": "Learning loop unavailable."}, status=503)
    try:
        payload = {
            "stats": learning_loop.get_stats(),
        }
        example_store = getattr(learning_loop, "example_store", None)
        if example_store and hasattr(example_store, "get_statistics"):
            payload["example_store"] = example_store.get_statistics()
        payload = json.loads(json.dumps(payload, default=str))
        return web.json_response(payload)
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to fetch learning loop status")
        return web.json_response({"error": "Internal server error."}, status=500)


async def learning_loop_run_cycle(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    learning_loop = getattr(vera, "learning_loop", None)
    if not learning_loop:
        return web.json_response({"error": "Learning loop unavailable."}, status=503)

    payload: Dict[str, Any] = {}
    if request.can_read_body:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                payload = raw
        except Exception:
            payload = {}

    force = bool(payload.get("force", False))
    wait_for_completion = bool(payload.get("wait", False))
    timeout_raw = payload.get("timeout_seconds", None)
    timeout_seconds = float(timeout_raw or 0)
    if wait_for_completion:
        # Default to a practical sync wait window when caller requests completion.
        # The prior implicit 1s floor caused false timeout errors for healthy runs.
        if timeout_seconds <= 0:
            timeout_seconds = 120.0
        timeout_seconds = max(1.0, min(timeout_seconds, 300.0))
    else:
        timeout_seconds = 0.0

    async def _run_once() -> Dict[str, Any]:
        if hasattr(learning_loop, "run_daily_learning_cycle_if_due"):
            return await learning_loop.run_daily_learning_cycle_if_due(force=force)
        result = await learning_loop.run_daily_learning_cycle()
        return {"ran": True, "reason": "legacy_run_daily", "result": result}

    def _consume_cycle_task(task: "asyncio.Task[Dict[str, Any]]") -> None:
        try:
            task.result()
        except Exception:
            logging.getLogger(__name__).exception("Background learning loop cycle failed")

    try:
        if wait_for_completion:
            run_task: "asyncio.Task[Dict[str, Any]]" = asyncio.create_task(_run_once())
            run_task.add_done_callback(_consume_cycle_task)
            try:
                completed = (
                    await asyncio.wait_for(asyncio.shield(run_task), timeout=timeout_seconds)
                    if timeout_seconds
                    else await run_task
                )
                safe_completed = json.loads(json.dumps(completed, default=str))
                return web.json_response({
                    "scheduled": True,
                    "completed": True,
                    "result": safe_completed,
                })
            except asyncio.TimeoutError:
                return web.json_response(
                    {
                        "scheduled": True,
                        "completed": False,
                        "in_progress": True,
                        "timeout_seconds": timeout_seconds,
                        "error": "learning loop cycle timed out; continuing in background",
                    },
                    status=202,
                )

        async def _background_run() -> None:
            try:
                await _run_once()
            except Exception:
                logging.getLogger(__name__).exception("Background learning loop cycle failed")

        asyncio.create_task(_background_run())
        return web.json_response({
            "scheduled": True,
            "completed": False,
            "force": force,
        })
    except asyncio.TimeoutError:
        return web.json_response(
            {"scheduled": True, "completed": False, "error": "learning loop cycle timed out"},
            status=504,
        )
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to run learning loop cycle")
        return web.json_response({"error": "Internal server error."}, status=500)


async def learning_loop_lora_evals(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    learning_loop = getattr(vera, "learning_loop", None)
    if not learning_loop:
        return web.json_response({"error": "Learning loop unavailable."}, status=503)

    limit_raw = str(request.query.get("limit") or "20").strip()
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(500, limit))

    adapter_id = str(request.query.get("adapter_id") or "").strip()
    include_last_raw = str(request.query.get("include_last") or "1").strip().lower()
    include_last = include_last_raw not in {"0", "false", "off", "no"}

    try:
        rows: List[Dict[str, Any]] = []
        if hasattr(learning_loop, "get_lora_eval_history"):
            rows = list(learning_loop.get_lora_eval_history(limit=limit, adapter_id=adapter_id))

        last_report: Dict[str, Any] = {}
        if include_last and hasattr(learning_loop, "get_stats"):
            stats = learning_loop.get_stats()
            if isinstance(stats, dict):
                from_stats = stats.get("lora_last_eval_report")
                if isinstance(from_stats, dict):
                    last_report = from_stats
                elif isinstance(stats.get("state"), dict):
                    last_report = dict(stats["state"].get("lora_last_eval_report") or {})

        payload = {
            "ok": True,
            "count": len(rows),
            "limit": limit,
            "adapter_id": adapter_id,
            "include_last": include_last,
            "rows": rows,
            "last_report": last_report,
        }
        payload = json.loads(json.dumps(payload, default=str))
        return web.json_response(payload)
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to fetch LoRA evaluation reports")
        return web.json_response({"error": "Internal server error."}, status=500)


async def learning_loop_lora_readiness(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    learning_loop = getattr(vera, "learning_loop", None)
    if not learning_loop:
        return web.json_response({"error": "Learning loop unavailable."}, status=503)

    try:
        payload: Dict[str, Any] = {}
        if hasattr(learning_loop, "get_lora_backend_readiness"):
            payload = learning_loop.get_lora_backend_readiness()
        elif hasattr(learning_loop, "get_stats"):
            payload = {
                "fallback": True,
                "stats": learning_loop.get_stats(),
            }
        safe_payload = json.loads(json.dumps(payload, default=str))
        return web.json_response(safe_payload)
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to fetch LoRA backend readiness")
        return web.json_response({"error": "Internal server error."}, status=500)


async def skills_list(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    learning_loop = getattr(vera, "learning_loop", None)
    if not learning_loop:
        return web.json_response({"error": "Learning loop unavailable."}, status=503)
    try:
        sort_by = request.query.get("sort", "trust_tier")
        trust_filter = request.query.get("trust", "")
        skills = learning_loop.list_skills(sort_by=sort_by, trust_filter=trust_filter)
        return web.json_response({
            "total": len(skills),
            "sort": sort_by,
            "trust_filter": trust_filter or "all",
            "skills": skills,
        })
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to list skills")
        return web.json_response({"error": "Internal server error."}, status=500)


async def innerlife_status(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    inner_life = getattr(vera, "inner_life", None)
    if not inner_life:
        return web.json_response({"error": "Inner life engine unavailable."}, status=503)
    limit_raw = (request.query.get("limit") or "10").strip()
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(50, limit))
    try:
        recent = [entry.to_dict() for entry in inner_life.get_recent_monologue(limit)]
        personality = inner_life.personality.to_dict() if getattr(inner_life, "personality", None) else {}
        stats = inner_life.get_statistics()
        autonomy = {}
        proactive = getattr(vera, "proactive_manager", None)
        if proactive and hasattr(proactive, "get_autonomy_status"):
            autonomy = proactive.get_autonomy_status()
        goals = []
        if hasattr(inner_life, "list_active_goals"):
            goals = inner_life.list_active_goals()

        proactive_status = {}
        cal_state_path = getattr(proactive, "_memory_dir", None) if proactive else None
        if cal_state_path:
            cal_state = safe_json_read(cal_state_path / "calendar_alerts_state.json", default={})
            proactive_status = {
                "calendar_last_poll": cal_state.get("last_poll_utc"),
                "calendar_alerts_today": len(cal_state.get("alerted_event_ids", [])),
                "calendar_enabled": os.getenv("VERA_CALENDAR_PROACTIVE", "1") == "1",
                "proactive_execution_enabled": os.getenv("VERA_PROACTIVE_EXECUTION", "1") == "1",
            }

        return web.json_response({
            "stats": stats,
            "personality": personality,
            "recent_thoughts": recent,
            "autonomy": autonomy,
            "goals": goals,
            "proactive": proactive_status,
        })
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to fetch inner life status")
        return web.json_response({"error": "Internal server error."}, status=500)


async def innerlife_goals_add(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    inner_life = getattr(vera, "inner_life", None)
    if not inner_life:
        return web.json_response({"error": "Inner life engine unavailable."}, status=503)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body."}, status=400)
    description = str(body.get("description") or "").strip()
    if not description:
        return web.json_response({"error": "description is required."}, status=400)
    category = str(body.get("category", "self_improvement"))
    priority = int(body.get("priority", 3))
    goal = inner_life.add_goal(description=description, category=category, priority=priority)
    if not goal:
        return web.json_response({"error": "At active goal capacity."}, status=409)
    return web.json_response({"goal": goal})


async def innerlife_reflect(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    inner_life = getattr(vera, "inner_life", None)
    if not inner_life:
        return web.json_response({"error": "Inner life engine unavailable."}, status=503)
    if not inner_life.config.enabled:
        return web.json_response({"error": "Inner life engine is disabled."}, status=400)
    payload: Dict[str, Any] = {}
    if request.can_read_body:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                payload = raw
        except Exception:
            payload = {}
    wait_for_completion = bool(payload.get("wait", False))
    timeout_seconds = float(payload.get("timeout_seconds", 0) or 0)
    timeout_seconds = max(1.0, min(timeout_seconds, 300.0)) if wait_for_completion else 0.0

    def _consume_reflection_task(task: "asyncio.Task[Any]") -> None:
        try:
            task.result()
        except Exception:
            logging.getLogger(__name__).exception("Background inner life reflection failed")

    try:
        if wait_for_completion:
            run_task: "asyncio.Task[Any]" = asyncio.create_task(
                vera._run_reflection_cycle(trigger="manual", force=True)
            )
            run_task.add_done_callback(_consume_reflection_task)
            result = (
                await asyncio.wait_for(asyncio.shield(run_task), timeout=timeout_seconds)
                if timeout_seconds
                else await run_task
            )
            result_data = result.to_dict() if hasattr(result, "to_dict") else {}
            return web.json_response({
                "scheduled": True,
                "completed": True,
                "result": result_data,
            })
        run_task = asyncio.create_task(vera._run_reflection_cycle(trigger="manual", force=True))
        run_task.add_done_callback(_consume_reflection_task)
        return web.json_response({"scheduled": True})
    except asyncio.TimeoutError:
        return web.json_response(
            {
                "scheduled": True,
                "completed": False,
                "in_progress": True,
                "timeout_seconds": timeout_seconds,
                "error": "reflection timed out; continuing in background",
            },
            status=202,
        )
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to schedule inner life reflection")
        return web.json_response({"error": "Internal server error."}, status=500)


async def innerlife_autonomy_cycle(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    proactive = getattr(vera, "proactive_manager", None)
    if not proactive:
        return web.json_response({"error": "Proactive manager unavailable."}, status=503)
    payload: Dict[str, Any] = {}
    if request.can_read_body:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                payload = raw
        except Exception:
            payload = {}

    trigger = str(payload.get("trigger") or "manual_api")
    force = bool(payload.get("force", False))
    wait_for_completion = bool(payload.get("wait", False))
    timeout_raw = payload.get("timeout_seconds", None)
    if wait_for_completion:
        if timeout_raw in (None, "", 0, 0.0):
            timeout_seconds = 30.0
        else:
            try:
                timeout_seconds = float(timeout_raw)
            except Exception:
                timeout_seconds = 30.0
        timeout_seconds = max(1.0, min(timeout_seconds, 300.0))
    else:
        timeout_seconds = 0.0

    try:
        scheduled = proactive.action_autonomy_cycle({"trigger": trigger, "force": force})
        response_payload: Dict[str, Any] = {
            "scheduled": bool(scheduled.get("scheduled")),
            "result": scheduled,
        }
        if wait_for_completion and response_payload["scheduled"]:
            cycle_future = getattr(proactive, "_autonomy_cycle_future", None)
            if cycle_future is not None:
                if asyncio.isfuture(cycle_future):
                    completed = await asyncio.wait_for(cycle_future, timeout=timeout_seconds) if timeout_seconds else await cycle_future
                else:
                    completed = await asyncio.wait_for(
                        asyncio.wrap_future(cycle_future),
                        timeout=timeout_seconds,
                    ) if timeout_seconds else await asyncio.wrap_future(cycle_future)
                response_payload["completed"] = True
                response_payload["cycle_result"] = completed
            else:
                response_payload["completed"] = False
                response_payload["cycle_result"] = {"reason": "no_cycle_future"}
        response_payload["autonomy"] = proactive.get_autonomy_status()
        return web.json_response(response_payload)
    except asyncio.TimeoutError:
        return web.json_response(
            {
                "scheduled": True,
                "completed": False,
                "in_progress": True,
                "timeout_seconds": timeout_seconds,
                "error": "autonomy cycle timed out; continuing in background",
            },
            status=202,
        )
    except Exception as exc:
        logging.getLogger(__name__).exception("Failed to schedule autonomy cycle")
        return web.json_response({"error": "Internal server error."}, status=500)


async def autonomy_action_run(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    proactive = getattr(vera, "proactive_manager", None)
    if not proactive:
        return web.json_response({"error": "Proactive manager unavailable."}, status=503)

    payload: Dict[str, Any] = {}
    if request.can_read_body:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                payload = raw
        except Exception:
            payload = {}

    action_type = str(payload.get("action_type") or "").strip()
    allowed_actions = {
        "check_tasks",
        "week1_due_check",
        "red_team_check",
        "reload_config",
    }
    if action_type not in allowed_actions:
        return web.json_response(
            {"error": "Unsupported autonomy action.", "allowed_actions": sorted(allowed_actions)},
            status=400,
        )

    handler = getattr(proactive, f"action_{action_type}", None)
    if not callable(handler):
        return web.json_response({"error": "Action handler unavailable."}, status=503)

    action_payload = payload.get("payload")
    if not isinstance(action_payload, dict):
        action_payload = {}

    try:
        result = handler(action_payload)
        return web.json_response({"ok": True, "action_type": action_type, "result": result})
    except Exception:
        logging.getLogger(__name__).exception("Failed to run autonomy action")
        return web.json_response({"error": "Internal server error."}, status=500)


async def autonomy_jobs(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    proactive = getattr(vera, "proactive_manager", None)
    runplane = getattr(proactive, "runplane", None) if proactive else None
    if not runplane:
        return web.json_response({"error": "Autonomy runplane unavailable."}, status=503)

    try:
        limit = int(str(request.query.get("limit", "200")).strip())
    except Exception:
        limit = 200
    limit = max(1, min(limit, 2000))
    state_filter = str(request.query.get("state", "") or "").strip().lower()
    if state_filter and state_filter not in {
        "planned",
        "due",
        "running",
        "delivered",
        "acked",
        "escalated",
        "closed",
        "failed",
        "dead_letter",
    }:
        return web.json_response({"error": "invalid state filter"}, status=400)

    rows = runplane.list_jobs(limit=limit, state_filter=state_filter)
    payload = {
        "count": len(rows),
        "limit": limit,
        "state_filter": state_filter or "all",
        "jobs": rows,
        "status": runplane.status_snapshot(),
    }
    return web.json_response(json.loads(json.dumps(payload, default=str)))


async def autonomy_runs(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    proactive = getattr(vera, "proactive_manager", None)
    runplane = getattr(proactive, "runplane", None) if proactive else None
    if not runplane:
        return web.json_response({"error": "Autonomy runplane unavailable."}, status=503)

    try:
        limit = int(str(request.query.get("limit", "200")).strip())
    except Exception:
        limit = 200
    limit = max(1, min(limit, 4000))
    job_id = str(request.query.get("job_id", "") or "").strip()
    status_filter = str(request.query.get("status", "") or "").strip().lower()
    if status_filter and status_filter not in {
        "planned",
        "due",
        "running",
        "delivered",
        "acked",
        "escalated",
        "closed",
        "failed",
        "dead_letter",
    }:
        return web.json_response({"error": "invalid status filter"}, status=400)

    rows = runplane.list_runs(limit=limit, job_id=job_id, status_filter=status_filter)
    payload = {
        "count": len(rows),
        "limit": limit,
        "job_id": job_id or "",
        "status_filter": status_filter or "all",
        "runs": rows,
        "status": runplane.status_snapshot(),
    }
    return web.json_response(json.loads(json.dumps(payload, default=str)))


async def autonomy_runs_mark(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    proactive = getattr(vera, "proactive_manager", None)
    runplane = getattr(proactive, "runplane", None) if proactive else None
    if not runplane:
        return web.json_response({"error": "Autonomy runplane unavailable."}, status=503)

    payload: Dict[str, Any] = {}
    if request.can_read_body:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                payload = raw
        except Exception:
            payload = {}

    run_id = str(payload.get("run_id") or "").strip()
    status = str(payload.get("status") or "").strip().lower()
    source = str(payload.get("source") or "api").strip()
    note = str(payload.get("note") or "").strip()
    if not run_id or not status:
        return web.json_response({"error": "run_id and status required"}, status=400)

    result = runplane.mark_run_status(
        run_id=run_id,
        status=status,
        source=source,
        note=note,
    )
    if not result.get("ok"):
        reason = str(result.get("reason") or "mark_failed")
        status_code = 404 if reason == "run_not_found" else 400
        return web.json_response({"ok": False, "error": reason, "result": result}, status=status_code)
    response_payload = {
        "ok": True,
        "result": result,
        "status": runplane.status_snapshot(),
        "slo": runplane.slo_snapshot(),
    }
    return web.json_response(json.loads(json.dumps(response_payload, default=str)))


async def autonomy_dead_letter(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    proactive = getattr(vera, "proactive_manager", None)
    runplane = getattr(proactive, "runplane", None) if proactive else None
    if not runplane:
        return web.json_response({"error": "Autonomy runplane unavailable."}, status=503)

    try:
        limit = int(str(request.query.get("limit", "200")).strip())
    except Exception:
        limit = 200
    limit = max(1, min(limit, 2000))
    rows = runplane.list_dead_letters(limit=limit)
    payload = {
        "count": len(rows),
        "limit": limit,
        "dead_letters": rows,
        "status": runplane.status_snapshot(),
    }
    return web.json_response(json.loads(json.dumps(payload, default=str)))


async def autonomy_dead_letter_replay(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    proactive = getattr(vera, "proactive_manager", None)
    runplane = getattr(proactive, "runplane", None) if proactive else None
    if not runplane:
        return web.json_response({"error": "Autonomy runplane unavailable."}, status=503)

    payload: Dict[str, Any] = {}
    if request.can_read_body:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                payload = raw
        except Exception:
            payload = {}
    run_id = str(payload.get("run_id") or "").strip()
    job_id = str(payload.get("job_id") or "").strip()
    trigger = str(payload.get("trigger") or "api_replay").strip() or "api_replay"
    if not run_id and not job_id:
        return web.json_response({"error": "run_id or job_id required"}, status=400)

    result = runplane.replay_dead_letter(run_id=run_id, job_id=job_id, trigger=trigger)
    if result.get("ok"):
        response_payload = {
            "ok": True,
            "result": result,
            "status": runplane.status_snapshot(),
            "slo": runplane.slo_snapshot(),
        }
        return web.json_response(json.loads(json.dumps(response_payload, default=str)))

    reason = str(result.get("reason") or "replay_failed")
    status_code = 404 if reason in {"dead_letter_not_found", "job_not_found"} else 400
    return web.json_response({"ok": False, "error": reason, "result": result}, status=status_code)


async def autonomy_slo(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    proactive = getattr(vera, "proactive_manager", None)
    runplane = getattr(proactive, "runplane", None) if proactive else None
    if not runplane:
        return web.json_response({"error": "Autonomy runplane unavailable."}, status=503)

    payload = {
        "slo": runplane.slo_snapshot(),
        "operator_baseline": runplane.operator_baseline_snapshot(),
        "status": runplane.status_snapshot(),
    }
    slo_windows = getattr(runplane, "slo_windows_snapshot", None)
    if callable(slo_windows):
        try:
            payload["windows"] = slo_windows()
        except Exception:
            logger.debug("Failed to compute autonomy SLO windows", exc_info=True)
    return web.json_response(json.loads(json.dumps(payload, default=str)))


async def improvement_archive_suggest(request: web.Request) -> web.Response:
    payload: Dict[str, Any] = {}
    if request.can_read_body:
        try:
            raw = await request.json()
            if isinstance(raw, dict):
                payload = raw
        except Exception:
            payload = {}

    archive_path = Path(str(payload.get("archive_path") or "vera_memory/improvement_archive.json"))
    if not archive_path.exists():
        return web.json_response(
            {
                "ok": False,
                "error": "improvement_archive_missing",
                "archive_path": str(archive_path),
            },
            status=404,
        )

    try:
        from observability.improvement_archive import suggest_improvement_entries

        result = suggest_improvement_entries(
            archive_path=archive_path,
            problem_signature=str(payload.get("problem_signature") or ""),
            failure_class=str(payload.get("failure_class") or ""),
            limit=max(0, int(payload.get("limit") or 3)),
        )
        return web.json_response({"ok": True, "result": result})
    except Exception as exc:
        logger.exception("improvement_archive_suggest failed")
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def browser_status(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    enabled = os.getenv("VERA_BROWSER", "0") == "1"
    bridge = getattr(vera, "_browser_bridge", None)
    available = bridge is not None
    launched = bool(bridge and getattr(bridge, "is_launched", False))
    native_errors = getattr(vera, "_native_tool_errors", {}) or {}
    error = native_errors.get("browser")
    return web.json_response({
        "enabled": enabled,
        "available": available,
        "launched": launched,
        "error": error,
    })


async def browser_launch(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    if os.getenv("VERA_BROWSER", "0") != "1":
        return web.json_response({"error": "Browser automation is disabled."}, status=400)
    bridge = getattr(vera, "_browser_bridge", None)
    if not bridge:
        return web.json_response({"error": "Browser tool unavailable."}, status=400)
    try:
        if not bridge.is_launched:
            await bridge.launch()
        return web.json_response({"ok": True, "launched": True})
    except Exception as exc:
        logger.error("Browser launch failed: %s", exc)
        return web.json_response({"error": "Internal server error."}, status=500)


async def browser_close(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    bridge = getattr(vera, "_browser_bridge", None)
    if not bridge:
        return web.json_response({"error": "Browser tool unavailable."}, status=400)
    try:
        if bridge.is_launched:
            await bridge.close()
        return web.json_response({"ok": True, "launched": False})
    except Exception as exc:
        logger.error("Browser close failed: %s", exc)
        return web.json_response({"error": "Internal server error."}, status=500)


async def self_improvement_budget_get(request: web.Request) -> web.Response:
    config, source = load_budget_config()
    state = load_budget_state()
    return web.json_response({
        "config": budget_config_to_dict(config),
        "state": state,
        "config_source": source,
        "config_path": str(DEFAULT_CONFIG_PATH),
        "state_path": str(DEFAULT_BUDGET_PATH),
    })


_budget_update_lock = asyncio.Lock()


async def self_improvement_budget_update(request: web.Request) -> web.Response:
    payload = await request.json()
    config_payload = payload.get("config", payload) if isinstance(payload, dict) else {}
    reset_usage = bool(payload.get("reset_usage", False)) if isinstance(payload, dict) else False

    async with _budget_update_lock:
        config, _ = load_budget_config()
        try:
            updated = _apply_budget_overrides(config, config_payload or {})
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        atomic_json_write(DEFAULT_CONFIG_PATH, budget_config_to_dict(updated))

        if reset_usage:
            state = reset_budget_state()
        else:
            state = load_budget_state()

    return web.json_response({
        "config": budget_config_to_dict(updated),
        "state": state,
        "config_source": "file",
        "config_path": str(DEFAULT_CONFIG_PATH),
        "state_path": str(DEFAULT_BUDGET_PATH),
    })


async def self_improvement_status(request: web.Request) -> web.Response:
    runner = request.app["self_improvement_runner"]
    return web.json_response(runner.get_status())


async def self_improvement_logs(request: web.Request) -> web.Response:
    runner = request.app["self_improvement_runner"]
    try:
        lines = int(request.query.get("lines", "200"))
    except ValueError:
        lines = 200
    return web.json_response({"lines": lines, "log": runner.tail_log(lines)})


async def self_improvement_run(request: web.Request) -> web.Response:
    runner = request.app["self_improvement_runner"]
    vera = request.app.get("vera")
    payload = await request.json()
    action = str(payload.get("action", "")).strip()
    params = payload.get("params") if isinstance(payload, dict) else None
    if not action:
        return web.json_response({"error": "Missing action."}, status=400)
    result = runner.start(action, params=params or {}, vera=vera)
    if not result.get("ok"):
        return web.json_response(result, status=409)
    return web.json_response(result)


async def self_improvement_simulate(request: web.Request) -> web.Response:
    payload = await request.json()
    patch_ops = payload.get("patch") if isinstance(payload, dict) else None
    include_config = bool(payload.get("include_config", False)) if isinstance(payload, dict) else False
    if not isinstance(patch_ops, list):
        return web.json_response({"error": "Patch must be a JSON array."}, status=400)

    config, validation = load_genome_config(DEFAULT_GENOME_PATH)
    if not validation.valid:
        return web.json_response({"error": "Genome config invalid.", "details": validation.errors}, status=400)

    patched, patch_validation = apply_genome_patch(config, patch_ops)
    response = {
        "valid": patch_validation.valid,
        "errors": patch_validation.errors,
    }
    if include_config and patch_validation.valid:
        response["patched_config"] = patched
    return web.json_response(response)


async def _acquire_mcp_call_capacity(
    app: web.Application,
    server_name: str,
    timeout: float,
) -> Tuple[Optional[asyncio.Semaphore], Optional[asyncio.Semaphore]]:
    global_sem = app.get("mcp_call_global_semaphore")
    server_map = app.get("mcp_call_server_semaphores") or {}
    server_sem = server_map.get(server_name)
    queue_timeout_default = float(app.get("mcp_call_queue_timeout_seconds", 3.0) or 3.0)
    queue_timeout = max(0.1, min(timeout, queue_timeout_default))
    acquired_global = False
    acquired_server = False

    try:
        if global_sem is not None:
            await asyncio.wait_for(global_sem.acquire(), timeout=queue_timeout)
            acquired_global = True
        if server_sem is not None:
            await asyncio.wait_for(server_sem.acquire(), timeout=queue_timeout)
            acquired_server = True
        return global_sem, server_sem
    except Exception:
        if acquired_server and server_sem is not None:
            server_sem.release()
        if acquired_global and global_sem is not None:
            global_sem.release()
        raise


def _release_mcp_call_capacity(
    global_sem: Optional[asyncio.Semaphore],
    server_sem: Optional[asyncio.Semaphore],
) -> None:
    if server_sem is not None:
        server_sem.release()
    if global_sem is not None:
        global_sem.release()


def _mcp_server_not_running_error(vera, server_name: str) -> str:
    try:
        status = vera.mcp.get_status()
    except Exception:
        return ""
    if not isinstance(status, dict):
        return ""
    servers = status.get("servers")
    if not isinstance(servers, dict):
        return ""
    info = servers.get(server_name)
    if not isinstance(info, dict):
        return ""
    running = info.get("running")
    effective_health = str(info.get("effective_health") or "").strip().lower()
    health = str(info.get("health") or "").strip().lower()
    if running is False or effective_health in {"stopped", "unhealthy"} or health == "stopped":
        return f"MCP server {server_name} not running"
    return ""


async def tools_call(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    payload = await request.json()

    tool_name = payload.get("name")
    if not tool_name:
        return web.json_response({"error": "Tool name is required."}, status=400)

    args = payload.get("arguments")
    if args is None:
        args = payload.get("args")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return web.json_response({"error": "Tool arguments must be an object."}, status=400)

    if tool_name in vera._native_tool_handlers:
        handler = vera._native_tool_handlers[tool_name]
        try:
            result = await handler(tool_name, args)
        except Exception as exc:
            logger.error("Native tool call %s failed: %s", tool_name, exc)
            return web.json_response({"error": "Internal server error."}, status=500)
        return web.json_response({"result": result, "tool": tool_name, "type": "native"})

    server_name = payload.get("server")
    if not server_name:
        return web.json_response({"error": "Server name is required for MCP tools."}, status=400)

    timeout_value = payload.get("timeout")
    if timeout_value is None:
        timeout = _default_mcp_tool_timeout_seconds(server_name, str(tool_name))
    else:
        try:
            timeout = float(timeout_value)
        except (TypeError, ValueError):
            return web.json_response({"error": "timeout must be a number."}, status=400)
    if timeout <= 0:
        return web.json_response({"error": "timeout must be > 0."}, status=400)

    capacity_global: Optional[asyncio.Semaphore] = None
    capacity_server: Optional[asyncio.Semaphore] = None
    try:
        capacity_global, capacity_server = await _acquire_mcp_call_capacity(
            request.app,
            server_name,
            timeout,
        )
    except asyncio.TimeoutError:
        unavailable_error = _mcp_server_not_running_error(vera, server_name)
        if unavailable_error:
            return web.json_response(
                {
                    "error": unavailable_error,
                    "server": server_name,
                    "tool": tool_name,
                },
                status=502,
            )
        return web.json_response(
            {
                "error": "Tool server is busy; please retry.",
                "server": server_name,
                "tool": tool_name,
            },
            status=429,
        )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(vera.mcp.call_tool, server_name, tool_name, args, timeout),
            timeout=timeout + 1.0,
        )
    except asyncio.TimeoutError:
        return web.json_response(
            {"error": f"Tool call timed out after {timeout:.1f}s", "server": server_name, "tool": tool_name},
            status=504,
        )
    except Exception as exc:
        logger.error("MCP tool call %s/%s failed: %s", server_name, tool_name, exc)
        return web.json_response(
            {"error": _safe_mcp_exception_text(exc), "server": server_name, "tool": tool_name},
            status=502,
        )
    finally:
        _release_mcp_call_capacity(capacity_global, capacity_server)

    mcp_error = _extract_mcp_error_text(result)
    if mcp_error:
        logger.warning("MCP tool call %s/%s returned error payload: %s", server_name, tool_name, mcp_error)
        return web.json_response(
            {"error": mcp_error, "server": server_name, "tool": tool_name},
            status=502,
        )

    return web.json_response({"result": result, "tool": tool_name, "server": server_name, "type": "mcp"})


def _default_mcp_tool_timeout_seconds(server_name: str, tool_name: str) -> float:
    server = str(server_name or "").strip().lower()
    tool = str(tool_name or "").strip().lower()
    if server == "call-me" and tool == "initiate_call":
        return 75.0
    return 20.0


def _safe_mcp_exception_text(exc: Exception) -> str:
    text = str(exc or "").strip()
    if not text:
        return "MCP tool execution failed."
    return text


def _extract_mcp_error_text(result: Any) -> str:
    if not isinstance(result, dict) or not result.get("isError"):
        return ""
    content = result.get("content")
    if isinstance(content, list):
        for entry in content:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text") or "").strip()
            if text:
                return text
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("error", "message", "detail", "result", "text"):
            value = structured.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "MCP tool returned error payload."


async def _call_mcp_tool(
    vera,
    server: str,
    tool: str,
    args: Dict[str, Any],
    timeout: float,
) -> Tuple[bool, str]:
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(vera.mcp.call_tool, server, tool, args, timeout),
            timeout=timeout + 1.0,
        )
        mcp_error = _extract_mcp_error_text(result)
        if mcp_error:
            return False, mcp_error
        return True, ""
    except asyncio.TimeoutError:
        return False, "timed out"
    except Exception as exc:
        return False, str(exc)


async def tools_verify(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    payload: Dict[str, Any] = {}
    if request.can_read_body:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

    timeout = float(payload.get("timeout", 30))
    memvid_timeout = float(payload.get("memvid_timeout", 120))

    root_dir = Path(__file__).resolve().parents[2]
    tmp_dir = root_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    expected_servers = [
        "filesystem",
        "memory",
        "time",
        "sequential-thinking",
        "wikipedia",
        "pdf-reader",
        "memvid",
        "searxng",
        "brave-search",
        "github",
        "google-workspace",
    ]

    for name in expected_servers:
        await asyncio.to_thread(vera.mcp.start_server, name)

    tools_map = vera.mcp.get_available_tools()

    results: List[Dict[str, str]] = []
    summary = {"ok": 0, "skipped": 0, "failed": 0}

    def record(status: str, server: str, detail: str = "") -> None:
        results.append({"server": server, "status": status, "detail": detail})
        if status == "ok":
            summary["ok"] += 1
        elif status == "skip":
            summary["skipped"] += 1
        else:
            summary["failed"] += 1

    def pick_tool(server: str, candidates: List[str]) -> str:
        available = tools_map.get(server, [])
        for candidate in candidates:
            if candidate in available:
                return candidate
        return ""

    # filesystem
    fs_tool = pick_tool("filesystem", ["list_allowed_directories", "list_directory"])
    if fs_tool:
        fs_args = {} if fs_tool == "list_allowed_directories" else {"path": str(root_dir)}
        ok, detail = await _call_mcp_tool(vera, "filesystem", fs_tool, fs_args, timeout)
        record("ok" if ok else "fail", "filesystem", detail)
    else:
        record("skip", "filesystem", "tool not available")

    # memory
    if "read_graph" in tools_map.get("memory", []):
        ok, detail = await _call_mcp_tool(vera, "memory", "read_graph", {}, timeout)
        record("ok" if ok else "fail", "memory", detail)
    else:
        record("skip", "memory", "tool not available")

    # time
    if "time" in tools_map.get("time", []):
        ok, detail = await _call_mcp_tool(
            vera,
            "time",
            "time",
            {"timezone": "UTC", "format": "iso"},
            timeout,
        )
        record("ok" if ok else "fail", "time", detail)
    else:
        record("skip", "time", "tool not available")

    # sequential-thinking
    if "sequentialthinking" in tools_map.get("sequential-thinking", []):
        ok, detail = await _call_mcp_tool(
            vera,
            "sequential-thinking",
            "sequentialthinking",
            {
                "thought": "diagnostic test",
                "nextThoughtNeeded": False,
                "thoughtNumber": 1,
                "totalThoughts": 1,
            },
            timeout,
        )
        record("ok" if ok else "fail", "sequential-thinking", detail)
    else:
        record("skip", "sequential-thinking", "tool not available")

    # wikipedia
    if "wikipedia_search" in tools_map.get("wikipedia", []):
        ok, detail = await _call_mcp_tool(
            vera,
            "wikipedia",
            "wikipedia_search",
            {"query": "Vera AI", "limit": 1},
            timeout,
        )
        record("ok" if ok else "fail", "wikipedia", detail)
    else:
        record("skip", "wikipedia", "tool not available")

    # pdf-reader
    pdf_path = root_dir / "research" / "Skeleton_of_Thought.pdf"
    if "get_pdf_info" in tools_map.get("pdf-reader", []) and pdf_path.exists():
        ok, detail = await _call_mcp_tool(
            vera,
            "pdf-reader",
            "get_pdf_info",
            {"file_path": str(pdf_path)},
            timeout,
        )
        record("ok" if ok else "fail", "pdf-reader", detail)
    else:
        record("skip", "pdf-reader", "tool not available")

    # memvid
    memvid_tools = tools_map.get("memvid", [])
    if "memvid_encode_text" in memvid_tools and "memvid_search" in memvid_tools:
        video_path = tmp_dir / "vera_memvid_verify.mp4"
        index_path = tmp_dir / "vera_memvid_verify.index"
        ok, detail = await _call_mcp_tool(
            vera,
            "memvid",
            "memvid_encode_text",
            {
                "text": "diagnostic memory test",
                "output_video": str(video_path),
                "output_index": str(index_path),
                "chunk_size": 200,
                "overlap": 20,
            },
            memvid_timeout,
        )
        if ok:
            ok, detail = await _call_mcp_tool(
                vera,
                "memvid",
                "memvid_search",
                {
                    "query": "diagnostic memory test",
                    "video_path": str(video_path),
                    "index_path": str(index_path),
                    "top_k": 3,
                },
                memvid_timeout,
            )
        record("ok" if ok else "fail", "memvid", detail)
    else:
        record("skip", "memvid", "tool not available")

    # searxng
    searx_tool = pick_tool("searxng", ["searxng_search"])
    if searx_tool:
        ok, detail = await _call_mcp_tool(
            vera,
            "searxng",
            searx_tool,
            {"query": "VERA AI"},
            timeout,
        )
        record("ok" if ok else "fail", "searxng", detail)
    else:
        record("skip", "searxng", "tool not available")

    # brave-search
    brave_tool = pick_tool("brave-search", ["brave_web_search", "brave_local_search"])
    if brave_tool:
        ok, detail = await _call_mcp_tool(
            vera,
            "brave-search",
            brave_tool,
            {"query": "VERA AI", "count": 1},
            timeout,
        )
        if not ok and _is_auth_error(detail):
            record("skip", "brave-search", "credentials required")
        else:
            record("ok" if ok else "fail", "brave-search", detail)
    else:
        record("skip", "brave-search", "tool not available")

    # github
    if "search_repositories" in tools_map.get("github", []):
        ok, detail = await _call_mcp_tool(
            vera,
            "github",
            "search_repositories",
            {"query": "vera", "per_page": 1},
            timeout,
        )
        if not ok and _is_auth_error(detail):
            record("skip", "github", "credentials required")
        else:
            record("ok" if ok else "fail", "github", detail)
    else:
        record("skip", "github", "tool not available")

    # google-workspace
    if "list_calendars" in tools_map.get("google-workspace", []):
        ok, detail = await _call_mcp_tool(
            vera,
            "google-workspace",
            "list_calendars",
            {},
            timeout,
        )
        if not ok and _is_auth_error(detail):
            record("skip", "google-workspace", "credentials required")
        else:
            record("ok" if ok else "fail", "google-workspace", detail)
    else:
        record("skip", "google-workspace", "tool not available")

    return web.json_response({"summary": summary, "results": results})


async def voice_status(request: web.Request) -> web.Response:
    enabled = _voice_enabled()
    voice_state = request.app.get("voice_state") or {}
    default_voice = os.getenv("VERA_VOICE_DEFAULT", "eve").strip().lower() or "eve"
    status: Dict[str, Any] = {
        "enabled": enabled,
        "api_key_present": bool(os.getenv("XAI_API_KEY") or os.getenv("API_KEY")),
        "selected_voice": voice_state.get("last_voice", default_voice),
        "session_active": bool(voice_state.get("active", False)),
    }
    if not enabled:
        status["message"] = "Voice disabled (VERA_VOICE=0)."
        return web.json_response(status)

    try:
        from voice import get_available_backend
        from voice.session import WEBSOCKETS_AVAILABLE
        from voice.session import Voice

        backend = get_available_backend()
        status["backend"] = backend.value
        status["backend_ready"] = backend.value != "none"
        status["websockets_available"] = bool(WEBSOCKETS_AVAILABLE)
        status["available_voices"] = [voice.value for voice in Voice]
    except Exception as exc:
        status["backend_ready"] = False
        status["backend_error"] = str(exc)

    return web.json_response(status)

def _pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2
) -> bytes:
    """Wrap PCM data in a WAV container."""
    data_size = len(pcm_data)
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    bits_per_sample = sample_width * 8
    header = (
        b"RIFF"
        + (36 + data_size).to_bytes(4, "little")
        + b"WAVE"
        + b"fmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + channels.to_bytes(2, "little")
        + sample_rate.to_bytes(4, "little")
        + byte_rate.to_bytes(4, "little")
        + block_align.to_bytes(2, "little")
        + bits_per_sample.to_bytes(2, "little")
        + b"data"
        + data_size.to_bytes(4, "little")
    )
    return header + pcm_data


async def voice_test(request: web.Request) -> web.Response:
    if not _voice_enabled():
        return web.json_response(
            {"ok": False, "error": "Voice disabled (VERA_VOICE=0)."},
            status=400,
        )

    try:
        from voice import VoiceSessionManager, SessionConfig
        from voice.session import AudioFormat, Voice

        payload = {}
        if request.can_read_body:
            try:
                payload = await request.json()
            except Exception:
                payload = {}

        voice_name = payload.get("voice") or os.getenv("VERA_VOICE_DEFAULT", "eve")
        voice_name = str(voice_name).strip().lower()
        include_audio = bool(payload.get("include_audio", False))

        try:
            voice = Voice(voice_name)
        except Exception:
            voice = Voice.ARA

        manager = VoiceSessionManager()
        audio_buffer = bytearray()
        audio_event = asyncio.Event()

        def _capture_audio(chunk: bytes) -> None:
            if audio_event.is_set():
                return
            audio_buffer.extend(chunk)
            if len(audio_buffer) >= 48000:  # ~1s at 24kHz mono 16-bit
                audio_event.set()

        manager.on_audio(_capture_audio)
        output_format = AudioFormat.PCM_24K
        session_id = await manager.connect(SessionConfig(
            voice=voice,
            output_audio_format=output_format,
        ))

        if include_audio:
            await manager.send_text("This is a voice diagnostics test.")
            try:
                await asyncio.wait_for(audio_event.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                logger.debug("Suppressed Exception in server")
                pass

        await manager.disconnect()

        response_payload = {"ok": True, "session_id": session_id, "voice": voice.value}
        if include_audio and audio_buffer:
            wav_bytes = _pcm_to_wav(bytes(audio_buffer), sample_rate=24000)
            response_payload["audio_b64"] = base64.b64encode(wav_bytes).decode("ascii")
            response_payload["audio_format"] = "audio/wav"
        return web.json_response(response_payload)
    except Exception as exc:
        logger.error("Voice diagnostics failed: %s", exc)
        return web.json_response({"ok": False, "error": "Internal server error."}, status=500)


async def voice_ws_handler(request: web.Request) -> web.WebSocketResponse:
    vera = request.app["vera"]
    voice_state = request.app.setdefault("voice_state", {"active": False, "last_voice": "eve"})
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    session = None
    tool_bridge = None
    state = "idle"
    pending_response = False
    assistant_text_buffer = ""
    assistant_text_last = ""
    assistant_text_seen = False
    assistant_text_source = ""
    speech_timeout_task = None
    speech_active = False
    no_speech_task = None
    last_audio_at = 0.0
    max_speech_raw = os.getenv("VERA_VOICE_MAX_SPEECH_SECONDS", "12").strip()
    try:
        max_speech_seconds = float(max_speech_raw)
    except ValueError:
        max_speech_seconds = 12.0
    vad_threshold_raw = os.getenv("VERA_VOICE_VAD_THRESHOLD", "").strip()
    vad_prefix_raw = os.getenv("VERA_VOICE_VAD_PREFIX_MS", "").strip()
    vad_silence_raw = os.getenv("VERA_VOICE_VAD_SILENCE_MS", "").strip()
    try:
        vad_threshold = float(vad_threshold_raw) if vad_threshold_raw else 0.5
    except ValueError:
        vad_threshold = 0.5
    try:
        vad_prefix_ms = int(vad_prefix_raw) if vad_prefix_raw else 300
    except ValueError:
        vad_prefix_ms = 300
    try:
        vad_silence_ms = int(vad_silence_raw) if vad_silence_raw else 500
    except ValueError:
        vad_silence_ms = 500
    no_speech_raw = os.getenv("VERA_VOICE_NO_SPEECH_SECONDS", "2.5").strip()
    try:
        no_speech_seconds = float(no_speech_raw)
    except ValueError:
        no_speech_seconds = 2.5

    async def send_state(value: str) -> None:
        nonlocal state
        if state == value or ws.closed:
            return
        state = value
        await ws.send_json({"type": "state", "state": value})

    async def _speech_timeout_guard() -> None:
        nonlocal speech_timeout_task, speech_active
        if max_speech_seconds <= 0:
            return
        try:
            await asyncio.sleep(max_speech_seconds)
        except asyncio.CancelledError:
            return
        if ws.closed or not session or pending_response or not speech_active:
            return
        logger.warning("Voice VAD timeout hit; forcing response after %.1fs", max_speech_seconds)
        try:
            await session.commit_audio()
        except Exception:
            logger.debug("Suppressed Exception in server")
            pass
        await request_response()
        speech_active = False
        speech_timeout_task = None

    async def _no_speech_guard(started_at: float) -> None:
        nonlocal no_speech_task
        if no_speech_seconds <= 0:
            return
        try:
            await asyncio.sleep(no_speech_seconds)
        except asyncio.CancelledError:
            return
        if ws.closed or not session or pending_response or speech_active:
            return
        if time.time() - started_at < no_speech_seconds:
            return
        logger.warning("Voice VAD did not trigger; forcing response after %.1fs", no_speech_seconds)
        try:
            await session.commit_audio()
        except Exception:
            logger.debug("Suppressed Exception in server")
            pass
        await request_response()
        no_speech_task = None

    def send_audio(chunk: bytes) -> None:
        if ws.closed:
            return
        asyncio.create_task(ws.send_bytes(chunk))

    async def handle_tool_call(event: Dict[str, Any]) -> Any:
        if not tool_bridge:
            return {"error": "Tool bridge unavailable"}
        function_call = event.get("function_call", {})
        name = function_call.get("name", "")
        arguments = function_call.get("arguments", "{}")
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            args = {}
        result = await tool_bridge.execute_tool(name, args)
        await ws.send_json({"type": "tool_result", "name": name, "result": result})
        return result

    async def handle_user_transcript(event: Dict[str, Any]) -> None:
        transcript = event.get("transcript", "")
        transcript = _normalize_voice_transcript(transcript)
        if transcript and not ws.closed:
            await ws.send_json({"type": "transcript", "role": "user", "text": transcript})

    def _parse_pcm_rate(format_value: str) -> int:
        match = re.search(r"rate=(\d+)", format_value or "")
        return int(match.group(1)) if match else 16000

    def _normalize_voice_transcript(text: str) -> str:
        if not text or "grok" not in text.lower():
            return text
        patterns = (
            r"^(\s*(?:hey|hi|hello|yo|sup|good morning|good afternoon|good evening)\s*,?\s*)grok\b",
            r"^(\s*)grok\s*,",
            r"^(\s*)grok\s+(?=(?:what|who|when|where|why|how|can|could|would|will|shall|do|did|does|is|are|please)\b)",
        )
        updated = text
        for pattern in patterns:
            updated = re.sub(pattern, r"\1Vera", updated, flags=re.IGNORECASE)
        return updated

    async def handle_response_done(event: Dict[str, Any]) -> None:
        nonlocal pending_response, assistant_text_last, assistant_text_seen, assistant_text_buffer, assistant_text_source
        pending_response = False
        sent_text = False

        if assistant_text_seen and assistant_text_buffer and not ws.closed:
            combined = assistant_text_buffer.strip()
            if combined:
                await ws.send_json({"type": "assistant_final", "text": combined})
                sent_text = True

        if not sent_text:
            response = event.get("response", {})
            for output in response.get("output", []):
                if output.get("type") != "message":
                    continue
                for content in output.get("content", []):
                    if content.get("type") in {"text", "output_text"}:
                        text = content.get("text", "")
                        if text and not ws.closed:
                            await ws.send_json({"type": "assistant_final", "text": text})
                            sent_text = True
        assistant_text_buffer = ""
        assistant_text_last = ""
        assistant_text_seen = False
        assistant_text_source = ""
        await send_state("listening")

    def handle_assistant_text(text: str) -> None:
        nonlocal assistant_text_last, assistant_text_seen, assistant_text_buffer
        if not text:
            return
        assistant_text_seen = True
        if assistant_text_last == text:
            return

        current = assistant_text_buffer
        incoming = text

        if not current:
            assistant_text_buffer = incoming
            assistant_text_last = incoming
            return

        if incoming.startswith(current):
            assistant_text_buffer = incoming
            assistant_text_last = incoming
            return

        if current.startswith(incoming) or incoming in current:
            assistant_text_last = incoming
            return

        max_overlap = 0
        max_len = min(len(current), len(incoming))
        for i in range(1, max_len + 1):
            if current[-i:] == incoming[:i]:
                max_overlap = i

        assistant_text_buffer = current + incoming[max_overlap:]
        assistant_text_last = incoming

    async def send_assistant_delta() -> None:
        if ws.closed:
            return
        text = assistant_text_buffer.strip()
        if text:
            await ws.send_json({"type": "assistant_delta", "text": text})

    def handle_assistant_text_event(event: Dict[str, Any], source: str) -> None:
        nonlocal assistant_text_source
        text = event.get("delta") or event.get("text") or event.get("transcript", "")
        if not text:
            return
        if source == "text":
            if assistant_text_source != "text":
                assistant_text_source = "text"
        else:
            if assistant_text_source == "text":
                return
            if not assistant_text_source:
                assistant_text_source = "audio"
        handle_assistant_text(text)
        asyncio.create_task(send_assistant_delta())

    async def request_response(_event: Optional[Dict[str, Any]] = None) -> None:
        nonlocal pending_response
        if not session or pending_response:
            return
        pending_response = True
        try:
            await session.request_response(modalities=["text", "audio"])
            await send_state("processing")
        except Exception as exc:
            pending_response = False
            if not ws.closed:
                await ws.send_json({"type": "error", "message": str(exc)})

    async def handle_speech_started(_event: Optional[Dict[str, Any]] = None) -> None:
        nonlocal speech_timeout_task, speech_active
        speech_active = True
        if no_speech_task:
            no_speech_task.cancel()
            no_speech_task = None
        if speech_timeout_task:
            speech_timeout_task.cancel()
        if max_speech_seconds > 0:
            speech_timeout_task = asyncio.create_task(_speech_timeout_guard())
        await send_state("listening")

    async def handle_speech_stopped(_event: Optional[Dict[str, Any]] = None) -> None:
        nonlocal speech_timeout_task, speech_active, no_speech_task
        speech_active = False
        if speech_timeout_task:
            speech_timeout_task.cancel()
            speech_timeout_task = None
        if no_speech_task:
            no_speech_task.cancel()
            no_speech_task = None
        await request_response()

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "Invalid JSON"})
                    continue

                msg_type = payload.get("type")
                if msg_type == "start":
                    if session:
                        await ws.send_json({"type": "error", "message": "Voice session already active"})
                        continue
                    voice_name = payload.get("voice") or os.getenv("VERA_VOICE_DEFAULT", "eve")
                    voice_name = str(voice_name).strip().lower()
                    try:
                        from voice.session import (
                            AudioFormat,
                            SessionConfig,
                            TurnDetectionMode,
                            Voice,
                            VoiceSessionManager,
                        )
                        from voice.tools import VoiceToolBridge

                        try:
                            voice = Voice(voice_name)
                        except Exception:
                            voice = Voice.ARA

                        tool_bridge = VoiceToolBridge(vera)
                        instructions = (
                            "You are VERA, a calm, precise assistant with dry British wit, never cruel. "
                            "You can call tools (Gmail, Calendar, Drive, web, files) when helpful. "
                            "Never claim you lack tools if they are available. "
                            "For email, always confirm recipient, subject, and body before sending; "
                            "if spoken input is ambiguous, ask the user to spell the address. "
                            "Keep responses concise and conversational."
                        )
                        session = VoiceSessionManager()
                        session.on_audio(send_audio)
                        session.on_tool_call(handle_tool_call)
                        session.on(
                            "response.output_audio_transcript.delta",
                            lambda event: handle_assistant_text_event(event, "audio"),
                        )
                        session.on(
                            "response.text.delta",
                            lambda event: handle_assistant_text_event(event, "text"),
                        )
                        session.on(
                            "response.output_text.delta",
                            lambda event: handle_assistant_text_event(event, "text"),
                        )
                        session.on("conversation.item.input_audio_transcription.completed", handle_user_transcript)
                        session.on("response.done", handle_response_done)
                        session.on("input_audio_buffer.speech_started", handle_speech_started)
                        session.on("input_audio_buffer.speech_stopped", handle_speech_stopped)
                        session.on("response.audio.delta", lambda _: asyncio.create_task(send_state("speaking")))
                        session.on("response.output_audio.delta", lambda _: asyncio.create_task(send_state("speaking")))

                        output_format = AudioFormat.PCM_24K
                        session_id = await session.connect(SessionConfig(
                            voice=voice,
                            instructions=instructions,
                            turn_detection=TurnDetectionMode.SERVER_VAD,
                            vad_threshold=vad_threshold,
                            vad_prefix_padding_ms=vad_prefix_ms,
                            vad_silence_duration_ms=vad_silence_ms,
                            tools=tool_bridge.tools,
                            output_audio_format=output_format,
                        ))
                        voice_state["active"] = True
                        voice_state["last_voice"] = voice.value
                        pending_response = False
                        assistant_text_buffer = ""
                        assistant_text_last = ""
                        assistant_text_seen = False
                        assistant_text_source = ""
                        await ws.send_json({
                            "type": "started",
                            "session_id": session_id,
                            "voice": voice.value,
                            "sample_rate": _parse_pcm_rate(output_format.value),
                        })
                        await send_state("listening")
                    except Exception as exc:
                        session = None
                        tool_bridge = None
                        await ws.send_json({"type": "error", "message": str(exc)})
                    continue

                if msg_type == "stop":
                    if session:
                        await session.disconnect()
                        session = None
                        tool_bridge = None
                    voice_state["active"] = False
                    pending_response = False
                    speech_active = False
                    if speech_timeout_task:
                        speech_timeout_task.cancel()
                        speech_timeout_task = None
                    assistant_text_buffer = ""
                    assistant_text_last = ""
                    assistant_text_seen = False
                    assistant_text_source = ""
                    await send_state("idle")
                    await ws.send_json({"type": "stopped"})
                    continue

                if msg_type == "text":
                    if not session:
                        await ws.send_json({"type": "error", "message": "Voice session not active"})
                        continue
                    text = payload.get("text", "")
                    if text:
                        await session.send_text(text)
                        await send_state("processing")
                    continue

                if msg_type == "commit":
                    if not session:
                        await ws.send_json({"type": "error", "message": "Voice session not active"})
                        continue
                    await session.commit_audio()
                    await request_response()
                    continue

                await ws.send_json({"type": "error", "message": "Unknown voice command"})

            elif msg.type == web.WSMsgType.BINARY:
                if not session:
                    continue
                last_audio_at = time.time()
                if not speech_active and no_speech_seconds > 0:
                    if no_speech_task:
                        no_speech_task.cancel()
                    no_speech_task = asyncio.create_task(_no_speech_guard(last_audio_at))
                await session.send_audio(msg.data)

    finally:
        if speech_timeout_task:
            speech_timeout_task.cancel()
        if no_speech_task:
            no_speech_task.cancel()
        if session:
            try:
                await session.disconnect()
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass
        voice_state["active"] = False

    return ws


async def set_keys(request: web.Request) -> web.Response:
    vera = request.app["vera"]
    payload = await request.json()
    raw_keys = payload.get("keys", {})
    restart = bool(payload.get("restart", False))

    keys: Dict[str, str] = {}
    for key, value in (raw_keys or {}).items():
        if not value:
            continue
        if isinstance(value, str):
            cleaned = value.strip()
        else:
            cleaned = str(value).strip()
        if cleaned:
            keys[str(key)] = cleaned

    env_updates, persisted = _persist_tool_keys(keys)

    updated = []
    for key, value in {**keys, **env_updates}.items():
        if not value:
            continue
        os.environ[key] = value
        if key not in updated:
            updated.append(key)

    vera.mcp.reload_configs()

    if restart and updated:
        await asyncio.to_thread(vera.mcp.start_all)

    return web.json_response({"updated": updated, "persisted": persisted})


# === Right-Rail Drawer Endpoints ===


async def api_ping(request: web.Request) -> web.Response:
    """Simple connection test — UI measures round-trip latency client-side."""
    vera = request.app.get("vera")
    bridge = getattr(vera, "_llm_bridge", None) if vera else None
    model = getattr(bridge, "model", None) or os.getenv("VERA_MODEL", "grok-4.20-experimental-beta-0304-reasoning")
    return web.json_response({
        "pong": True,
        "model": model,
        "timestamp": datetime.now().isoformat(),
    })


async def session_stats(request: web.Request) -> web.Response:
    """Session metrics for the System Diagnostics drawer."""
    vera = request.app.get("vera")
    if not vera:
        return web.json_response({"error": "VERA unavailable"}, status=503)
    store = getattr(vera, "session_store", None)
    bridge = getattr(vera, "_llm_bridge", None)
    # Aggregate across all active sessions
    input_tokens = 0
    output_tokens = 0
    message_count = 0
    if store:
        for entry in getattr(store, "_sessions", {}).values():
            input_tokens += getattr(entry, "input_tokens", 0)
            output_tokens += getattr(entry, "output_tokens", 0)
            message_count += getattr(entry, "message_count", 0)
    total_tokens = input_tokens + output_tokens
    tool_calls = len(getattr(bridge, "tool_execution_history", [])) if bridge else 0
    return web.json_response({
        "message_count": message_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "tool_calls": tool_calls,
        "estimated_cost": 0,
    })


async def api_errors(request: web.Request) -> web.Response:
    """Error log for the System Diagnostics drawer."""
    vera = request.app.get("vera")
    if not vera:
        return web.json_response([], content_type="application/json")
    errors = []
    # Health monitor errors
    monitor = getattr(vera, "health_monitor", None)
    if monitor:
        for err in getattr(monitor, "errors", []):
            errors.append({
                "timestamp": err.get("timestamp", ""),
                "type": err.get("context", "runtime"),
                "message": err.get("error", ""),
            })
    # Native tool errors
    native_errors = getattr(vera, "_native_tool_errors", {}) or {}
    for tool_name, msg in native_errors.items():
        errors.append({
            "timestamp": "",
            "type": f"native.{tool_name}",
            "message": str(msg),
        })
    return web.json_response(errors)


async def api_errors_clear(request: web.Request) -> web.Response:
    """Clear the error log."""
    vera = request.app.get("vera")
    if vera:
        monitor = getattr(vera, "health_monitor", None)
        if monitor:
            monitor.errors = []
    return web.json_response({"ok": True})


async def api_activity(request: web.Request) -> web.Response:
    """Activity event feed for the Activity drawer."""
    vera = request.app.get("vera")
    if not vera:
        return web.json_response([])
    event_bus = getattr(vera, "event_bus", None)
    if not event_bus:
        return web.json_response([])
    limit_raw = (request.query.get("limit") or "50").strip()
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(200, limit))
    history = event_bus.get_history(limit=limit)
    events = []
    for ev in history:
        evt_type = ev.event_type
        # Simplify event type for UI: "tool.completed" → "tool"
        simple_type = evt_type.split(".")[0] if "." in evt_type else evt_type
        events.append({
            "id": ev.event_id,
            "type": simple_type,
            "title": ev.payload.get("title", evt_type),
            "name": ev.payload.get("name", ""),
            "detail": ev.payload.get("detail", ""),
            "timestamp": datetime.fromtimestamp(ev.timestamp).isoformat(),
            "duration_ms": ev.payload.get("duration_ms"),
            "status": ev.payload.get("status", "success"),
            "error": ev.payload.get("error"),
        })
    return web.json_response(events)


async def api_activity_clear(request: web.Request) -> web.Response:
    """Clear the activity log."""
    vera = request.app.get("vera")
    if vera:
        event_bus = getattr(vera, "event_bus", None)
        if event_bus:
            event_bus._history = []
    return web.json_response({"ok": True})


async def ws_activity_handler(request: web.Request) -> web.WebSocketResponse:
    """WebSocket handler for live activity stream."""
    vera = request.app["vera"]
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    await ws.send_json({"type": "status", "message": "connected"})

    event_bus = getattr(vera, "event_bus", None)
    if not event_bus:
        await ws.send_json({"type": "error", "message": "EventBus unavailable"})
        await ws.close()
        return ws

    activity_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _on_event(event) -> None:
        evt_type = event.event_type
        simple_type = evt_type.split(".")[0] if "." in evt_type else evt_type
        payload = {
            "type": "activity",
            "event": {
                "id": event.event_id,
                "type": simple_type,
                "title": event.payload.get("title", evt_type),
                "name": event.payload.get("name", ""),
                "detail": event.payload.get("detail", ""),
                "timestamp": datetime.fromtimestamp(event.timestamp).isoformat(),
                "duration_ms": event.payload.get("duration_ms"),
                "status": event.payload.get("status", "success"),
                "error": event.payload.get("error"),
            },
        }
        try:
            loop.call_soon_threadsafe(activity_queue.put_nowait, payload)
        except Exception:
            pass

    sub_id = None
    try:
        sub_id = event_bus.subscribe(
            "*",
            _on_event,
            subscriber_id=f"ws-activity-{id(ws)}",
        )
    except Exception:
        sub_id = None

    async def _stream_events() -> None:
        while True:
            payload = await activity_queue.get()
            if ws.closed:
                break
            try:
                await ws.send_json(payload)
            except Exception:
                break

    stream_task = asyncio.create_task(_stream_events())

    try:
        async for msg in ws:
            # Keep connection alive — no inbound messages expected
            pass
    finally:
        stream_task.cancel()
        try:
            await stream_task
        except (asyncio.CancelledError, Exception):
            pass
        if sub_id and event_bus:
            try:
                event_bus.unsubscribe(sub_id)
            except Exception:
                pass

    return ws


async def tools_server_start(request: web.Request) -> web.Response:
    """Start an individual MCP server."""
    vera = request.app.get("vera")
    if not vera:
        return web.json_response({"error": "VERA unavailable"}, status=503)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    server_name = body.get("server", "").strip()
    if not server_name:
        return web.json_response({"error": "Missing 'server' field"}, status=400)
    mcp = getattr(vera, "mcp", None)
    if not mcp:
        return web.json_response({"error": "MCP orchestrator unavailable"}, status=503)
    try:
        ok = mcp.start_server(server_name)
        return web.json_response({"ok": ok, "server": server_name})
    except Exception as exc:
        logger.error("MCP server start %s failed: %s", server_name, exc)
        return web.json_response({"error": "Internal server error."}, status=500)


async def tools_server_stop(request: web.Request) -> web.Response:
    """Stop an individual MCP server."""
    vera = request.app.get("vera")
    if not vera:
        return web.json_response({"error": "VERA unavailable"}, status=503)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    server_name = body.get("server", "").strip()
    if not server_name:
        return web.json_response({"error": "Missing 'server' field"}, status=400)
    mcp = getattr(vera, "mcp", None)
    if not mcp:
        return web.json_response({"error": "MCP orchestrator unavailable"}, status=503)
    try:
        ok = mcp.stop_server(server_name)
        return web.json_response({"ok": ok, "server": server_name})
    except Exception as exc:
        logger.error("MCP server stop %s failed: %s", server_name, exc)
        return web.json_response({"error": "Internal server error."}, status=500)


async def tools_server_restart(request: web.Request) -> web.Response:
    """Restart an individual MCP server."""
    vera = request.app.get("vera")
    if not vera:
        return web.json_response({"error": "VERA unavailable"}, status=503)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    server_name = body.get("server", "").strip()
    if not server_name:
        return web.json_response({"error": "Missing 'server' field"}, status=400)
    mcp = getattr(vera, "mcp", None)
    if not mcp:
        return web.json_response({"error": "MCP orchestrator unavailable"}, status=503)
    try:
        ok = mcp.restart_server(server_name)
        return web.json_response({"ok": ok, "server": server_name})
    except Exception as exc:
        logger.error("MCP server restart %s failed: %s", server_name, exc)
        return web.json_response({"error": "Internal server error."}, status=500)


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    vera = request.app["vera"]
    clients = request.app.setdefault("ws_clients", set())
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    clients.add(ws)

    await ws.send_json({"type": "status", "message": "connected"})
    innerlife_task: Optional[asyncio.Task] = None
    innerlife_sub_id: Optional[str] = None
    innerlife_queue: Optional[asyncio.Queue] = None
    event_bus = getattr(vera, "event_bus", None)
    if event_bus:
        innerlife_queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _on_innerlife(event) -> None:
            payload = {
                "type": "innerlife",
                "event": {
                    "event_type": event.event_type,
                    "timestamp": event.timestamp,
                    "source": event.source,
                    "priority": getattr(event.priority, "value", event.priority),
                    "event_id": event.event_id,
                    "payload": event.payload,
                },
            }
            try:
                loop.call_soon_threadsafe(innerlife_queue.put_nowait, payload)
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass

        try:
            innerlife_sub_id = event_bus.subscribe(
                "innerlife.*",
                _on_innerlife,
                subscriber_id=f"ws-innerlife-{id(ws)}",
            )
        except Exception:
            innerlife_sub_id = None

        async def _stream_innerlife_events() -> None:
            while True:
                payload = await innerlife_queue.get()
                if ws.closed:
                    break
                try:
                    await ws.send_json(payload)
                except Exception:
                    break

        innerlife_task = asyncio.create_task(_stream_innerlife_events())

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            if payload.get("type") == "tools":
                await ws.send_json({"type": "tools", "data": vera.mcp.get_status()})
                bridge = getattr(vera, "_llm_bridge", None)
                if bridge and getattr(bridge, "get_last_tool_payload", None):
                    await ws.send_json({"type": "tool_payload", "data": bridge.get_last_tool_payload()})
                continue

            if payload.get("type") == "quorum":
                await ws.send_json({"type": "quorum", "data": vera.get_quorum_status()})
                continue

            if payload.get("type") == "message":
                text = payload.get("content", "")
                if not text:
                    await ws.send_json({"type": "error", "message": "Empty message"})
                    continue
                _MAX_WS_MESSAGE_CHARS = 100_000
                if len(text) > _MAX_WS_MESSAGE_CHARS:
                    await ws.send_json({
                        "type": "error",
                        "message": f"Message too large ({len(text)} chars). Maximum is {_MAX_WS_MESSAGE_CHARS}."
                    })
                    continue

                # Set up thinking stream listener for this request
                thinking_task = None
                if THINKING_AVAILABLE:
                    thinking_stream = get_thinking_stream()
                    if thinking_stream:
                        thinking_stream.clear()  # Clear old events
                        thinking_queue = thinking_stream.create_async_queue()

                        async def stream_thinking():
                            try:
                                while True:
                                    event = await asyncio.wait_for(thinking_queue.get(), timeout=0.1)
                                    await ws.send_json(event.to_dict())
                            except asyncio.TimeoutError:
                                logger.debug("Suppressed Exception in server")
                                pass
                            except asyncio.CancelledError:
                                pass
                            except Exception:
                                logger.debug("Suppressed Exception in server")
                                pass

                        # Start streaming thinking events
                        thinking_task = asyncio.create_task(stream_thinking())

                response_text = await vera.process_user_message(text)
                await _broadcast_confirmation_events(clients, vera)

                # Stop thinking stream and send any remaining events
                if thinking_task:
                    thinking_task.cancel()
                    try:
                        await thinking_task
                    except asyncio.CancelledError:
                        logger.debug("Suppressed Exception in server")
                        pass
                    # Drain any remaining events
                    if THINKING_AVAILABLE:
                        thinking_stream = get_thinking_stream()
                        if thinking_stream:
                            for event in thinking_stream.drain():
                                await ws.send_json(event.to_dict())

                await ws.send_json({"type": "response", "content": response_text})
                bridge = getattr(vera, "_llm_bridge", None)
                if bridge and getattr(bridge, "get_last_tool_payload", None):
                    await ws.send_json({"type": "tool_payload", "data": bridge.get_last_tool_payload()})
                continue
    finally:
        if innerlife_task:
            innerlife_task.cancel()
            try:
                await innerlife_task
            except asyncio.CancelledError:
                logger.debug("Suppressed Exception in server")
                pass
        if event_bus and innerlife_sub_id:
            try:
                event_bus.unsubscribe(innerlife_sub_id)
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass
        clients.discard(ws)

    return ws


def _serve_index(ui_dir: Path) -> web.Response:
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(index_path)


# === Terminal WebSocket ===

# Track active terminal processes per connection
# ---------------------------------------------------------------------------
# Terminal command blocklist (defense-in-depth for H3)
# ---------------------------------------------------------------------------
_TERMINAL_BLOCKED_PATTERNS = [
    re.compile(r"rm\s+(-[^\s]*[rf][^\s]*|--recursive|--force)\s+.*(\/|~|\$HOME)", re.IGNORECASE),
    re.compile(r"dd\s+if=/dev/(zero|random|urandom)\s+of=", re.IGNORECASE),
    re.compile(r"mkfs\.", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:", re.IGNORECASE),  # fork bomb
    re.compile(r">\s*/dev/(sda|sdb|sdc|nvme)", re.IGNORECASE),
    re.compile(r"chmod\s+(-R|--recursive)?\s*777\s+(/|~)", re.IGNORECASE),
    re.compile(r"curl\s+.*\|\s*(ba)?sh", re.IGNORECASE),
    re.compile(r"wget\s+.*\|\s*(ba)?sh", re.IGNORECASE),
    re.compile(r"(sed|awk|perl|python).*run_vera\.py|>.*run_vera\.py", re.IGNORECASE),
    re.compile(r"rm\s+.*run_vera\.py", re.IGNORECASE),
    re.compile(r"rm\s+(-[^\s]*r[^\s]*|--recursive)\s+.*vera_memory", re.IGNORECASE),
    re.compile(r"find\s+.*-exec\s+.*rm\b", re.IGNORECASE),  # find -exec rm
    re.compile(r"awk\s+.*\bsystem\s*\(", re.IGNORECASE),  # awk system() injection
    re.compile(r"python[23]?\s+-c\s+.*import\s+os", re.IGNORECASE),  # python -c os module
    re.compile(r"nc\s+(-[^\s]*)?\s*-e\s+/bin/(ba)?sh", re.IGNORECASE),  # netcat reverse shell
]


def _terminal_command_blocked(command: str) -> Optional[str]:
    """Return block reason if command matches a dangerous pattern, else None."""
    # Normalize: strip ANSI escapes, $'...' hex/octal sequences, and
    # collapse whitespace so encoding tricks don't bypass the denylist.
    normalized = command
    # Expand $'\xNN' / $'\NNN' bash quoting to catch obfuscated commands
    normalized = re.sub(r"\$'([^']*)'", lambda m: m.group(1), normalized)
    normalized = re.sub(r"\\x[0-9a-fA-F]{2}", " ", normalized)
    normalized = re.sub(r"\\[0-7]{1,3}", " ", normalized)
    # Check both raw and normalized forms
    for cmd_form in (command, normalized):
        for pattern in _TERMINAL_BLOCKED_PATTERNS:
            if pattern.search(cmd_form):
                return "Command blocked by safety filter."
    return None


_terminal_processes: Dict[int, asyncio.subprocess.Process] = {}


async def terminal_ws_handler(request: web.Request) -> web.WebSocketResponse:
    """WebSocket handler for terminal command execution with streaming output."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Kill switch: disable terminal entirely via env var
    if os.getenv("VERA_TERMINAL_ENABLED", "1") == "0":
        await ws.send_json({"type": "error", "message": "Terminal is disabled."})
        await ws.close()
        return ws

    current_process: Optional[asyncio.subprocess.Process] = None
    ws_id = id(ws)

    await ws.send_json({"type": "connected", "message": "Terminal ready"})

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue

            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = payload.get("type", "")

            if msg_type == "execute":
                command = payload.get("command", "").strip()
                cwd = payload.get("cwd", "")

                if not command:
                    await ws.send_json({"type": "error", "message": "Empty command"})
                    continue

                # Safety check: block catastrophic commands
                block_reason = _terminal_command_blocked(command)
                if block_reason:
                    await ws.send_json({"type": "error", "message": block_reason})
                    logger.warning("Terminal command blocked: %s", command)
                    continue

                # Use editor working directory if not specified
                if not cwd:
                    cwd = _editor_state.get("working_directory", "")
                if not cwd:
                    cwd = os.getcwd()
                cwd = os.path.expanduser(cwd)

                # Kill any existing process for this connection
                if current_process and current_process.returncode is None:
                    try:
                        current_process.terminate()
                        await asyncio.wait_for(current_process.wait(), timeout=2.0)
                    except Exception:
                        current_process.kill()

                try:
                    # Start the process
                    current_process = await asyncio.create_subprocess_shell(
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd,
                    )
                    _terminal_processes[ws_id] = current_process

                    await ws.send_json({
                        "type": "started",
                        "pid": current_process.pid,
                        "command": command,
                        "cwd": cwd
                    })

                    # Stream stdout and stderr concurrently
                    async def stream_output(stream, stream_name):
                        while True:
                            line = await stream.readline()
                            if not line:
                                break
                            try:
                                text = line.decode("utf-8", errors="replace")
                                await ws.send_json({
                                    "type": "output",
                                    "stream": stream_name,
                                    "data": text
                                })
                            except Exception:
                                break

                    # Run both streams concurrently
                    await asyncio.gather(
                        stream_output(current_process.stdout, "stdout"),
                        stream_output(current_process.stderr, "stderr"),
                    )

                    # Wait for process to complete
                    return_code = await current_process.wait()
                    await ws.send_json({
                        "type": "exit",
                        "code": return_code
                    })

                except Exception as e:
                    logger.error("Terminal command execution failed: %s", e)
                    await ws.send_json({
                        "type": "error",
                        "message": "Command execution failed."
                    })

            elif msg_type == "kill":
                if current_process and current_process.returncode is None:
                    try:
                        current_process.terminate()
                        await asyncio.wait_for(current_process.wait(), timeout=2.0)
                        await ws.send_json({"type": "killed", "message": "Process terminated"})
                    except asyncio.TimeoutError:
                        current_process.kill()
                        await ws.send_json({"type": "killed", "message": "Process killed"})
                    except Exception as e:
                        logger.error("Terminal process kill failed: %s", e)
                        await ws.send_json({"type": "error", "message": "Failed to kill process."})
                else:
                    await ws.send_json({"type": "error", "message": "No running process"})

            elif msg_type == "resize":
                # Terminal resize - store dimensions for future use
                cols = payload.get("cols", 80)
                rows = payload.get("rows", 24)
                await ws.send_json({"type": "resized", "cols": cols, "rows": rows})

    except Exception as e:
        logger.error("Terminal WebSocket error: %s", e)
    finally:
        # Cleanup: kill any running process
        if current_process and current_process.returncode is None:
            try:
                current_process.terminate()
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass
        _terminal_processes.pop(ws_id, None)

    return ws


async def _broadcast_confirmation_events(clients: set, vera) -> None:
    if not clients or not getattr(vera, "pop_confirmation_events", None):
        return
    events = vera.pop_confirmation_events()
    if not events:
        return
    payloads = [{"type": "confirmation", "data": event} for event in events]
    for ws in list(clients):
        if ws.closed:
            clients.discard(ws)
            continue
        for payload in payloads:
            try:
                await ws.send_json(payload)
            except Exception:
                clients.discard(ws)


def create_app(vera, ui_dist: Optional[Path] = None) -> web.Application:
    # 50MB limit to handle base64-encoded images (default is 2MB which causes 413 errors)
    app = web.Application(middlewares=[cors_middleware, auth_middleware, rate_limit_middleware], client_max_size=50 * 1024 * 1024)
    app["vera"] = vera
    app["ws_clients"] = set()
    app["voice_state"] = {"active": False, "last_voice": os.getenv("VERA_VOICE_DEFAULT", "eve").strip().lower() or "eve"}
    app["self_improvement_runner"] = SelfImprovementRunner(Path("vera_memory") / "flight_recorder")
    app["push_service"] = PushNotificationService()
    app["native_push_service"] = NativePushNotificationService()
    app["last_reachout_event"] = {}
    app["reachout_runplane_seen"] = {}
    app["started_at"] = time.time()
    app["tool_execution_history"] = []  # In-memory ring buffer for tool execution tracking
    app["vera_api_key"] = _get_secret_env("VERA_API_KEY")
    app["anthropic_proxy_rate_limit"] = {}
    app["global_rate_limit"] = {}
    global_mcp_inflight = _parse_int_env("VERA_MCP_CALL_MAX_INFLIGHT", 24, minimum=1)
    app["mcp_call_global_semaphore"] = asyncio.Semaphore(global_mcp_inflight)
    app["mcp_call_queue_timeout_seconds"] = _parse_float_env(
        "VERA_MCP_CALL_QUEUE_TIMEOUT_SECONDS",
        3.0,
        minimum=0.1,
    )
    server_limits = _default_server_concurrency()
    app["mcp_call_server_semaphores"] = {
        name: asyncio.Semaphore(limit)
        for name, limit in server_limits.items()
    }
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/readiness", readiness)
    app.router.add_get("/api/tools", tools_status)
    app.router.add_get("/api/tools/status", tools_status)
    app.router.add_get("/api/channels/status", channels_status)
    app.router.add_get("/api/channels/whatsapp/webhook", whatsapp_webhook_verify)
    app.router.add_post("/api/channels/whatsapp/webhook", whatsapp_webhook_receive)
    app.router.add_post("/api/channels/local/inbound", local_loopback_inbound)
    app.router.add_get("/api/channels/local/outbox", local_loopback_outbox)
    app.router.add_post("/api/channels/local/outbox/clear", local_loopback_outbox_clear)
    app.router.add_get("/api/push/vapid", push_vapid)
    app.router.add_post("/api/push/subscribe", push_subscribe)
    app.router.add_post("/api/push/unsubscribe", push_unsubscribe)
    app.router.add_post("/api/push/test", push_test)
    app.router.add_get("/api/push/native/status", push_native_status)
    app.router.add_post("/api/push/native/register", push_native_register)
    app.router.add_post("/api/push/native/unregister", push_native_unregister)
    app.router.add_post("/api/push/native/test", push_native_test)
    app.router.add_post("/api/push/native/ack", push_native_ack)
    app.router.add_route("*", "/api/push/native/targets", push_native_targets)
    app.router.add_post("/api/anthropic/messages", anthropic_messages_proxy)
    app.router.add_get("/api/google/auth/status", google_auth_status)
    app.router.add_post("/api/google/auth/start", google_auth_start)
    app.router.add_get("/api/tools/list", tools_list)
    app.router.add_get("/api/tools/defs", tools_defs)
    app.router.add_get("/api/tools/last_payload", tools_last_payload)
    app.router.add_post("/api/tools/preview", tools_preview)
    app.router.add_post("/api/tools/start", tools_start)
    app.router.add_post("/api/tools/restart", tools_restart)
    app.router.add_post("/api/tools/call", tools_call)
    app.router.add_post("/api/tools/verify", tools_verify)
    app.router.add_get("/api/tools/history", tools_history)
    app.router.add_post("/api/tools/history/clear", tools_history_clear)
    app.router.add_get("/api/quorum/status", quorum_status)
    app.router.add_get("/api/quorum/list", quorum_list)
    app.router.add_post("/api/quorum/settings", quorum_settings)
    app.router.add_post("/api/quorum/custom", quorum_custom_create)
    app.router.add_post("/api/quorum/custom/delete", quorum_custom_delete)
    app.router.add_get("/api/memory/stats", memory_stats)
    app.router.add_get("/api/skills", skills_list)
    app.router.add_get("/api/learning/status", learning_loop_status)
    app.router.add_get("/api/learning/lora-evals", learning_loop_lora_evals)
    app.router.add_get("/api/learning/lora-readiness", learning_loop_lora_readiness)
    app.router.add_post("/api/learning/run-cycle", learning_loop_run_cycle)
    app.router.add_get("/api/innerlife/status", innerlife_status)
    app.router.add_get("/api/autonomy/jobs", autonomy_jobs)
    app.router.add_post("/api/autonomy/actions/run", autonomy_action_run)
    app.router.add_get("/api/autonomy/runs", autonomy_runs)
    app.router.add_post("/api/autonomy/runs/mark", autonomy_runs_mark)
    app.router.add_get("/api/autonomy/dead-letter", autonomy_dead_letter)
    app.router.add_post("/api/autonomy/dead-letter/replay", autonomy_dead_letter_replay)
    app.router.add_get("/api/autonomy/slo", autonomy_slo)
    app.router.add_post("/api/improvement-archive/suggest", improvement_archive_suggest)
    app.router.add_post("/api/innerlife/goals", innerlife_goals_add)
    app.router.add_post("/api/innerlife/reflect", innerlife_reflect)
    app.router.add_post("/api/innerlife/autonomy-cycle", innerlife_autonomy_cycle)
    app.router.add_get("/api/browser/status", browser_status)
    app.router.add_post("/api/browser/launch", browser_launch)
    app.router.add_post("/api/browser/close", browser_close)
    app.router.add_get("/api/self_improvement/budget", self_improvement_budget_get)
    app.router.add_post("/api/self_improvement/budget", self_improvement_budget_update)
    app.router.add_get("/api/self_improvement/status", self_improvement_status)
    app.router.add_get("/api/self_improvement/logs", self_improvement_logs)
    app.router.add_post("/api/self_improvement/run", self_improvement_run)
    app.router.add_post("/api/self_improvement/simulate", self_improvement_simulate)
    app.router.add_get("/api/voice/status", voice_status)
    app.router.add_post("/api/voice/test", voice_test)
    app.router.add_post("/api/keys", set_keys)
    app.router.add_post("/api/exit", api_exit)
    app.router.add_post("/api/file/read", file_read)
    app.router.add_post("/api/file/write", file_write)
    app.router.add_get("/api/editor", editor_get)
    app.router.add_post("/api/editor", editor_set)
    app.router.add_post("/api/editor/save", editor_save)
    app.router.add_post("/api/editor/undo", editor_undo)
    app.router.add_get("/api/editor/workspace", workspace_get)
    app.router.add_post("/api/editor/workspace", workspace_set)
    app.router.add_get("/api/editor/files", workspace_files)
    app.router.add_post("/api/editor/file/open", workspace_open_file)
    app.router.add_get("/api/git/status", git_status)
    app.router.add_get("/api/git/files", git_files)
    app.router.add_post("/api/confirmations/clear", confirmations_clear)
    app.router.add_post("/api/confirmations/sync", confirmations_sync)
    app.router.add_post("/api/session/activity", session_activity)
    app.router.add_get("/api/session/link-map", session_link_map)
    app.router.add_post("/api/session/link-map", session_link_map_update)
    app.router.add_get("/api/session/links", session_links)
    app.router.add_post("/api/session/link", session_link)
    app.router.add_get("/api/preferences/partner-model", partner_model_status)
    app.router.add_get("/api/preferences/core-identity", core_identity_status)
    app.router.add_post("/api/preferences/core-identity/refresh", core_identity_refresh)
    app.router.add_post("/api/preferences/core-identity/revert", core_identity_revert)
    # Back-compat aliases retained for older tooling/scripts.
    app.router.add_get("/api/preferences/identity", core_identity_status)
    app.router.add_get("/api/preferences/promote", core_identity_status)
    app.router.add_post("/api/preferences/promote", core_identity_refresh)

    # Right-rail drawer endpoints
    app.router.add_get("/api/ping", api_ping)
    app.router.add_get("/api/session/stats", session_stats)
    app.router.add_get("/api/errors", api_errors)
    app.router.add_post("/api/errors/clear", api_errors_clear)
    app.router.add_get("/api/activity", api_activity)
    app.router.add_post("/api/activity/clear", api_activity_clear)
    app.router.add_post("/api/tools/server/start", tools_server_start)
    app.router.add_post("/api/tools/server/stop", tools_server_stop)
    app.router.add_post("/api/tools/server/restart", tools_server_restart)

    app.router.add_get("/v1/models", list_models)
    app.router.add_post("/v1/chat/completions", chat_completions)
    app.router.add_post("/v1/chat/voice", voice_chat_completions)
    app.router.add_post("/v1/images/generations", image_generations)
    app.router.add_post("/v1/videos/generations", video_generations)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/ws/voice", voice_ws_handler)
    app.router.add_get("/api/voice/ws", voice_ws_handler)
    app.router.add_get("/ws/terminal", terminal_ws_handler)
    app.router.add_get("/ws/activity", ws_activity_handler)

    if ui_dist and ui_dist.exists():
        assets_dir = ui_dist / "assets"
        if assets_dir.exists():
            app.router.add_static("/assets", assets_dir)
        for folder in ("images", "animations", "sounds", "webfonts"):
            static_dir = ui_dist / folder
            if static_dir.exists():
                app.router.add_static(f"/{folder}", static_dir)
        for filename in ("sw.js", "sw.mjs", "registerSW.js", "manifest.webmanifest", "reset_tokens.html"):
            file_path = ui_dist / filename
            if file_path.exists():
                app.router.add_get(
                    f"/{filename}",
                    lambda _, path=file_path: web.FileResponse(path),
                )
        app.router.add_get("/", lambda _: _serve_index(ui_dist))
        app.router.add_get("/{tail:.*}", lambda _: _serve_index(ui_dist))
    else:
        # Keep the root URL useful in headless mode so local checks do not see
        # a misleading 404 when the API is healthy.
        app.router.add_get("/", health)
        app.router.add_get("/health", health)

    push_service = app.get("push_service")
    event_bus = getattr(vera, "event_bus", None)
    if event_bus:
        def _record_reachout_delivery_run(payload: Dict[str, Any], timestamp: Any) -> None:
            run_id = str(payload.get("run_id") or "").strip()
            if not run_id:
                return
            proactive = getattr(vera, "proactive_manager", None)
            runplane = getattr(proactive, "runplane", None) if proactive else None
            if not runplane:
                return
            seen = app.get("reachout_runplane_seen")
            if not isinstance(seen, dict):
                seen = {}
                app["reachout_runplane_seen"] = seen
            if run_id in seen:
                return
            seen[run_id] = time.time()
            if len(seen) > 512:
                for stale_run_id, _ in sorted(seen.items(), key=lambda item: float(item[1]))[:128]:
                    seen.pop(stale_run_id, None)

            delivered_to_raw = payload.get("delivered_to")
            delivered_to = [str(item).strip() for item in delivered_to_raw] if isinstance(delivered_to_raw, list) else []
            delivered_to = [item for item in delivered_to if item][:8]
            effective_delivered_to = _effective_reachout_delivery_channels(app, delivered_to)
            ack_channels = _expected_reachout_ack_channels(app, delivered_to)
            ack_expected = bool(ack_channels)

            job_id = f"delivery.reachout.{run_id}"
            lane_key = f"delivery:reachout:{run_id}"
            begin = runplane.begin_run(
                job_id=job_id,
                lane_key=lane_key,
                trigger="innerlife.reached_out",
                kind="delivery_reachout",
                metadata={
                    "external_run_id": run_id,
                    "innerlife_run_id": run_id,
                    "ack_expected": ack_expected,
                    "ack_channels": list(ack_channels),
                },
                max_attempts=4,
            )
            if not begin.get("ok"):
                return
            runplane_run_id = str(begin.get("run_id") or "").strip()
            if not runplane_run_id:
                return

            result_payload = {
                "external_run_id": run_id,
                "innerlife_run_id": run_id,
                "event_timestamp": str(timestamp),
                "delivered_to": effective_delivered_to,
                "delivery_source_channels": delivered_to,
                "ack_expected": ack_expected,
            }
            if ack_channels:
                result_payload["ack_channels"] = list(ack_channels)
            if effective_delivered_to:
                complete_result = runplane.complete_run(
                    job_id=job_id,
                    run_id=runplane_run_id,
                    ok=True,
                    status="delivered",
                    result=result_payload,
                )
                if complete_result.get("ok"):
                    _close_superseded_reachout_runs(
                        app,
                        current_run_id=runplane_run_id,
                    )
            else:
                runplane.complete_run(
                    job_id=job_id,
                    run_id=runplane_run_id,
                    ok=False,
                    failure_class="delivery_unroutable",
                    retryable=True,
                    result={
                        **result_payload,
                        "reason": "no_delivery_channels",
                    },
                )

        def _track_innerlife_reachout(event) -> None:
            if event.event_type != "innerlife.reached_out":
                return
            payload = event.payload if isinstance(event.payload, dict) else {}
            run_id = str(payload.get("run_id") or "").strip()
            if not run_id:
                return
            try:
                app["last_reachout_event"] = {"run_id": run_id, "timestamp": str(event.timestamp)}
            except Exception:
                pass
            try:
                _record_reachout_delivery_run(payload, event.timestamp)
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass

        try:
            event_bus.subscribe(
                "innerlife.reached_out",
                _track_innerlife_reachout,
                subscriber_id="reachout-state-tracker",
            )
        except Exception:
            logger.debug("Suppressed Exception in server")
            pass

    if event_bus and isinstance(push_service, PushNotificationService) and push_service.enabled:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        def _read_bool_env(name: str, default: str = "1") -> bool:
            value = os.getenv(name, default).strip().lower()
            return value not in {"0", "false", "no", "off", "disabled"}

        def _read_int_env(name: str, default: int) -> int:
            raw = os.getenv(name, str(default)).strip()
            try:
                return int(raw)
            except (TypeError, ValueError):
                return default

        def _truncate(text: str, limit: int = 140) -> str:
            if not text:
                return ""
            normalized = " ".join(str(text).split())
            if len(normalized) <= limit:
                return normalized
            return normalized[: max(0, limit - 3)] + "..."

        push_idle_seconds = _read_int_env("VERA_PUSH_IDLE_SECONDS", 90)
        push_message_events = _read_bool_env("VERA_PUSH_MESSAGE_EVENTS", "1")
        push_tool_events = _read_bool_env("VERA_PUSH_TOOL_EVENTS", "1")
        push_error_events = _read_bool_env("VERA_PUSH_ERROR_EVENTS", "1")

        def _queue_push(payload: Dict[str, Any]) -> None:
            if not loop:
                return
            try:
                asyncio.run_coroutine_threadsafe(push_service.broadcast(payload), loop)
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass

        def _on_innerlife(event) -> None:
            if not loop:
                return
            if event.event_type != "innerlife.reached_out":
                return
            event_payload = event.payload if isinstance(event.payload, dict) else {}
            run_id = str(event_payload.get("run_id") or "").strip()
            if run_id:
                try:
                    app["last_reachout_event"] = {"run_id": run_id, "timestamp": str(event.timestamp)}
                except Exception:
                    pass
            push_data: Dict[str, Any] = {
                "event_type": event.event_type,
                "timestamp": event.timestamp,
            }
            if run_id:
                push_data["run_id"] = run_id
                push_data["ack_endpoint"] = "/api/push/native/ack"
                push_data["ack_type"] = "opened"
            delivered_to = event_payload.get("delivered_to")
            if isinstance(delivered_to, list):
                push_data["delivered_to"] = [str(item) for item in delivered_to if str(item).strip()]
            payload = {
                "title": "VERA reached out",
                "body": "VERA has a new update. Tap to open.",
                "icon": "/assets/icon-192.png",
                "badge": "/assets/icon-192.png",
                "data": push_data,
            }
            try:
                asyncio.run_coroutine_threadsafe(push_service.broadcast(payload), loop)
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass

        def _on_innerlife_native(event) -> None:
            if not loop:
                return
            if event.event_type != "innerlife.reached_out":
                return
            native_service = app.get("native_push_service")
            if not isinstance(native_service, NativePushNotificationService):
                return
            if not native_service.enabled or not native_service.configured:
                return
            try:
                if not native_service.list_devices():
                    return
            except Exception:
                logger.debug("Suppressed Exception in server")
                return
            event_payload = event.payload if isinstance(event.payload, dict) else {}
            run_id = str(event_payload.get("run_id") or "").strip()
            push_data: Dict[str, Any] = {
                "event_type": event.event_type,
                "timestamp": event.timestamp,
            }
            if run_id:
                push_data["run_id"] = run_id
                push_data["ack_endpoint"] = "/api/push/native/ack"
                push_data["ack_type"] = "opened"
            delivered_to = event_payload.get("delivered_to")
            if isinstance(delivered_to, list):
                push_data["delivered_to"] = [str(item) for item in delivered_to if str(item).strip()]
            payload = {
                "title": "VERA reached out",
                "body": "VERA has a new update. Tap to open.",
                "data": push_data,
            }
            try:
                asyncio.run_coroutine_threadsafe(native_service.broadcast(payload), loop)
            except Exception:
                logger.debug("Suppressed Exception in server")
                pass

        def _on_message(event) -> None:
            if event.event_type != "message.assistant" or not push_message_events:
                return
            idle_seconds = event.payload.get("idle_seconds")
            if push_idle_seconds > 0 and isinstance(idle_seconds, (int, float)):
                if idle_seconds < push_idle_seconds:
                    return
            body = _truncate(event.payload.get("text") or "New message from VERA.", 160)
            payload = {
                "title": "VERA replied",
                "body": body or "New message from VERA.",
                "icon": "/assets/icon-192.png",
                "badge": "/assets/icon-192.png",
                "data": {
                    "event_type": event.event_type,
                    "conversation_id": event.payload.get("conversation_id"),
                },
            }
            _queue_push(payload)

        def _on_tool(event) -> None:
            if event.event_type not in {"tool.completed", "tool.failed"} or not push_tool_events:
                return
            tool_name = event.payload.get("tool_name") or "tool"
            success = bool(event.payload.get("success", True))
            title = "Tool finished" if success else "Tool failed"
            body = (
                f"{tool_name} completed."
                if success
                else _truncate(event.payload.get("error") or f"{tool_name} failed.", 160)
            )
            payload = {
                "title": title,
                "body": body,
                "icon": "/assets/icon-192.png",
                "badge": "/assets/icon-192.png",
                "data": {
                    "event_type": event.event_type,
                    "tool_name": tool_name,
                    "conversation_id": event.payload.get("conversation_id"),
                },
            }
            _queue_push(payload)

        def _on_error(event) -> None:
            if not push_error_events:
                return
            body = _truncate(event.payload.get("error") or "VERA error.", 160)
            payload = {
                "title": "VERA error",
                "body": body,
                "icon": "/assets/icon-192.png",
                "badge": "/assets/icon-192.png",
                "data": {
                    "event_type": event.event_type,
                    "conversation_id": event.payload.get("conversation_id"),
                },
            }
            _queue_push(payload)

        try:
            event_bus.subscribe(
                "innerlife.reached_out",
                _on_innerlife,
                subscriber_id="push-innerlife",
            )
            event_bus.subscribe(
                "innerlife.reached_out",
                _on_innerlife_native,
                subscriber_id="native-push-innerlife",
            )
            event_bus.subscribe(
                "message.assistant",
                _on_message,
                subscriber_id="push-message",
            )
            event_bus.subscribe(
                "tool.*",
                _on_tool,
                subscriber_id="push-tool",
            )
            event_bus.subscribe(
                "error.*",
                _on_error,
                subscriber_id="push-error",
            )
        except Exception:
            logger.debug("Suppressed Exception in server")
            pass

    # Background task: periodically prune expired sessions to prevent memory growth
    _session_prune_interval = _parse_int_env("VERA_SESSION_PRUNE_INTERVAL", 300, minimum=60)

    async def _session_prune_loop(app: web.Application) -> None:
        while True:
            await asyncio.sleep(_session_prune_interval)
            try:
                store = getattr(app.get("vera"), "session_store", None)
                if store and hasattr(store, "prune_expired"):
                    pruned = store.prune_expired()
                    if pruned:
                        logger.debug("Pruned %d expired sessions", pruned)
            except Exception as exc:
                logger.debug("Session prune error: %s", exc)

    async def _start_background_tasks(app: web.Application) -> None:
        app["_session_prune_task"] = asyncio.create_task(_session_prune_loop(app))

    async def _cleanup_background_tasks(app: web.Application) -> None:
        task = app.get("_session_prune_task")
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app.on_startup.append(_start_background_tasks)
    app.on_cleanup.append(_cleanup_background_tasks)

    return app
