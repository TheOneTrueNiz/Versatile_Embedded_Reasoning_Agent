"""
Tool Orchestrator
=================

Encapsulates the tool execution pipeline (safety checks, caching, verification,
compression, logging, and memory integration).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

try:
    from core.runtime.thinking_stream import thinking_tool
except ImportError:
    def thinking_tool(*args, **kwargs):  # type: ignore
        return None

from observability.cost_tracker import BudgetStatus
from observability.decision_ledger import DecisionType
from observability.tool_quota import ToolQuotaManager
from orchestration.error_handler import RecoveryAction
from safety.safety_validator import ValidationResult

logger = logging.getLogger(__name__)


class ToolOrchestrator:
    """Tool execution pipeline extracted from VERA."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner
        self._tool_source_cache: Dict[str, Dict[str, Any]] = {}
        self._tool_source_cache_ts = 0.0
        self._untrusted_sources_by_convo: Dict[str, List[Dict[str, Any]]] = {}
        self.tool_quota = None
        if os.getenv("VERA_TOOL_QUOTA_ENABLED", "1").lower() in {"1", "true", "yes", "on"}:
            self.tool_quota = ToolQuotaManager()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner, name)

    @staticmethod
    def _extract_embedded_tool_error(result: Any) -> str:
        """Detect tool-level errors returned as structured payloads."""
        if not isinstance(result, dict):
            return ""

        err = result.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()
        if isinstance(err, dict):
            for key in ("message", "detail", "error"):
                value = err.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        status = str(result.get("status") or "").strip().lower()
        if status in {"error", "failed"}:
            for key in ("message", "detail", "reason"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return f"Tool returned status={status}"

        return ""

    def _refresh_tool_source_cache(self) -> None:
        fallback_server_categories = {
            "filesystem": ["files"],
            "memory": ["memory"],
            "time": ["time"],
            "sequential-thinking": ["reasoning"],
            "brave-search": ["web", "grounding", "news", "media"],
            "searxng": ["web"],
            "wikipedia": ["knowledge"],
            "wikipedia-mcp": ["knowledge"],
            "grokipedia": ["knowledge"],
            "pdf-reader": ["pdf"],
            "memvid": ["media", "memory"],
            "github": ["dev"],
            "google-workspace": ["workspace"],
            "youtube-transcript": ["media", "web", "knowledge"],
            "call-me": ["phone", "voice", "messaging", "sms", "mms"],
        }

        cache: Dict[str, Dict[str, Any]] = {}
        if not getattr(self, "mcp", None):
            self._tool_source_cache = cache
            self._tool_source_cache_ts = time.time()
            return

        try:
            available = self.mcp.get_available_tools()
        except Exception:
            self._tool_source_cache = cache
            self._tool_source_cache_ts = time.time()
            return

        server_categories: Dict[str, List[str]] = {}
        if getattr(self.mcp, "configs", None):
            for name, config in self.mcp.configs.items():
                server_categories[name] = list(getattr(config, "categories", []) or [])
        for name in available:
            if not server_categories.get(name):
                server_categories[name] = fallback_server_categories.get(name, [])

        for server_name, tools in available.items():
            categories = server_categories.get(server_name, [])
            for tool in tools:
                cache[tool] = {"server": server_name, "categories": categories}

        self._tool_source_cache = cache
        self._tool_source_cache_ts = time.time()

    def _extract_url_from_params(self, params: Dict[str, Any]) -> Optional[str]:
        for key in ("url", "urls", "link", "video_url", "repo_url", "source_url"):
            value = params.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.startswith(("http://", "https://")):
                        return item
        return None

    @staticmethod
    def _classify_source_type(categories: List[str], tool_name: str) -> str:
        lowered = {str(cat).lower() for cat in categories if cat}
        if "dev" in lowered or "repo" in lowered:
            return "repo"
        if "media" in lowered or "image_gen" in lowered:
            return "media"
        if "pdf" in lowered:
            return "pdf"
        if "web" in lowered or "grounding" in lowered or "knowledge" in lowered:
            return "web"
        if "files" in lowered or "canvas" in lowered:
            return "local"
        if "workspace" in lowered:
            return "workspace"
        if tool_name.startswith("browser_"):
            return "web"
        if tool_name.startswith("pdf_"):
            return "pdf"
        return "tool"

    def _resolve_tool_source(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        categories: List[str] = []
        server_name = None

        if tool_name.startswith("browser_"):
            categories = ["web"]
        elif tool_name.startswith("desktop_"):
            categories = ["local"]
        elif tool_name.startswith("pdf_"):
            categories = ["pdf"]
        elif tool_name.startswith("editor_"):
            categories = ["files"]
        elif tool_name == "generate_image":
            categories = ["media"]
        elif tool_name == "recursive_summarize":
            categories = ["memory"]
        else:
            cache_ttl = float(os.getenv("VERA_TOOL_SOURCE_CACHE_TTL", "300"))
            if (
                (time.time() - self._tool_source_cache_ts) > cache_ttl
                or tool_name not in self._tool_source_cache
            ):
                self._refresh_tool_source_cache()
            cached = self._tool_source_cache.get(tool_name, {})
            categories = list(cached.get("categories", []) or [])
            server_name = cached.get("server")

        url_hint = self._extract_url_from_params(params or {})
        source_id = tool_name
        if url_hint:
            source_id = url_hint
            host = urlparse(url_hint).netloc.lower()
            if "youtube" in host or "youtu.be" in host:
                categories = list({*categories, "media"})
            elif "github" in host or "gitlab" in host:
                categories = list({*categories, "dev"})
            else:
                categories = list({*categories, "web"})

        source_type = self._classify_source_type(categories, tool_name)
        return {
            "source_type": source_type,
            "source_id": source_id,
            "server": server_name,
            "categories": categories,
            "tool": tool_name,
        }

    @staticmethod
    def _resolve_quota_key(tool_name: str, source_info: Dict[str, Any]) -> Optional[str]:
        server = (source_info.get("server") or "").strip().lower()
        tool_lower = tool_name.lower()

        if tool_lower.startswith("brave_") or server == "brave-search":
            return "brave"
        if tool_lower == "searxng_search" or server == "searxng":
            return "searxng"
        if tool_lower in {"search_youtube", "get_transcript"} or server == "youtube-transcript":
            return "youtube"
        if server == "browserbase" or tool_lower.startswith("browserbase_"):
            return "browserbase"
        if server == "scrapeless" or tool_lower.startswith("scrapeless_"):
            return "scrapeless"
        if server == "x-twitter" or tool_lower.startswith("twitter_") or tool_lower.startswith("x_"):
            return "twitter"
        if server == "call-me" or tool_lower.startswith("call_"):
            return "call-me"

        return None

    def _get_untrusted_source_types(self) -> set:
        raw = os.getenv(
            "VERA_TWO_SOURCE_UNTRUSTED_SOURCES",
            "web,media,repo,image,pdf,external",
        )
        return self._parse_tool_list(raw)

    def _record_untrusted_source(
        self,
        conversation_id: str,
        source_info: Dict[str, Any],
        verification: Optional[Any] = None
    ) -> None:
        convo_id = self._normalize_conversation_id(conversation_id)
        source_type = source_info.get("source_type") or "tool"
        untrusted_types = self._get_untrusted_source_types()
        requires_confirmation = bool(getattr(verification, "requires_confirmation", False))

        if source_type not in untrusted_types and not requires_confirmation:
            return

        source_id = source_info.get("source_id") or source_info.get("server") or source_info.get("tool") or "unknown"
        entry = {
            "source_id": source_id,
            "source_type": source_type,
            "timestamp": time.time(),
        }

        existing = self._untrusted_sources_by_convo.get(convo_id, [])
        existing_ids = {f"{item.get('source_type')}::{item.get('source_id')}" for item in existing}
        entry_key = f"{source_type}::{source_id}"
        if entry_key not in existing_ids:
            existing.append(entry)
        self._untrusted_sources_by_convo[convo_id] = existing
        self._prune_untrusted_sources(convo_id)

    def _prune_untrusted_sources(self, conversation_id: str) -> None:
        try:
            ttl = int(os.getenv("VERA_TWO_SOURCE_TTL_SECONDS", "900"))
        except (ValueError, TypeError):
            ttl = 900
        now = time.time()
        convo_id = self._normalize_conversation_id(conversation_id)
        entries = self._untrusted_sources_by_convo.get(convo_id, [])
        self._untrusted_sources_by_convo[convo_id] = [
            entry for entry in entries if (now - entry.get("timestamp", now)) <= ttl
        ]

    def _get_recent_untrusted_sources(self, conversation_id: str) -> List[Dict[str, Any]]:
        convo_id = self._normalize_conversation_id(conversation_id)
        self._prune_untrusted_sources(convo_id)
        return list(self._untrusted_sources_by_convo.get(convo_id, []))

    def _is_high_impact_tool(self, tool_name: str) -> bool:
        exempt = self._parse_tool_list(os.getenv("VERA_TWO_SOURCE_EXEMPT_TOOLS", ""))
        if tool_name in exempt:
            return False
        patterns_raw = os.getenv(
            "VERA_TWO_SOURCE_HIGH_IMPACT_PATTERNS",
            "send_,delete_,remove_,update_,create_,write_,commit,merge,push,upload,publish,share,grant,"
            "revoke,transfer,pay,charge,order,book,schedule,cancel"
        )
        patterns = [token.strip().lower() for token in patterns_raw.split(",") if token.strip()]
        lowered = tool_name.lower()
        return any(pattern in lowered for pattern in patterns)

    def _should_log_tool_decision(
        self,
        tool_name: str,
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        mode = os.getenv("VERA_DECISION_LOG_TOOLS", "high").strip().lower()
        if context and context.get("log_decision") is True:
            return True
        if mode in {"0", "false", "no", "off", "none"}:
            return False
        if mode in {"1", "true", "yes", "on", "all"}:
            return True
        return self._is_high_impact_tool(tool_name)

    @staticmethod
    def _summarize_tool_params(params: Dict[str, Any]) -> Dict[str, Any]:
        if not params:
            return {}
        summary: Dict[str, Any] = {}
        redaction_tokens = (
            "password", "pass", "token", "api_key", "apikey", "secret",
            "client_secret", "authorization", "auth", "key",
        )
        for key, value in params.items():
            key_lower = str(key).lower()
            if any(token in key_lower for token in redaction_tokens):
                summary[key] = "[redacted]"
                continue
            if isinstance(value, str):
                summary[key] = value if len(value) <= 120 else value[:117] + "..."
            elif isinstance(value, list):
                summary[key] = value if len(value) <= 6 else {"items": len(value)}
            elif isinstance(value, dict):
                summary[key] = {"keys": list(value.keys())[:6], "size": len(value)}
            else:
                summary[key] = value
        return summary

    @staticmethod
    def _decision_type_for_tool(tool_name: str) -> DecisionType:
        name = (tool_name or "").lower()
        if any(token in name for token in ("gmail", "email")):
            return DecisionType.MESSAGE_RESPONSE
        if any(token in name for token in ("message", "sms", "whatsapp", "telegram", "signal", "discord")):
            return DecisionType.MESSAGE_RESPONSE
        if any(token in name for token in ("calendar", "meeting", "schedule", "invite")):
            return DecisionType.CALENDAR_CHANGE
        if "task" in name or "todo" in name:
            if any(token in name for token in ("complete", "completed", "done", "finish")):
                return DecisionType.TASK_COMPLETION
            return DecisionType.TASK_CREATION
        if any(token in name for token in ("delete", "remove", "update", "write", "edit", "create", "commit", "merge", "push", "upload", "publish", "save", "rename", "move")):
            return DecisionType.FILE_MODIFICATION
        if any(token in name for token in ("suppress", "mute", "silence", "notification")):
            return DecisionType.NOTIFICATION_SUPPRESS
        return DecisionType.OTHER

    def _log_tool_decision(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        source_info: Optional[Dict[str, Any]] = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        if not self._should_log_tool_decision(tool_name, context):
            return
        decision_type = self._decision_type_for_tool(tool_name)
        summarized_params = self._summarize_tool_params(params or {})
        convo_id = self._normalize_conversation_id((context or {}).get("conversation_id"))
        action = f"Executed tool {tool_name}"
        reasoning = "State-changing tool executed via tool orchestrator"
        ctx = {
            "tool": tool_name,
            "params": summarized_params,
            "conversation_id": convo_id,
            "source_type": (source_info or {}).get("source_type"),
            "server": (source_info or {}).get("server"),
            "categories": (source_info or {}).get("categories", []),
            "latency_ms": latency_ms,
            "confirmed_by_user": bool((context or {}).get("confirmed_by_user")),
            "secondary_source_verified": bool((context or {}).get("secondary_source_verified")),
        }
        try:
            self.log_decision(
                decision_type=decision_type,
                action=action,
                reasoning=reasoning,
                alternatives=["Skip tool execution", "Request confirmation"],
                confidence=0.85,
                context=ctx,
            )
        except Exception as exc:
            logger.debug("Decision ledger logging failed for tool %s: %s", tool_name, exc)

    def _publish_tool_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        event_bus = getattr(self, "event_bus", None)
        if not event_bus:
            return
        try:
            event_bus.publish(event_type, payload=payload, source="tool_orchestrator")
        except Exception:
            logger.debug("Suppressed Exception in vera")
            pass

    def _log_tool_block(
        self,
        tool_name: str,
        params: Dict[str, Any],
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        action: Optional[str] = None,
        decision_type: DecisionType = DecisionType.SAFETY_BLOCK,
        extra_context: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> None:
        mode = os.getenv("VERA_DECISION_LOG_TOOLS", "high").strip().lower()
        if mode in {"0", "false", "no", "off", "none"}:
            return
        if not force and not self._should_log_tool_decision(tool_name, context):
            return
        summarized_params = self._summarize_tool_params(params or {})
        convo_id = self._normalize_conversation_id((context or {}).get("conversation_id"))
        ctx = {
            "tool": tool_name,
            "params": summarized_params,
            "conversation_id": convo_id,
            "reason": reason,
            "confirmed_by_user": bool((context or {}).get("confirmed_by_user")),
            "secondary_source_verified": bool((context or {}).get("secondary_source_verified")),
        }
        if extra_context:
            ctx.update(extra_context)
        try:
            self.log_decision(
                decision_type=decision_type,
                action=action or f"Blocked tool {tool_name}",
                reasoning=reason,
                alternatives=["Cancel tool execution", "Request confirmation"],
                confidence=0.7,
                context=ctx,
            )
        except Exception as exc:
            logger.debug("Decision ledger logging failed for blocked tool %s: %s", tool_name, exc)

    def _maybe_require_two_source_confirmation(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        if os.getenv("VERA_TWO_SOURCE_RULE", "1").lower() not in {"1", "true", "yes", "on"}:
            return None
        if context and context.get("confirmed_by_user"):
            return None
        if context and context.get("secondary_source_verified"):
            return None
        if not self._is_high_impact_tool(tool_name):
            return None

        conversation_id = self._normalize_conversation_id(
            context.get("conversation_id") if context else None
        )
        sources = self._get_recent_untrusted_sources(conversation_id)
        unique_sources = {
            f"{src.get('source_type')}::{src.get('source_id')}" for src in sources
        }
        if not unique_sources or len(unique_sources) >= 2:
            return None

        now = time.time()
        self._pending_tool_confirmations[conversation_id] = {
            "tool_name": tool_name,
            "params": params,
            "context": context or {},
            "created_at": now,
            "expires_at": now + self._pending_confirmation_ttl_seconds,
            "safety_message": "Two-source rule confirmation required.",
            "matched_pattern": "two_source_rule",
        }
        self._persist_pending_tool_confirmations()
        logger.info(
            "Two-source rule confirmation required conversation_id=%s tool=%s",
            conversation_id,
            tool_name
        )
        return (
            "⚠️ Two-source rule: high-impact action based on untrusted data. "
            "Provide a second independent source or reply 'yes' to proceed."
        )

    def _should_store_tool_output(self, tool_name: str, context: Optional[Dict[str, Any]]) -> bool:
        if context and context.get("store_tool_output") is True:
            return True
        if os.getenv("VERA_TOOL_STORE_OUTPUTS", "0").lower() not in {"1", "true", "yes", "on"}:
            return False
        allow = self._parse_tool_list(os.getenv("VERA_TOOL_STORE_OUTPUTS_ALLOWLIST", ""))
        deny = self._parse_tool_list(os.getenv("VERA_TOOL_STORE_OUTPUTS_DENYLIST", ""))
        if deny and tool_name in deny:
            return False
        if allow and tool_name not in allow:
            return False
        return True

    async def _store_tool_output_event(
        self,
        tool_name: str,
        result: Any,
        source_info: Dict[str, Any],
        verification: Any,
        context: Optional[Dict[str, Any]]
    ) -> None:
        if not self.memory:
            return

        quarantine_sources = self._parse_tool_list(
            os.getenv("VERA_MEMORY_QUARANTINE_SOURCES", "web,media,repo,image,pdf,external")
        )
        source_type = source_info.get("source_type") or "tool"
        quarantine = source_type in quarantine_sources
        if verification and getattr(verification, "requires_confirmation", False):
            if not (context or {}).get("confirmed_by_user"):
                quarantine = True

        provenance = {
            "source_type": source_type,
            "source_id": source_info.get("source_id"),
            "tool": tool_name,
            "server": source_info.get("server"),
            "categories": source_info.get("categories", []),
            "verification_status": getattr(verification, "status", "unknown"),
            "verification_issues": getattr(verification, "issues", []),
            "verification_risk": getattr(verification, "risk_score", 0.0),
            "structured_output": getattr(verification, "structured", False),
            "quarantine": quarantine,
        }

        await self.memory.process_event({
            "type": "external_data",
            "content": result,
            "timestamp": datetime.now().isoformat(),
            "tags": ["tool_output", tool_name, source_type],
            "provenance": provenance,
            "created_by": "tool_execution",
        })

    def _skip_command_tree_for_tool(self, tool_name: str) -> bool:
        # Command-tree parsing is tuned for shell-like command strings. Structured
        # tool args (for example edit_file JSON payloads) can false-positive.
        raw = os.getenv("VERA_SAFETY_SKIP_COMMAND_TREE_TOOLS", "edit_file")
        skip_tools = {item.strip().lower() for item in raw.split(",") if item.strip()}
        return str(tool_name or "").strip().lower() in skip_tools

    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        fallback_depth: int = 0,
        fallback_chain: Optional[List[str]] = None,
        original_tool: Optional[str] = None,
        skip_safety: bool = False
    ) -> str:
        """
        Execute a tool with caching, safety checks, and error recovery.

        Pipeline:
        cache -> safety -> execution -> filtering -> selection memory -> cache store
        """
        context = context or {}
        conversation_id = self._normalize_conversation_id(context.get("conversation_id"))
        context["conversation_id"] = conversation_id
        start_time = time.time()

        # Emit thinking event for tool execution start
        thinking_tool(f"Calling {tool_name}...", tool=tool_name)

        if tool_name == "send_gmail_message":
            confirm = bool(params.get("confirm"))
            if not confirm:
                query = (context.get("query") or "").lower()
                if any(token in query for token in ("confirm send", "confirm email", "yes send", "send it")):
                    confirm = True
            if not confirm:
                to_addr = params.get("to", "")
                subject = params.get("subject", "")
                body = params.get("body", "")
                body_preview = body if len(body) <= 200 else body[:200] + "..."
                self._log_tool_block(
                    tool_name=tool_name,
                    params=params,
                    reason="Email confirmation required before sending.",
                    context=context,
                    action=f"Deferred tool {tool_name} pending confirmation",
                    decision_type=DecisionType.SAFETY_BLOCK,
                    extra_context={
                        "confirmation_required": True,
                        "recipient": to_addr,
                        "subject": subject,
                    },
                    force=True,
                )
                return (
                    "⚠️ Email confirmation required.\n"
                    f"To: {to_addr}\n"
                    f"Subject: {subject}\n"
                    f"Body: {body_preview}\n"
                    "Reply with 'confirm send' to proceed, or provide corrections."
                )
            params = {key: value for key, value in params.items() if key != "confirm"}

        skip_cache = tool_name in {"consult_quorum", "consult_swarm"}
        if not skip_cache:
            cached = self.cache.get(tool_name, params)
            if cached:
                thinking_tool(f"Cache hit for {tool_name}", tool=tool_name, cached=True)
                if self.config.observability:
                    self.observability.record_event("tool_cache_hit", tool=tool_name)
                self.tool_selection.record_result(
                    tool_name=tool_name,
                    context=context,
                    success=True,
                    latency=0.0
                )
                if self.flight_recorder:
                    try:
                        self.flight_recorder.record_tool_call(
                            tool_name=tool_name,
                            params=params,
                            result={
                                "cached": True,
                                "result_preview": str(cached)[:400],
                            },
                            success=True,
                            latency_ms=0.0,
                            conversation_id=conversation_id,
                            source_type="cache",
                            error=None,
                        )
                    except Exception:
                        logger.debug("Suppressed Exception in vera")
                        pass
                self._publish_tool_event(
                    "tool.completed",
                    {
                        "tool_name": tool_name,
                        "success": True,
                        "latency_ms": 0.0,
                        "conversation_id": conversation_id,
                        "source_type": "cache",
                        "cached": True,
                    },
                )
                return cached

        if not skip_safety:
            safety_context = {
                "tool_name": tool_name,
                "skip_command_tree": self._skip_command_tree_for_tool(tool_name),
            }
            safety_decision = self.safety_validator.validate(
                f"{tool_name} {json.dumps(params, ensure_ascii=True, default=str)}",
                context=safety_context,
            )
            if safety_decision.result == ValidationResult.BLOCKED:
                self._log_tool_block(
                    tool_name=tool_name,
                    params=params,
                    reason=f"Safety validator blocked tool: {safety_decision.matched_pattern}",
                    context=context,
                    action=f"Blocked tool {tool_name}",
                    decision_type=DecisionType.SAFETY_BLOCK,
                    extra_context={
                        "safety_message": safety_decision.message,
                        "matched_pattern": safety_decision.matched_pattern,
                        "safety_result": safety_decision.result.value,
                    },
                    force=True,
                )
                return f"⚠️ Safety Block: Tool execution rejected. Reason: {safety_decision.matched_pattern}"
            if safety_decision.result == ValidationResult.REQUIRES_CONFIRMATION:
                conversation_id = self._normalize_conversation_id(
                    context.get("conversation_id") if context else None
                )
                now = time.time()
                self._pending_tool_confirmations[conversation_id] = {
                    "tool_name": tool_name,
                    "params": params,
                    "context": context,
                    "created_at": now,
                    "expires_at": now + self._pending_confirmation_ttl_seconds,
                    "safety_message": safety_decision.message,
                    "matched_pattern": safety_decision.matched_pattern,
                }
                self._persist_pending_tool_confirmations()
                logger.info(
                    "Tool confirmation required conversation_id=%s tool=%s pattern=%s",
                    conversation_id,
                    tool_name,
                    safety_decision.matched_pattern
                )
                self._log_tool_block(
                    tool_name=tool_name,
                    params=params,
                    reason="Safety validator requires confirmation before tool execution.",
                    context=context,
                    action=f"Deferred tool {tool_name} pending confirmation",
                    decision_type=DecisionType.SAFETY_BLOCK,
                    extra_context={
                        "safety_message": safety_decision.message,
                        "matched_pattern": safety_decision.matched_pattern,
                        "safety_result": safety_decision.result.value,
                        "confirmation_required": True,
                    },
                    force=True,
                )
                return f"{safety_decision.message}\n\nReply 'yes' to proceed or 'no' to cancel."

        # --- Quorum auto-trigger for high-severity actions ---
        if (
            not skip_safety
            and safety_decision.severity >= 4
            and os.getenv("VERA_QUORUM_AUTO_TRIGGER", "0") == "1"
        ):
            convo_id = self._normalize_conversation_id(
                context.get("conversation_id") if context else None
            )
            auto_trigger_key = f"_quorum_auto_triggered_{convo_id}"
            if not getattr(self._owner, auto_trigger_key, False):
                try:
                    setattr(self._owner, auto_trigger_key, True)
                    advisory = await self._owner._run_quorum_tool(
                        mode="quorum",
                        params={
                            "question": (
                                f"Safety severity {safety_decision.severity} for "
                                f"tool '{tool_name}'. Should this proceed? "
                                f"Pattern: {safety_decision.matched_pattern}"
                            ),
                            "context": json.dumps(params, default=str)[:500],
                        },
                        manual=True,
                        trigger="auto_safety",
                    )
                    logger.info(
                        "Quorum auto-trigger advisory for %s (severity %d): %s",
                        tool_name, safety_decision.severity, advisory[:200],
                    )
                except Exception:
                    logger.debug(
                        "Quorum auto-trigger failed for %s", tool_name, exc_info=True
                    )

        two_source_message = self._maybe_require_two_source_confirmation(tool_name, params, context)
        if two_source_message:
            convo_id = self._normalize_conversation_id(
                context.get("conversation_id") if context else None
            )
            sources = self._get_recent_untrusted_sources(convo_id)
            source_types = sorted({src.get("source_type") for src in sources if src.get("source_type")})
            unique_sources = {
                f"{src.get('source_type')}::{src.get('source_id')}" for src in sources
            }
            self._log_tool_block(
                tool_name=tool_name,
                params=params,
                reason="Two-source rule requires secondary verification before high-impact tool execution.",
                context=context,
                action=f"Deferred tool {tool_name} pending secondary source verification",
                decision_type=DecisionType.SAFETY_BLOCK,
                extra_context={
                    "confirmation_required": True,
                    "untrusted_source_types": source_types,
                    "untrusted_source_count": len(unique_sources),
                },
                force=True,
            )
            return two_source_message

        source_info = self._resolve_tool_source(tool_name, params)
        quota_key = self._resolve_quota_key(tool_name, source_info)
        if quota_key and self.tool_quota:
            allowed, detail = self.tool_quota.check_and_record(quota_key)
            if not allowed:
                reason = f"Tool quota exceeded for {quota_key}: {detail or 'limit reached'}"
                self._log_tool_block(
                    tool_name=tool_name,
                    params=params,
                    reason=reason,
                    context=context,
                    action=f"Blocked tool {tool_name} due to quota",
                    decision_type=DecisionType.SAFETY_BLOCK,
                    extra_context={
                        "quota_key": quota_key,
                        "quota_detail": detail,
                    },
                    force=True,
                )
                return (
                    f"⚠️ Tool quota exceeded for {quota_key}"
                    f"{f' ({detail})' if detail else ''}. "
                    "Try later or adjust VERA_TOOL_QUOTA_OVERRIDES."
                )

        attempt = 1
        raw_result: Any = None
        tool_error: Optional[str] = None
        tool_success = False
        while True:
            try:
                if getattr(self, "cost_tracker", None):
                    budget_enforced = os.getenv("VERA_TOOL_BUDGET_ENFORCE", "0").strip().lower() in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
                    if budget_enforced:
                        budget_status = self.cost_tracker.check_budget(tool_name)
                        if budget_status in {
                            BudgetStatus.HARD_LIMIT_EXCEEDED,
                            BudgetStatus.TOOL_LIMIT_EXCEEDED,
                        }:
                            reason = (
                                "Session budget exceeded"
                                if budget_status == BudgetStatus.HARD_LIMIT_EXCEEDED
                                else "Tool usage limit exceeded"
                            )
                            self._log_tool_block(
                                tool_name=tool_name,
                                params=params,
                                reason=reason,
                                context=context,
                                action=f"Blocked tool {tool_name} due to budget",
                                decision_type=DecisionType.SAFETY_BLOCK,
                                extra_context={"budget_status": budget_status.value},
                                force=True,
                            )
                            return (
                                f"⚠️ {reason}. "
                                "Adjust session budget or tool limits before retrying."
                            )

                attempt_start = time.time()
                task_id = await self.tool_executor.invoke_tool(tool_name, params)
                task_result = await self.tool_executor.wait_for_task(task_id)
                status = task_result.get("status")
                if status == "completed":
                    raw_result = task_result.get("result")
                    embedded_error = self._extract_embedded_tool_error(raw_result)
                    if embedded_error:
                        raise RuntimeError(embedded_error)
                else:
                    raise RuntimeError(task_result.get("error", "Unknown tool error"))
                tool_success = True
                break
            except Exception as exc:
                tool_error = str(exc)
                decision = self.error_handler.handle_error(
                    tool_name=tool_name,
                    error_message=str(exc),
                    params=params,
                    attempt_number=attempt,
                    fallback_depth=fallback_depth,
                    fallback_chain=fallback_chain,
                    original_tool=original_tool
                )

                if decision.action == RecoveryAction.RETRY:
                    attempt += 1
                    await asyncio.sleep(decision.wait_seconds)
                    continue

                if decision.action == RecoveryAction.FALLBACK and decision.fallback_tool:
                    await asyncio.sleep(decision.wait_seconds)
                    return await self.execute_tool(
                        decision.fallback_tool,
                        decision.fallback_params or {},
                        context=context,
                        fallback_depth=decision.fallback_depth,
                        fallback_chain=decision.fallback_chain,
                        original_tool=decision.fallback_chain[0] if decision.fallback_chain else tool_name
                    )

                if decision.action == RecoveryAction.DEGRADE and decision.degraded_result is not None:
                    raw_result = decision.degraded_result
                    break

                latency = time.time() - start_time
                self.tool_selection.record_result(
                    tool_name=tool_name,
                    context=context,
                    success=False,
                    latency=latency,
                    error=str(exc)
                )
                if self.flight_recorder:
                    try:
                        self.flight_recorder.record_tool_call(
                            tool_name=tool_name,
                            params=params,
                            result={"error": str(exc)},
                            success=False,
                            latency_ms=latency * 1000,
                            conversation_id=conversation_id,
                            source_type="tool",
                            error=str(exc),
                        )
                    except Exception:
                        logger.debug("Suppressed Exception in vera")
                        pass
                self._publish_tool_event(
                    "tool.failed",
                    {
                        "tool_name": tool_name,
                        "success": False,
                        "error": str(exc),
                        "latency_ms": latency * 1000,
                        "conversation_id": conversation_id,
                    },
                )
                return decision.escalation_message or f"Error: {exc}"
            finally:
                if getattr(self, "cost_tracker", None):
                    try:
                        duration_ms = (time.time() - attempt_start) * 1000
                        self.cost_tracker.record_usage(
                            tool_name=tool_name,
                            duration_ms=duration_ms,
                            cached=False,
                        )
                    except Exception:
                        logger.debug("Suppressed Exception in vera")
                        pass

        verification = self.tool_output_verifier.verify(
            raw_result,
            source_type=source_info.get("source_type", ""),
            tool_name=tool_name
        )
        self._record_untrusted_source(conversation_id, source_info, verification)

        if os.getenv("VERA_TOOL_SANITIZE", "1") == "1":
            if self._should_sanitize_tool(tool_name):
                raw_result = self._sanitize_tool_output(raw_result)

        compressed, stats = self.output_filter.compress(
            raw_result,
            context=context,
            target_ratio=0.3
        )
        if isinstance(compressed, str):
            result_text = compressed
        else:
            result_text = json.dumps(compressed, ensure_ascii=True, default=str)

        latency = time.time() - start_time
        execution_success = bool(tool_success)

        # Emit thinking event for tool completion
        thinking_tool(
            f"Completed {tool_name} ({latency*1000:.0f}ms)",
            tool=tool_name,
            latency_ms=latency * 1000,
            success=execution_success
        )
        self.tool_selection.record_result(
            tool_name=tool_name,
            context=context,
            success=execution_success,
            latency=latency
        )

        if self.flight_recorder:
            try:
                self.flight_recorder.record_tool_call(
                    tool_name=tool_name,
                    params=params,
                    result=compressed,
                    success=tool_success,
                    latency_ms=latency * 1000,
                    conversation_id=conversation_id,
                    source_type=source_info.get("source_type", "tool"),
                    error=tool_error,
                )
            except Exception:
                logger.debug("Suppressed Exception in vera")
                pass

        if not skip_cache:
            self.cache.put(tool_name, params, result_text)

        if self.config.observability:
            self.observability.record_event(
                "tool_execution",
                tool=tool_name,
                latency_ms=stats.duration_ms,
                compression_ratio=stats.compression_ratio
            )

        if self.memory:
            try:
                await self.memory.process_event({
                    "type": "tool_execution",
                    "content": f"{tool_name} executed",
                    "timestamp": datetime.now().isoformat(),
                    "tags": ["tool", tool_name],
                    "provenance": {
                        "tool": tool_name,
                        "success": execution_success,
                        "source_type": source_info.get("source_type", "tool"),
                    },
                    "created_by": "tool_execution",
                })
            except Exception as exc:
                if self.config.debug:
                    logger.error(f"[DEBUG] Tool memory event failed: {exc}")

        if self._should_store_tool_output(tool_name, context):
            try:
                await self._store_tool_output_event(
                    tool_name,
                    compressed,
                    source_info,
                    verification,
                    context
                )
            except Exception as exc:
                if self.config.debug:
                    logger.error(f"[DEBUG] Tool output memory event failed: {exc}")

        if tool_success:
            self._log_tool_decision(
                tool_name=tool_name,
                params=params,
                context=context,
                source_info=source_info,
                latency_ms=latency * 1000,
            )

        self._publish_tool_event(
            "tool.completed",
            {
                "tool_name": tool_name,
                "success": tool_success,
                "latency_ms": latency * 1000,
                "conversation_id": conversation_id,
                "source_type": source_info.get("source_type", "tool"),
                "server": source_info.get("server"),
                "categories": source_info.get("categories", []),
            },
        )

        return result_text

    @staticmethod
    def _parse_tool_list(env_value: str) -> set:
        if not env_value:
            return set()
        return {item.strip() for item in env_value.split(",") if item.strip()}

    @classmethod
    def _should_sanitize_tool(cls, tool_name: str) -> bool:
        skip = cls._parse_tool_list(os.getenv("VERA_TOOL_SANITIZE_SKIP", ""))
        return tool_name not in skip

    @staticmethod
    def _sanitize_tool_output(raw_result: Any) -> Any:
        """
        Remove likely prompt-injection content from tool outputs.

        This is a conservative sanitizer that strips suspicious lines and drops
        high-risk keys from structured outputs.
        """
        import re

        line_patterns = [
            r"(?i)ignore (all|previous|prior) instructions",
            r"(?i)system prompt",
            r"(?i)developer message",
            r"(?i)role:\s*(system|developer)",
            r"(?i)BEGIN SYSTEM PROMPT",
            r"(?i)END SYSTEM PROMPT",
            r"(?i)###\s*instruction",
            r"(?i)tool call",
            r"(?i)function call",
            r"(?i)exfiltrat",
        ]
        key_pattern = re.compile(r"(?i)(prompt|system|instruction|role|tool_call|function_call)")
        allow_keys = {
            key.strip().lower()
            for key in os.getenv("VERA_TOOL_SANITIZE_ALLOW_KEYS", "").split(",")
            if key.strip()
        }
        compiled = [re.compile(pat) for pat in line_patterns]

        def sanitize_text(text: str) -> str:
            lines = text.splitlines()
            kept = []
            removed = 0
            for line in lines:
                if any(pat.search(line) for pat in compiled):
                    removed += 1
                    continue
                kept.append(line)
            if removed and not kept:
                return "[Tool output sanitized: content removed]"
            return "\n".join(kept) if removed else text

        def sanitize_value(value: Any, depth: int = 0) -> Any:
            if depth > 6:
                return value
            if isinstance(value, str):
                return sanitize_text(value)
            if isinstance(value, list):
                return [sanitize_value(item, depth + 1) for item in value]
            if isinstance(value, dict):
                cleaned = {}
                for k, v in value.items():
                    key_name = str(k).strip().lower()
                    if key_name in allow_keys:
                        cleaned[k] = sanitize_value(v, depth + 1)
                        continue
                    if key_pattern.search(str(k)):
                        continue
                    cleaned[k] = sanitize_value(v, depth + 1)
                return cleaned
            return value

        if isinstance(raw_result, (dict, list, str)):
            return sanitize_value(raw_result)

        # Try to parse JSON-like strings.
        if isinstance(raw_result, bytes):
            try:
                raw_result = raw_result.decode("utf-8", errors="replace")
                return sanitize_value(raw_result)
            except Exception:
                return raw_result

        return raw_result
