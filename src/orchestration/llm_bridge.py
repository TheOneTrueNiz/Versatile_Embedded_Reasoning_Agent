#!/usr/bin/env python3
"""
VERA 2.0 LLM Bridge
=====================

Provider-agnostic LLM bridge with tool-calling support and history management.
Supports fallback chains across multiple providers (Grok, Claude, Gemini, OpenAI).

Backward compatible: works with direct httpx calls (legacy) or ProviderRegistry.
"""

import json
import logging
import os
import time
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

import httpx

# Observable thinking stream
try:
    from core.runtime.thinking_stream import (
        emit_thinking, thinking_analyzing, thinking_routing, thinking_decision
    )
    THINKING_AVAILABLE = True
except ImportError:
    THINKING_AVAILABLE = False
    def emit_thinking(*args, **kwargs): pass
    def thinking_analyzing(*args, **kwargs): pass
    def thinking_routing(*args, **kwargs): pass
    def thinking_decision(*args, **kwargs): pass

try:
    from pydantic import BaseModel
    PYDANTIC_AVAILABLE = True
except ImportError:
    BaseModel = None  # type: ignore
    PYDANTIC_AVAILABLE = False

# Provider registry (optional - graceful fallback if not available)
try:
    from orchestration.providers.registry import ProviderRegistry
    PROVIDERS_AVAILABLE = True
except ImportError:
    ProviderRegistry = None  # type: ignore
    PROVIDERS_AVAILABLE = False

T = TypeVar("T")

logger = logging.getLogger(__name__)


# Backward-compatible alias
GrokReasoningBridge = None  # Set after class definition


class LLMBridge:
    """
    Provider-agnostic LLM bridge with tool-calling support.

    Supports two modes:
    1. Registry mode: Uses ProviderRegistry for multi-provider fallback
    2. Legacy mode: Direct httpx calls to a single endpoint (backward compat)

    Usage:
        # Registry mode (VERA 2.0)
        bridge = LLMBridge(vera_instance, registry=provider_registry)

        # Legacy mode (backward compatible)
        bridge = LLMBridge(vera_instance)

        response = await bridge.respond("Hello")
    """

    def __init__(
        self,
        vera_instance: Any,
        model: Optional[str] = None,
        base_url: str = "https://api.x.ai/v1",
        timeout: float = 60.0,
        max_tool_rounds: int = 5,
        registry: Optional[Any] = None,
    ):
        self.vera = vera_instance
        self.registry = registry  # ProviderRegistry for multi-provider fallback

        env_base_url = os.getenv("VERA_LLM_BASE_URL", "").strip()
        if env_base_url:
            base_url = env_base_url.rstrip("/")

        self.api_key = (
            os.getenv("VERA_LLM_API_KEY")
            or os.getenv("XAI_API_KEY")
            or os.getenv("API_KEY")
        )
        # Only require key if no registry and using a remote API
        if not self.api_key and not self.registry and self._requires_key(base_url):
            raise ValueError("XAI_API_KEY or API_KEY is required (or provide a ProviderRegistry)")

        self.model = model or os.getenv("VERA_MODEL", "grok-4-1-fast-reasoning")
        self.base_url = base_url
        self.timeout = timeout
        self.max_tool_rounds = max_tool_rounds
        self.history: List[Dict[str, Any]] = []
        self.last_tool_payload: Optional[Dict[str, Any]] = None
        self.last_model_used: Optional[str] = None
        self.last_tools_used: List[str] = []
        self.tool_execution_history: List[Dict[str, Any]] = []
        self._tool_aliases: Dict[str, Dict[str, str]] = {}
        self._active_workflow_plan: Dict[str, Any] = {}
        self._request_workflow_hint: Optional[Dict[str, Any]] = None
        self._genome_generation_config: Optional[Dict[str, Any]] = None
        self._genome_tool_overrides: Dict[str, Dict[str, Any]] = {}
        self._workflow_trace_debug = str(os.getenv("VERA_WORKFLOW_TRACE_DEBUG", "")).strip().lower() in {
            "1", "true", "yes", "on",
        }

        # Legacy direct client (used when no registry)
        self._client = httpx.AsyncClient(timeout=self.timeout, base_url=self.base_url)
        self._load_genome_overrides()

    def _trace_workflow(self, message: str, *args: Any) -> None:
        if not self._workflow_trace_debug:
            return
        logger.info("[workflow-debug] " + message, *args)

    @staticmethod
    def _normalize_task_text(task_text: str) -> str:
        return " ".join(str(task_text or "").strip().lower().split())

    @classmethod
    def _is_acknowledgement_turn(cls, task_text: str) -> bool:
        normalized = cls._normalize_task_text(task_text)
        if not normalized:
            return True
        acknowledgement_phrases = {
            "yes",
            "yes please",
            "y",
            "ok",
            "okay",
            "sure",
            "yep",
            "yup",
            "no",
            "n",
            "no thanks",
            "cancel",
            "thanks",
            "thank you",
            "great",
            "perfect",
            "sounds good",
            "looks good",
            "cool",
            "done",
        }
        return normalized in acknowledgement_phrases

    @staticmethod
    def _tool_result_requires_confirmation(result: Any) -> bool:
        lowered = str(result or "").strip().lower()
        if not lowered:
            return False
        return any(
            phrase in lowered
            for phrase in (
                "confirmation required",
                "awaiting confirmation",
                "reply 'yes' to proceed",
                "reply \"yes\" to proceed",
                "reply with 'yes' to proceed",
                "proceed? (yes/no)",
                "proceed (yes/no)",
            )
        )

    @staticmethod
    def _parse_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _workflow_chain_step_budget(self) -> int:
        raw = str(os.getenv("VERA_WORKFLOW_MAX_FORCED_STEPS", "")).strip()
        if raw:
            try:
                return max(1, int(raw))
            except (TypeError, ValueError):
                pass
        return max(1, int(self.max_tool_rounds) - 1)

    def _should_accept_workflow_chain(
        self,
        *,
        context: str,
        workflow_plan: Dict[str, Any],
        workflow_chain: List[str],
        explicit_tools: List[str],
        forced_tool: Optional[str],
    ) -> Tuple[bool, str]:
        chain = [
            str(name).strip()
            for name in workflow_chain
            if isinstance(name, str) and str(name).strip()
        ]
        if len(chain) < 2:
            return False, "chain_too_short"
        chain_budget = self._workflow_chain_step_budget()
        if len(chain) > chain_budget:
            return False, f"chain_exceeds_budget:{len(chain)}>{chain_budget}"
        if self._is_acknowledgement_turn(context):
            return False, "acknowledgement_turn"

        explicit = {str(name).strip() for name in explicit_tools if isinstance(name, str) and str(name).strip()}
        if explicit and explicit.isdisjoint(set(chain)):
            return False, "explicit_intent_mismatch"

        forced = str(forced_tool or "").strip()
        if forced and forced not in chain:
            return False, f"forced_tool_mismatch:{forced}"

        source = str(workflow_plan.get("source") or "").strip().lower()
        if source == "fuzzy":
            confidence = self._parse_float(workflow_plan.get("confidence"), 0.0)
            min_conf = self._parse_float(os.getenv("VERA_WORKFLOW_FUZZY_MIN_CONFIDENCE", "0.70"), 0.70)
            if min_conf < 0.0:
                min_conf = 0.0
            if min_conf > 1.0:
                min_conf = 1.0
            if confidence < min_conf:
                return False, f"fuzzy_low_confidence:{confidence:.3f}<{min_conf:.3f}"

        return True, "ok"

    def set_request_workflow_hint(
        self,
        task_text: str,
        workflow_plan: Optional[Dict[str, Any]],
    ) -> None:
        normalized_task = self._normalize_task_text(task_text)
        raw_plan = workflow_plan if isinstance(workflow_plan, dict) else {}
        plan = dict(raw_plan)
        chain = plan.get("tool_chain", [])
        if isinstance(chain, list):
            plan["tool_chain"] = [
                str(name).strip()
                for name in chain
                if isinstance(name, str) and str(name).strip()
            ]
        else:
            plan["tool_chain"] = []

        if not normalized_task or len(plan.get("tool_chain", [])) < 2:
            self._request_workflow_hint = None
            self._trace_workflow(
                "request_hint_clear task_len=%s chain=%s",
                len(normalized_task),
                list(plan.get("tool_chain", [])),
            )
            return

        self._request_workflow_hint = {
            "task_text": normalized_task,
            "workflow_plan": plan,
        }
        self._trace_workflow(
            "request_hint_set task_len=%s signature=%s chain=%s",
            len(normalized_task),
            str(plan.get("signature", "")),
            list(plan.get("tool_chain", [])),
        )

    def _consume_request_workflow_hint(self, context: Optional[str]) -> Dict[str, Any]:
        raw_hint = self._request_workflow_hint if isinstance(self._request_workflow_hint, dict) else {}
        self._request_workflow_hint = None
        if not raw_hint:
            return {}

        hinted_task = self._normalize_task_text(str(raw_hint.get("task_text", "")))
        context_task = self._normalize_task_text(context or "")
        if hinted_task and context_task and hinted_task != context_task:
            if hinted_task not in context_task and context_task not in hinted_task:
                self._trace_workflow(
                    "request_hint_drop reason=task_mismatch hint_len=%s context_len=%s",
                    len(hinted_task),
                    len(context_task),
                )
                return {}

        raw_plan = raw_hint.get("workflow_plan", {})
        if not isinstance(raw_plan, dict):
            self._trace_workflow("request_hint_drop reason=invalid_plan_type")
            return {}

        plan = dict(raw_plan)
        chain = plan.get("tool_chain", [])
        if not isinstance(chain, list):
            self._trace_workflow("request_hint_drop reason=invalid_chain_type")
            return {}
        normalized_chain = [
            str(name).strip()
            for name in chain
            if isinstance(name, str) and str(name).strip()
        ]
        if len(normalized_chain) < 2:
            self._trace_workflow("request_hint_drop reason=chain_too_short")
            return {}
        plan["tool_chain"] = normalized_chain
        return plan

    def _load_genome_overrides(self) -> None:
        try:
            from core.runtime.genome_config import load_genome_config
        except Exception:
            return
        try:
            config, validation = load_genome_config()
            if not validation.valid:
                return
            hyper = config.get("hyperparameters") or {}
            gen_cfg: Dict[str, Any] = {}
            if "temperature" in hyper:
                gen_cfg["temperature"] = float(hyper["temperature"])
            if gen_cfg:
                self._genome_generation_config = gen_cfg
            max_steps = hyper.get("max_steps")
            if max_steps is not None:
                try:
                    max_steps = int(max_steps)
                    self.max_tool_rounds = max(1, min(12, max_steps))
                except (TypeError, ValueError):
                    logger.debug("Suppressed TypeError, ValueError in llm_bridge")
                    pass

            tool_overrides: Dict[str, Dict[str, Any]] = {}
            for tool in config.get("tools", []) or []:
                name = tool.get("name")
                if name:
                    tool_overrides[name] = tool
            self._genome_tool_overrides = tool_overrides
        except Exception:
            return

    @staticmethod
    def _requires_key(base_url: str) -> bool:
        lowered = (base_url or "").lower()
        return not lowered or "api.x.ai" in lowered

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def close(self) -> None:
        """Close underlying HTTP client and provider registry."""
        await self._client.aclose()
        if self.registry is not None:
            try:
                await self.registry.close_all()
            except Exception:
                logger.debug("Suppressed Exception in llm_bridge")
                pass

    @staticmethod
    def _extract_explicit_tool_mentions(
        context: Optional[str],
        tool_names: List[str]
    ) -> List[str]:
        if not context:
            return []
        context_lower = context.lower()
        explicit_matches: List[str] = []

        def _record_match(name: str) -> None:
            if name not in explicit_matches:
                explicit_matches.append(name)

        # Respect explicit backticked tool names, including single-word tools
        # like `calculate` that do not contain underscores.
        for name in tool_names:
            if f"`{name}`" in context_lower:
                _record_match(name)
        explicit_candidates = [name for name in tool_names if "_" in name]
        for name in explicit_candidates:
            if re.search(rf"\\b{re.escape(name)}\\b", context_lower):
                _record_match(name)
        return explicit_matches

    @staticmethod
    def _detect_forced_tool_choice(
        context: Optional[str],
        tool_names: List[str]
    ) -> Optional[str]:
        if not context:
            return None
        context_lower = context.lower()
        tool_set = set(tool_names or [])
        explicit_matches = LLMBridge._extract_explicit_tool_mentions(context, tool_names)

        # Only force a tool when the user explicitly asks for exactly one.
        # When multiple explicit tool names are present, keep tool_choice=auto
        # so multi-tool chains are not accidentally collapsed.
        if len(explicit_matches) == 1:
            return explicit_matches[0]

        # Conservative intent forcing: only for direct action requests,
        # not "capability" questions ("can you", "is it possible", etc.).
        capability_query = (
            "?" in context_lower
            and any(
                phrase in context_lower
                for phrase in (
                    "can you",
                    "could you",
                    "would you",
                    "do you",
                    "are you able",
                    "is it possible",
                )
            )
        )
        action_request = any(
            phrase in context_lower
            for phrase in (
                "set ",
                "schedule",
                "book",
                "create ",
                "send ",
                "remind",
                "notify",
            )
        )

        if action_request and not capability_query:
            reminder_signal = any(
                phrase in context_lower
                for phrase in (
                    "remind me",
                    "set reminder",
                    "set a reminder",
                    "reminder",
                    "schedule",
                    "calendar",
                    "appointment",
                    "event",
                )
            )
            if reminder_signal:
                for name in ("create_event", "create_task", "create_task_list", "set_reminder"):
                    if name in tool_set:
                        return name

            push_signal = any(
                phrase in context_lower
                for phrase in (
                    "push",
                    "notification",
                    "notify",
                    "alert",
                    "ping",
                )
            )
            if push_signal:
                for name in ("send_native_push", "send_mobile_push", "send_sms", "send_mms"):
                    if name in tool_set:
                        return name
        return None

    def _select_model_for_task(
        self,
        user_message: str,
        selected_categories: List[str],
    ) -> Tuple[str, str]:
        """Select the optimal Grok model variant based on task signals.

        Uses confidence-scored detection so the right model activates
        whenever appropriate — not just from explicit trigger words.

        NOTE: Image and video generation are handled via native tools
        (generate_image, generate_video) that call dedicated xAI endpoints.
        The chat model stays as a reasoning model so it can decide to
        invoke those tools. This method only routes between reasoning
        and code models.

        Returns (model_name, reason) tuple.
        """
        text = user_message.lower()

        # -----------------------------------------------------------
        # Code task — scored (threshold: 2)
        # -----------------------------------------------------------
        code_score = 0

        code_keywords = (
            "write code", "write a function", "write a script",
            "write a program", "write a class", "write a method",
            "implement", "debug", "refactor",
            "code review", "fix bug", "fix the bug",
            "programming", "algorithm",
            "data structure", "api endpoint", "unittest", "test case",
            "compile", "syntax error", "runtime error",
            "python", "javascript", "typescript", "rust", "golang",
            "java", "c++", "swift", "kotlin", "sql query",
            "html", "css", "react", "vue", "angular",
            "node.js", "django", "flask", "fastapi",
            "sorting", "binary search", "linked list",
            "recursion", "regex", "parse", " function",
        )
        code_strong_signals = ("```", "def ", "function ", "class ", "import ", "const ", "var ", "let ")

        code_score += sum(1 for kw in code_keywords if kw in text)
        code_score += sum(3 for sig in code_strong_signals if sig in user_message)

        if "canvas" in selected_categories:
            code_score += 4

        if code_score >= 2:
            model = os.getenv("VERA_MODEL_CODE", "grok-code-fast-1")
            return model, f"code_task_detected (score={code_score})"

        # Default reasoning model
        return self.model, "default_reasoning"

    @staticmethod
    def _detect_media_generation_intent(user_message: str) -> Optional[str]:
        """Detect if the user wants image or video generation.

        Uses confidence-scored detection so media generation triggers
        from natural language — not just explicit keywords.

        Returns 'image', 'video', or None.
        """
        text = user_message.lower()

        # -----------------------------------------------------------
        # Video generation — scored (threshold: 2)
        # Checked BEFORE image because video intent is more specific
        # -----------------------------------------------------------
        video_score = 0

        video_strong = (
            "generate video", "generate a video", "create video",
            "create a video", "make a video", "make video",
            "render video", "produce a video",
            "video generation",
        )
        video_score += sum(3 for kw in video_strong if kw in text)
        if re.search(r"\b(generate|create|make|render|produce)\s+(?:an?\s+|another\s+)?video\b", text):
            video_score += 3

        video_medium = (
            "animate", "animation of", "video of", "clip of",
            "timelapse", "time-lapse", "motion graphics",
            "movie ", "film ", "short film", "cinematic video",
            "video showing", "video with", "animation", "loop",
            "video loop", "animated loop",
        )
        video_score += sum(2 for kw in video_medium if kw in text)

        video_weak = (
            "moving image", "in motion", "animated",
            "slow motion", "footage", "b-roll",
            "transition", "visual effect", "vfx", "looping",
            "seamless loop",
        )
        video_score += sum(1 for kw in video_weak if kw in text)

        if video_score >= 2:
            return "video"

        # -----------------------------------------------------------
        # Image generation — scored (threshold: 2)
        # -----------------------------------------------------------
        image_score = 0

        image_strong = (
            "generate image", "generate an image", "create image",
            "create an image", "make an image", "make image",
            "render image", "design image", "create a picture",
            "image generation",
        )
        image_score += sum(3 for kw in image_strong if kw in text)
        if re.search(r"\b(generate|create|make|render|design)\s+(?:an?\s+|another\s+)?image\b", text):
            image_score += 3

        image_medium = (
            "draw ", "draw me", "sketch ", "illustration",
            "logo", "picture of", "photo of", "portrait of",
            "poster", "infographic", "wallpaper", "artwork",
            "meme", "comic", "icon of", "thumbnail",
            "concept art", "sticker", "avatar",
            "show me what", "looks like",
        )
        image_score += sum(2 for kw in image_medium if kw in text)

        image_weak = (
            "visualize", "what does",
            "how would it look", "imagine ", "depict",
            "style of", "aesthetic", "photorealistic",
            "cartoon", "pixel art", "watercolor", "oil painting",
            "painting", "3d render", "digital art",
            "landscape", "scene of", "cinematic",
            "high resolution", "4k", "8k",
        )
        image_score += sum(1 for kw in image_weak if kw in text)

        if image_score >= 2:
            return "image"

        return None

    @staticmethod
    def _response_claims_generated_media(response_text: str, media_type: str) -> bool:
        """Detect placeholder-style media success claims in plain text."""
        text = str(response_text or "").lower()
        if not text:
            return False

        if media_type == "video":
            markers = ("embedded video", "generated video", ".mp4", " video:")
        else:
            markers = ("embedded image", "generated image", ".png", ".jpg", ".jpeg", ".webp", " image:")
        return any(marker in text for marker in markers)

    def _resolve_media_retry_tool(
        self,
        user_message: str,
        assistant_content: str,
        available_tool_names: List[str],
    ) -> Optional[str]:
        """Pick media tool to force when intent/claim exists but no tool call happened."""
        available = {str(name).strip() for name in (available_tool_names or []) if str(name).strip()}

        media_intent = self._detect_media_generation_intent(str(user_message or ""))
        if media_intent == "video" and "generate_video" in available:
            return "generate_video"
        if media_intent == "image" and "generate_image" in available:
            return "generate_image"

        if self._response_claims_generated_media(assistant_content, "video") and "generate_video" in available:
            return "generate_video"
        if self._response_claims_generated_media(assistant_content, "image") and "generate_image" in available:
            return "generate_image"
        return None

    @staticmethod
    def _media_tool_for_intent(media_intent: Optional[str]) -> Optional[str]:
        if media_intent == "video":
            return "generate_video"
        if media_intent == "image":
            return "generate_image"
        return None

    @staticmethod
    def _detect_live_data_intent(user_message: str) -> bool:
        """Detect if the query requires live/current data that should NOT be
        answered from training data alone.

        Returns True if a web search tool should be forced.
        """
        text = user_message.lower()

        # Skip pure capability questions ("can you do X?" not "can you tell me X?")
        capability_phrases = ("are you able to", "do you have the ability", "how do you")
        if any(p in text for p in capability_phrases):
            return False
        # "Can you [verb]?" is a capability question, but "can you tell/get/find me" is a request
        if text.startswith("can you") and not any(
            text.startswith(f"can you {v}") for v in (
                "tell", "get", "find", "check", "look up", "search", "show",
                "give", "fetch", "pull", "grab", "please",
            )
        ):
            return False

        score = 0

        # Strong temporal signals (3 points each)
        temporal_strong = (
            "current price", "price of", "price today",
            "right now", "currently trading", "live price",
            "latest news", "breaking news", "today's news",
            "current weather", "weather today", "weather right now",
            "forecast for", "weather forecast",
            "latest score", "game score", "who won",
            "stock price", "share price", "market cap",
            "exchange rate", "interest rate",
            "who is the current", "who is the president",
            "who is the speaker", "who is the ceo",
            "is it open", "is it available", "hours today",
        )
        score += sum(3 for kw in temporal_strong if kw in text)

        # Medium temporal signals (2 points each)
        temporal_medium = (
            "current", "right now", "today", "tonight",
            "this week", "this month", "latest",
            "as of now", "at the moment", "presently",
            "up to date", "most recent", "just happened",
            "how much is", "how much does",
            "what is the price", "what's the price",
        )
        score += sum(2 for kw in temporal_medium if kw in text)

        # Weak signals — topics that change frequently (1 point each)
        temporal_weak = (
            "bitcoin", "btc", "ethereum", "eth", "crypto",
            "litecoin", "dogecoin", "solana", "xrp",
            "stock", "nasdaq", "s&p", "dow jones",
            "weather", "temperature", "forecast",
            "election", "poll", "vote",
            "headline", "breaking",
            "gas price", "oil price", "gold price",
            "flight", "hotel", "availability",
            "score", "standings", "roster", "playoffs",
        )
        score += sum(1 for kw in temporal_weak if kw in text)

        return score >= 3

    @staticmethod
    def _read_int_env(name: str, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
        raw = os.getenv(name, "").strip()
        if not raw:
            value = default
        else:
            try:
                value = int(raw)
            except (TypeError, ValueError):
                value = default
        if min_value is not None and value < min_value:
            value = min_value
        if max_value is not None and value > max_value:
            value = max_value
        return value

    @staticmethod
    def _parse_blocked_tools(raw: str) -> set[str]:
        if not raw:
            return set()
        lowered = raw.strip().lower()
        if lowered in {"0", "false", "off", "none", "no"}:
            return set()
        return {item.strip().lower() for item in raw.split(",") if item.strip()}

    def _is_tool_blocked(self, server_name: str, tool_name: str) -> bool:
        blocked = self._parse_blocked_tools(os.getenv("VERA_TOOL_BLOCKLIST", ""))
        if not blocked:
            return False
        server = (server_name or "").strip().lower()
        tool = (tool_name or "").strip().lower()
        if not tool:
            return False
        if tool in blocked:
            return True
        if server and f"{server}:{tool}" in blocked:
            return True
        if server and f"{server}:*" in blocked:
            return True
        return False

    def _ordered_server_names(
        self,
        available_from_defs: Dict[str, List[str]],
        available_from_names: Dict[str, List[str]],
    ) -> List[str]:
        seen = set()
        ordered: List[str] = []

        config_order: List[str] = []
        if self.vera and getattr(self.vera, "mcp", None):
            configs = getattr(self.vera.mcp, "configs", {}) or {}
            for server_name in configs.keys():
                if server_name in available_from_defs or server_name in available_from_names:
                    config_order.append(server_name)

        for server_name in config_order:
            if server_name not in seen:
                seen.add(server_name)
                ordered.append(server_name)

        extras = sorted(
            (set(available_from_defs.keys()) | set(available_from_names.keys())) - set(ordered)
        )
        for server_name in extras:
            if server_name not in seen:
                seen.add(server_name)
                ordered.append(server_name)
        return ordered

    @staticmethod
    def _make_tool_alias(server_name: str, tool_name: str, taken_names: set) -> str:
        base = f"{server_name}__{tool_name}".replace("-", "_")
        alias = base
        idx = 2
        while alias in taken_names:
            alias = f"{base}__{idx}"
            idx += 1
        return alias

    def _resolve_tool_alias(
        self,
        tool_name: str,
        params: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any]]:
        alias = self._tool_aliases.get(tool_name)
        if not alias:
            return tool_name, params

        resolved_name = alias.get("tool") or tool_name
        resolved_server = alias.get("server") or ""
        resolved_params = dict(params or {})
        if resolved_server:
            resolved_params["__mcp_server"] = resolved_server
        return resolved_name, resolved_params

    async def _build_tool_schemas(
        self,
        context: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], List[str]]:
        """
        Build tool schemas for the LLM from MCP.

        Tool selection defaults to a lightweight auto-filter to avoid oversized
        payloads when many MCP servers are enabled. Override with:
        - VERA_TOOL_MODE=all|auto|core|none
        - VERA_TOOL_MAX=<int> (optional cap)
        """
        if not self.vera:
            return [], None, []

        # Emit thinking event for tool selection start
        thinking_analyzing("Analyzing query for tool selection...")

        tool_mode = os.getenv("VERA_TOOL_MODE", "auto").lower()
        router_enabled = os.getenv("VERA_TOOL_ROUTER", "0").strip().lower() in {"1", "true", "yes", "on"}
        include_full = os.getenv("VERA_TOOL_PAYLOAD_FULL", "0").strip().lower() in {"1", "true", "yes", "on"}
        router_max = 0
        default_tool_max = 0 if tool_mode == "all" else 30
        tool_max = self._read_int_env("VERA_TOOL_MAX", default_tool_max, min_value=0)
        auto_hits: Dict[str, str] = {}

        native_tools: List[Dict[str, Any]] = []
        if getattr(self.vera, "get_tool_definitions", None):
            native_tools = list(getattr(self.vera, "_native_tool_defs", []))

        if tool_mode == "none":
            return native_tools, None, []

        if not getattr(self.vera, "mcp", None):
            return native_tools, None, []

        available_defs = {}
        if getattr(self.vera.mcp, "get_available_tool_defs", None):
            available_defs = self.vera.mcp.get_available_tool_defs()

        available_from_defs = {
            server_name: [
                tool_def.get("name")
                for tool_def in tool_defs
                if isinstance(tool_def, dict) and tool_def.get("name")
            ]
            for server_name, tool_defs in available_defs.items()
        }

        available_from_names: Dict[str, List[str]] = {}
        if getattr(self.vera.mcp, "get_available_tools", None):
            try:
                available_from_names = self.vera.mcp.get_available_tools()
            except Exception:
                available_from_names = {}

        # Merge def-based + name-based discovery so partial tool-def timeouts
        # do not collapse tool visibility for otherwise healthy MCP servers.
        available: Dict[str, List[str]] = {}
        for server_name in self._ordered_server_names(available_from_defs, available_from_names):
            merged: List[str] = []
            for tool_name in (available_from_defs.get(server_name) or []) + (available_from_names.get(server_name) or []):
                if isinstance(tool_name, str) and tool_name and tool_name not in merged:
                    merged.append(tool_name)
            if merged:
                available[server_name] = merged

        if not available:
            available = available_from_names

        # Optional policy-level blocklist for tools that should not be exposed
        # to the LLM router (e.g. endpoints unavailable on current provider tier).
        filtered_available: Dict[str, List[str]] = {}
        for server_name, tool_names in available.items():
            keep = [name for name in tool_names if not self._is_tool_blocked(server_name, name)]
            if keep:
                filtered_available[server_name] = keep
            elif logger.isEnabledFor(logging.DEBUG):
                logger.debug("All tools blocked for server %s by VERA_TOOL_BLOCKLIST", server_name)
        available = filtered_available

        filtered_defs: Dict[str, List[Dict[str, Any]]] = {}
        for server_name, tool_defs in available_defs.items():
            keep_defs: List[Dict[str, Any]] = []
            for tool_def in tool_defs or []:
                if isinstance(tool_def, dict):
                    tool_name = str(tool_def.get("name") or "")
                    if tool_name and self._is_tool_blocked(server_name, tool_name):
                        continue
                    keep_defs.append(tool_def)
                elif isinstance(tool_def, str):
                    if self._is_tool_blocked(server_name, tool_def):
                        continue
                    keep_defs.append({"name": tool_def})
            if keep_defs:
                filtered_defs[server_name] = keep_defs
        available_defs = filtered_defs

        context_text = (context or "").lower()
        def _read_bias(name: str, default: float) -> float:
            raw = os.getenv(name, "").strip()
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        recency_bias = _read_bias("VERA_ROUTER_RECENCY_BIAS", 1.0)
        reliability_bias = _read_bias("VERA_ROUTER_RELIABILITY_BIAS", 1.0)
        grounding_bias = _read_bias("VERA_ROUTER_GROUNDING_BIAS", 1.0)
        user_priority_bias = _read_bias("VERA_ROUTER_USER_PRIORITY_BIAS", 1.0)
        grounding_threshold = _read_bias("VERA_ROUTER_GROUNDING_THRESHOLD", 1.0)
        bias_threshold = _read_bias("VERA_ROUTER_BIAS_THRESHOLD", 0.9)
        long_context_trigger = self._read_int_env("VERA_LONG_CONTEXT_TRIGGER_CHARS", 2200, min_value=0)
        grounding_keywords = (
            "research",
            "deep research",
            "grounding",
            "citations",
            "citation",
            "sources",
            "source",
            "evidence",
        )
        verification_keywords = (
            "verify",
            "check",
            "confirm",
            "prove",
            "fact check",
            "fact-check",
            "stats",
            "statistics",
            "data",
            "numbers",
            "references",
            "peer review",
            "peer-reviewed",
        )
        recency_keywords = (
            "latest",
            "current",
            "today",
            "this week",
            "this month",
            "this year",
            "recent",
            "recently",
            "now",
            "breaking",
            "update",
        )
        time_of_day_pattern = re.compile(
            r"\b\d{1,2}:\d{2}\s*(am|pm)?\b|\b\d{1,2}\s*(am|pm)\b"
        )
        time_zone_pattern = re.compile(
            r"\b(utc|gmt|est|cst|mst|pst|edt|cdt|mdt|pdt|bst|cet|cest|jst|kst|aest|acst|awst|nzst|nzdt)\b"
        )
        question_keywords = (
            "who",
            "what",
            "when",
            "where",
            "why",
            "how",
            "which",
            "top",
            "best",
            "rank",
            "list",
            "compare",
            "difference",
            "define",
            "meaning",
            "explain",
        )
        factual_keywords = (
            "who is",
            "what is",
            "when did",
            "where is",
            "born",
            "founded",
            "founder",
            "ceo",
            "headquarters",
            "population",
            "capital",
            "height",
            "weight",
            "distance",
            "age",
        )
        summarize_keywords = (
            "summary",
            "summarize",
            "summariser",
            "summarizer",
            "tl;dr",
            "tldr",
        )
        long_context_keywords = (
            "synthesize",
            "recap",
            "long document",
            "long text",
            "large document",
            "full report",
            "entire document",
            "multi page",
            "many pages",
            "whitepaper",
        )
        news_keywords = (
            "news",
            "headline",
            "reported",
            "report",
            "press release",
            "announced",
            "announcement",
            "breaking news",
            "coverage",
            "journal",
            "publication",
        )
        pricing_keywords = (
            "price",
            "pricing",
            "cost",
            "budget",
            "msrp",
            "discount",
            "sale",
            "fee",
            "subscription",
            "plan",
            "quote",
        )
        finance_keywords = (
            "stock",
            "shares",
            "ticker",
            "earnings",
            "revenue",
            "profit",
            "guidance",
            "market cap",
            "valuation",
            "p/e",
            "pe ratio",
            "dividend",
            "yield",
        )
        macro_keywords = (
            "rate",
            "interest",
            "apr",
            "inflation",
            "cpi",
            "gdp",
            "unemployment",
            "exchange rate",
            "fx",
            "percent",
            "percentage",
        )
        spec_keywords = (
            "benchmark",
            "performance",
            "latency",
            "accuracy",
            "throughput",
            "fps",
            "battery life",
            "capacity",
            "specs",
            "specifications",
            "dimensions",
            "weight",
            "speed",
        )
        release_keywords = (
            "release date",
            "launch",
            "version",
            "changelog",
            "patch",
            "update",
            "cve",
            "vulnerability",
        )
        creative_keywords = (
            "poem",
            "story",
            "fiction",
            "novel",
            "lyrics",
            "brainstorm",
            "creative",
            "imagine",
            "roleplay",
        )
        user_priority_keywords = (
            "need to",
            "must",
            "asap",
            "urgent",
            "please",
            "send",
            "schedule",
            "book",
            "create",
            "update",
            "delete",
            "upload",
            "share",
            "move",
            "email",
            # Payment/Transaction
            "checkout",
            "purchase",
            "buy",
            "order",
            "payment",
            "charge",
            "refund",
            "invoice",
            "bill",
        )
        # Math/Computation keywords (triggers sandbox, knowledge)
        math_keywords = (
            "calculate",
            "compute",
            "solve",
            "equation",
            "formula",
            "algorithm",
            "analysis",
            "math",
            "arithmetic",
            "algebra",
            "geometry",
            "calculus",
            "convert",
            "conversion",
        )
        # Language/Translation keywords (triggers knowledge tools)
        translation_keywords = (
            "translate",
            "translation",
            "language",
            "spanish",
            "french",
            "german",
            "chinese",
            "japanese",
            "korean",
            "portuguese",
            "italian",
            "russian",
            "arabic",
            "hindi",
            "en español",
            "en français",
            "auf deutsch",
        )
        # Code quality keywords (triggers dev tools)
        code_quality_keywords = (
            "test",
            "unittest",
            "pytest",
            "coverage",
            "lint",
            "linting",
            "formatter",
            "prettier",
            "eslint",
            "ci/cd",
            "pipeline",
            "build",
            "deploy",
            "debug",
        )
        # Video/multimedia keywords (triggers media tools)
        video_keywords = (
            "video",
            "youtube",
            "stream",
            "recording",
            "screen capture",
            "screencast",
            "clip",
            "watch",
            "movie",
            "film",
            "trailer",
        )
        reminder_keywords = (
            "remind me",
            "set reminder",
            "set a reminder",
            "reminder",
            "schedule",
            "calendar",
            "appointment",
            "event",
            "due",
        )
        push_keywords = (
            "push",
            "notification",
            "notify",
            "alert",
            "ping",
            "oneplus",
            "tablet",
            "phone",
            "device",
        )

        explicit_grounding = any(keyword in context_text for keyword in grounding_keywords)
        verification_signal = any(keyword in context_text for keyword in verification_keywords)
        recency_signal = any(keyword in context_text for keyword in recency_keywords)
        news_signal = any(keyword in context_text for keyword in news_keywords)
        pricing_signal = any(keyword in context_text for keyword in pricing_keywords)
        finance_signal = any(keyword in context_text for keyword in finance_keywords)
        macro_signal = any(keyword in context_text for keyword in macro_keywords)
        spec_signal = any(keyword in context_text for keyword in spec_keywords)
        release_signal = any(keyword in context_text for keyword in release_keywords)
        year_signal = bool(re.search(r"\b(19|20)\d{2}\b", context_text))
        number_signal = any(char.isdigit() for char in context_text)
        time_signal = bool(
            time_of_day_pattern.search(context_text) or time_zone_pattern.search(context_text)
        )
        question_signal = (
            "?" in context_text
            or any(context_text.startswith(f"{keyword} ") for keyword in question_keywords)
            or any(f" {keyword} " in context_text for keyword in question_keywords)
        )
        factual_signal = any(keyword in context_text for keyword in factual_keywords)
        creative_signal = any(keyword in context_text for keyword in creative_keywords)
        should_expose_summary = any(keyword in context_text for keyword in summarize_keywords)
        user_priority_signal = any(keyword in context_text for keyword in user_priority_keywords)
        phone_keywords = [
            "call me",
            "call you",
            "call him",
            "call her",
            "call them",
            "call us",
            "call back",
            "phone call",
            "phone me",
            "give me a call",
            "dial",
            "ring",
            "call ",
        ]
        phone_hit = next((keyword for keyword in phone_keywords if keyword in context_text), None)
        math_signal = any(keyword in context_text for keyword in math_keywords)
        translation_signal = any(keyword in context_text for keyword in translation_keywords)
        code_quality_signal = any(keyword in context_text for keyword in code_quality_keywords)
        video_signal = any(keyword in context_text for keyword in video_keywords)
        reminder_signal = any(keyword in context_text for keyword in reminder_keywords)
        push_signal = any(keyword in context_text for keyword in push_keywords)
        time_recency_signal = time_signal and (
            recency_signal
            or news_signal
            or release_signal
            or verification_signal
            or pricing_signal
            or finance_signal
            or macro_signal
            or spec_signal
            or question_signal
        )
        number_or_time_signal = number_signal or time_recency_signal
        long_context_signal = len(context_text) >= long_context_trigger or any(
            keyword in context_text for keyword in (*summarize_keywords, *long_context_keywords)
        )
        grounding_score = (
            grounding_bias * (1.0 if explicit_grounding else 0.0)
            + reliability_bias * (1.0 if (verification_signal or factual_signal) else 0.0)
            + recency_bias * (
                1.0
                if (
                    recency_signal
                    or time_recency_signal
                    or news_signal
                    or release_signal
                    or year_signal
                    or number_signal
                )
                else 0.0
            )
            + user_priority_bias * (1.0 if question_signal else 0.0)
        )
        should_expose_grounding = grounding_score >= grounding_threshold or (
            number_or_time_signal
            and (
                verification_signal
                or recency_signal
                or time_recency_signal
                or news_signal
                or pricing_signal
                or finance_signal
                or macro_signal
                or spec_signal
                or release_signal
                or question_signal
            )
            and not creative_signal
        )
        reserved_slots = 1 if should_expose_grounding else 0
        if tool_max and reserved_slots > tool_max:
            reserved_slots = tool_max

        core_servers = ["filesystem", "memory", "time", "sequential-thinking"]
        core_categories = {"files", "memory", "time", "reasoning"}

        category_defs = {
            "files": "Local file operations and project data access.",
            "memory": "Long-term memory storage and retrieval.",
            "time": "Time, dates, and timezone utilities.",
            "reasoning": "Step-by-step decomposition or structured thinking.",
            "math": "Deterministic arithmetic and conversion operations.",
            "web": "Web search, grounding, recency, and external facts.",
            "knowledge": "Encyclopedic knowledge sources (Wikipedia/Grokipedia).",
            "workspace": "Email (Gmail), Calendar, Drive, Docs, Sheets, Slides, Tasks, Chat.",
            "dev": "GitHub repositories, issues, PRs, and code lookups.",
            "pdf": "PDF parsing, OCR, and document extraction.",
            "media": "Media/archival tools like memvid.",
            "browser": "Browser automation and web UI control.",
            "desktop": "Desktop automation and OS-level control.",
            "phone": "Telephony tools (call-me) for placing phone calls.",
            "messaging": "SMS/MMS delivery and text-based notifications.",
            "sms": "Text-only messaging (SMS).",
            "mms": "Media messaging (MMS).",
            "image_gen": "Image generation from text prompts.",
            "long_context": "Recursive summarization for large inputs or synthesis tasks.",
            "canvas": "Code editor canvas for collaborative coding and file editing.",
            "social": "Social media tools (Twitter/X, Facebook, Instagram, LinkedIn).",
            "automation": "Third-party app integration and workflow automation (Composio).",
            "finance": "Trading, crypto, forex, and financial market tools.",
        }

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
            "calculator": ["math", "utility", "sandbox"],
            "call-me": ["phone", "voice", "messaging", "sms", "mms"],
            "composio": ["social", "email", "automation"],
            "x-twitter": ["social"],
            "nofx-trading": ["finance", "trading"],
            "scrapeless": ["web", "scraping"],
        }

        server_categories: Dict[str, List[str]] = {}
        if getattr(self.vera, "mcp", None) and getattr(self.vera.mcp, "configs", None):
            for name, config in self.vera.mcp.configs.items():
                server_categories[name] = list(getattr(config, "categories", []) or [])
        for name in available:
            if not server_categories.get(name):
                server_categories[name] = fallback_server_categories.get(name, [])

        native_tool_categories: Dict[str, List[str]] = {}
        for tool_name in list(getattr(self.vera, "_native_tool_handlers", {}).keys()):
            if tool_name.startswith("browser_"):
                native_tool_categories[tool_name] = ["browser", "web"]
            elif tool_name.startswith("desktop_"):
                native_tool_categories[tool_name] = ["desktop"]
            elif tool_name.startswith("pdf_"):
                native_tool_categories[tool_name] = ["pdf"]
            elif tool_name.startswith("editor_"):
                native_tool_categories[tool_name] = ["canvas", "files"]
            elif tool_name == "generate_image":
                native_tool_categories[tool_name] = ["image_gen"]
            elif tool_name == "generate_video":
                native_tool_categories[tool_name] = ["video_gen"]
            elif tool_name == "recursive_summarize":
                native_tool_categories[tool_name] = ["long_context", "memory", "pdf"]

        selected_categories: List[str] = []
        if tool_mode == "all":
            selected_servers = list(available.keys())
            selected_categories = list({*category_defs.keys(), *core_categories})
        else:
            selected_servers = [name for name in core_servers if name in available]

            if tool_mode == "auto":
                if router_enabled:
                    category_max = self._read_int_env("VERA_TOOL_ROUTER_CATEGORY_MAX", 4, min_value=0)
                    selected_categories = await self._route_tool_categories(
                        context or "",
                        category_defs,
                        category_max,
                    )
                    workspace_keywords = [
                        "email",
                        "mail",
                        "gmail",
                        "inbox",
                        "compose",
                        "draft",
                        "send email",
                        "send mail",
                        "drive",
                        "calendar",
                        "docs",
                        "sheets",
                        "slides",
                        "forms",
                        "tasks",
                        "chat",
                        "workspace",
                        "meeting",
                        "schedule",
                        "invite",
                        "appointment",
                        "attachment",
                        "my documents",
                        "google doc",
                        "spreadsheet",
                        "reminder",
                        "remind",
                    ]
                    workspace_hit = next(
                        (keyword for keyword in workspace_keywords if keyword in context_text),
                        None,
                    )
                    messaging_keywords = [
                        "push",
                        "notification",
                        "notify",
                        "alert",
                        "ping",
                        "text",
                        "sms",
                        "mms",
                        "message me",
                        "send message",
                        "send a message",
                    ]
                    messaging_hit = next(
                        (keyword for keyword in messaging_keywords if keyword in context_text),
                        None,
                    )
                    if workspace_hit and "workspace" not in selected_categories:
                        selected_categories.append("workspace")
                        auto_hits["workspace"] = workspace_hit
                    if phone_hit and "phone" not in selected_categories:
                        selected_categories.append("phone")
                        auto_hits["phone"] = phone_hit
                    if messaging_hit and "messaging" not in selected_categories:
                        selected_categories.append("messaging")
                        auto_hits["messaging"] = messaging_hit
                    if long_context_signal and "long_context" not in selected_categories:
                        selected_categories.append("long_context")
                        auto_hits["long_context"] = "summarize"
                    bias_categories = {}
                    if should_expose_grounding:
                        bias_categories["web"] = grounding_score
                    if user_priority_signal and workspace_hit:
                        bias_categories["workspace"] = user_priority_bias
                    if reminder_signal:
                        bias_categories["workspace"] = max(
                            bias_categories.get("workspace", 0.0),
                            user_priority_bias,
                        )
                    if push_signal:
                        bias_categories["messaging"] = user_priority_bias
                    if long_context_signal:
                        bias_categories["long_context"] = user_priority_bias
                    # New signal-based category inclusion
                    if math_signal:
                        bias_categories["math"] = reliability_bias
                        bias_categories["sandbox"] = reliability_bias
                    if translation_signal:
                        bias_categories["knowledge"] = reliability_bias
                    if code_quality_signal:
                        bias_categories["dev"] = reliability_bias
                    if video_signal:
                        bias_categories["media"] = user_priority_bias
                    # Social / Automation / Finance signal detection
                    social_keywords = (
                        "twitter", "tweet", "x.com", "social media", "social",
                        "facebook", "instagram", "trending", "hashtag",
                    )
                    automation_keywords = (
                        "composio", "automate", "automation", "workflow",
                        "integration", "agent mail", "agentmail",
                    )
                    finance_keywords = (
                        "trade", "trading", "crypto", "bitcoin", "forex",
                        "portfolio", "nofx", "exchange",
                    )
                    if any(kw in context_text for kw in social_keywords):
                        bias_categories["social"] = user_priority_bias
                    if any(kw in context_text for kw in automation_keywords):
                        bias_categories["automation"] = user_priority_bias
                    if any(kw in context_text for kw in finance_keywords):
                        bias_categories["finance"] = user_priority_bias
                    for name, score in bias_categories.items():
                        if score >= bias_threshold and name not in selected_categories:
                            selected_categories.append(name)
                    selected_categories = list({*selected_categories, *core_categories})
                    if should_expose_grounding or should_expose_summary:
                        selected_categories = list({*selected_categories, "web"})
                    selected_servers = [name for name in selected_servers if name in available]
                    for server_name, categories in server_categories.items():
                        if server_name not in available:
                            continue
                        if categories and set(categories).intersection(selected_categories):
                            if server_name not in selected_servers:
                                selected_servers.append(server_name)
                    if phone_hit and "call-me" in available and "call-me" not in selected_servers:
                        selected_servers.append("call-me")
                else:
                    category_keywords = {
                        "workspace": [
                            "email",
                            "mail",
                            "gmail",
                            "inbox",
                            "compose",
                            "draft",
                            "send email",
                            "send mail",
                            "drive",
                            "calendar",
                            "docs",
                            "sheets",
                            "slides",
                            "forms",
                            "tasks",
                            "chat",
                            "workspace",
                            "meeting",
                            "schedule",
                            "invite",
                            "appointment",
                            "attachment",
                            "my documents",
                            "google doc",
                            "spreadsheet",
                        ],
                        "dev": [
                            "github",
                            "repo",
                            "pull request",
                            "issue",
                            "commit",
                            "branch",
                            "pr",
                            "merge",
                            # Code quality triggers
                            "test",
                            "unittest",
                            "pytest",
                            "coverage",
                            "lint",
                            "linting",
                            "ci/cd",
                            "pipeline",
                            "build",
                            "deploy",
                            "debug",
                        ],
                        "web": [
                            "search",
                            "web",
                            "internet",
                            "grounding",
                            "citations",
                            "sources",
                            "research",
                            "evidence",
                            "news",
                            "price",
                            "pricing",
                            "cost",
                            "stock",
                            "ticker",
                            "earnings",
                            "rate",
                            "inflation",
                            "benchmark",
                            "performance",
                            "release date",
                            "update",
                            "cve",
                            "vulnerability",
                            "look up",
                            "find out",
                            "what is",
                            "who is",
                            "when did",
                            "current",
                            "latest",
                            "recent",
                        ],
                        "knowledge": [
                            "wikipedia",
                            "wiki",
                            "grokipedia",
                            "encyclopedia",
                            "definition",
                            # Translation triggers
                            "translate",
                            "translation",
                            "spanish",
                            "french",
                            "german",
                            "chinese",
                            "japanese",
                            "korean",
                            "portuguese",
                            "italian",
                            "russian",
                            "arabic",
                            "hindi",
                            "en español",
                            "en français",
                            "auf deutsch",
                        ],
                        "pdf": ["pdf", "ocr", "document", "paper", "read pdf", "parse pdf"],
                        "media": [
                            "memvid",
                            "video memory",
                            "archive",
                            "semantic memory",
                            "youtube",
                            "transcript",
                            "subtitle",
                            "subtitles",
                            "captions",
                            "video transcript",
                            "youtube search",
                            "youtube video",
                            "find video",
                            # Additional video triggers
                            "video",
                            "stream",
                            "recording",
                            "screen capture",
                            "screencast",
                            "clip",
                            "watch",
                            "movie",
                            "film",
                        ],
                        "browser": ["browser", "webpage", "website", "open url", "navigate to"],
                        "desktop": ["desktop", "screen", "window", "click", "mouse", "keyboard"],
                        "phone": [
                            "call me",
                            "call you",
                            "call him",
                            "call her",
                            "call them",
                            "call us",
                            "call back",
                            "phone call",
                            "phone me",
                            "give me a call",
                            "dial",
                            "ring",
                            "call ",
                        ],
                        "messaging": [
                            "push",
                            "notification",
                            "notify",
                            "alert",
                            "ping",
                            "text",
                            "sms",
                            "mms",
                            "message me",
                            "send message",
                            "send a message",
                        ],
                        "image_gen": ["image", "generate image", "logo", "illustration", "picture", "draw", "create image"],
                        "long_context": ["summarize", "summary", "recap", "synthesize", "long document", "long text", "tldr", "tl;dr", "condense"],
                        "math": [
                            "calculate",
                            "compute",
                            "solve",
                            "equation",
                            "formula",
                            "math",
                            "arithmetic",
                            "convert",
                            "conversion",
                        ],
                        "canvas": [
                            "canvas",
                            "code editor",
                            "editor",
                            "write code",
                            "show code",
                            "edit code",
                            "open file",
                            "load file",
                            "working directory",
                            "project directory",
                            "coding",
                            "script",
                            "program",
                            "function",
                            "implement",
                            "undo",
                            "revert",
                            "rollback",
                            "artifact",
                            "artifacts",
                        ],
                        "sandbox": [
                            # Math/Computation triggers
                            "calculate",
                            "compute",
                            "solve",
                            "equation",
                            "formula",
                            "algorithm",
                            "math",
                            "arithmetic",
                            "convert",
                            "conversion",
                        ],
                        "social": [
                            "twitter",
                            "tweet",
                            "x.com",
                            "post on x",
                            "post on twitter",
                            "retweet",
                            "dm",
                            "direct message",
                            "timeline",
                            "trending",
                            "hashtag",
                            "follow",
                            "unfollow",
                            "social media",
                            "social",
                            "facebook",
                            "instagram",
                            "threads",
                            "tiktok",
                            "linkedin",
                        ],
                        "automation": [
                            "composio",
                            "automate",
                            "automation",
                            "workflow",
                            "zapier",
                            "integration",
                            "trigger",
                            "action",
                            "connect",
                            "third-party",
                            "agent mail",
                            "agentmail",
                        ],
                        "finance": [
                            "trade",
                            "trading",
                            "crypto",
                            "bitcoin",
                            "btc",
                            "eth",
                            "futures",
                            "forex",
                            "portfolio",
                            "exchange",
                            "buy",
                            "sell",
                            "position",
                            "order",
                            "backtest",
                            "market",
                            "nofx",
                            "leverage",
                        ],
                    }
                    # === Smart Router: Pass 1 — keyword scoring ===
                    category_confidence: Dict[str, float] = {}
                    for category, keywords in category_keywords.items():
                        hits = [kw for kw in keywords if kw in context_text]
                        if hits:
                            confidence = min(1.0, len(hits) * 0.3 + 0.2)
                            category_confidence[category] = confidence
                            selected_categories.append(category)
                            auto_hits[category] = hits[0]

                    # Core categories always at baseline
                    for cat in core_categories:
                        if cat not in category_confidence:
                            category_confidence[cat] = 0.3

                    pass1_confidence = max(category_confidence.values()) if category_confidence else 0.0

                    # === Smart Router: Pass 2 — Tool Selection Memory ===
                    tool_confidence: Dict[str, float] = {}
                    tsm = getattr(self.vera, "tool_selection", None) if self.vera else None
                    if tsm and hasattr(tsm, "rank_tools"):
                        candidate_tools: List[str] = []
                        for srv_name, srv_cats in server_categories.items():
                            if srv_name not in available:
                                continue
                            if srv_cats and set(srv_cats).intersection(category_confidence.keys()):
                                candidate_tools.extend(available.get(srv_name, []))
                        if candidate_tools:
                            try:
                                task_ctx = {
                                    "query": (context or "")[:200],
                                    "categories": list(category_confidence.keys()),
                                }
                                ranked = tsm.rank_tools(candidate_tools, task_ctx)
                                for entry in ranked:
                                    tool_confidence[entry["name"]] = entry.get("score", 0.5)
                                memory_max_conf = max(
                                    (e.get("confidence", 0.0) for e in ranked), default=0.0
                                )
                                pass1_confidence = max(
                                    pass1_confidence, memory_max_conf * 0.5 + pass1_confidence * 0.5
                                )
                            except Exception:
                                pass

                    # === Smart Router: Pass 3 — LLM router (ambiguous only) ===
                    routing_confidence_threshold = float(
                        os.getenv("VERA_ROUTING_CONFIDENCE_THRESHOLD", "0.8")
                    )
                    used_llm_router = False
                    if pass1_confidence < routing_confidence_threshold and router_enabled:
                        try:
                            category_max_val = self._read_int_env(
                                "VERA_TOOL_ROUTER_CATEGORY_MAX", 4, min_value=0
                            )
                            llm_cats = await self._route_tool_categories(
                                context or "", category_defs, category_max_val
                            )
                            for cat in llm_cats:
                                category_confidence[cat] = max(
                                    category_confidence.get(cat, 0.0), 0.9
                                )
                                if cat not in selected_categories:
                                    selected_categories.append(cat)
                            used_llm_router = True
                        except Exception:
                            pass

                    # Emit thinking event for keyword detection results
                    if auto_hits:
                        hits_str = ", ".join(f"{cat} ('{kw}')" for cat, kw in auto_hits.items())
                        conf_str = f" [confidence={pass1_confidence:.2f}]"
                        thinking_routing(f"Keywords detected: {hits_str}{conf_str}")
                    else:
                        thinking_routing("No specific keywords detected, using core tools")

                    selected_categories = list({*selected_categories, *core_categories})
                    if should_expose_grounding or should_expose_summary:
                        selected_categories = list({*selected_categories, "web"})
                    for server_name, categories in server_categories.items():
                        if server_name not in available:
                            continue
                        if categories and set(categories).intersection(selected_categories):
                            if server_name not in selected_servers:
                                selected_servers.append(server_name)

        # Store routing metadata for learning signals
        self._last_routing_meta = {
            "category_confidence": locals().get("category_confidence", {}),
            "tool_confidence": locals().get("tool_confidence", {}),
            "pass1_confidence": locals().get("pass1_confidence", 0.0),
            "used_llm_router": locals().get("used_llm_router", False),
        }

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Tool selection: mode=%s tool_max=%s native_tools=%s mcp_servers=%s selected_servers=%s categories=%s auto_hits=%s",
                tool_mode,
                tool_max or "none",
                len(native_tools),
                len(available),
                selected_servers,
                selected_categories or "none",
                auto_hits or "none",
            )

        native_defs: Dict[str, Dict[str, Any]] = {}
        for tool in native_tools:
            func = tool.get("function", {})
            name = func.get("name")
            if not name or name in native_defs:
                continue
            native_defs[name] = tool

        all_mcp_tools: List[str] = []
        tool_to_server: Dict[str, str] = {}
        for server_name, tool_names in available.items():
            for tool_name in tool_names:
                all_mcp_tools.append(tool_name)
                if tool_name not in tool_to_server:
                    tool_to_server[tool_name] = server_name

        explicit_tools = self._extract_explicit_tool_mentions(
            context,
            list(native_defs.keys()) + all_mcp_tools,
        )
        forced_tool = self._detect_forced_tool_choice(
            context,
            list(native_defs.keys()) + all_mcp_tools
        )

        # Auto-detect media generation intent and force the native tool
        if not forced_tool and context:
            media_intent = self._detect_media_generation_intent(context)
            if media_intent == "video" and "generate_video" in native_defs:
                forced_tool = "generate_video"
            elif media_intent == "image" and "generate_image" in native_defs:
                forced_tool = "generate_image"

        # Auto-detect live data intent and force web search
        self._live_data_forced_tool: Optional[str] = None
        if not forced_tool and context:
            if self._detect_live_data_intent(context):
                # Prefer brave_ai_grounding for factual queries, fallback to brave_web_search
                search_tools = [t for t in all_mcp_tools if t in (
                    "brave_ai_grounding", "brave_web_search", "searxng_search",
                )]
                if search_tools:
                    forced_tool = search_tools[0]
                    self._live_data_forced_tool = forced_tool
                    # Ensure web category is included so search servers are selected
                    if "web" not in selected_categories:
                        selected_categories.append("web")
                    logger.info("Live data intent detected — forcing tool: %s", forced_tool)

        self._tool_aliases = {}
        mcp_defs: Dict[str, Dict[str, Any]] = {}
        primary_owner: Dict[str, str] = {}
        self._tool_to_server = primary_owner  # expose for execution history
        server_tool_to_exposed: Dict[Tuple[str, str], str] = {}
        taken_tool_names = set(native_defs.keys())
        for server_name in selected_servers:
            tool_defs = available_defs.get(server_name, [])
            if not tool_defs:
                tool_defs = [{"name": name} for name in available.get(server_name, [])]
            for tool_def in tool_defs:
                if isinstance(tool_def, str):
                    tool_def = {"name": tool_def}
                tool_name = tool_def.get("name")
                if not tool_name or tool_name in native_defs:
                    continue
                key = (server_name, tool_name)
                if key in server_tool_to_exposed:
                    continue
                description = tool_def.get("description") or f"MCP tool from {server_name}."
                parameters = tool_def.get("inputSchema") or {"type": "object", "properties": {}}
                exposed_name = tool_name
                if tool_name in primary_owner and primary_owner[tool_name] != server_name:
                    exposed_name = self._make_tool_alias(server_name, tool_name, taken_tool_names)
                    description = f"{description} (Alias for `{tool_name}` on `{server_name}`.)"
                    self._tool_aliases[exposed_name] = {"server": server_name, "tool": tool_name}
                else:
                    primary_owner.setdefault(tool_name, server_name)
                    if exposed_name in taken_tool_names:
                        continue
                taken_tool_names.add(exposed_name)
                server_tool_to_exposed[key] = exposed_name
                mcp_defs[exposed_name] = {
                    "type": "function",
                    "function": {
                        "name": exposed_name,
                        "description": description,
                        "parameters": parameters,
                    },
                }

        if self._genome_tool_overrides:
            for tool_name, override in self._genome_tool_overrides.items():
                description = override.get("description")
                parameters = override.get("parameters")
                if tool_name in native_defs:
                    func = native_defs[tool_name].get("function", {})
                    if description:
                        func["description"] = description
                    if isinstance(parameters, dict):
                        func["parameters"] = parameters
                if tool_name in mcp_defs:
                    func = mcp_defs[tool_name].get("function", {})
                    if description:
                        func["description"] = description
                    if isinstance(parameters, dict):
                        func["parameters"] = parameters

        def _ensure_mcp_tool_visible(tool_name: str) -> None:
            if tool_name in native_defs or tool_name in mcp_defs:
                return
            server_name = tool_to_server.get(tool_name)
            if not server_name:
                return
            tool_defs = available_defs.get(server_name, [])
            tool_def = next(
                (
                    entry for entry in tool_defs
                    if isinstance(entry, dict) and entry.get("name") == tool_name
                ),
                None
            )
            description = (tool_def or {}).get("description") or f"MCP tool from {server_name}."
            parameters = (tool_def or {}).get("inputSchema") or {"type": "object", "properties": {}}
            mcp_defs[tool_name] = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": description,
                    "parameters": parameters,
                },
            }
            primary_owner.setdefault(tool_name, server_name)
            server_tool_to_exposed[(server_name, tool_name)] = tool_name
            taken_tool_names.add(tool_name)
            if server_name not in selected_servers:
                selected_servers.append(server_name)

        # Guarantee explicitly named tools are visible even when category routing
        # does not naturally select their server in this turn.
        for tool_name in explicit_tools:
            _ensure_mcp_tool_visible(tool_name)

        if forced_tool:
            _ensure_mcp_tool_visible(forced_tool)

        if forced_tool and forced_tool not in native_defs and forced_tool not in mcp_defs:
            server_name = tool_to_server.get(forced_tool)
            if server_name:
                tool_defs = available_defs.get(server_name, [])
                tool_def = next(
                    (
                        entry for entry in tool_defs
                        if isinstance(entry, dict) and entry.get("name") == forced_tool
                    ),
                    None
                )
                description = (tool_def or {}).get("description") or f"MCP tool from {server_name}."
                parameters = (tool_def or {}).get("inputSchema") or {"type": "object", "properties": {}}
                mcp_defs[forced_tool] = {
                    "type": "function",
                    "function": {
                        "name": forced_tool,
                        "description": description,
                        "parameters": parameters,
                    },
                }
                primary_owner.setdefault(forced_tool, server_name)
                server_tool_to_exposed[(server_name, forced_tool)] = forced_tool
                taken_tool_names.add(forced_tool)
                if server_name not in selected_servers:
                    selected_servers.append(server_name)

        tools: List[Dict[str, Any]] = []
        seen = set()
        native_included = 0
        mcp_included = 0

        def _resolve_exposed_name(server_name: str, tool_name: str) -> Optional[str]:
            return server_tool_to_exposed.get((server_name, tool_name))

        router_tools: List[str] = []
        if router_enabled and tool_mode not in {"none", "all"}:
            router_max = self._read_int_env("VERA_TOOL_ROUTER_MAX", 12, min_value=0)
            if tool_max and router_max > tool_max:
                router_max = tool_max
            if tool_max and reserved_slots and router_max > tool_max - reserved_slots:
                router_max = max(tool_max - reserved_slots, 0)

            router_candidates: Dict[str, List[str]] = {}
            if native_defs:
                filtered_native = []
                for name in sorted(native_defs.keys()):
                    categories = native_tool_categories.get(name, [])
                    if not selected_categories or not categories:
                        filtered_native.append(name)
                    elif set(categories).intersection(selected_categories):
                        filtered_native.append(name)
                if filtered_native:
                    router_candidates["native"] = filtered_native
            for server_name in selected_servers:
                router_candidates[server_name] = available.get(server_name, [])

            router_tools = await self._route_tool_names(context or "", router_candidates, router_max)
            if router_tools and logger.isEnabledFor(logging.DEBUG):
                logger.debug("Router selected tools: %s", router_tools)

        if router_tools:
            filtered_router_tools = []
            for tool_name in router_tools:
                if tool_name == "brave_summarize" and not should_expose_summary:
                    continue
                if tool_name == "brave_ai_grounding" and not should_expose_grounding:
                    continue
                filtered_router_tools.append(tool_name)
            router_tools = filtered_router_tools

        priority_tools = []
        if should_expose_grounding:
            priority_tools.append("brave_ai_grounding")
        if should_expose_summary:
            priority_tools.append("brave_summarize")
        if long_context_signal:
            priority_tools.append("recursive_summarize")
        if phone_hit and "initiate_call" in mcp_defs:
            priority_tools.append("initiate_call")
        if reminder_signal:
            for reminder_tool in ("create_event", "get_events", "list_calendars"):
                if reminder_tool in mcp_defs and reminder_tool not in priority_tools:
                    priority_tools.append(reminder_tool)
        if push_signal:
            for push_tool in ("send_native_push", "send_mobile_push", "send_sms", "send_mms"):
                if push_tool in mcp_defs and push_tool not in priority_tools:
                    priority_tools.append(push_tool)
        # Prioritize editor/canvas tools when canvas category is selected
        if "canvas" in selected_categories:
            editor_priority = [
                "editor_set_workspace",
                "editor_list_files",
                "editor_open_file",
                "editor_read",
                "editor_write",
                "editor_undo",
            ]
            save_keywords = ["save", "persist", "write to disk", "commit file", "save file"]
            language_keywords = ["language", "syntax", "highlight", "file type", "extension"]
            if any(keyword in context_text for keyword in save_keywords):
                editor_priority.append("editor_save")
            if any(keyword in context_text for keyword in language_keywords):
                editor_priority.append("editor_set_language")
            for editor_tool in editor_priority:
                if editor_tool not in priority_tools:
                    priority_tools.append(editor_tool)

        for tool_name in explicit_tools:
            if (tool_name in native_defs or tool_name in mcp_defs) and tool_name not in priority_tools:
                priority_tools.append(tool_name)

        if forced_tool and (forced_tool in native_defs or forced_tool in mcp_defs):
            if forced_tool not in priority_tools:
                priority_tools.insert(0, forced_tool)

        workflow_plan: Dict[str, Any] = self._consume_request_workflow_hint(context)
        workflow_suggested_chain: List[str] = list(workflow_plan.get("tool_chain", []) or [])
        if self._is_acknowledgement_turn(context or ""):
            workflow_plan = {}
            workflow_suggested_chain = []
            self._trace_workflow("suggest_chain_skip reason=acknowledgement_turn")
        if workflow_suggested_chain:
            self._trace_workflow(
                "suggest_chain_result context_len=%s chain=%s signature=%s source=%s",
                len(str(context or "")),
                workflow_suggested_chain,
                str(workflow_plan.get("signature", "")),
                str(workflow_plan.get("source", "request_hint")),
            )
        else:
            learning_loop = getattr(self.vera, "learning_loop", None) if self.vera else None
            if not learning_loop:
                self._trace_workflow("suggest_chain_skip reason=no_learning_loop")
            elif self._is_acknowledgement_turn(context or ""):
                self._trace_workflow("suggest_chain_skip reason=acknowledgement_turn")
            elif not context:
                self._trace_workflow("suggest_chain_skip reason=empty_context")
            if learning_loop and context and not self._is_acknowledgement_turn(context or ""):
                try:
                    if hasattr(learning_loop, "get_workflow_plan"):
                        raw_plan = learning_loop.get_workflow_plan(context)
                        if isinstance(raw_plan, dict):
                            workflow_plan = dict(raw_plan)
                            workflow_suggested_chain = list(workflow_plan.get("tool_chain", []) or [])
                    else:
                        workflow_suggested_chain = list(learning_loop.suggest_workflow_chain(context))
                    self._trace_workflow(
                        "suggest_chain_result context_len=%s chain=%s signature=%s source=%s",
                        len(str(context or "")),
                        workflow_suggested_chain,
                        str(workflow_plan.get("signature", "")),
                        str(workflow_plan.get("source", "")),
                    )
                except Exception:
                    self._trace_workflow("suggest_chain_error")
                    workflow_plan = {}
                    workflow_suggested_chain = []
        if workflow_suggested_chain:
            chain_ok, chain_reason = self._should_accept_workflow_chain(
                context=str(context or ""),
                workflow_plan=workflow_plan,
                workflow_chain=workflow_suggested_chain,
                explicit_tools=list(explicit_tools),
                forced_tool=forced_tool,
            )
            if not chain_ok:
                self._trace_workflow(
                    "suggest_chain_skip reason=%s chain=%s signature=%s source=%s",
                    chain_reason,
                    list(workflow_suggested_chain),
                    str(workflow_plan.get("signature", "")),
                    str(workflow_plan.get("source", "")),
                )
                workflow_plan = {}
                workflow_suggested_chain = []
        if workflow_suggested_chain:
            promoted_chain = [
                name for name in workflow_suggested_chain
                if name in native_defs or name in mcp_defs
            ]
            # Media generation should execute directly; reusing learned chains here
            # can force unrelated memory/web tools and exhaust tool-call rounds.
            if forced_tool in {"generate_image", "generate_video"}:
                self._trace_workflow(
                    "suggest_chain_skip reason=media_forced_tool forced=%s chain=%s",
                    forced_tool,
                    list(workflow_suggested_chain),
                )
                workflow_plan = {}
                workflow_suggested_chain = []
                promoted_chain = []
            if promoted_chain:
                forced_prefix: List[str] = []
                if forced_tool and forced_tool in promoted_chain:
                    promoted_chain = [name for name in promoted_chain if name != forced_tool]
                    forced_prefix = [forced_tool]
                existing = [name for name in priority_tools if name not in promoted_chain]
                if forced_tool and forced_tool in existing and forced_tool not in forced_prefix:
                    existing = [name for name in existing if name != forced_tool]
                    forced_prefix = [forced_tool]
                priority_tools = forced_prefix + promoted_chain + existing

        for tool_name in priority_tools:
            if tool_name in seen:
                continue
            tool_def = mcp_defs.get(tool_name) or native_defs.get(tool_name)
            if not tool_def:
                continue
            if tool_max and len(tools) >= tool_max:
                break
            tools.append(tool_def)
            seen.add(tool_name)
            if tool_name in mcp_defs:
                mcp_included += 1
            else:
                native_included += 1

        if router_tools:
            for tool_name in router_tools:
                if tool_name in seen:
                    continue
                if tool_name in native_defs:
                    tools.append(native_defs[tool_name])
                    native_included += 1
                elif tool_name in mcp_defs:
                    tools.append(mcp_defs[tool_name])
                    mcp_included += 1
                else:
                    continue
                seen.add(tool_name)
                if tool_max and len(tools) >= tool_max:
                    break
        else:
            if tool_max:
                # Prioritize MCP tools when capped to avoid starving MCP visibility.
                for server_name in selected_servers:
                    tool_names = available.get(server_name, [])
                    remaining = max(tool_max - len(tools), 0)
                    if remaining <= 0:
                        break
                    if tool_max and len(tool_names) > remaining and logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Capping MCP server %s: tool_max=%s current=%s server_tools=%s",
                            server_name,
                            tool_max,
                            len(tools),
                            len(tool_names),
                        )
                    for tool_name in tool_names:
                        if remaining <= 0:
                            break
                        exposed_name = _resolve_exposed_name(server_name, tool_name)
                        if not exposed_name:
                            continue
                        if exposed_name in seen:
                            continue
                        if tool_name == "brave_summarize" and not should_expose_summary:
                            continue
                        if tool_name == "brave_ai_grounding" and not should_expose_grounding:
                            continue
                        seen.add(exposed_name)
                        tools.append(mcp_defs[exposed_name])
                        mcp_included += 1
                        remaining -= 1

                remaining = max(tool_max - len(tools), 0)
                for tool_name, tool in native_defs.items():
                    if remaining <= 0:
                        break
                    if tool_name in seen:
                        continue
                    seen.add(tool_name)
                    tools.append(tool)
                    native_included += 1
                    remaining -= 1
            else:
                for tool_name, tool in native_defs.items():
                    if tool_name in seen:
                        continue
                    seen.add(tool_name)
                    tools.append(tool)
                    native_included += 1

                for server_name in selected_servers:
                    tool_names = available.get(server_name, [])
                    for tool_name in tool_names:
                        exposed_name = _resolve_exposed_name(server_name, tool_name)
                        if not exposed_name:
                            continue
                        if exposed_name in seen:
                            continue
                        if tool_name == "brave_summarize" and not should_expose_summary:
                            continue
                        if tool_name == "brave_ai_grounding" and not should_expose_grounding:
                            continue
                        seen.add(exposed_name)
                        tools.append(mcp_defs[exposed_name])
                        mcp_included += 1

        # NOTE: Duplicate tool selection block removed (was lines 825-885).
        # The if/else block above (router_tools vs fallback) already handles
        # all tool selection. The duplicate block caused redundant iteration.

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Tool payload built: total=%s native=%s mcp=%s selected_servers=%s",
                len(tools),
                native_included,
                mcp_included,
                selected_servers,
            )

        tool_names = []
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name")
            if name:
                tool_names.append(name)

        # Merge smart router confidence with tool selection memory ranking
        routing_confidence = getattr(self, "_last_routing_meta", {}).get("tool_confidence", {})
        if self.vera and getattr(self.vera, "tool_selection", None) and tool_names:
            ranked = self.vera.tool_selection.rank_tools(
                tool_names,
                {"query": context or "", "categories": selected_categories or []},
            )
            # Blend memory ranking with smart router confidence
            rank_scores: Dict[str, float] = {}
            for idx, entry in enumerate(ranked):
                mem_score = entry.get("score", 0.5)
                router_score = routing_confidence.get(entry["name"], 0.5)
                # Weighted blend: 60% memory, 40% router confidence
                rank_scores[entry["name"]] = 0.6 * mem_score + 0.4 * router_score
            priority_set = set(priority_tools)
            priority_defs = []
            other_defs = []
            for tool in tools:
                func = tool.get("function", {})
                name = func.get("name")
                if not name:
                    continue
                if name in priority_set:
                    priority_defs.append(tool)
                else:
                    other_defs.append(tool)
            other_defs.sort(
                key=lambda t: rank_scores.get(t.get("function", {}).get("name", ""), 0.0),
                reverse=True,
            )
            tools = priority_defs + other_defs
            tool_names = []
            for tool in tools:
                func = tool.get("function", {})
                name = func.get("name")
                if name:
                    tool_names.append(name)

        if self.vera:
            allow_quorum = getattr(self.vera, "quorum_auto_enabled", False)
            allow_swarm = getattr(self.vera, "swarm_auto_enabled", False)
            if not allow_quorum or not allow_swarm:
                filtered = []
                for tool in tools:
                    func = tool.get("function", {})
                    name = func.get("name")
                    if name == "consult_quorum" and not allow_quorum:
                        continue
                    if name == "consult_swarm" and not allow_swarm:
                        continue
                    filtered.append(tool)
                tools = filtered

        native_names = set()
        for tool in native_tools:
            func = tool.get("function", {})
            name = func.get("name")
            if name:
                native_names.add(name)

        native_included = 0
        mcp_included = 0
        tool_names = []
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name")
            if name:
                tool_names.append(name)
                if name in native_names:
                    native_included += 1
                else:
                    mcp_included += 1

        tool_choice: Optional[Dict[str, Any]] = None
        if forced_tool and forced_tool in tool_names:
            tool_choice = {"type": "function", "function": {"name": forced_tool}}
            logger.info("Forcing tool_choice: %s (tool present in %d tools)", forced_tool, len(tool_names))
        elif forced_tool:
            logger.warning("Forced tool %s NOT in tool list (%d tools); skipping tool_choice", forced_tool, len(tool_names))

        # Don't overwrite last_tool_payload for auto-title requests (UI sends
        # "Summarize my initial request in 5 words or less" after each response)
        _is_title_gen = context and "5 words or less" in context.lower()
        if not _is_title_gen:
            self.last_tool_payload = {
                "tool_mode": tool_mode,
                "tool_max": tool_max,
                "router_enabled": router_enabled,
                "router_max": router_max,
                "selected_servers": selected_servers,
                "selected_categories": selected_categories,
                "native_included": native_included,
                "mcp_included": mcp_included,
                "tool_count": len(tools),
                "tool_names": tool_names,
                "forced_tool": forced_tool or "",
                "tool_choice": tool_choice["function"]["name"] if tool_choice else "auto",
                "tool_alias_count": len(self._tool_aliases),
                "workflow_suggested_chain": workflow_suggested_chain,
                "workflow_plan": workflow_plan,
            }
            if self._tool_aliases:
                self.last_tool_payload["tool_aliases"] = dict(self._tool_aliases)
            if include_full:
                self.last_tool_payload["tools"] = tools

        # Emit thinking event for final tool selection
        if tool_names:
            categories_str = ", ".join(selected_categories) if selected_categories else "core"
            top_tools = tool_names[:5]
            tools_str = ", ".join(top_tools)
            if len(tool_names) > 5:
                tools_str += f" (+{len(tool_names) - 5} more)"
            thinking_decision(
                f"Selected {len(tools)} tools [{categories_str}]: {tools_str}",
                tool_count=len(tools),
                categories=selected_categories,
            )

        return tools, tool_choice, selected_categories

    def get_last_tool_payload(self) -> Dict[str, Any]:
        """Return the last tool payload sent to the LLM."""
        payload = dict(self.last_tool_payload or {})
        payload["last_tools_used"] = list(self.last_tools_used or [])
        payload["last_tools_used_count"] = len(payload["last_tools_used"])
        return self._trim_tool_payload(payload)

    @staticmethod
    def _trim_tool_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            name_limit = int(os.getenv("VERA_TOOL_PAYLOAD_NAME_LIMIT", "80"))
        except ValueError:
            name_limit = 80
        try:
            tool_limit = int(os.getenv("VERA_TOOL_PAYLOAD_TOOL_LIMIT", "80"))
        except ValueError:
            tool_limit = 80

        names = payload.get("tool_names")
        if isinstance(names, list):
            payload["tool_names_total"] = len(names)
            if name_limit >= 0 and len(names) > name_limit:
                payload["tool_names"] = names[:name_limit]
                payload["tool_names_truncated"] = True
            else:
                payload["tool_names_truncated"] = False

        tools = payload.get("tools")
        if isinstance(tools, list):
            payload["tools_total"] = len(tools)
            if tool_limit >= 0 and len(tools) > tool_limit:
                payload["tools"] = tools[:tool_limit]
                payload["tools_truncated"] = True
            else:
                payload["tools_truncated"] = False

        return payload

    async def _route_tool_names(
        self,
        context: str,
        candidates: Dict[str, List[str]],
        max_tools: int
    ) -> List[str]:
        if not context or not candidates:
            return []

        planned_queries = self._plan_tool_queries(context)
        if len(planned_queries) <= 1:
            return await self._route_tool_names_single(context, candidates, max_tools)

        selected: List[str] = []
        for query in planned_queries:
            remaining = max_tools - len(selected)
            if remaining <= 0:
                break
            tools = await self._route_tool_names_single(query, candidates, remaining)
            for name in tools:
                if name not in selected:
                    selected.append(name)
        return selected[:max_tools]

    def _plan_tool_queries(self, context: str) -> List[str]:
        cleaned = re.sub(r"```.*?```", " ", context, flags=re.DOTALL)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return []

        split_pattern = r"(?:;|\n|\band then\b|\bthen\b|\balso\b|\bafter that\b|\bnext\b)"
        parts = re.split(split_pattern, cleaned, flags=re.IGNORECASE)
        parts = [part.strip() for part in parts if len(part.strip()) >= 6]
        if len(parts) <= 1:
            return [cleaned]
        return parts[:3]

    async def _route_tool_names_single(
        self,
        context: str,
        candidates: Dict[str, List[str]],
        max_tools: int
    ) -> List[str]:
        tool_lines = []
        for server_name, tool_names in candidates.items():
            if not tool_names:
                continue
            tool_lines.append(f"{server_name}: {', '.join(tool_names)}")

        tools_json = json.dumps({"tools": ["tool_a", "tool_b"]})
        empty_json = json.dumps({"tools": []})
        prompt = (
            "You are a tool router. Select up to "
            f"{max_tools} tool names that best match the user request.\n"
            f"Return JSON only: {tools_json}.\n"
            f"Only choose from the list; if none apply, return {empty_json}.\n\n"
            f"User request:\n{context}\n\n"
            f"Available tools:\n{chr(10).join(tool_lines)}"
        )

        router_model = os.getenv("VERA_TOOL_ROUTER_MODEL", self.model)
        payload = {
            "messages": [
                {"role": "system", "content": "You are a strict JSON-only tool router."},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            data = await self._call_chat(
                payload["messages"],
                tools=None,
                generation_config={"temperature": 0},
                model_override=router_model,
            )
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Tool router failed: %s", exc)
            return []

        choices = data.get("choices", [])
        if not choices:
            return []
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            return []

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            try:
                start = content.index("{")
                end = content.rindex("}") + 1
                parsed = json.loads(content[start:end])
            except Exception:
                return []

        tools = parsed.get("tools", [])
        if not isinstance(tools, list):
            return []

        cleaned = []
        seen = set()
        for name in tools:
            if not isinstance(name, str):
                continue
            if name in seen:
                continue
            seen.add(name)
            cleaned.append(name)
        return cleaned[:max_tools]

    async def _route_tool_categories(
        self,
        context: str,
        categories: Dict[str, str],
        max_categories: int
    ) -> List[str]:
        if not context or not categories:
            return []

        category_lines = [f"{name}: {desc}" for name, desc in categories.items()]
        categories_json = json.dumps({"categories": ["category_a", "category_b"]})
        empty_json = json.dumps({"categories": []})
        prompt = (
            "You are a tool router. Select up to "
            f"{max_categories} categories that best match the user request.\n"
            f"Return JSON only: {categories_json}.\n"
            f"Only choose from the list; if none apply, return {empty_json}.\n\n"
            f"User request:\n{context}\n\n"
            f"Available categories:\n{chr(10).join(category_lines)}"
        )

        router_model = os.getenv("VERA_TOOL_ROUTER_MODEL", self.model)
        payload = {
            "messages": [
                {"role": "system", "content": "You are a strict JSON-only tool router."},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            data = await self._call_chat(
                payload["messages"],
                tools=None,
                generation_config={"temperature": 0},
                model_override=router_model,
            )
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Category router failed: %s", exc)
            return []

        choices = data.get("choices", [])
        if not choices:
            return []
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            return []

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            try:
                start = content.index("{")
                end = content.rindex("}") + 1
                parsed = json.loads(content[start:end])
            except Exception:
                return []

        if not isinstance(parsed, dict):
            return []
        selected = parsed.get("categories", [])
        if not isinstance(selected, list):
            return []

        cleaned = []
        for item in selected:
            if not isinstance(item, str):
                continue
            name = item.strip()
            if name in categories and name not in cleaned:
                cleaned.append(name)
        return cleaned[:max_categories]

    @staticmethod
    def _measure_message_chars(messages: List[Dict[str, Any]]) -> int:
        message_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                message_chars += len(json.dumps(content))
            else:
                message_chars += len(str(content))
        return message_chars

    async def _call_chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a chat completion request via registry or direct HTTP.

        When a ProviderRegistry is available, delegates to it for
        multi-provider fallback. Otherwise falls back to direct httpx
        calls (legacy behavior).

        Returns raw OpenAI-format response dict for backward compatibility.
        """
        start_time = time.time()

        # --- Registry mode: use multi-provider fallback ---
        _registry_error: Optional[Exception] = None
        if self.registry is not None:
            try:
                # Pass system prompt via generation_config for providers
                # that need it separately (Claude, Gemini)
                gen_config = dict(generation_config) if generation_config else {}

                # Extract system message for non-OpenAI providers
                system_parts = []
                non_system_messages = []
                for msg in messages:
                    if msg.get("role") == "system":
                        system_parts.append(msg.get("content", ""))
                    else:
                        non_system_messages.append(msg)
                if system_parts:
                    gen_config["system"] = "\n\n".join(system_parts)

                async def _on_provider_switch(old_id, new_id):
                    logger.info(f"LLM provider switch: {old_id} -> {new_id}")

                llm_response = await self.registry.chat_with_fallback(
                    messages=messages,  # Pass full messages; registry normalizes per provider
                    tools=tools,
                    tool_choice=tool_choice,
                    generation_config=gen_config,
                    model=model_override or self.model,
                    on_provider_switch=_on_provider_switch,
                )

                # Convert LLMResponse back to OpenAI-format dict for backward compat
                data = {
                    "model": llm_response.model,
                    "choices": [{
                        "index": 0,
                        "message": llm_response.raw_message,
                        "finish_reason": llm_response.finish_reason,
                    }],
                }
                if llm_response.usage:
                    data["usage"] = llm_response.usage

                # Record costs
                if llm_response.usage and getattr(self.vera, "record_tool_cost", None):
                    provider_name = llm_response.provider_id or "llm"
                    self.vera.record_tool_cost(
                        tool_name=f"{provider_name}_chat",
                        tokens_in=llm_response.input_tokens,
                        tokens_out=llm_response.output_tokens,
                        cached=False,
                    )

                # Record to flight recorder
                if self.vera and getattr(self.vera, "flight_recorder", None):
                    try:
                        latency_ms = (time.time() - start_time) * 1000
                        self.vera.flight_recorder.record_llm_call(
                            model=llm_response.model,
                            messages=messages,
                            response=data,
                            latency_ms=latency_ms,
                            success=True,
                            tool_choice=tool_choice,
                        )
                    except Exception:
                        logger.debug("Suppressed Exception in llm_bridge")
                        pass

                return data

            except Exception as e:
                _registry_error = e
                logger.warning(f"Registry call failed, falling back to direct: {e}")
                # Fall through to legacy mode if registry fails entirely

        # --- Legacy mode: direct httpx call ---
        payload: Dict[str, Any] = {
            "model": model_override or self.model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if response_format:
            payload["response_format"] = response_format
        applied_config: Dict[str, Any] = {}
        if generation_config:
            for key in ("temperature", "top_p", "max_tokens", "frequency_penalty", "presence_penalty"):
                if key in generation_config and generation_config[key] is not None:
                    payload[key] = generation_config[key]
                    applied_config[key] = generation_config[key]

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "LLM request: model=%s messages=%s chars=%s tools=%s tool_choice=%s",
                payload.get("model"),
                len(messages),
                self._measure_message_chars(messages),
                len(payload.get("tools") or []),
                payload.get("tool_choice"),
            )

        headers = self._build_headers()
        response = await self._client.post("/chat/completions", headers=headers, json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            if response.status_code == 400 and (tools or applied_config):
                self._log_bad_request(payload, response)
                fallback = dict(payload)
                if tools:
                    fallback.pop("tools", None)
                    fallback.pop("tool_choice", None)
                for key in applied_config:
                    fallback.pop(key, None)
                retry = await self._client.post("/chat/completions", headers=headers, json=fallback)
                retry.raise_for_status()
                return retry.json()
            if response.status_code == 400:
                self._log_bad_request(payload, response)
            if detail:
                raise RuntimeError(f"{exc} :: {detail}") from exc
            raise
        data = response.json()

        usage = data.get("usage", {})
        if usage and getattr(self.vera, "record_tool_cost", None):
            input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
            output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))
            self.vera.record_tool_cost(
                tool_name="grok_chat",
                tokens_in=input_tokens or 0,
                tokens_out=output_tokens or 0,
                cached=False,
            )

        if self.vera and getattr(self.vera, "flight_recorder", None):
            try:
                latency_ms = (time.time() - start_time) * 1000
                self.vera.flight_recorder.record_llm_call(
                    model=payload.get("model", ""),
                    messages=payload.get("messages", []),
                    response=data,
                    latency_ms=latency_ms,
                    success=True,
                    tool_choice=payload.get("tool_choice"),
                )
            except Exception:
                logger.debug("Suppressed Exception in llm_bridge")
                pass

        return data

    def _log_bad_request(self, payload: Dict[str, Any], response: httpx.Response) -> None:
        tools = payload.get("tools") or []
        message_chars = self._measure_message_chars(payload.get("messages", []))

        detail = response.text.strip().replace("\n", " ")
        if len(detail) > 500:
            detail = detail[:500] + "..."

        logger.error(
            "xAI 400 Bad Request: model=%s tool_count=%s message_count=%s message_chars=%s tool_mode=%s prompt_tool_mode=%s detail=%s",
            payload.get("model"),
            len(tools),
            len(payload.get("messages", [])),
            message_chars,
            os.getenv("VERA_TOOL_MODE"),
            os.getenv("VERA_PROMPT_TOOL_MODE"),
            detail,
        )

    def _sanitize_response_text(self, text: str) -> str:
        enabled = os.getenv("VERA_RESPONSE_SANITIZE", "1").strip().lower() in {"1", "true", "yes", "on"}
        if not enabled or not text:
            return text

        allow_raw = os.getenv("VERA_RESPONSE_SANITIZE_ALLOW", "")
        skip_raw = os.getenv("VERA_RESPONSE_SANITIZE_SKIP", "")
        allow_tokens = [t.strip() for t in allow_raw.split(",") if t.strip()]
        skip_tokens = [t.strip() for t in skip_raw.split(",") if t.strip()]

        patterns = [
            r"how (may|can) i (assist|help)( you)?\??$",
            r"is there anything else( i can do)?\??$",
            r"let me know if you (need|have) (anything|more)( else)?\??$",
            r"let me know if i can help\??$",
            r"feel free to (reach out|ask|ask anything)( anytime)?\??$",
            r"i'?m here to help\??$",
            r"(ready|standing) by\.?$",
            r"anything else\??$",
        ]

        lines = text.rstrip().splitlines()
        if not lines:
            return text.rstrip()

        last_index = len(lines) - 1
        while last_index >= 0 and not lines[last_index].strip():
            last_index -= 1
        if last_index < 0:
            return text.rstrip()

        last_line = lines[last_index].strip()
        lowered_last = last_line.lower()

        if allow_tokens:
            for token in allow_tokens:
                if token.lower() in lowered_last:
                    return text.rstrip()

        if skip_tokens:
            lowered_text = text.lower()
            for token in skip_tokens:
                if token.lower() in lowered_text:
                    return text.rstrip()

        for pattern in patterns:
            if re.search(pattern, last_line, re.IGNORECASE):
                stripped_lines = lines[:last_index]
                sanitized = self._sanitize_tool_availability_claims("\n".join(stripped_lines).rstrip())
                return self._sanitize_push_manual_fallback(sanitized)

        sanitized = self._sanitize_tool_availability_claims(text.rstrip())
        return self._sanitize_push_manual_fallback(sanitized)

    def _sanitize_tool_availability_claims(self, text: str) -> str:
        if not text:
            return text

        payload = self.last_tool_payload if isinstance(self.last_tool_payload, dict) else {}
        tool_names = payload.get("tool_names") if isinstance(payload, dict) else []
        if not isinstance(tool_names, list):
            return text

        tool_set = {str(name).strip() for name in tool_names if isinstance(name, str)}
        has_scheduler = bool(tool_set.intersection({"create_event", "create_task", "create_task_list", "set_reminder"}))
        has_push = bool(tool_set.intersection({"send_native_push", "send_mobile_push", "send_sms", "send_mms"}))
        if not (has_scheduler or has_push):
            return text

        lowered = text.lower()
        misleading = any(
            token in lowered
            for token in (
                "tools limited to",
                "no scheduler",
                "no calendar tool",
                "no native push",
                "no push tool",
                "native push tool online yet",
                "scheduler tool online yet",
            )
        )
        if not misleading:
            return text

        filtered_lines: List[str] = []
        suppress_followups = False
        for line in text.splitlines():
            stripped = line.strip()
            lower_line = stripped.lower()

            if any(
                token in lower_line
                for token in (
                    "tools limited to",
                    "no scheduler",
                    "no calendar tool",
                    "no native push",
                    "no push tool",
                    "native push tool online yet",
                    "scheduler tool online yet",
                )
            ):
                suppress_followups = True
                continue

            if suppress_followups:
                if not stripped:
                    suppress_followups = False
                    continue
                if lower_line.startswith("alternatives:"):
                    continue
                if re.match(r"^\d+\.\s", lower_line):
                    continue
                if any(
                    token in lower_line
                    for token in (
                        "manual alarm",
                        "tool rollout",
                        "shall i marm",
                        "marm-persist",
                    )
                ):
                    continue
                suppress_followups = False

            filtered_lines.append(line)

        cleaned = "\n".join(filtered_lines).strip()
        if cleaned:
            return cleaned

        if has_scheduler and has_push:
            return "Scheduler and push tools are online. Share the date and timezone and I'll execute now."
        if has_scheduler:
            return "Scheduler tools are online. Share the date and timezone and I'll execute now."
        return "Push tools are online. Share the target/time details and I'll execute now."

    def _sanitize_push_manual_fallback(self, text: str) -> str:
        if not text:
            return text

        payload = self.last_tool_payload if isinstance(self.last_tool_payload, dict) else {}
        tool_names = payload.get("tool_names") if isinstance(payload, dict) else []
        if not isinstance(tool_names, list):
            return text

        tool_set = {str(name).strip() for name in tool_names if isinstance(name, str)}
        has_push = bool(tool_set.intersection({"send_native_push", "send_mobile_push", "send_sms", "send_mms"}))
        if not has_push:
            return text

        lowered = text.lower()
        manual_tokens = (
            "manually add",
            "clock app",
            "oneplus tip",
            "enable notifications in clock",
            "set it manually",
            "manual fix",
            "open google calendar app",
            "copy-paste",
            "copy paste",
            "google calendar app >",
            "manual entry",
        )
        if not any(token in lowered for token in manual_tokens):
            return text

        filtered_lines: List[str] = []
        for line in text.splitlines():
            lower_line = line.strip().lower()
            if any(token in lower_line for token in manual_tokens):
                continue
            filtered_lines.append(line)

        cleaned = "\n".join(filtered_lines).strip()
        cleaned = re.sub(r"\bno dice\b", "I can't complete that step", cleaned, flags=re.IGNORECASE)
        advisory = (
            "I can send an immediate native push now. "
            "For scheduled reminder delivery, share your Google email and timezone so I can create the calendar event."
        )
        if not cleaned:
            return advisory
        if "immediate native push" not in cleaned.lower():
            cleaned = f"{cleaned}\n\n{advisory}"
        return cleaned

    async def _get_system_prompt(
        self,
        last_user: str,
        system_override: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        if system_override:
            return system_override
        if not self.vera:
            return ""
        memory_constraints = []
        if getattr(self.vera, "get_relevant_past_corrections", None):
            try:
                memory_constraints = await self.vera.get_relevant_past_corrections(last_user)
            except Exception:
                logger.debug("Suppressed Exception in llm_bridge")
                memory_constraints = []
        return self.vera.build_system_prompt(
            conversation_id=conversation_id,
            router_context=last_user,
            memory_constraints=memory_constraints,
        )

    def _emit_routing_signals(
        self,
        user_message: str,
        selected_categories: List[str],
        model_override: str,
        model_reason: str,
        tools_used: List[str],
        conversation_id: str = "default",
    ) -> None:
        """Emit routing decisions as learning signals to flight recorder and tool selection memory."""
        routing_meta = getattr(self, "_last_routing_meta", {})
        tool_confidence = routing_meta.get("tool_confidence", {})
        pass1_confidence = routing_meta.get("pass1_confidence", 0.0)
        used_llm_router = routing_meta.get("used_llm_router", False)
        workflow_reward_score = 0.0
        active_plan = self._active_workflow_plan if isinstance(self._active_workflow_plan, dict) else {}
        if active_plan:
            try:
                workflow_reward_score = float(active_plan.get("reward_score_ema", 0.0) or 0.0)
            except Exception:
                workflow_reward_score = 0.0

        # Flight recorder: routing decision
        fr = getattr(self.vera, "flight_recorder", None) if self.vera else None
        if fr and hasattr(fr, "record_routing_decision"):
            try:
                fr.record_routing_decision(
                    conversation_id=conversation_id,
                    query_preview=user_message[:200],
                    selected_categories=selected_categories,
                    selected_servers=[],
                    tool_confidence=tool_confidence,
                    pass1_confidence=pass1_confidence,
                    used_llm_router=used_llm_router,
                    model_selected=model_override,
                    model_reason=model_reason,
                )
            except Exception:
                pass

        # Flight recorder: model selection
        if fr and hasattr(fr, "record_model_selection") and model_reason != "default_reasoning":
            try:
                fr.record_model_selection(
                    conversation_id=conversation_id,
                    model_selected=model_override,
                    reason=model_reason,
                    alternatives=[self.model],
                )
            except Exception:
                pass

        # Tool selection memory: routing outcome
        tsm = getattr(self.vera, "tool_selection", None) if self.vera else None
        if tsm and hasattr(tsm, "record_routing_outcome") and tools_used:
            try:
                reward_scores = {
                    tool_name: workflow_reward_score
                    for tool_name in tools_used
                }
                tsm.record_routing_outcome(
                    selected_categories=selected_categories,
                    tools_used=tools_used,
                    tools_succeeded=tools_used,  # assume success unless we track failures
                    context={"task": user_message[:200]},
                    tool_reward_scores=reward_scores,
                )
            except Exception:
                pass

    def _record_workflow_outcome(
        self,
        task_text: str,
        tools_used: List[str],
        success: bool,
        conversation_id: str,
        error: str = "",
    ) -> None:
        if self._is_acknowledgement_turn(task_text):
            self._trace_workflow("record_outcome_skip reason=acknowledgement_turn")
            return
        if not self.vera:
            self._trace_workflow("record_outcome_skip reason=no_vera")
            return
        learning_loop = getattr(self.vera, "learning_loop", None)
        if not learning_loop or not hasattr(learning_loop, "record_workflow_outcome"):
            self._trace_workflow("record_outcome_skip reason=learning_loop_unavailable")
            return
        self._trace_workflow(
            "record_outcome_call success=%s tools=%s conversation_id=%s error=%s",
            bool(success),
            list(tools_used or []),
            str(conversation_id or "default"),
            str(error or "")[:120],
        )
        try:
            learning_loop.record_workflow_outcome(
                task_text=task_text,
                tools_used=list(tools_used or []),
                success=bool(success),
                conversation_id=str(conversation_id or "default"),
                error=str(error or ""),
            )
            self._trace_workflow("record_outcome_done")
        except Exception:
            self._trace_workflow("record_outcome_error")
            logger.debug("Suppressed Exception in llm_bridge")

    def _record_workflow_replay_result(
        self,
        task_text: str,
        workflow_plan: Dict[str, Any],
        success: bool,
        conversation_id: str,
        error: str = "",
    ) -> None:
        if self._is_acknowledgement_turn(task_text):
            self._trace_workflow("record_replay_skip reason=acknowledgement_turn")
            return
        if not self.vera:
            self._trace_workflow("record_replay_skip reason=no_vera")
            return
        if not workflow_plan:
            self._trace_workflow("record_replay_skip reason=empty_workflow_plan")
            return
        forced_steps = int(workflow_plan.get("forced_steps", 0) or 0)
        chain = workflow_plan.get("tool_chain", [])
        if forced_steps <= 0 or not isinstance(chain, list) or len(chain) < 2:
            self._trace_workflow(
                "record_replay_skip reason=not_replayed forced_steps=%s chain=%s",
                forced_steps,
                chain if isinstance(chain, list) else [],
            )
            return

        learning_loop = getattr(self.vera, "learning_loop", None)
        if not learning_loop or not hasattr(learning_loop, "record_workflow_replay_result"):
            self._trace_workflow("record_replay_skip reason=learning_loop_unavailable")
            return
        self._trace_workflow(
            "record_replay_call success=%s chain=%s forced_steps=%s conversation_id=%s signature=%s error=%s",
            bool(success),
            list(chain),
            forced_steps,
            str(conversation_id or "default"),
            str(workflow_plan.get("signature") or ""),
            str(error or "")[:120],
        )
        try:
            learning_loop.record_workflow_replay_result(
                task_text=task_text,
                tool_chain=list(chain),
                success=bool(success),
                conversation_id=str(conversation_id or "default"),
                error=str(error or ""),
                signature=str(workflow_plan.get("signature") or ""),
            )
            self._trace_workflow("record_replay_done")
        except Exception:
            self._trace_workflow("record_replay_error")
            logger.debug("Suppressed Exception in llm_bridge")

    @staticmethod
    def _force_tool_choice(tool_name: str) -> Dict[str, Any]:
        return {"type": "function", "function": {"name": str(tool_name)}}

    def _resolve_workflow_runtime_plan(
        self,
        task_text: str,
        available_tools: List[str],
        existing_tool_choice: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        plan: Dict[str, Any] = {}
        if not task_text:
            self._trace_workflow("runtime_plan_skip reason=empty_task_text")
            return plan
        if self._is_acknowledgement_turn(task_text):
            self._trace_workflow("runtime_plan_skip reason=acknowledgement_turn")
            return plan

        payload = self.last_tool_payload if isinstance(self.last_tool_payload, dict) else {}
        raw_plan = payload.get("workflow_plan", {})
        raw_chain = payload.get("workflow_suggested_chain", [])

        if isinstance(raw_plan, dict):
            plan = dict(raw_plan)
        if "tool_chain" not in plan and isinstance(raw_chain, list):
            plan["tool_chain"] = list(raw_chain)

        chain = [
            str(name)
            for name in list(plan.get("tool_chain", []) or [])
            if isinstance(name, str) and name in set(available_tools)
        ]
        if len(chain) < 2:
            self._trace_workflow(
                "runtime_plan_skip reason=chain_too_short available=%s proposed=%s",
                sorted(set(available_tools)),
                list(plan.get("tool_chain", []) or []),
            )
            return {}
        chain_budget = self._workflow_chain_step_budget()
        if len(chain) > chain_budget:
            self._trace_workflow(
                "runtime_plan_skip reason=chain_exceeds_budget chain_len=%s budget=%s signature=%s",
                len(chain),
                chain_budget,
                str(plan.get("signature") or ""),
            )
            return {}

        if existing_tool_choice and isinstance(existing_tool_choice, dict):
            forced_name = str((existing_tool_choice.get("function", {}) or {}).get("name") or "").strip()
            if forced_name and forced_name != chain[0]:
                self._trace_workflow(
                    "runtime_plan_skip reason=forced_tool_mismatch forced=%s chain_head=%s",
                    forced_name,
                    chain[0],
                )
                return {}

        plan["tool_chain"] = chain
        plan["active"] = True
        plan["next_index"] = 0
        plan["forced_steps"] = 0
        plan["completed_steps"] = 0
        plan["completed"] = False
        plan["abandon_reason"] = ""
        self._trace_workflow(
            "runtime_plan_ready signature=%s chain=%s source=%s confidence=%s",
            str(plan.get("signature") or ""),
            chain,
            str(plan.get("source") or ""),
            str(plan.get("confidence") or ""),
        )
        return plan

    def _advance_workflow_runtime_plan(
        self,
        workflow_plan: Dict[str, Any],
        called_tools: List[str],
        workflow_failed: bool,
    ) -> Optional[Dict[str, Any]]:
        if not workflow_plan or not workflow_plan.get("active"):
            self._trace_workflow("runtime_advance_skip reason=inactive_plan")
            return None
        chain = list(workflow_plan.get("tool_chain", []) or [])
        if not chain:
            workflow_plan["active"] = False
            self._trace_workflow("runtime_advance_stop reason=empty_chain")
            return None

        try:
            next_index = int(workflow_plan.get("next_index", 0) or 0)
        except Exception:
            next_index = 0
        if next_index < 0:
            next_index = 0
        if next_index >= len(chain):
            workflow_plan["active"] = False
            workflow_plan["completed"] = True
            self._trace_workflow("runtime_advance_stop reason=already_complete")
            return None

        expected = chain[next_index]
        matched = False
        for tool_name in called_tools:
            if next_index < len(chain) and tool_name == chain[next_index]:
                matched = True
                next_index += 1
                workflow_plan["completed_steps"] = int(workflow_plan.get("completed_steps", 0) or 0) + 1

        workflow_plan["next_index"] = next_index
        if not matched:
            workflow_plan["active"] = False
            if called_tools:
                workflow_plan["abandon_reason"] = f"chain_mismatch_expected_{expected}_got_{called_tools[0]}"
            else:
                workflow_plan["abandon_reason"] = f"chain_mismatch_expected_{expected}_got_none"
            self._trace_workflow(
                "runtime_advance_stop reason=chain_mismatch expected=%s called=%s",
                expected,
                called_tools[0] if called_tools else "none",
            )
            return None

        if workflow_failed:
            workflow_plan["active"] = False
            workflow_plan["abandon_reason"] = "workflow_failed"
            self._trace_workflow("runtime_advance_stop reason=workflow_failed")
            return None

        if next_index >= len(chain):
            workflow_plan["active"] = False
            workflow_plan["completed"] = True
            self._trace_workflow("runtime_advance_stop reason=completed")
            return None

        next_tool = chain[next_index]
        workflow_plan["forced_steps"] = int(workflow_plan.get("forced_steps", 0) or 0) + 1
        self._trace_workflow(
            "runtime_advance_next forced_steps=%s next_tool=%s completed_steps=%s",
            int(workflow_plan.get("forced_steps", 0) or 0),
            next_tool,
            int(workflow_plan.get("completed_steps", 0) or 0),
        )
        return self._force_tool_choice(next_tool)

    async def respond(self, user_message: str) -> str:
        """
        Send a user message and handle tool-calling loops.

        Uses the configured provider (or fallback chain) to generate responses.
        Returns the final assistant response text.
        """
        self.history.append({"role": "user", "content": user_message})
        tools_used: List[str] = []
        self.last_tools_used = []
        workflow_failed = False
        workflow_error = ""

        system_prompt = await self._get_system_prompt(
            user_message,
            conversation_id="default",
        )
        tools, tool_choice, selected_categories = await self._build_tool_schemas(user_message)
        available_tool_names = [
            str((tool.get("function", {}) or {}).get("name") or "")
            for tool in tools
            if isinstance(tool, dict)
        ]
        workflow_plan = self._resolve_workflow_runtime_plan(
            task_text=user_message,
            available_tools=[name for name in available_tool_names if name],
            existing_tool_choice=tool_choice,
        )
        self._active_workflow_plan = dict(workflow_plan)
        current_tool_choice = tool_choice
        if workflow_plan and not current_tool_choice:
            workflow_plan["forced_steps"] = int(workflow_plan.get("forced_steps", 0) or 0) + 1
            current_tool_choice = self._force_tool_choice(workflow_plan["tool_chain"][0])
        model_override, model_reason = self._select_model_for_task(user_message, selected_categories)
        self.last_model_used = model_override
        if isinstance(self.last_tool_payload, dict):
            self.last_tool_payload["model_override"] = model_override
            self.last_tool_payload["model_reason"] = model_reason
        media_intent = self._detect_media_generation_intent(user_message)
        media_tool = self._media_tool_for_intent(media_intent)
        if media_tool:
            if media_tool not in available_tool_names:
                unavailable_type = "Video" if media_intent == "video" else "Image"
                unavailable_msg = (
                    f"{unavailable_type} generation is currently unavailable because "
                    f"`{media_tool}` is not registered in this runtime."
                )
                self.last_tools_used = list(tools_used)
                self._emit_routing_signals(
                    user_message, selected_categories, model_override,
                    model_reason, tools_used,
                )
                self._record_workflow_outcome(
                    task_text=user_message,
                    tools_used=tools_used,
                    success=False,
                    conversation_id="default",
                    error=unavailable_msg,
                )
                self._record_workflow_replay_result(
                    task_text=user_message,
                    workflow_plan=workflow_plan,
                    success=False,
                    conversation_id="default",
                    error=unavailable_msg,
                )
                self._active_workflow_plan = {}
                return unavailable_msg
            current_tool_choice = self._force_tool_choice(media_tool)
            workflow_plan = {}
            self._active_workflow_plan = {}
        media_retry_attempted = False

        # Inject system prompt instruction when live data intent requires tool use
        if getattr(self, "_live_data_forced_tool", None):
            tool_name = self._live_data_forced_tool
            system_prompt += (
                f"\n\n## CRITICAL — Live Data Required\n"
                f"The user is asking for information that changes over time (prices, weather, "
                f"news, scores, etc.). You MUST call the `{tool_name}` tool to get current data. "
                f"Do NOT answer from your training data — it may be outdated. "
                f"Call the tool FIRST, then use the result to answer."
            )

        for round_idx in range(self.max_tool_rounds):
            messages = [{"role": "system", "content": system_prompt}] + self.history
            data = await self._call_chat(
                messages,
                tools=tools,
                tool_choice=current_tool_choice,
                generation_config=self._genome_generation_config,
                model_override=model_override,
            )

            choices = data.get("choices", [])
            if not choices:
                self._record_workflow_outcome(
                    task_text=user_message,
                    tools_used=tools_used,
                    success=False,
                    conversation_id="default",
                    error="No response from model",
                )
                self._record_workflow_replay_result(
                    task_text=user_message,
                    workflow_plan=workflow_plan,
                    success=False,
                    conversation_id="default",
                    error="No response from model",
                )
                return "Error: No response from model."

            message = choices[0].get("message", {})
            self.history.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                content = message.get("content") or ""
                if not media_retry_attempted and round_idx < (self.max_tool_rounds - 1):
                    media_retry_tool = self._resolve_media_retry_tool(
                        user_message=user_message,
                        assistant_content=content,
                        available_tool_names=available_tool_names,
                    )
                    if media_retry_tool:
                        media_retry_attempted = True
                        if self.history:
                            self.history.pop()
                        current_tool_choice = self._force_tool_choice(media_retry_tool)
                        system_prompt += (
                            f"\n\n## CRITICAL — Media Generation Required\n"
                            f"The user asked for generated media. You MUST call `{media_retry_tool}` "
                            f"before making any success claim. Do not output placeholder media text."
                        )
                        logger.warning(
                            "Media intent/claim detected without tool call; retrying with forced tool: %s",
                            media_retry_tool,
                        )
                        continue

                self.last_tools_used = list(tools_used)
                self._emit_routing_signals(
                    user_message, selected_categories, model_override,
                    model_reason, tools_used,
                )
                self._record_workflow_outcome(
                    task_text=user_message,
                    tools_used=tools_used,
                    success=not workflow_failed,
                    conversation_id="default",
                    error=workflow_error,
                )
                replay_error = workflow_error or str(workflow_plan.get("abandon_reason") or "")
                replay_success = (
                    (not workflow_failed)
                    and (
                        not workflow_plan
                        or int(workflow_plan.get("forced_steps", 0) or 0) <= 0
                        or bool(workflow_plan.get("completed", False))
                    )
                )
                if workflow_plan and int(workflow_plan.get("forced_steps", 0) or 0) > 0 and not replay_success and not replay_error:
                    replay_error = "cached_chain_not_completed"
                self._record_workflow_replay_result(
                    task_text=user_message,
                    workflow_plan=workflow_plan,
                    success=replay_success,
                    conversation_id="default",
                    error=replay_error,
                )
                self._active_workflow_plan = dict(workflow_plan)
                sanitized = self._sanitize_response_text(content)
                if sanitized != content:
                    message["content"] = sanitized
                return sanitized

            called_tools: List[str] = []
            for call in tool_calls:
                func = call.get("function", {})
                tool_name = func.get("name", "")
                if tool_name:
                    called_tools.append(tool_name)
                if tool_name and tool_name not in tools_used:
                    tools_used.append(tool_name)
                args_raw = func.get("arguments", "{}")
                try:
                    params = json.loads(args_raw) if args_raw else {}
                except json.JSONDecodeError:
                    params = {}
                resolved_tool_name, resolved_params = self._resolve_tool_alias(tool_name, params)

                tool_result = ""
                exec_start = time.time()
                exec_status = "ok"
                if self.vera and getattr(self.vera, "execute_tool", None):
                    try:
                        tool_result = await self.vera.execute_tool(
                            resolved_tool_name,
                            resolved_params,
                            context={"query": user_message, "conversation_id": "default"}
                        )
                    except Exception as exc:
                        tool_result = f"Tool execution error: {exc}"
                        exec_status = "error"
                else:
                    tool_result = f"Tool execution unavailable for: {tool_name}"
                    exec_status = "error"

                if exec_status == "ok" and self._tool_result_requires_confirmation(tool_result):
                    exec_status = "error"
                    if not workflow_error:
                        workflow_error = f"confirmation_required:{tool_name}"
                    workflow_failed = True
                    if workflow_plan and workflow_plan.get("active"):
                        workflow_plan["active"] = False
                        if not workflow_plan.get("abandon_reason"):
                            workflow_plan["abandon_reason"] = f"confirmation_required:{tool_name}"

                exec_entry = {
                    "tool_name": tool_name,
                    "server": getattr(self, "_tool_to_server", {}).get(tool_name, ""),
                    "status": "success" if exec_status == "ok" else "error",
                    "duration_ms": int((time.time() - exec_start) * 1000),
                    "timestamp": datetime.now().isoformat(),
                    "result_length": len(str(tool_result)),
                }
                if exec_status != "ok":
                    exec_entry["error"] = str(tool_result)[:200]
                    workflow_failed = True
                    if not workflow_error:
                        workflow_error = str(tool_result)[:220]
                    if workflow_plan and workflow_plan.get("active"):
                        workflow_plan["active"] = False
                        if not workflow_plan.get("abandon_reason"):
                            workflow_plan["abandon_reason"] = f"tool_execution_error:{tool_name}"
                self.tool_execution_history.append(exec_entry)
                if len(self.tool_execution_history) > 100:
                    self.tool_execution_history = self.tool_execution_history[-100:]

                self.history.append({
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": tool_name,
                    "content": tool_result,
                })
            current_tool_choice = self._advance_workflow_runtime_plan(
                workflow_plan=workflow_plan,
                called_tools=called_tools,
                workflow_failed=workflow_failed,
            )

        self.last_tools_used = list(tools_used)
        self._emit_routing_signals(
            user_message, selected_categories, model_override,
            model_reason, tools_used,
        )
        self._record_workflow_outcome(
            task_text=user_message,
            tools_used=tools_used,
            success=False,
            conversation_id="default",
            error=workflow_error or "Tool call limit reached",
        )
        replay_error = workflow_error or str(workflow_plan.get("abandon_reason") or "Tool call limit reached")
        self._record_workflow_replay_result(
            task_text=user_message,
            workflow_plan=workflow_plan,
            success=False,
            conversation_id="default",
            error=replay_error,
        )
        self._active_workflow_plan = dict(workflow_plan)
        return "Tool call limit reached; unable to complete the request."

    async def respond_messages(
        self,
        messages: List[Dict[str, Any]],
        system_override: Optional[str] = None,
        persist_history: bool = False,
        generation_config: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        tool_choice_override: Optional[Any] = None,
    ) -> str:
        """
        Respond using a full message list (OpenAI format), with tool support.

        If persist_history is False, the internal history is not modified.
        """
        history = [m for m in messages if m.get("role") != "system"]
        if persist_history:
            self.history = list(history)

        tools_used: List[str] = []
        workflow_failed = False
        workflow_error = ""
        effective_generation_config = generation_config or self._genome_generation_config
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = msg.get("content", "")
                break
        # Don't reset tools tracking for auto-title requests
        _is_title_gen = "5 words or less" in last_user.lower() if last_user else False
        if not _is_title_gen:
            self.last_tools_used = []
        system_prompt = await self._get_system_prompt(
            last_user,
            system_override,
            conversation_id=conversation_id,
        )
        tools, tool_choice, selected_categories = await self._build_tool_schemas(last_user)
        forced_override_name = ""
        if isinstance(tool_choice_override, dict):
            forced_override_name = str(
                ((tool_choice_override.get("function") or {}).get("name") or "")
            ).strip()
        forced_override_available = True
        if forced_override_name:
            current_names = [
                str((tool.get("function", {}) or {}).get("name") or "")
                for tool in tools
                if isinstance(tool, dict)
            ]
            if forced_override_name not in current_names:
                augmented_context = (
                    f"{last_user}\n\n"
                    f"Tool override requirement: `{forced_override_name}`"
                ).strip()
                tools, tool_choice, selected_categories = await self._build_tool_schemas(
                    augmented_context
                )
                refreshed_names = [
                    str((tool.get("function", {}) or {}).get("name") or "")
                    for tool in tools
                    if isinstance(tool, dict)
                ]
                if forced_override_name in refreshed_names:
                    logger.info(
                        "Forced tool override injected into schema set: %s",
                        forced_override_name,
                    )
                else:
                    forced_override_available = False
                    logger.warning(
                        "Forced tool override still unavailable in schema set: %s",
                        forced_override_name,
                    )
        available_tool_names = [
            str((tool.get("function", {}) or {}).get("name") or "")
            for tool in tools
            if isinstance(tool, dict)
        ]
        model_override, model_reason = self._select_model_for_task(last_user, selected_categories)
        self.last_model_used = model_override
        if isinstance(self.last_tool_payload, dict):
            self.last_tool_payload["model_override"] = model_override
            self.last_tool_payload["model_reason"] = model_reason
        effective_tool_choice = tool_choice_override if tool_choice_override is not None else tool_choice
        if tool_choice_override is not None and forced_override_name and not forced_override_available:
            # Avoid invalid forced tool_choice payloads that trigger provider 400 responses.
            effective_tool_choice = tool_choice
            logger.warning(
                "Requested tool_choice override unavailable; falling back to auto selection: %s",
                forced_override_name,
            )
        workflow_plan = self._resolve_workflow_runtime_plan(
            task_text=last_user,
            available_tools=[name for name in available_tool_names if name],
            existing_tool_choice=effective_tool_choice if isinstance(effective_tool_choice, dict) else None,
        )
        self._active_workflow_plan = dict(workflow_plan)
        current_tool_choice = effective_tool_choice
        if workflow_plan and not current_tool_choice:
            workflow_plan["forced_steps"] = int(workflow_plan.get("forced_steps", 0) or 0) + 1
            current_tool_choice = self._force_tool_choice(workflow_plan["tool_chain"][0])
        media_intent = self._detect_media_generation_intent(last_user)
        media_tool = self._media_tool_for_intent(media_intent)
        if media_tool:
            if media_tool not in available_tool_names:
                unavailable_type = "Video" if media_intent == "video" else "Image"
                unavailable_msg = (
                    f"{unavailable_type} generation is currently unavailable because "
                    f"`{media_tool}` is not registered in this runtime."
                )
                if persist_history:
                    self.history = list(history)
                if not _is_title_gen:
                    self.last_tools_used = list(tools_used)
                self._emit_routing_signals(
                    last_user, selected_categories, model_override,
                    model_reason, tools_used, conversation_id or "default",
                )
                self._record_workflow_outcome(
                    task_text=last_user,
                    tools_used=tools_used,
                    success=False,
                    conversation_id=conversation_id or "default",
                    error=unavailable_msg,
                )
                self._record_workflow_replay_result(
                    task_text=last_user,
                    workflow_plan=workflow_plan,
                    success=False,
                    conversation_id=conversation_id or "default",
                    error=unavailable_msg,
                )
                self._active_workflow_plan = {}
                return unavailable_msg
            current_tool_choice = self._force_tool_choice(media_tool)
            workflow_plan = {}
            self._active_workflow_plan = {}
        if isinstance(self.last_tool_payload, dict):
            self.last_tool_payload["requested_tool_choice"] = (
                effective_tool_choice if effective_tool_choice is not None else "auto"
            )
        media_retry_attempted = False

        # Inject system prompt instruction when live data intent requires tool use
        if getattr(self, "_live_data_forced_tool", None):
            tool_name = self._live_data_forced_tool
            system_prompt += (
                f"\n\n## CRITICAL — Live Data Required\n"
                f"The user is asking for information that changes over time (prices, weather, "
                f"news, scores, etc.). You MUST call the `{tool_name}` tool to get current data. "
                f"Do NOT answer from your training data — it may be outdated. "
                f"Call the tool FIRST, then use the result to answer."
            )
            logger.info("Injected live-data system prompt for tool: %s", tool_name)

        working_history = list(history)
        for _round_idx in range(self.max_tool_rounds):
            payload_messages = [{"role": "system", "content": system_prompt}] + working_history
            data = await self._call_chat(
                payload_messages,
                tools=tools,
                generation_config=effective_generation_config,
                tool_choice=current_tool_choice,
                model_override=model_override,
            )

            choices = data.get("choices", [])
            if not choices:
                self._record_workflow_outcome(
                    task_text=last_user,
                    tools_used=tools_used,
                    success=False,
                    conversation_id=conversation_id or "default",
                    error="No response from model",
                )
                self._record_workflow_replay_result(
                    task_text=last_user,
                    workflow_plan=workflow_plan,
                    success=False,
                    conversation_id=conversation_id or "default",
                    error="No response from model",
                )
                self._active_workflow_plan = dict(workflow_plan)
                return "Error: No response from model."

            message = choices[0].get("message", {})
            working_history.append(message)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                content = message.get("content") or ""
                if not media_retry_attempted and _round_idx < (self.max_tool_rounds - 1):
                    media_retry_tool = self._resolve_media_retry_tool(
                        user_message=last_user,
                        assistant_content=content,
                        available_tool_names=available_tool_names,
                    )
                    if media_retry_tool:
                        media_retry_attempted = True
                        if working_history:
                            working_history.pop()
                        current_tool_choice = self._force_tool_choice(media_retry_tool)
                        system_prompt += (
                            f"\n\n## CRITICAL — Media Generation Required\n"
                            f"The user asked for generated media. You MUST call `{media_retry_tool}` "
                            f"before making any success claim. Do not output placeholder media text."
                        )
                        logger.warning(
                            "Media intent/claim detected without tool call; retrying with forced tool: %s",
                            media_retry_tool,
                        )
                        continue

                if persist_history:
                    self.history = working_history
                if not _is_title_gen:
                    self.last_tools_used = list(tools_used)
                self._emit_routing_signals(
                    last_user, selected_categories, model_override,
                    model_reason, tools_used, conversation_id or "default",
                )
                self._record_workflow_outcome(
                    task_text=last_user,
                    tools_used=tools_used,
                    success=not workflow_failed,
                    conversation_id=conversation_id or "default",
                    error=workflow_error,
                )
                replay_error = workflow_error or str(workflow_plan.get("abandon_reason") or "")
                replay_success = (
                    (not workflow_failed)
                    and (
                        not workflow_plan
                        or int(workflow_plan.get("forced_steps", 0) or 0) <= 0
                        or bool(workflow_plan.get("completed", False))
                    )
                )
                if workflow_plan and int(workflow_plan.get("forced_steps", 0) or 0) > 0 and not replay_success and not replay_error:
                    replay_error = "cached_chain_not_completed"
                self._record_workflow_replay_result(
                    task_text=last_user,
                    workflow_plan=workflow_plan,
                    success=replay_success,
                    conversation_id=conversation_id or "default",
                    error=replay_error,
                )
                self._active_workflow_plan = dict(workflow_plan)
                sanitized = self._sanitize_response_text(content)
                if sanitized != content:
                    message["content"] = sanitized
                return sanitized

            called_tools: List[str] = []
            for call in tool_calls:
                func = call.get("function", {})
                tool_name = func.get("name", "")
                if tool_name:
                    called_tools.append(tool_name)
                if tool_name and tool_name not in tools_used:
                    tools_used.append(tool_name)
                args_raw = func.get("arguments", "{}")
                try:
                    params = json.loads(args_raw) if args_raw else {}
                except json.JSONDecodeError:
                    params = {}
                resolved_tool_name, resolved_params = self._resolve_tool_alias(tool_name, params)

                tool_result = ""
                exec_start = time.time()
                exec_status = "ok"
                if self.vera and getattr(self.vera, "execute_tool", None):
                    try:
                        tool_result = await self.vera.execute_tool(
                            resolved_tool_name,
                            resolved_params,
                            context={"source": "api", "conversation_id": conversation_id}
                        )
                    except Exception as exc:
                        tool_result = f"Tool execution error: {exc}"
                        exec_status = "error"
                else:
                    tool_result = f"Tool execution unavailable for: {tool_name}"
                    exec_status = "error"

                if exec_status == "ok" and self._tool_result_requires_confirmation(tool_result):
                    exec_status = "error"
                    if not workflow_error:
                        workflow_error = f"confirmation_required:{tool_name}"
                    workflow_failed = True
                    if workflow_plan and workflow_plan.get("active"):
                        workflow_plan["active"] = False
                        if not workflow_plan.get("abandon_reason"):
                            workflow_plan["abandon_reason"] = f"confirmation_required:{tool_name}"

                # Record execution in history
                exec_entry = {
                    "tool_name": tool_name,
                    "server": getattr(self, "_tool_to_server", {}).get(tool_name, ""),
                    "status": "success" if exec_status == "ok" else "error",
                    "duration_ms": int((time.time() - exec_start) * 1000),
                    "timestamp": datetime.now().isoformat(),
                    "result_length": len(str(tool_result)),
                }
                if exec_status != "ok":
                    exec_entry["error"] = str(tool_result)[:200]
                    workflow_failed = True
                    if not workflow_error:
                        workflow_error = str(tool_result)[:220]
                    if workflow_plan and workflow_plan.get("active"):
                        workflow_plan["active"] = False
                        if not workflow_plan.get("abandon_reason"):
                            workflow_plan["abandon_reason"] = f"tool_execution_error:{tool_name}"
                self.tool_execution_history.append(exec_entry)
                # Cap at 100 entries
                if len(self.tool_execution_history) > 100:
                    self.tool_execution_history = self.tool_execution_history[-100:]

                working_history.append({
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": tool_name,
                    "content": tool_result,
                })
            current_tool_choice = self._advance_workflow_runtime_plan(
                workflow_plan=workflow_plan,
                called_tools=called_tools,
                workflow_failed=workflow_failed,
            )

        if persist_history:
            self.history = working_history
        if not _is_title_gen:
            self.last_tools_used = list(tools_used)
        self._emit_routing_signals(
            last_user, selected_categories, model_override,
            model_reason, tools_used, conversation_id or "default",
        )
        self._record_workflow_outcome(
            task_text=last_user,
            tools_used=tools_used,
            success=False,
            conversation_id=conversation_id or "default",
            error=workflow_error or "Tool call limit reached",
        )
        replay_error = workflow_error or str(workflow_plan.get("abandon_reason") or "Tool call limit reached")
        self._record_workflow_replay_result(
            task_text=last_user,
            workflow_plan=workflow_plan,
            success=False,
            conversation_id=conversation_id or "default",
            error=replay_error,
        )
        self._active_workflow_plan = dict(workflow_plan)

        return "Tool call limit reached; unable to complete the request."

    async def parse_structured(
        self,
        messages: List[Dict[str, Any]],
        response_model: Type[T],
        system_override: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None
    ) -> T:
        """
        Parse a structured response using a Pydantic model.

        Similar to OpenAI's client.beta.chat.completions.parse() - sends a request
        with JSON schema enforcement and parses the response into the model.

        Args:
            messages: List of messages in OpenAI format
            response_model: Pydantic BaseModel class to parse response into
            system_override: Optional system prompt override
            generation_config: Optional generation parameters

        Returns:
            Parsed instance of response_model

        Raises:
            ValueError: If Pydantic is not available or parsing fails
            RuntimeError: If API request fails
        """
        if not PYDANTIC_AVAILABLE:
            raise ValueError("Pydantic is required for structured output parsing")

        if not hasattr(response_model, "model_json_schema"):
            raise ValueError(f"{response_model} must be a Pydantic BaseModel")

        # Build response_format with JSON schema from Pydantic model
        schema = response_model.model_json_schema()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "strict": True,
                "schema": schema
            }
        }

        # Prepare messages with optional system override
        history = [m for m in messages if m.get("role") != "system"]
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = msg.get("content", "")
                break
        system_prompt = await self._get_system_prompt(last_user, system_override)
        payload_messages = [{"role": "system", "content": system_prompt}] + history

        # Call API with structured output
        data = await self._call_chat(
            payload_messages,
            tools=None,
            generation_config=generation_config,
            response_format=response_format
        )

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("No response from model")

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise RuntimeError("Empty response from model")

        # Parse JSON and validate with Pydantic
        try:
            parsed_data = json.loads(content)
            return response_model.model_validate(parsed_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}") from e
        except Exception as e:
            raise ValueError(f"Failed to validate response: {e}") from e

    async def json_mode(
        self,
        messages: List[Dict[str, Any]],
        system_override: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Request a JSON response without schema enforcement.

        Simpler than parse_structured - just ensures JSON output.

        Args:
            messages: List of messages in OpenAI format
            system_override: Optional system prompt override
            generation_config: Optional generation parameters

        Returns:
            Parsed JSON as a dictionary

        Raises:
            RuntimeError: If API request fails
            ValueError: If response is not valid JSON
        """
        response_format = {"type": "json_object"}

        history = [m for m in messages if m.get("role") != "system"]
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = msg.get("content", "")
                break
        system_prompt = await self._get_system_prompt(last_user, system_override)
        # Ensure system prompt mentions JSON for best results
        if "json" not in system_prompt.lower():
            system_prompt = f"{system_prompt}\n\nRespond with valid JSON only."
        payload_messages = [{"role": "system", "content": system_prompt}] + history

        data = await self._call_chat(
            payload_messages,
            tools=None,
            generation_config=generation_config,
            response_format=response_format
        )

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("No response from model")

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise RuntimeError("Empty response from model")

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON response: {e}") from e


# Backward-compatible alias so existing imports still work
GrokReasoningBridge = LLMBridge
