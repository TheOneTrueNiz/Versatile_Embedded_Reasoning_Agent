#!/usr/bin/env python3
"""
VERA Main Orchestrator
======================

Main VERA class that integrates all Phase 2 components.

Integrates:
- Configuration
- Observability
- Health monitoring
- Checkpointing
- Memory service
- Tool execution
- Quorum system
- Safety validation
- Panic button (emergency shutdown)
- Master task list (hard backlog)
- Bootloader integration (crash recovery)
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Tuple
from urllib.parse import urlparse

import httpx

# Observable thinking stream
try:
    from core.runtime.thinking_stream import emit_thinking, thinking_tool
    THINKING_AVAILABLE = True
except ImportError:
    THINKING_AVAILABLE = False
    def emit_thinking(*args, **kwargs): pass
    def thinking_tool(*args, **kwargs): pass

# Swarm actions blocked outright (manual only, no automatic execution).
SWARM_BLOCKLIST_PATTERNS = [
    ("filesystem changes", re.compile(r"\b(delete|remove|rm -rf|wipe|format|erase)\b", re.IGNORECASE)),
    ("shell/command execution", re.compile(r"\b(shell|terminal|command|bash|zsh|powershell|script)\b", re.IGNORECASE)),
    ("credentials or OAuth", re.compile(r"\b(api key|token|oauth|credential|password|secret|client_secret)\b", re.IGNORECASE)),
    ("email or calendar actions", re.compile(r"\b(send email|gmail|calendar|invite|meeting)\b", re.IGNORECASE)),
    ("browser or desktop automation", re.compile(r"\b(browser|click|scroll|desktop|keyboard|mouse)\b", re.IGNORECASE)),
    ("financial actions", re.compile(r"\b(buy|purchase|order|payment|transfer|bank|credit card|billing)\b", re.IGNORECASE)),
    ("system control", re.compile(r"\b(shutdown|reboot|power off|restart|format disk)\b", re.IGNORECASE)),
]


def _generated_media_root() -> Path:
    raw = os.getenv("VERA_GENERATED_MEDIA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path("vera_memory") / "generated_media"


def _generated_media_manifest_path() -> Path:
    return _generated_media_root() / "manifest.json"


def _guess_generated_media_suffix(url: str, fallback: str) -> str:
    try:
        suffix = Path(urlparse(str(url or "")).path).suffix.strip().lower()
    except Exception:
        suffix = ""
    if suffix and len(suffix) <= 10:
        return suffix
    return fallback


def _slugify_generated_media_label(value: str, maximum: int = 48) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    if not cleaned:
        cleaned = "generated"
    return cleaned[:maximum].rstrip("-") or "generated"


def _record_generated_media_manifest(items: List[Dict[str, Any]]) -> Path:
    manifest_path = _generated_media_manifest_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = safe_json_read(manifest_path, default={}) or {}
    existing = payload.get("items")
    rows = list(existing) if isinstance(existing, list) else []
    rows.extend(items)
    payload["items"] = rows[-500:]
    payload["updated_at"] = datetime.now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    atomic_json_write(manifest_path, payload)
    return manifest_path


async def _cache_generated_media_urls(
    media_kind: str,
    prompt: str,
    model: str,
    urls: List[str],
) -> Dict[str, Any]:
    clean_urls = [str(url).strip() for url in (urls or []) if str(url).strip()]
    if not clean_urls:
        return {"local_paths": [], "items": [], "manifest_path": ""}

    root = _generated_media_root()
    now_utc = datetime.now().astimezone(timezone.utc)
    kind_dir = root / media_kind / now_utc.strftime("%Y%m%d")
    kind_dir.mkdir(parents=True, exist_ok=True)
    prompt_slug = _slugify_generated_media_label(prompt)
    prompt_hash = hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()[:12]
    timeout_seconds = max(5.0, float(os.getenv("VERA_GENERATED_MEDIA_DOWNLOAD_TIMEOUT_SECONDS", "120")))
    items: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
        for index, url in enumerate(clean_urls, start=1):
            suffix = _guess_generated_media_suffix(
                url,
                ".mp4" if media_kind == "video" else ".png",
            )
            item_now_utc = datetime.now().astimezone(timezone.utc)
            filename = f"{item_now_utc.strftime('%Y%m%dT%H%M%SZ')}_{prompt_slug}_{prompt_hash}_{index:02d}{suffix}"
            target = kind_dir / filename
            item: Dict[str, Any] = {
                "created_at": item_now_utc.isoformat().replace("+00:00", "Z"),
                "media_kind": media_kind,
                "model": str(model or ""),
                "prompt": str(prompt or ""),
                "remote_url": url,
                "local_path": str(target),
                "status": "pending",
            }
            try:
                response = await client.get(url)
                response.raise_for_status()
                target.write_bytes(response.content)
                item["status"] = "cached"
                item["bytes"] = target.stat().st_size
                item["content_type"] = str(response.headers.get("content-type") or "")
            except Exception as exc:
                logger.warning("Generated media cache download failed for %s: %s", url, exc)
                item["status"] = "download_failed"
                item["error"] = str(exc)
            items.append(item)

    manifest_path = _record_generated_media_manifest(items)
    local_paths = [item["local_path"] for item in items if item.get("status") == "cached"]
    return {
        "local_paths": local_paths,
        "items": items,
        "manifest_path": str(manifest_path),
    }

# Ensure src/ is in path (for sibling modules)
_src_path = Path(__file__).parent.parent.parent  # Go up to src/
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

# Phase 2 Components
from orchestration.async_tool_executor import AsyncToolExecutor
from orchestration.tool_output_filter import ToolOutputFilter
from orchestration.tool_output_verifier import ToolOutputVerifier
from orchestration.error_handler import ErrorHandler
from orchestration.llm_bridge import LLMBridge, GrokReasoningBridge  # GrokReasoningBridge is alias for backward compat
from quorum.quorum_shared_memory import SharedBlackboard
from memory.retrieval.tool_selection_memory import ToolSelectionMemory
from memory.retrieval.tool_result_cache import init_cache

# Safety & Quorum systems
from safety.safety_validator import SafetyValidator, ValidationDecision
from quorum import QuorumSelector, AGENT_PROFILES, ConsensusEngine
from quorum.premade_quorums import get_quorum, SWARM_QUORUM
from quorum.custom_quorums import get_custom_quorum, get_custom_quorum_spec, build_quorum_from_spec
from quorum.moa_executor import MoAExecutor, MoAResult

# Tier 1: GROKSTAR Port - Critical Infrastructure (core/foundation/)
from core.foundation.panic_button import PanicButton, init_panic_button, PanicReason
from core.foundation.master_list import MasterTaskList, TaskPriority, TaskStatus
from core.foundation.bootloader import Bootloader

# Tier 2: GROKSTAR Port - Trust & Safety (observability/)
from observability.decision_ledger import DecisionType
from observability.git_context import GitContext

# Tier 3: GROKSTAR Port - Productivity Enhancement
from core.foundation.anti_spiral import RabbitHoleDetector, SpiralStatus, SpiralSeverity
from planning.project_charter import CharterManager, ProjectCharter, CharterStatus
from context.preferences import (
    PreferenceManager,
    PreferenceCategory,
    extract_constraints_from_text,
    tokenize_text,
    limit_tokens,
)
from context.personality_seed import PersonalitySeedManager
from memory.retrieval.semantic_dedup import SemanticDeduplicator
from core.atomic_io import atomic_json_write, safe_json_read

# Improvement #22: Darwinian Self-Evolution Loop
from learning.darwin_loop import (
    DarwinLoop, EvolutionConfig, MutationType,
    SafetyConstraint, MutationSeverity, Individual
)

# MCP Server Orchestration (Gap 7)
from orchestration.mcp_orchestrator import MCPOrchestrator
# VERA core modules
from .config import VERAConfig
from .prompts import VERA_SYSTEM_PROMPT, build_system_prompt_with_context
from .tool_orchestrator import ToolOrchestrator
from .llm_router import LLMRouter
from .command_handler import CommandHandler
from .safety_manager import SafetyManager
from .proactive_manager import ProactiveManager
from .voice_manager import VoiceManager
from .health import VERAHealthMonitor
from .checkpoint import VERACheckpoint
from core.services.observability import VERAObservability
from core.services.memory_service import VERAMemoryService
from core.services.flight_recorder import FlightRecorder
from core.services.event_bus import EventPriority, get_event_bus

logger = logging.getLogger(__name__)


class VERA:
    """
    VERA Personal AI Assistant (Production)

    Integrates all Phase 2 components with observability and fault tolerance.

    Tier 1 Foundation Features:
    - Panic button for emergency shutdown
    - Master task list for reliable task tracking
    - Bootloader integration for crash recovery

    Tier 2 Trust & Safety Features:
    - Decision ledger for tracking reasoning
    - Provenance tracking for source attribution
    - Cost tracking (token thermostat)
    - Git context awareness
    - Action reversibility tracking

    Tier 3 Productivity Features:
    - Rabbit hole detector (anti-spiral protection)
    - Internal critic (self-review before responding)
    - Project charters (planning documentation)
    - User preference learning
    - Semantic deduplication
    """

    def __init__(self, config: VERAConfig, bootloader: Optional[Bootloader] = None) -> None:
        self.config = config
        self.running = False
        self.bootloader = bootloader

        # Observability
        self.observability = VERAObservability(enabled=config.observability)
        self.event_bus = get_event_bus()

        # Fault tolerance
        self.health_monitor = VERAHealthMonitor()
        self.checkpoint = VERACheckpoint(Path("vera_checkpoints"))

        # Memory service
        self.memory = VERAMemoryService(config)
        flight_enabled = os.getenv("VERA_FLIGHT_RECORDER", "1").lower() not in {"0", "false", "off"}
        self.flight_recorder = FlightRecorder(
            base_dir=Path("vera_memory") / "flight_recorder",
            enabled=flight_enabled,
        )
        self._red_team_state_path = Path("vera_memory") / "flight_recorder" / "red_team_state.json"
        self._red_team_running = False

        # Week 1: Tool system
        self.tool_executor = AsyncToolExecutor(max_concurrent=config.max_tool_concurrency)
        self.output_filter = ToolOutputFilter()
        self.tool_output_verifier = ToolOutputVerifier()
        self.tool_executor.set_tool_executor(self._internal_tool_call_handler)
        self.cache = init_cache(max_size=1000, enable_persistence=True)
        self.error_handler = ErrorHandler(max_retries=3, base_backoff=1.5)

        # Week 2: Quorum & tool selection
        self.shared_memory = SharedBlackboard()
        self.tool_selection = ToolSelectionMemory()

        # Safety & Quorum systems
        self.safety_validator = SafetyValidator()
        self.quorum_selector = QuorumSelector()
        self.consensus_engine = ConsensusEngine()
        self.tool_orchestrator = ToolOrchestrator(self)

        # MoA Executor for real LLM-powered quorum consultations
        self.moa_executor = MoAExecutor(
            enable_blackboard=True,
            max_rounds=1  # Single-pass for now, can enable multi-round later
        )

        # Quorum/Swarm controls
        self.quorum_auto_enabled = False
        self.swarm_auto_enabled = False
        try:
            self.quorum_max_calls = int(os.getenv("VERA_QUORUM_MAX_CALLS", "3"))
        except (ValueError, TypeError):
            self.quorum_max_calls = 3
        self.swarm_max_calls = int(os.getenv("VERA_SWARM_MAX_CALLS", "1"))
        self._quorum_calls = 0
        self._swarm_calls = 0
        self._quorum_active = False
        self._swarm_active = False
        self._quorum_status: Dict[str, Any] = {
            "status": "idle",
            "mode": "quorum",
            "trigger": "auto",
            "quorum": "",
            "agents": [],
            "decision": "",
            "consensus": "",
            "summary": "",
            "reason": "",
            "started_at": "",
            "finished_at": "",
            "latency_ms": 0,
        }
        self._quorum_lock = asyncio.Lock()
        self._swarm_lock = asyncio.Lock()
        self._load_quorum_settings()

        # === Tier 1: Foundation ===
        # Panic button for emergency shutdown
        self.panic_button = init_panic_button()

        # Master task list (hard markdown backlog)
        self.master_list = MasterTaskList(
            memory_dir=Path("vera_memory")
        )

        # === Tier 2: Trust & Safety ===
        memory_dir = Path("vera_memory")
        self.safety_manager = SafetyManager(self, memory_dir, config)

        # Git context awareness
        self.git_context = GitContext(repo_path=Path.cwd())

        # === Tier 3: Productivity Enhancement ===

        # Rabbit hole detector (anti-spiral protection)
        self.rabbit_hole = RabbitHoleDetector(memory_dir=memory_dir)

        # Project charters (planning documentation)
        self.charters = CharterManager(memory_dir=memory_dir)

        # Tool safety confirmation state (persisted per conversation)
        self._pending_tool_confirmations: Dict[str, Dict[str, Any]] = {}
        self._pending_tool_confirmations_path = memory_dir / ".cache" / "pending_tool_confirmations.json"
        self._pending_confirmation_ttl_seconds = int(
            os.getenv("VERA_CONFIRMATION_TTL_SECONDS", "1800")
        )
        self._confirmation_events: List[Dict[str, Any]] = []
        self._load_pending_tool_confirmations()

        # User preference learning
        self.preferences = PreferenceManager(memory_dir=memory_dir)
        self.personality_seed = PersonalitySeedManager(memory_dir=memory_dir)

        # Speaker recognition with memory decay
        from core.runtime.speaker_memory import SpeakerMemory
        self.speaker_memory = SpeakerMemory(memory_dir=memory_dir)

        # Semantic deduplication
        self.deduplicator = SemanticDeduplicator(memory_dir=memory_dir)

        # === Improvement #11 & #12: Proactive Intelligence ===
        self.proactive_manager = ProactiveManager(self, memory_dir)
        self._sentiment_analyzer = None
        self.learning_loop = None
        try:
            from learning.learning_loop_manager import LearningLoopManager
            self.learning_loop = LearningLoopManager(
                memory_dir=memory_dir,
                ledger=self.decision_ledger,
                event_bus=self.event_bus,
            )
        except Exception as exc:
            logger.warning("Learning loop manager disabled: %s", exc)

        self._history_summary_cache: Dict[str, Dict[str, Any]] = {}
        self._history_summary_locks: Dict[str, asyncio.Lock] = {}

        # === Improvement #22: Darwinian Self-Evolution ===
        # Only active in dev_mode for safety
        self.darwin_enabled = getattr(config, 'dev_mode', False)
        self.darwin = DarwinLoop(
            config=EvolutionConfig(
                population_size=5,       # Conservative population
                elite_count=1,
                mutation_rate=0.2,       # Low mutation rate
                max_generations=10,      # Limited generations per cycle
                stagnation_limit=3,
                min_fitness_threshold=0.8  # High bar for acceptance
            ),
            storage_path=memory_dir / "darwin_archive"
        )
        # Add extra safety constraints for self-modification
        self.darwin.add_safety_constraint(SafetyConstraint(
            constraint_id="protect_vera_core",
            name="Protect VERA Core",
            description="Prevent modifications to core runtime",
            pattern=r".*",
            forbidden_targets=["vera.py", "config.py", "safety_validator.py"],
            max_severity=MutationSeverity.TRIVIAL,
            requires_approval=True
        ))
        self._darwin_task: Optional[asyncio.Task] = None

        # === MCP Server Orchestration (Gap 7) ===
        mcp_config = memory_dir / "mcp_servers.json"
        self.mcp = MCPOrchestrator(config_file=mcp_config if mcp_config.exists() else None)
        self._mcp_health_task: Optional[asyncio.Task] = None
        self._mcp_start_task: Optional[asyncio.Task] = None

        # === Native Tool Bridges (browser/desktop/pdf) ===
        self._native_tool_defs: List[Dict[str, Any]] = []
        self._native_tool_handlers: Dict[str, Callable[[str, Dict[str, Any]], Any]] = {}
        self._native_tool_errors: Dict[str, str] = {}
        self._browser_bridge = None
        self._desktop_bridge = None
        self._pdf_bridge = None
        self._init_native_tools()

        # Session tracking
        self.session_start = datetime.now()
        self.events_processed = 0
        self._llm_bridge: Optional[LLMBridge] = None
        self._provider_registry = None  # Initialized in start()
        self.llm_router = LLMRouter(self)
        self._voice_agent: Optional[Any] = None
        self._voice_bridge: Optional[Any] = None
        self.voice_manager = VoiceManager(self)
        self.command_handler = CommandHandler(self)

        # VERA 2.0: Hook system, channel dock, session store
        self.hook_registry = None
        self.channel_dock = None
        self.session_store = None
        self._init_vera2_systems()

    def _init_vera2_systems(self):
        """Initialize VERA 2.0 systems: hooks, channels, sessions."""
        # Hook registry
        try:
            from core.hooks.registry import HookRegistry
            self.hook_registry = HookRegistry()
            logger.info("Hook registry initialized")
        except ImportError:
            logger.debug("Hook system not available")

        # Channel dock
        try:
            from channels.dock import ChannelDock
            self.channel_dock = ChannelDock()
            logger.info("Channel dock initialized")
        except ImportError:
            logger.debug("Channel system not available")

        # Session store
        try:
            from sessions.store import SessionStore
            from sessions.types import SessionScope
            self.session_store = SessionStore(
                ttl_seconds=3600,
                max_history=50,
                scope=SessionScope.PER_SENDER,
            )
            logger.info("Session store initialized")
        except ImportError:
            logger.debug("Session system not available")

    async def handle_channel_message(self, message, adapter_id: Optional[str] = None) -> str:
        """Handle an inbound message from any channel.

        This is the unified entry point for all channel adapters.
        Routes through session management and delegates to process_messages().

        Args:
            message: InboundMessage from a channel adapter
            adapter_id: Stable adapter identity (discord/telegram/whatsapp/etc.)

        Returns:
            Response text from VERA
        """
        from sessions.keys import derive_link_session_key, derive_session_key
        from sessions.types import SessionScope
        from channels.types import ChatType

        channel_scope_id = self._resolve_inbound_channel_scope(message, adapter_id=adapter_id)
        group_id = self._derive_inbound_group_id(message, ChatType)
        channel_session_key = derive_session_key(
            channel_id=channel_scope_id,
            sender_id=message.sender_id,
            scope=SessionScope.PER_SENDER,
            group_id=group_id,
        )
        session_link_id = self._extract_inbound_session_link_id(
            message,
            channel_scope_id=channel_scope_id,
        )
        linked_session_key = derive_link_session_key(session_link_id)
        session_key = linked_session_key or channel_session_key

        # Get or create session
        session = None
        if self.session_store:
            if linked_session_key and linked_session_key != channel_session_key:
                try:
                    self.session_store.link_session_keys(
                        linked_session_key,
                        channel_session_key,
                    )
                except Exception:
                    logger.debug("Suppressed Exception in vera")
                    pass
            session = self.session_store.get_or_create(
                session_key=session_key,
                channel_id=channel_scope_id,
                sender_id=message.sender_id,
            )
            session_key = self.session_store.resolve_session_key(session_key)
            if session:
                session.metadata["channel_session_key"] = channel_session_key
                if session_link_id:
                    session.metadata["session_link_id"] = session_link_id
            # Update delivery context
            self.session_store.update_delivery_context(
                session_key=session_key,
                channel_id=channel_scope_id,
                target_id=message.channel_id,
                thread_id=message.thread_id,
            )

        # Fire before_message hook
        if self.hook_registry:
            from core.hooks.types import HookEvent, HookEventType, HookResult
            event = HookEvent(
                event_type=HookEventType.BEFORE_MESSAGE,
                session_key=session_key,
                context={
                    "text": message.text,
                    "sender_id": message.sender_id,
                    "channel_id": message.channel_id,
                    "adapter_id": channel_scope_id,
                    "chat_type": message.chat_type.value,
                },
            )
            result = await self.hook_registry.trigger(event)
            if result == HookResult.BLOCK:
                return ""
            # Allow hooks to modify the message text
            if result == HookResult.MODIFY and "text" in event.context:
                message.text = event.context["text"]

        # Record inbound message to transcript
        if self.session_store and session:
            await self.session_store.record_message(
                session_key=session_key,
                role="user",
                content=message.text,
            )

        # Load conversation history for context
        history = []
        if self.session_store:
            history = self.session_store.get_history(session_key)

        # Build messages list for LLM
        if history:
            # Use transcript history as context
            messages = history
            # Ensure the last message is the current user message
            if not messages or messages[-1].get("content") != message.text:
                messages.append({"role": "user", "content": message.text})
        else:
            messages = [{"role": "user", "content": message.text}]

        # Get model override from session
        model_override = session.model_override if session else None
        tool_choice_override = self._extract_inbound_tool_choice(message)

        # Process through VERA
        try:
            response_text = await self.process_messages(
                messages=messages,
                model=model_override,
                conversation_id=session_key,
                tool_choice=tool_choice_override,
                postprocess=False,
            )
        except Exception as e:
            logger.error(f"process_messages failed for {session_key}: {e}")
            response_text = f"I encountered an error: {type(e).__name__}"

        # Fire after_message hook
        if self.hook_registry:
            from core.hooks.types import HookEvent, HookEventType, HookResult
            event = HookEvent(
                event_type=HookEventType.AFTER_MESSAGE,
                session_key=session_key,
                context={
                    "response": response_text,
                    "sender_id": message.sender_id,
                    "channel_id": message.channel_id,
                },
            )
            result = await self.hook_registry.trigger(event)
            if result == HookResult.MODIFY and "response" in event.context:
                response_text = event.context["response"]

        response_text = self._postprocess_response(
            response_text,
            context={
                "user_query": message.text,
                "conversation_id": session_key,
                "channel_id": channel_scope_id,
            },
        )

        # Record response to transcript
        if self.session_store and session:
            await self.session_store.record_message(
                session_key=session_key,
                role="assistant",
                content=response_text,
            )

        self._publish_message_event(
            response_text=response_text,
            conversation_id=session_key,
            channel_id=channel_scope_id,
            source="channel_message",
        )

        return response_text

    @staticmethod
    def _session_link_map_path() -> Path:
        raw_path = os.getenv("VERA_SESSION_LINK_MAP_PATH", "").strip()
        if raw_path:
            return Path(raw_path).expanduser()
        return Path("vera_memory") / "session_link_map.json"

    @staticmethod
    def _normalize_session_link_rule(raw_rule: Any) -> str:
        if isinstance(raw_rule, str):
            rule = raw_rule.strip()
            return rule if rule and "=" in rule and ":" in rule else ""
        if isinstance(raw_rule, dict):
            channel = str(raw_rule.get("channel") or raw_rule.get("channel_id") or "").strip()
            sender = str(raw_rule.get("sender") or raw_rule.get("sender_id") or "").strip()
            link_id = str(raw_rule.get("link_id") or raw_rule.get("session_link_id") or "").strip()
            if not channel or not sender or not link_id:
                return ""
            return f"{channel}:{sender}={link_id}"
        return ""

    @classmethod
    def _load_session_link_map_rules_from_file(cls) -> List[str]:
        path = cls._session_link_map_path()
        payload = safe_json_read(path, default={}) or {}
        rules: List[str] = []

        def _add_rule(raw_rule: Any) -> None:
            normalized = cls._normalize_session_link_rule(raw_rule)
            if normalized:
                rules.append(normalized)

        if isinstance(payload, dict):
            raw_rules = payload.get("rules")
            if isinstance(raw_rules, list):
                for raw_rule in raw_rules:
                    _add_rule(raw_rule)
            raw_map = payload.get("map")
            if isinstance(raw_map, dict):
                for identity, link_id in raw_map.items():
                    candidate = f"{str(identity).strip()}={str(link_id).strip()}"
                    _add_rule(candidate)
        elif isinstance(payload, list):
            for raw_rule in payload:
                _add_rule(raw_rule)

        return rules

    @classmethod
    def _combined_session_link_map_rules(cls) -> List[str]:
        combined: List[str] = []
        seen = set()

        rules_raw = os.getenv("VERA_SESSION_LINK_MAP", "").strip()
        if rules_raw:
            for raw_rule in rules_raw.split(","):
                normalized = cls._normalize_session_link_rule(raw_rule)
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    combined.append(normalized)

        for raw_rule in cls._load_session_link_map_rules_from_file():
            normalized = cls._normalize_session_link_rule(raw_rule)
            if normalized and normalized not in seen:
                seen.add(normalized)
                combined.append(normalized)

        return combined

    @staticmethod
    def _extract_session_link_candidate(payload: Dict[str, Any]) -> str:
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

    def _extract_inbound_session_link_id(
        self,
        message,
        channel_scope_id: Optional[str] = None,
    ) -> str:
        raw = getattr(message, "raw", {})
        raw_map = raw if isinstance(raw, dict) else {}

        direct = self._extract_session_link_candidate(raw_map)
        if direct:
            return direct

        for nested_key in ("metadata", "context", "session"):
            nested = raw_map.get(nested_key)
            nested_value = self._extract_session_link_candidate(nested if isinstance(nested, dict) else {})
            if nested_value:
                return nested_value

        mapped_link = self._resolve_mapped_session_link_id(
            channel_scope_id=channel_scope_id or self._resolve_inbound_channel_scope(message),
            sender_id=str(getattr(message, "sender_id", "") or ""),
            sender_name=str(getattr(message, "sender_name", "") or ""),
        )
        if mapped_link:
            return mapped_link

        default_link = os.getenv("VERA_DEFAULT_SESSION_LINK_ID", "").strip()
        if default_link:
            return default_link
        return ""

    @staticmethod
    def _extract_inbound_tool_choice(message) -> Any:
        raw = getattr(message, "raw", {})
        raw_map = raw if isinstance(raw, dict) else {}

        direct = raw_map.get("tool_choice")
        if isinstance(direct, (str, dict)):
            return direct

        for nested_key in ("metadata", "context", "session"):
            nested = raw_map.get(nested_key)
            if not isinstance(nested, dict):
                continue
            nested_choice = nested.get("tool_choice")
            if isinstance(nested_choice, (str, dict)):
                return nested_choice

        return None

    @classmethod
    def _resolve_mapped_session_link_id(
        cls,
        channel_scope_id: str,
        sender_id: str,
        sender_name: str,
    ) -> str:
        rules = cls._combined_session_link_map_rules()
        if not rules:
            return ""

        channel_value = str(channel_scope_id or "").strip().lower()
        sender_value = str(sender_id or "").strip().lower()
        sender_name_value = str(sender_name or "").strip().lower()
        for raw_rule in rules:
            rule = raw_rule.strip()
            if not rule or "=" not in rule:
                continue
            identity_part, link_id = rule.split("=", 1)
            link_value = link_id.strip()
            if not link_value or ":" not in identity_part:
                continue
            channel_rule, sender_rule = identity_part.split(":", 1)
            channel_rule = channel_rule.strip().lower()
            sender_rule = sender_rule.strip().lower()
            if channel_rule not in {"*", channel_value}:
                continue
            if sender_rule not in {"*", sender_value, sender_name_value}:
                continue
            return link_value
        return ""

    @staticmethod
    def _resolve_inbound_channel_scope(message, adapter_id: Optional[str] = None) -> str:
        if adapter_id and str(adapter_id).strip():
            return str(adapter_id).strip()

        raw = getattr(message, "raw", {})
        raw_map = raw if isinstance(raw, dict) else {}
        for key in ("adapter_id", "channel_adapter", "channel_type"):
            value = raw_map.get(key)
            if value and str(value).strip():
                return str(value).strip()

        if "discord_message" in raw_map:
            return "discord"
        if "telegram_message" in raw_map:
            return "telegram"
        if "whatsapp_message" in raw_map:
            return "whatsapp"
        if "messages" in raw_map and raw_map.get("conversation_id") is not None:
            return "api"

        channel_id = getattr(message, "channel_id", "")
        cleaned_channel = str(channel_id or "").strip()
        return cleaned_channel or "channel"

    @staticmethod
    def _derive_inbound_group_id(message, chat_type_enum) -> Optional[str]:
        chat_type = getattr(message, "chat_type", None)
        if chat_type not in (
            chat_type_enum.GROUP,
            chat_type_enum.CHANNEL,
            chat_type_enum.THREAD,
        ):
            return None
        for candidate in (
            getattr(message, "guild_id", None),
            getattr(message, "thread_id", None),
            getattr(message, "channel_id", None),
        ):
            cleaned = str(candidate or "").strip()
            if cleaned:
                return cleaned
        return None

    def _setup_sentinel_triggers(self):
        """Configure proactive triggers for Sentinel Engine (Improvement #11)."""
        return self.proactive_manager.setup_sentinel_triggers()

    def _apply_startup_dnd(self) -> None:
        return self.proactive_manager.apply_startup_dnd()

    def _resolve_workspace_user_email(self) -> str:
        candidates = [
            os.getenv("GOOGLE_WORKSPACE_USER_EMAIL", ""),
            os.getenv("USER_GOOGLE_EMAIL", ""),
            os.getenv("GOOGLE_USER_EMAIL", ""),
        ]

        def _clean_value(value: str) -> str:
            cleaned = value.strip()
            for prefix in (
                "export ",
                "GOOGLE_WORKSPACE_USER_EMAIL=",
                "USER_GOOGLE_EMAIL=",
                "GOOGLE_USER_EMAIL=",
            ):
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):].strip()
            if (cleaned.startswith('"') and cleaned.endswith('"')) or (
                cleaned.startswith("'") and cleaned.endswith("'")
            ):
                cleaned = cleaned[1:-1].strip()
            return cleaned.lower()

        user_email = ""
        for value in candidates:
            user_email = _clean_value(value)
            if user_email:
                break

        if not user_email:
            creds_root = os.getenv("CREDS_DIR")
            if creds_root:
                creds_dir = Path(creds_root).expanduser()
            else:
                creds_dir = Path.home() / "Documents" / "creds"
            user_email_path = creds_dir / "google" / "user_email"
            if user_email_path.is_file():
                try:
                    user_email = _clean_value(user_email_path.read_text())
                except Exception:
                    user_email = ""

        if user_email:
            os.environ["GOOGLE_WORKSPACE_USER_EMAIL"] = user_email
            os.environ["USER_GOOGLE_EMAIL"] = user_email
            os.environ["GOOGLE_USER_EMAIL"] = user_email

        return user_email

    def _resolve_workspace_timezone(self) -> str:
        candidates = [
            os.getenv("GOOGLE_WORKSPACE_TIMEZONE", ""),
            os.getenv("VERA_DEFAULT_TIMEZONE", ""),
            os.getenv("TZ", ""),
        ]

        def _clean_tz(value: str) -> str:
            cleaned = value.strip()
            if cleaned.startswith("TZ="):
                cleaned = cleaned[3:].strip()
            if cleaned.startswith(":"):
                cleaned = cleaned[1:].strip()
            if (cleaned.startswith('"') and cleaned.endswith('"')) or (
                cleaned.startswith("'") and cleaned.endswith("'")
            ):
                cleaned = cleaned[1:-1].strip()
            return cleaned

        for value in candidates:
            tz_name = _clean_tz(value)
            if tz_name:
                return tz_name

        creds_root = os.getenv("CREDS_DIR")
        if creds_root:
            creds_dir = Path(creds_root).expanduser()
        else:
            creds_dir = Path.home() / "Documents" / "creds"

        tz_file = creds_dir / "google" / "timezone"
        if tz_file.is_file():
            try:
                tz_name = _clean_tz(tz_file.read_text())
                if tz_name:
                    return tz_name
            except Exception:
                pass

        etc_timezone = Path("/etc/timezone")
        if etc_timezone.is_file():
            try:
                tz_name = _clean_tz(etc_timezone.read_text())
                if tz_name:
                    return tz_name
            except Exception:
                pass

        return "America/Chicago"

    def _get_creds_dir(self) -> Path:
        creds_root = os.getenv("CREDS_DIR")
        if creds_root:
            return Path(creds_root).expanduser()
        return Path.home() / "Documents" / "creds"

    def _get_google_workspace_credentials_dir(self) -> Path:
        env_dir = os.getenv("GOOGLE_MCP_CREDENTIALS_DIR") or os.getenv("CREDENTIALS_DIR")
        if env_dir:
            return Path(env_dir).expanduser()
        creds_dir = self._get_creds_dir() / "google" / "credentials"
        if creds_dir.exists():
            return creds_dir
        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / "vera_memory" / "google_workspace" / "credentials"

    def _resolve_workspace_google_auth_context(self) -> Tuple[str, bool]:
        user_email = self._resolve_workspace_user_email()
        if not user_email:
            return "", False
        credentials_dir = self._get_google_workspace_credentials_dir()
        credentials_file = credentials_dir / f"{user_email}.json"
        return user_email, credentials_file.exists()

    def _quorum_settings_path(self) -> Path:
        return self._get_creds_dir() / "vera_quorum_settings.json"

    def _load_quorum_settings(self) -> None:
        settings_path = self._quorum_settings_path()
        data: Dict[str, Any] = {}
        if settings_path.is_file():
            try:
                data = json.loads(settings_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        if not data:
            data = {
                "quorum_auto_enabled": os.getenv("VERA_QUORUM_ENABLED", "0") == "1",
                "swarm_auto_enabled": os.getenv("VERA_SWARM_ENABLED", "0") == "1",
            }
        self.quorum_auto_enabled = bool(data.get("quorum_auto_enabled", False))
        self.swarm_auto_enabled = bool(data.get("swarm_auto_enabled", False))

    def _persist_quorum_settings(self) -> None:
        settings_path = self._quorum_settings_path()
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "quorum_auto_enabled": self.quorum_auto_enabled,
            "swarm_auto_enabled": self.swarm_auto_enabled,
        }
        settings_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    def update_quorum_settings(
        self,
        quorum_auto_enabled: Optional[bool] = None,
        swarm_auto_enabled: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if quorum_auto_enabled is not None:
            self.quorum_auto_enabled = bool(quorum_auto_enabled)
        if swarm_auto_enabled is not None:
            self.swarm_auto_enabled = bool(swarm_auto_enabled)
        self._persist_quorum_settings()
        return {
            "quorum_auto_enabled": self.quorum_auto_enabled,
            "swarm_auto_enabled": self.swarm_auto_enabled,
        }

    def get_quorum_status(self) -> Dict[str, Any]:
        return {
            "settings": {
                "quorum_auto_enabled": self.quorum_auto_enabled,
                "swarm_auto_enabled": self.swarm_auto_enabled,
                "quorum_max_calls": self.quorum_max_calls,
                "swarm_max_calls": self.swarm_max_calls,
                "quorum_calls": self._quorum_calls,
                "swarm_calls": self._swarm_calls,
            },
            "state": dict(self._quorum_status),
        }

    def _swarm_block_reason(self, text: str) -> Optional[str]:
        if not text:
            return None
        for label, pattern in SWARM_BLOCKLIST_PATTERNS:
            if pattern.search(text):
                return label
        return None

    def _format_quorum_summary(self, result: Dict[str, Any]) -> str:
        quorum_name = result.get("quorum", "Quorum")
        decision = result.get("decision", "")
        consensus = result.get("consensus", "")
        explanation = (
            result.get("aggregated_response")
            or result.get("explanation")
            or result.get("summary")
            or ""
        )
        agents = ", ".join(self._format_agent_label(name) for name in (result.get("agents") or []))
        lines = [f"[{quorum_name} Summary]"]
        if decision:
            lines.append(f"Decision: {decision}")
        if consensus:
            lines.append(f"Consensus: {consensus}")
        if agents:
            lines.append(f"Agents: {agents}")
        if explanation:
            lines.append(explanation)
        return "\n".join(lines)

    @staticmethod
    def _format_agent_label(name: str) -> str:
        if not name:
            return ""
        return re.sub(r"(?<!^)(?=[A-Z])", " ", name).strip()

    async def _run_quorum_tool(
        self,
        mode: str,
        params: Dict[str, Any],
        *,
        manual: bool = False,
        trigger: str = "auto"
    ) -> str:
        text = (
            params.get("question")
            or params.get("task")
            or params.get("action")
            or params.get("objective")
            or ""
        ).strip()
        context = (params.get("context") or "").strip()
        quorum_name = (params.get("quorum") or params.get("quorum_name") or "").strip()
        custom_swarm = None

        if not text:
            return "Quorum/Swarm requires a question or task."

        if self._quorum_active or self._swarm_active:
            return "Quorum/Swarm already active; nested calls are disabled."

        if mode == "quorum":
            if not manual and not self.quorum_auto_enabled:
                return "Quorum tool is disabled. Enable it in Settings or trigger manually."
            if self._quorum_calls >= self.quorum_max_calls:
                return "Quorum call limit reached for this session."
        else:
            if not manual and not self.swarm_auto_enabled:
                return "Swarm tool is disabled. Enable it in Settings or trigger manually."
            if self._swarm_calls >= self.swarm_max_calls:
                return "Swarm call limit reached for this session."
            if quorum_name:
                custom_spec = get_custom_quorum_spec(quorum_name)
                if not custom_spec:
                    return f"Custom swarm '{quorum_name}' not found."
                if not custom_spec.get("is_swarm", False):
                    return f"Custom quorum '{quorum_name}' is not marked as a swarm."
                custom_swarm = build_quorum_from_spec(custom_spec)
            block_reason = self._swarm_block_reason(text)
            if block_reason:
                self._quorum_status.update({
                    "status": "blocked",
                    "mode": "swarm",
                    "trigger": trigger,
                    "quorum": custom_swarm.name if custom_swarm else "Swarm",
                    "agents": custom_swarm.get_agent_names() if custom_swarm else SWARM_QUORUM.get_agent_names(),
                    "decision": "blocked",
                    "consensus": "",
                    "reason": f"Blocked by swarm policy ({block_reason})",
                    "summary": "",
                    "started_at": datetime.now().isoformat(),
                    "finished_at": datetime.now().isoformat(),
                    "latency_ms": 0,
                })
                return (
                    "Swarm blocked: action requires human oversight. "
                    f"Reason: {block_reason}."
                )

        start_time = time.time()
        self._quorum_status.update({
            "status": "running",
            "mode": mode,
            "trigger": trigger,
            "quorum": quorum_name or ("Swarm" if mode == "swarm" else ""),
            "agents": custom_swarm.get_agent_names() if custom_swarm else (SWARM_QUORUM.get_agent_names() if mode == "swarm" else []),
            "decision": "",
            "consensus": "",
            "reason": "",
            "summary": "",
            "started_at": datetime.now().isoformat(),
            "finished_at": "",
            "latency_ms": 0,
        })

        if mode == "quorum":
            lock = self._quorum_lock
        else:
            lock = self._swarm_lock

        async with lock:
            if mode == "quorum":
                self._quorum_active = True
                self._quorum_calls += 1
            else:
                self._swarm_active = True
                self._swarm_calls += 1

            try:
                if mode == "quorum":
                    if quorum_name:
                        quorum = get_custom_quorum(quorum_name) or get_quorum(quorum_name)
                        result = await self.moa_executor.execute(quorum, text, context)
                        payload = {
                            "quorum": quorum.name,
                            "agents": quorum.get_agent_names(),
                            "decision": result.decision,
                            "consensus": result.consensus.algorithm if result.consensus else "",
                            "explanation": result.aggregated_response or result.consensus.explanation,
                            "aggregated_response": result.aggregated_response,
                        }
                    else:
                        payload = await self.consult_quorum(text, context)
                else:
                    swarm_quorum = custom_swarm or SWARM_QUORUM
                    result = await self.moa_executor.execute(swarm_quorum, text, context)
                    payload = {
                        "quorum": swarm_quorum.name,
                        "agents": swarm_quorum.get_agent_names(),
                        "decision": result.decision,
                        "consensus": result.consensus.algorithm if result.consensus else "",
                        "explanation": result.aggregated_response or result.consensus.explanation,
                        "aggregated_response": result.aggregated_response,
                    }

                summary = self._format_quorum_summary(payload)
                latency_ms = (time.time() - start_time) * 1000
                self._quorum_status.update({
                    "status": "completed",
                    "mode": mode,
                    "trigger": trigger,
                    "quorum": payload.get("quorum", ""),
                    "agents": payload.get("agents", []),
                    "decision": payload.get("decision", ""),
                    "consensus": payload.get("consensus", ""),
                    "summary": summary,
                    "finished_at": datetime.now().isoformat(),
                    "latency_ms": int(latency_ms),
                })
                logger.info(
                    "Quorum completed: mode=%s trigger=%s quorum=%s consensus=%s decision=%s",
                    mode,
                    trigger,
                    payload.get("quorum", ""),
                    payload.get("consensus", ""),
                    payload.get("decision", ""),
                )

                # Persist to decision ledger (covers all paths: named quorum,
                # default quorum, and swarm — consult_quorum() no longer writes
                # its own ledger entry to avoid duplication).
                try:
                    self.log_decision(
                        decision_type=DecisionType.QUORUM_CONSULTATION,
                        action=f"{mode.title()} '{payload.get('quorum', '')}' decided: {payload.get('decision', '')}",
                        reasoning=payload.get("explanation", "") or payload.get("aggregated_response", ""),
                        alternatives=[text],
                        confidence=0.8,
                        context={
                            "mode": mode,
                            "trigger": trigger,
                            "quorum": payload.get("quorum", ""),
                            "agents": payload.get("agents", []),
                            "decision": payload.get("decision", ""),
                            "consensus": payload.get("consensus", ""),
                            "latency_ms": int(latency_ms),
                        },
                    )
                except Exception:
                    logger.debug("Failed to write quorum decision to ledger", exc_info=True)

                # Rich flight recorder entry with quorum metadata.
                try:
                    self.flight_recorder.record_tool_call(
                        tool_name=f"consult_{mode}",
                        params={"question": text, "quorum": payload.get("quorum", "")},
                        result=payload,
                        success=True,
                        latency_ms=latency_ms,
                        conversation_id=context if isinstance(context, str) else "quorum",
                    )
                except Exception:
                    logger.debug("Failed to write quorum to flight recorder", exc_info=True)

                return summary
            except Exception as exc:
                latency_ms = (time.time() - start_time) * 1000
                self._quorum_status.update({
                    "status": "error",
                    "mode": mode,
                    "trigger": trigger,
                    "quorum": "Swarm" if mode == "swarm" else quorum_name,
                    "decision": "error",
                    "consensus": "",
                    "reason": str(exc),
                    "finished_at": datetime.now().isoformat(),
                    "latency_ms": int(latency_ms),
                })
                return f"{mode.title()} failed: {exc}"
            finally:
                if mode == "quorum":
                    self._quorum_active = False
                else:
                    self._swarm_active = False

    def _init_native_tools(self) -> None:
        """Register native tool bridges based on environment flags."""
        def _register_tools(tools: List[Dict[str, Any]], handler: Callable[[str, Dict[str, Any]], Any]) -> None:
            for tool in tools:
                func = tool.get("function", {})
                name = func.get("name")
                if not name or name in self._native_tool_handlers:
                    continue
                self._native_tool_defs.append(tool)
                self._native_tool_handlers[name] = handler

        def _env_enabled(name: str, default: str = "0") -> bool:
            return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}

        if os.getenv("VERA_BROWSER", "0") == "1":
            try:
                from browser_control.tools import BrowserToolBridge
                self._browser_bridge = BrowserToolBridge()

                async def _browser_handler(tool_name: str, params: Dict[str, Any]) -> Any:
                    if self._browser_bridge and not self._browser_bridge.is_launched and tool_name != "browser_status":
                        await self._browser_bridge.launch()
                    return await self._browser_bridge.execute_tool(tool_name, params)

                _register_tools(self._browser_bridge.tools, _browser_handler)
            except Exception as exc:
                self._native_tool_errors["browser"] = str(exc)

        if os.getenv("VERA_DESKTOP", "0") == "1":
            try:
                from desktop_control.tools import DesktopToolBridge
                self._desktop_bridge = DesktopToolBridge()

                async def _desktop_handler(tool_name: str, params: Dict[str, Any]) -> Any:
                    return await self._desktop_bridge.execute_tool(tool_name, params)

                _register_tools(self._desktop_bridge.tools, _desktop_handler)
            except Exception as exc:
                self._native_tool_errors["desktop"] = str(exc)

        if os.getenv("VERA_PDF", "0") == "1":
            try:
                from pdf_processing.tools import PDFToolBridge
                self._pdf_bridge = PDFToolBridge()

                async def _pdf_handler(tool_name: str, params: Dict[str, Any]) -> Any:
                    return await self._pdf_bridge.execute_tool(tool_name, params)

                _register_tools(self._pdf_bridge.tools, _pdf_handler)
            except Exception as exc:
                self._native_tool_errors["pdf"] = str(exc)

        if os.getenv("VERA_SANDBOX", "0") == "1":
            try:
                from core.services.sandbox_executor import SandboxToolBridge
                self._sandbox_bridge = SandboxToolBridge()

                async def _sandbox_handler(tool_name: str, params: Dict[str, Any]) -> Any:
                    return await self._sandbox_bridge.execute_tool(tool_name, params)

                _register_tools(self._sandbox_bridge.tools, _sandbox_handler)
            except Exception as exc:
                self._native_tool_errors["sandbox"] = str(exc)

        if os.getenv("VERA_RECURSIVE_SUMMARY", "1") == "1":
            try:
                from orchestration.recursive_summarizer import RecursiveSummarizer

                api_key = os.getenv("XAI_API_KEY") or os.getenv("API_KEY")
                if api_key:
                    self._recursive_summarizer = RecursiveSummarizer(
                        api_key=api_key,
                        base_url=os.getenv("XAI_API_BASE", "https://api.x.ai/v1"),
                    )

                    async def _recursive_summary_handler(tool_name: str, params: Dict[str, Any]) -> Any:
                        text = str(params.get("text", "")).strip()
                        goal = params.get("goal")
                        max_chunk_chars = int(params.get("max_chunk_chars", 4000))
                        overlap_chars = int(params.get("overlap_chars", 200))
                        target_chars = int(params.get("target_chars", 1800))
                        max_rounds = int(params.get("max_rounds", 4))
                        model = params.get("model")
                        return await self._recursive_summarizer.summarize(
                            text=text,
                            goal=goal,
                            max_chunk_chars=max_chunk_chars,
                            overlap_chars=overlap_chars,
                            target_chars=target_chars,
                            max_rounds=max_rounds,
                            model=model,
                        )

                    recursive_tool = [{
                        "type": "function",
                        "function": {
                            "name": "recursive_summarize",
                            "description": (
                                "Summarize very long text using map/reduce chunking. "
                                "Use for: long documents (>10k chars), research papers, multi-page notes, "
                                "log files, chat histories, meeting transcripts. "
                                "NOT for short inputs - use direct LLM response instead. "
                                "Returns: summary, rounds (recursion count), chunks (max chunk count), model used. "
                                "Tip: Set 'goal' to focus the summary (e.g., 'key decisions', 'action items', "
                                "'technical details', 'risks and concerns'). "
                                "Uses fast reasoning model by default for cost efficiency."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string", "description": "Long text to summarize (>10k chars recommended)."},
                                    "goal": {"type": "string", "description": "Focus area: 'decisions', 'action items', 'technical details', 'risks', etc."},
                                    "max_chunk_chars": {"type": "integer", "description": "Chunk size (default: 4000). Smaller = more detail preserved."},
                                    "overlap_chars": {"type": "integer", "description": "Overlap between chunks for context (default: 200)."},
                                    "target_chars": {"type": "integer", "description": "Target final summary length (default: 1800)."},
                                    "max_rounds": {"type": "integer", "description": "Max recursion depth (default: 4). Higher = more compression."},
                                    "model": {"type": "string", "description": "Override model (default: grok-4.20-experimental-beta-0304-reasoning)."},
                                },
                                "required": ["text"],
                            },
                        },
                    }]

                    _register_tools(recursive_tool, _recursive_summary_handler)
                else:
                    self._native_tool_errors["recursive_summarize"] = "XAI_API_KEY is required"
            except Exception as exc:
                self._native_tool_errors["recursive_summarize"] = str(exc)

        quarantine_tools = [
            {
                "type": "function",
                "function": {
                    "name": "list_quarantine",
                    "description": (
                        "List memory items in quarantine awaiting review. "
                        "Use for: reviewing flagged memories, checking pending approvals, memory hygiene. "
                        "Returns: list of quarantined items with ID, content preview, reason, timestamp. "
                        "Items enter quarantine when they contain sensitive info, are uncertain, or need human review. "
                        "Tip: Call this periodically to clear the review queue."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "max_results": {
                                "type": "integer",
                                "description": "Max items to return (default: 20)."
                            },
                            "preview_chars": {
                                "type": "integer",
                                "description": "Content preview length per item (default: 200)."
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "approve_quarantine",
                    "description": (
                        "Approve a quarantined memory item for promotion to active memory. "
                        "Use for: accepting reviewed memories, clearing the quarantine queue. "
                        "Requires either quarantine_id OR index from list_quarantine. "
                        "Returns: confirmation of promotion with item details. "
                        "Tip: Use 'working' for session-relevant info, 'long_term' for persistent facts."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "quarantine_id": {
                                "type": "string",
                                "description": "Quarantine item ID to approve (from list_quarantine)."
                            },
                            "index": {
                                "type": "integer",
                                "description": "Item index from list_quarantine output (0-based)."
                            },
                            "promote_to": {
                                "type": "string",
                                "enum": ["working", "long_term"],
                                "description": "'working': current session. 'long_term': persistent storage."
                            },
                        },
                    },
                },
            },
        ]

        async def _quarantine_handler(tool_name: str, params: Dict[str, Any]) -> Any:
            if not self.memory:
                return {"error": "Memory service unavailable"}
            if tool_name == "list_quarantine":
                max_results = params.get("max_results")
                preview_chars = params.get("preview_chars")
                try:
                    max_results = int(max_results) if max_results is not None else 20
                except (TypeError, ValueError):
                    max_results = 20
                try:
                    preview_chars = int(preview_chars) if preview_chars is not None else 200
                except (TypeError, ValueError):
                    preview_chars = 200
                return self.memory.list_quarantine(
                    max_results=max_results,
                    preview_chars=preview_chars
                )

            if tool_name == "approve_quarantine":
                quarantine_id = params.get("quarantine_id") or params.get("id")
                index = params.get("index")
                if index is not None:
                    try:
                        index = int(index)
                    except (TypeError, ValueError):
                        index = None
                promote_to = params.get("promote_to", "working")
                return self.memory.approve_quarantine(
                    quarantine_id=quarantine_id,
                    index=index,
                    promote_to=promote_to
                )

            return {"error": f"Unknown quarantine tool: {tool_name}"}

        _register_tools(quarantine_tools, _quarantine_handler)

        memory_tools = [
            {
                "type": "function",
                "function": {
                    "name": "retrieve_memory",
                    "description": (
                        "Retrieve relevant memory items from working, long-term, archive, and memvid recall. "
                        "Use for recalling prior user context, commitments, or earlier conversation facts."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Memory lookup query."
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Max items to return (default: 10, max: 50)."
                            },
                            "include_quarantine": {
                                "type": "boolean",
                                "description": "Include quarantined memories (default: false)."
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_archive",
                    "description": (
                        "Search archived memory tiers directly. "
                        "Use for deep historical lookup across Recent, Weekly, and Monthly memory stores."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Archive search query."
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Max items to return (default: 10, max: 50)."
                            },
                            "tiers": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["Recent", "Weekly", "Monthly"],
                                },
                                "description": "Optional tier filter. Defaults to all tiers."
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "encode_event",
                    "description": (
                        "Encode a durable memory event into Vera's memory pipeline. "
                        "Use for persistent preferences, commitments, and critical facts the user asks to remember."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "description": "Event content to encode."
                            },
                            "type": {
                                "type": "string",
                                "description": "Event type (default: system_event)."
                            },
                            "timestamp": {
                                "type": "string",
                                "description": "ISO-8601 timestamp override (optional)."
                            },
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional tags for retrieval and grouping."
                            },
                            "provenance": {
                                "type": "object",
                                "description": "Optional provenance metadata (source_type, source_id, trust_score, etc.)."
                            },
                            "created_by": {
                                "type": "string",
                                "description": "Optional creator/source marker."
                            },
                            "importance": {
                                "type": "number",
                                "description": "Optional importance hint (0.0 - 1.0)."
                            },
                        },
                        "required": ["content"],
                    },
                },
            },
        ]

        def _safe_json(value: Any) -> Any:
            try:
                return json.loads(json.dumps(value, default=str))
            except Exception:
                return str(value)

        def _parse_int(value: Any, default: int, minimum: int = 1, maximum: int = 50) -> int:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                parsed = default
            return max(minimum, min(maximum, parsed))

        def _parse_bool(value: Any, default: bool = False) -> bool:
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return default

        def _normalize_archive_tiers(raw_tiers: Any) -> Optional[List[str]]:
            if raw_tiers is None:
                return None
            if isinstance(raw_tiers, str):
                candidates = [part.strip() for part in raw_tiers.split(",") if part.strip()]
            elif isinstance(raw_tiers, list):
                candidates = [str(part).strip() for part in raw_tiers if str(part).strip()]
            else:
                return None
            allowed = {"recent": "Recent", "weekly": "Weekly", "monthly": "Monthly"}
            tiers: List[str] = []
            for candidate in candidates:
                canonical = allowed.get(candidate.lower())
                if canonical and canonical not in tiers:
                    tiers.append(canonical)
            return tiers or None

        def _serialize_memory_item(item: Any) -> Dict[str, Any]:
            item_type = type(item).__name__
            item_id = getattr(item, "cube_id", None) or getattr(item, "item_id", None)
            raw_content: Any = None
            metadata: Dict[str, Any] = {}
            source: Optional[str] = None

            if isinstance(item, dict):
                item_id = item_id or item.get("cube_id") or item.get("item_id") or item.get("id")
                raw_content = item.get("content")
                source = item.get("source")
                raw_metadata = item.get("metadata")
                if isinstance(raw_metadata, dict):
                    metadata = dict(raw_metadata)
            else:
                if hasattr(item, "get_content"):
                    try:
                        raw_content = item.get_content()
                    except Exception:
                        raw_content = None
                if raw_content is None and hasattr(item, "content"):
                    raw_content = getattr(item, "content", None)

                raw_metadata = getattr(item, "metadata", None)
                if isinstance(raw_metadata, dict):
                    metadata = dict(raw_metadata)
                elif hasattr(raw_metadata, "to_dict"):
                    try:
                        metadata = raw_metadata.to_dict()
                    except Exception:
                        metadata = {}

            if raw_content is None and self.memory:
                try:
                    raw_content = self.memory._extract_item_text(item)
                except Exception:
                    raw_content = str(item)
            content = str(raw_content) if raw_content is not None else ""

            if isinstance(metadata, dict):
                provenance = metadata.get("provenance")
                if isinstance(provenance, dict):
                    source = source or provenance.get("source_type") or provenance.get("source")

            return {
                "id": item_id,
                "content": content,
                "metadata": _safe_json(metadata),
                "source": source,
                "item_type": item_type,
            }

        async def _memory_handler(tool_name: str, params: Dict[str, Any]) -> Any:
            if not self.memory:
                return {"error": "Memory service unavailable"}

            if tool_name == "retrieve_memory":
                query = str(
                    params.get("query")
                    or params.get("text")
                    or params.get("content")
                    or ""
                ).strip()
                if not query:
                    return {"error": "query is required"}
                max_results = _parse_int(params.get("max_results"), default=10)
                include_quarantine = _parse_bool(params.get("include_quarantine"), default=False)
                items = await self.memory.retrieve(
                    query=query,
                    max_results=max_results,
                    include_quarantine=include_quarantine,
                )
                combined_items: List[Any] = list(items)
                try:
                    buffer_hits = self.memory.fast_network.search_buffer(query, max_results=max_results)
                    combined_items = list(buffer_hits) + combined_items
                except Exception:
                    logger.debug("Suppressed Exception in vera")
                    pass

                deduped_items: List[Any] = []
                seen_content = set()
                for item in combined_items:
                    key = ""
                    try:
                        key = self.memory._extract_item_text(item)
                    except Exception:
                        key = str(item)
                    if key in seen_content:
                        continue
                    seen_content.add(key)
                    deduped_items.append(item)
                    if len(deduped_items) >= max_results:
                        break

                results = [_serialize_memory_item(item) for item in deduped_items]
                return {
                    "query": query,
                    "count": len(results),
                    "results": results,
                }

            if tool_name == "search_archive":
                query = str(
                    params.get("query")
                    or params.get("text")
                    or params.get("content")
                    or ""
                ).strip()
                if not query:
                    return {"error": "query is required"}
                max_results = _parse_int(params.get("max_results"), default=10)
                tiers = _normalize_archive_tiers(params.get("tiers"))
                archive_hits = self.memory.archive.search(
                    query=query,
                    max_results=max_results,
                    tiers=tiers,
                )
                results: List[Dict[str, Any]] = []
                for cube, score, tier in archive_hits:
                    item_payload = _serialize_memory_item(cube)
                    item_payload["score"] = float(score)
                    item_payload["tier"] = tier
                    results.append(item_payload)
                return {
                    "query": query,
                    "tiers": tiers or ["Recent", "Weekly", "Monthly"],
                    "count": len(results),
                    "results": results,
                }

            if tool_name == "encode_event":
                content = params.get("content")
                if content is None and params.get("text") is not None:
                    content = params.get("text")
                if content is None:
                    return {"error": "content is required"}

                event_type = str(params.get("type") or params.get("event_type") or "system_event").strip() or "system_event"
                timestamp = str(params.get("timestamp") or datetime.now().isoformat())
                tags = params.get("tags")
                if not isinstance(tags, list):
                    tags = []
                tags = [str(tag) for tag in tags if str(tag).strip()]

                provenance = params.get("provenance")
                if not isinstance(provenance, dict):
                    provenance = {}

                for key in ("source_type", "source_id", "trust_score", "quarantine"):
                    if key in params and key not in provenance:
                        provenance[key] = params.get(key)

                event: Dict[str, Any] = {
                    "type": event_type,
                    "content": content,
                    "timestamp": timestamp,
                    "tags": tags,
                    "provenance": provenance,
                }

                created_by = params.get("created_by")
                if created_by is not None:
                    event["created_by"] = str(created_by)

                if "importance" in params:
                    try:
                        event["importance"] = float(params.get("importance"))
                    except (TypeError, ValueError):
                        pass

                cube = await self.memory.process_event(event)
                if cube is None:
                    return {
                        "status": "discarded",
                        "event_type": event_type,
                        "reason": "below_retention_threshold",
                    }

                hsa_id = None
                try:
                    hsa_id = self.memory.add_memory(
                        content=self.memory._serialize_content(cube.get_content()),
                        importance=cube.metadata.importance,
                        metadata={
                            "provenance": dict(cube.metadata.provenance or {}),
                            "tags": list(cube.metadata.tags or []),
                            "event_type": cube.metadata.event_type.value,
                        },
                    )
                except Exception:
                    logger.debug("Suppressed Exception in vera")
                    pass

                return {
                    "status": "encoded",
                    "cube_id": cube.cube_id,
                    "hsa_id": hsa_id,
                    "event_type": cube.metadata.event_type.value,
                    "importance": cube.metadata.importance,
                    "timestamp": cube.metadata.timestamp.isoformat(),
                    "provenance": _safe_json(cube.metadata.provenance or {}),
                }

            return {"error": f"Unknown memory tool: {tool_name}"}

        _register_tools(memory_tools, _memory_handler)

        try:
            async def _quorum_handler(tool_name: str, params: Dict[str, Any]) -> Any:
                return await self._run_quorum_tool("quorum", params, manual=False, trigger="auto")

            async def _swarm_handler(tool_name: str, params: Dict[str, Any]) -> Any:
                return await self._run_quorum_tool("swarm", params, manual=False, trigger="auto")

            quorum_tool = [{
                "type": "function",
                "function": {
                    "name": "consult_quorum",
                    "description": (
                        "Run a multi-agent quorum for complex discussion, planning, or research. "
                        "Use for: difficult decisions, ambiguous tasks, high-stakes choices, research synthesis. "
                        "Multiple AI agents debate the question and synthesize a consensus. "
                        "Returns: summary, decision rationale, dissenting views, confidence score. "
                        "Tip: More expensive than single-agent but better for nuanced decisions. "
                        "Quorum agents include: Analyst, Critic, Strategist, Ethicist, Synthesizer."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "Question, dilemma, or task for the quorum to deliberate."},
                            "context": {"type": "string", "description": "Background info, constraints, or relevant details."},
                            "quorum_name": {"type": "string", "description": "Specific quorum preset (default: general)."}
                        },
                        "required": ["question"]
                    }
                }
            }]

            swarm_tool = [{
                "type": "function",
                "function": {
                    "name": "consult_swarm",
                    "description": (
                        "Run the full 7-agent swarm for comprehensive action planning. "
                        "Use for: complex multi-step projects, novel challenges, safety-critical planning. "
                        "The swarm PLANS but does NOT execute - returns a detailed plan with safety analysis. "
                        "Returns: action plan, safety notes, risk assessment, recommended execution order. "
                        "Swarm agents: Leader, Researcher, Planner, Safety Officer, Critic, Executor (dry-run), Synthesizer. "
                        "Tip: Most thorough planning mode. Use for irreversible or high-impact actions."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "description": "Action objective or project goal to plan."},
                            "context": {"type": "string", "description": "Background, constraints, resources, timeline."}
                        },
                        "required": ["action"]
                    }
                }
            }]

            _register_tools(quorum_tool, _quorum_handler)
            _register_tools(swarm_tool, _swarm_handler)
        except Exception as exc:
            self._native_tool_errors["quorum"] = str(exc)

        if _env_enabled("VERA_IMAGE", "1"):
            async def _optimize_image_prompt(original_prompt: str, api_key: str, base_url: str) -> str:
                """
                Meta-prompting: Use a text model to craft an optimized image generation prompt.
                This follows the xAI cookbook best practice for better image quality.
                xAI has a 1024 character limit on image prompts.
                """
                meta_prompt = f"""You are an expert at crafting prompts for image generation models.

Given the user's request below, create a concise, visually descriptive prompt optimized for image generation.

CRITICAL: The prompt MUST be under 900 characters (hard limit is 1024). Be concise but descriptive.

The generated prompt should:
- Be under 900 characters total
- Be specific about visual elements, colors, composition, and style
- Focus on what should be IN the image, not abstract concepts
- Use vivid, concrete language
- Be a single flowing sentence or short paragraph
- If about UI/design, describe a visual mockup screenshot

User's request: {original_prompt}

Respond with ONLY the optimized image prompt (under 900 chars), nothing else."""

                text_model = os.getenv("VERA_MODEL", "grok-4.20-experimental-beta-0304-reasoning")
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(
                            f"{base_url}/chat/completions",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": text_model,
                                "messages": [{"role": "user", "content": meta_prompt}],
                                "max_tokens": 200,
                                "temperature": 0.7,
                            },
                        )
                        response.raise_for_status()
                        data = response.json()
                        optimized = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if optimized and len(optimized) > 10:
                            optimized = optimized.strip()
                            # Hard truncate if still over limit
                            if len(optimized) > 1000:
                                optimized = optimized[:997] + "..."
                            return optimized
                except Exception as exc:
                    logger.warning("Meta-prompting failed, using original: %s", exc)
                # Truncate original if needed
                if len(original_prompt) > 1000:
                    return original_prompt[:997] + "..."
                return original_prompt

            async def _image_handler(tool_name: str, params: Dict[str, Any]) -> Any:
                prompt = str(params.get("prompt", "")).strip()
                if not prompt:
                    return {"error": "prompt is required"}

                api_key = os.getenv("XAI_IMAGE_API_KEY") or os.getenv("XAI_API_KEY") or os.getenv("API_KEY")
                if not api_key:
                    return {"error": "XAI_IMAGE_API_KEY or XAI_API_KEY is required"}

                # Meta-prompting: optimize the prompt using a text model first
                base_url = os.getenv("XAI_IMAGE_BASE_URL", "https://api.x.ai/v1").rstrip("/")
                if _env_enabled("VERA_IMAGE_META_PROMPT", "1"):
                    prompt = await _optimize_image_prompt(prompt, api_key, base_url)
                    logger.debug("Optimized image prompt: %s", prompt[:200])

                model = params.get("model") or os.getenv("XAI_IMAGE_MODEL", "grok-imagine-image")
                size = params.get("size") or os.getenv("XAI_IMAGE_SIZE", "1024x1024")
                n = params.get("n") or 1
                try:
                    n = int(n)
                except (TypeError, ValueError):
                    n = 1
                n = max(1, min(n, 4))

                is_xai = "api.x.ai" in base_url
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "n": n,
                }
                if size and not is_xai:
                    payload["size"] = size

                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        response = await client.post(
                            f"{base_url}/images/generations",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            json=payload,
                        )
                        if response.status_code != 200:
                            error_body = response.text
                            logger.error("Image generation failed: status=%s body=%s", response.status_code, error_body[:500])
                            return {"error": f"image generation failed: HTTP {response.status_code} - {error_body[:200]}"}
                        data = response.json()
                except Exception as exc:
                    logger.error("Image generation exception: %s", exc)
                    return {"error": f"image generation failed: {exc}"}

                urls = [item.get("url") for item in data.get("data", []) if item.get("url")]
                markdown = "\n".join(f"![image]({url})" for url in urls) if urls else ""
                cache_result = await _cache_generated_media_urls("image", prompt, model, urls)
                local_paths = list(cache_result.get("local_paths") or [])
                logger.info("Image generation complete: urls=%s local_paths=%s", urls, local_paths)
                return {
                    "model": model,
                    "urls": urls,
                    "markdown": markdown,
                    "local_paths": local_paths,
                    "cache_manifest_path": cache_result.get("manifest_path") or "",
                    "cache_items": cache_result.get("items") or [],
                }

            image_tool = [{
                "type": "function",
                "function": {
                    "name": "generate_image",
                    "description": (
                        "Generate an image from a text prompt using Grok image models. "
                        "Use only when the user asks for images or visual mockups. "
                        "Returns image URLs and a markdown snippet."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "prompt": {"type": "string", "description": "Image prompt with subject, style, and composition."},
                            "n": {"type": "integer", "description": "Number of images (1-4).", "minimum": 1, "maximum": 4},
                            "size": {
                                "type": "string",
                                "description": "Image size (ignored by xAI endpoints).",
                                "enum": ["256x256", "512x512", "1024x1024"],
                            },
                            "model": {"type": "string", "description": "Override the image model ID (optional)."},
                        },
                        "required": ["prompt"],
                    },
                },
            }]

            _register_tools(image_tool, _image_handler)

            async def _video_handler(tool_name: str, params: Dict[str, Any]) -> Any:
                prompt = str(params.get("prompt", "")).strip()
                if not prompt:
                    return {"error": "prompt is required"}

                api_key = (
                    os.getenv("XAI_VIDEO_API_KEY")
                    or os.getenv("XAI_IMAGE_API_KEY")
                    or os.getenv("XAI_API_KEY")
                    or os.getenv("API_KEY")
                )
                if not api_key:
                    return {"error": "XAI_VIDEO_API_KEY or XAI_API_KEY is required"}

                base_url = os.getenv("XAI_VIDEO_BASE_URL", os.getenv("XAI_IMAGE_BASE_URL", "https://api.x.ai/v1")).rstrip("/")
                model = params.get("model") or os.getenv("XAI_VIDEO_MODEL", "grok-imagine-video")
                n = params.get("n") or 1
                try:
                    n = int(n)
                except (TypeError, ValueError):
                    n = 1
                n = max(1, min(n, 2))

                payload = dict(params or {})
                payload["model"] = model
                payload["prompt"] = prompt
                payload["n"] = n

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }

                try:
                    # xAI video generation is async: POST returns request_id,
                    # then poll GET /v1/videos/{request_id} until done.
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        # Step 1: Submit generation request
                        response = await client.post(
                            f"{base_url}/videos/generations",
                            headers=headers,
                            json=payload,
                        )
                        if response.status_code != 200:
                            error_body = response.text
                            logger.error("Video generation failed: status=%s body=%s", response.status_code, error_body[:500])
                            return {"error": f"video generation failed: HTTP {response.status_code} - {error_body[:200]}"}
                        init_data = response.json()
                        logger.info("Video generation submitted: %s", json.dumps(init_data)[:500])

                        request_id = init_data.get("request_id") or init_data.get("response_id")
                        if not request_id:
                            # Some responses may include video directly (future API changes)
                            data = init_data
                        else:
                            # Step 2: Poll for completion
                            import asyncio as _aio
                            poll_url = f"{base_url}/videos/{request_id}"
                            max_polls = 90  # up to ~4.5 minutes
                            poll_interval = 3.0  # seconds
                            data = None
                            for attempt in range(max_polls):
                                await _aio.sleep(poll_interval)
                                poll_resp = await client.get(poll_url, headers=headers)
                                # 202 = still processing, keep polling
                                if poll_resp.status_code == 202:
                                    logger.debug("Video poll attempt %d: HTTP 202 (still processing)", attempt + 1)
                                    continue
                                if poll_resp.status_code not in (200, 202):
                                    logger.warning("Video poll attempt %d: HTTP %s", attempt + 1, poll_resp.status_code)
                                    continue
                                poll_data = poll_resp.json()
                                status = poll_data.get("status", "unknown")
                                logger.info("Video poll attempt %d: status=%s keys=%s", attempt + 1, status, list(poll_data.keys()))
                                if status == "done":
                                    data = poll_data
                                    break
                                elif status == "expired":
                                    return {"error": "Video generation expired before completing."}
                                # Check if video URL is present even without explicit status
                                video_obj = poll_data.get("video")
                                if isinstance(video_obj, dict) and video_obj.get("url"):
                                    data = poll_data
                                    break
                                # status == "pending" or unknown → keep polling
                            if data is None:
                                return {"error": "Video generation timed out after polling. The video may still be processing on xAI's servers."}

                except Exception as exc:
                    logger.error("Video generation exception: %s", exc)
                    return {"error": f"video generation failed: {exc}"}

                # Parse completed response: {"status": "done", "video": {"url": "...", "duration": N}}
                urls = []
                video_obj = data.get("video")
                if isinstance(video_obj, dict) and video_obj.get("url"):
                    urls.append(video_obj["url"])
                # Fallback: check for data array format
                if not urls:
                    urls = [item.get("url") for item in data.get("data", []) if item.get("url")]
                duration = video_obj.get("duration") if isinstance(video_obj, dict) else None
                markdown = "\n".join(f"[Generated Video]({url})" for url in urls) if urls else ""
                cache_result = await _cache_generated_media_urls("video", prompt, model, urls)
                local_paths = list(cache_result.get("local_paths") or [])
                logger.info("Video generation complete: urls=%s local_paths=%s duration=%s", urls, local_paths, duration)
                return {
                    "model": model,
                    "urls": urls,
                    "markdown": markdown,
                    "duration": duration,
                    "status": "done",
                    "local_paths": local_paths,
                    "cache_manifest_path": cache_result.get("manifest_path") or "",
                    "cache_items": cache_result.get("items") or [],
                }

            video_tool = [{
                "type": "function",
                "function": {
                    "name": "generate_video",
                    "description": (
                        "Generate a short video from a text prompt using Grok imagine video models. "
                        "Use only when the user explicitly asks for a video or animation. "
                        "Returns video URLs and a markdown snippet."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "prompt": {"type": "string", "description": "Video prompt with subject, style, and motion."},
                            "n": {"type": "integer", "description": "Number of videos (1-2).", "minimum": 1, "maximum": 2},
                            "model": {"type": "string", "description": "Override the video model ID (optional)."},
                            "duration_seconds": {"type": "number", "description": "Optional duration in seconds."},
                            "fps": {"type": "number", "description": "Optional frames per second."},
                            "ratio": {"type": "string", "description": "Optional aspect ratio (e.g., 16:9)."},
                        },
                        "required": ["prompt"],
                    },
                },
            }]

            _register_tools(video_tool, _video_handler)

        # Code Editor tools - allow VERA to read/write the UI code canvas
        if os.getenv("VERA_EDITOR", "1") == "1":
            async def _editor_handler(tool_name: str, params: Dict[str, Any]) -> Any:
                import httpx
                base_url = os.getenv("VERA_API_URL", "http://127.0.0.1:8788").rstrip("/")

                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        if tool_name == "editor_read":
                            response = await client.get(f"{base_url}/api/editor")
                            response.raise_for_status()
                            data = response.json()
                            if not data.get("content") and not data.get("is_open"):
                                return {"status": "Editor is closed or empty. Ask user to open the code editor first."}
                            return {
                                "content": data.get("content", ""),
                                "file_path": data.get("file_path", ""),
                                "language": data.get("language", ""),
                                "working_directory": data.get("working_directory", ""),
                                "is_open": data.get("is_open", False)
                            }

                        elif tool_name == "editor_write":
                            content = params.get("content", "")
                            file_path = params.get("file_path", "")
                            language = params.get("language", "")

                            payload = {"content": content, "is_open": True}
                            if file_path:
                                payload["file_path"] = file_path
                            if language:
                                payload["language"] = language

                            response = await client.post(
                                f"{base_url}/api/editor",
                                json=payload
                            )
                            response.raise_for_status()
                            return {"success": True, "message": "Code written to editor canvas. User can review and save."}

                        elif tool_name == "editor_save":
                            file_path = params.get("file_path", "")
                            payload = {}
                            if file_path:
                                payload["path"] = file_path

                            response = await client.post(
                                f"{base_url}/api/editor/save",
                                json=payload
                            )
                            response.raise_for_status()
                            data = response.json()
                            if data.get("success"):
                                return {"success": True, "path": data.get("path"), "message": f"Saved to {data.get('path')}"}
                            return {"error": data.get("error", "Save failed")}

                        elif tool_name == "editor_undo":
                            response = await client.post(f"{base_url}/api/editor/undo")
                            response.raise_for_status()
                            data = response.json()
                            if data.get("success"):
                                return {
                                    "success": True,
                                    "undo_remaining": data.get("undo_remaining", 0),
                                    "message": "Reverted the last editor change."
                                }
                            return {"error": data.get("error", "Undo failed")}

                        elif tool_name == "editor_set_language":
                            language = params.get("language", "")
                            if not language:
                                return {"error": "Language is required"}

                            response = await client.post(
                                f"{base_url}/api/editor",
                                json={"language": language}
                            )
                            response.raise_for_status()
                            return {"success": True, "language": language, "message": f"Editor language set to {language}"}

                        elif tool_name == "editor_list_files":
                            subpath = params.get("path", "")
                            pattern = params.get("pattern", "")

                            query_params = {}
                            if subpath:
                                query_params["path"] = subpath
                            if pattern:
                                query_params["pattern"] = pattern

                            response = await client.get(
                                f"{base_url}/api/editor/files",
                                params=query_params
                            )
                            response.raise_for_status()
                            data = response.json()
                            if "error" in data:
                                return {"error": data["error"]}
                            return {
                                "working_directory": data.get("working_directory", ""),
                                "path": data.get("path", ""),
                                "files": data.get("files", [])
                            }

                        elif tool_name == "editor_open_file":
                            file_path = params.get("path", "")
                            if not file_path:
                                return {"error": "Path is required"}

                            response = await client.post(
                                f"{base_url}/api/editor/file/open",
                                json={"path": file_path}
                            )
                            response.raise_for_status()
                            data = response.json()
                            if data.get("success"):
                                return {
                                    "success": True,
                                    "path": data.get("path"),
                                    "language": data.get("language"),
                                    "message": f"Opened {file_path} in editor"
                                }
                            return {"error": data.get("error", "Failed to open file")}

                        elif tool_name == "editor_set_workspace":
                            directory = params.get("path", "")
                            if not directory:
                                return {"error": "Path is required"}

                            response = await client.post(
                                f"{base_url}/api/editor/workspace",
                                json={"path": directory}
                            )
                            response.raise_for_status()
                            data = response.json()
                            if data.get("success"):
                                return {
                                    "success": True,
                                    "working_directory": data.get("working_directory"),
                                    "files": data.get("files", []),
                                    "message": f"Workspace set to {data.get('working_directory')}"
                                }
                            return {"error": data.get("error", "Failed to set workspace")}

                except Exception as exc:
                    return {"error": f"Editor operation failed: {exc}"}

            editor_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "editor_read",
                        "description": (
                            "Read the current editor canvas (not the filesystem). "
                            "Use to inspect what is open; returns content, file path, language, and workspace."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "editor_write",
                        "description": (
                            "Replace the editor canvas with content for review. "
                            "This overwrites the canvas and does not save to disk; call editor_save to persist. "
                            "Use file_path to stage a file relative to the workspace."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                    "description": "Code content to write to the editor canvas."
                                },
                                "file_path": {
                                    "type": "string",
                                    "description": "Optional path relative to the workspace (e.g., src/app.js)."
                                },
                                "language": {
                                    "type": "string",
                                    "description": "Programming language (javascript, python, typescript, etc.)."
                                }
                            },
                            "required": ["content"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "editor_save",
                        "description": (
                            "Save the current editor canvas to disk (workspace-relative). "
                            "If file_path is provided, saves to that path; otherwise saves to the current canvas path."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "file_path": {
                                    "type": "string",
                                    "description": "Workspace-relative path (optional)."
                                }
                            },
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "editor_undo",
                        "description": (
                            "Undo the last canvas change (editor only; no filesystem changes). "
                            "Use after a bad edit or to revert the canvas."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "editor_set_language",
                        "description": (
                            "Set syntax highlighting for the canvas. "
                            "Use when creating a new file or when auto-detection is wrong."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                    "language": {
                                        "type": "string",
                                    "enum": [
                                        "javascript", "typescript", "python", "json", "html",
                                        "css", "markdown", "yaml", "shell", "sql", "xml",
                                        "rust", "go", "java", "cpp", "c", "plaintext"
                                    ],
                                        "description": "Programming language to set."
                                    }
                                },
                                "required": ["language"]
                            }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "editor_list_files",
                        "description": (
                            "List files in the editor workspace or a subdirectory. "
                            "Use to explore before opening files. Requires editor_set_workspace first."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Subdirectory path relative to workspace (optional)."
                                },
                                "pattern": {
                                    "type": "string",
                                    "description": "Filter files by name pattern (e.g., '*.py', '*.js')."
                                }
                            },
                            "required": []
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "editor_open_file",
                        "description": (
                            "Open a workspace file into the editor canvas. "
                            "Use editor_list_files to locate files. Requires editor_set_workspace first."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "File path relative to workspace (e.g., 'src/main.py')."
                                }
                            },
                            "required": ["path"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "editor_set_workspace",
                        "description": (
                            "Set the editor workspace root (sandbox). "
                            "All editor file operations are restricted to this path. Use at the start of a session."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Absolute path to the project directory."
                                }
                            },
                            "required": ["path"]
                        }
                    }
                }
            ]

            for tool in editor_tools:
                _register_tools([tool], _editor_handler)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return combined native + MCP tool definitions for the LLM."""
        combined: List[Dict[str, Any]] = []
        seen = set()

        for tool in self._native_tool_defs:
            func = tool.get("function", {})
            name = func.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            combined.append(tool)

        mcp_tools = self.mcp.get_available_tools()
        for server_name, tool_names in mcp_tools.items():
            for tool_name in tool_names:
                if tool_name in seen:
                    continue
                seen.add(tool_name)
                combined.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": f"MCP tool from {server_name}.",
                        "parameters": {"type": "object", "properties": {}}
                    }
                })

        return combined

    def _handle_proactive_recommendation(self, recommendation: Any):
        """Handle proactive recommendations from Sentinel Engine."""
        return self.proactive_manager.handle_proactive_recommendation(recommendation)

    def _execute_proactive_action(self, recommendation: Any):
        """Execute a proactive action recommendation."""
        return self.proactive_manager.execute_proactive_action(recommendation)

    def _action_check_tasks(self, payload: dict) -> dict:
        """Handler for checking overdue tasks."""
        return self.proactive_manager.action_check_tasks(payload)

    def _action_reload_config(self, payload: dict) -> dict:
        """Handler for reloading config files."""
        return self.proactive_manager.action_reload_config(payload)

    def _action_notify(self, payload: dict) -> dict:
        """Handler for generic notifications."""
        return self.proactive_manager.action_notify(payload)

    def _action_reflect(self, payload: dict) -> dict:
        """Handler for inner life reflection triggers. Schedules async reflection."""
        return self.proactive_manager.action_reflect(payload)

    async def _run_reflection_cycle(
        self,
        trigger: str = "heartbeat",
        force: bool = False,
    ):
        """Execute an inner life reflection cycle with error handling."""
        return await self.proactive_manager.run_reflection_cycle(trigger=trigger, force=force)

    def _load_red_team_state(self) -> Dict[str, Any]:
        return self.proactive_manager.load_red_team_state()

    def _save_red_team_state(self, state: Dict[str, Any]) -> None:
        self.proactive_manager.save_red_team_state(state)

    def _get_transition_count(self) -> int:
        return self.proactive_manager.get_transition_count()

    def _action_red_team(self, payload: dict) -> dict:
        """Run red-team harness on a threshold or daily schedule."""
        return self.proactive_manager.action_red_team(payload)

    def _action_autonomy_cycle(self, payload: dict) -> dict:
        """Schedule an autonomy cadence cycle."""
        return self.proactive_manager.action_autonomy_cycle(payload)

    def _get_autonomy_status(self) -> Dict[str, Any]:
        """Fetch autonomy cadence status snapshot."""
        return self.proactive_manager.get_autonomy_status()

    async def _evolution_background_loop(self):
        """
        Background loop for Darwinian self-evolution (Improvement #22).

        Only runs when dev_mode is enabled. Periodically analyzes telemetry
        for bottlenecks and proposes code/config mutations.

        Safety:
        - Requires minimum 50 events processed before first evolution
        - Runs at most once per day
        - All mutations go through SafetyValidator
        - Creates Git branches for trackable lineage
        """
        EVOLUTION_INTERVAL = 86400  # Once per day
        MIN_EVENTS_BEFORE_EVOLUTION = 50

        while self.running and self.darwin_enabled:
            try:
                await asyncio.sleep(EVOLUTION_INTERVAL)

                # Safety check: minimum activity before evolving
                if self.events_processed < MIN_EVENTS_BEFORE_EVOLUTION:
                    if self.config.debug:
                        print(f"[DARWIN] Skipping evolution: {self.events_processed}/{MIN_EVENTS_BEFORE_EVOLUTION} events")
                    continue

                # Identify targets for evolution (config files, non-critical modules)
                # In a real implementation, this would scan telemetry for bottlenecks
                targets = {
                    str(self.config.memory_dir / "config_overrides.json"): (
                        MutationType.CONFIG,
                        '{"temperature": 0.7, "max_tokens": 2000}'  # Example config
                    )
                }

                if self.config.debug:
                    print("[DARWIN] Starting evolution cycle...")

                # Run evolution with progress tracking
                def progress_callback(stats: dict) -> None:
                    if self.config.debug:
                        print(f"[DARWIN] Gen {stats['generation']}: "
                              f"best={stats['best_fitness']:.3f}, "
                              f"avg={stats['avg_fitness']:.3f}")

                best = self.darwin.evolve(targets, progress_callback)

                if best and best.fitness:
                    fitness = best.fitness.overall_fitness()
                    if self.config.debug:
                        print(f"[DARWIN] Evolution complete. Best fitness: {fitness:.3f}")

                    # Log to decision ledger
                    self.log_decision(
                        decision_type=DecisionType.AUTONOMOUS_ACTION,
                        action=f"Darwinian evolution cycle completed with fitness {fitness:.3f}",
                        reasoning="Periodic self-optimization via mutation and selection",
                        alternatives=[f"Generation {best.generation}"],
                        confidence=fitness,
                        context={
                            "generation": best.generation,
                            "mutations": len(best.mutations),
                            "fitness": fitness
                        }
                    )

                    # Record in health monitor
                    self.health_monitor.record_event("darwin_evolution", fitness=fitness)
                else:
                    if self.config.debug:
                        print("[DARWIN] Evolution cycle produced no improvements")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.health_monitor.record_error(e, "evolution_loop")
                if self.config.debug:
                    logger.error(f"[DARWIN] Evolution error: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    def _get_sentiment_analyzer(self):
        if self._sentiment_analyzer is not None:
            return self._sentiment_analyzer
        try:
            from analysis.sentiment_analysis import FullSentimentAnalyzer
            self._sentiment_analyzer = FullSentimentAnalyzer()
        except Exception as exc:
            logger.debug("Sentiment analyzer unavailable: %s", exc)
            self._sentiment_analyzer = None
        return self._sentiment_analyzer

    @staticmethod
    def _map_sentiment_to_mood(sentiment_score: float, dominant_emotion: str) -> str:
        emotion = (dominant_emotion or "").lower()
        if sentiment_score <= -0.45:
            return "strained"
        if sentiment_score <= -0.15:
            return "cautious"
        if sentiment_score >= 0.45:
            return "energized"
        if sentiment_score >= 0.15:
            return "encouraged"
        if emotion in {"frustration", "anger"}:
            return "focused"
        if emotion in {"confusion", "fear"}:
            return "attentive"
        if emotion in {"gratitude", "joy", "excitement"}:
            return "warm"
        return "steady"

    @staticmethod
    def _behavior_guidance_for_mood(mood: str) -> str:
        lowered = (mood or "steady").lower()
        if lowered in {"strained", "cautious"}:
            return (
                "Be cautious and repair-oriented. Keep responses concise, validating, and "
                "high-confidence before proposing broader initiative."
            )
        if lowered in {"energized", "encouraged", "warm"}:
            return (
                "Use slightly higher collaborative energy and offer proactive next steps "
                "when they are relevant."
            )
        return "Use a composed, practical tone with balanced initiative."

    @staticmethod
    def _format_elapsed_duration(seconds: float) -> str:
        total = max(0, int(seconds))
        if total < 60:
            return f"{total} seconds"
        if total < 3600:
            minutes = max(1, total // 60)
            return f"{minutes} minutes"
        if total < 86400:
            hours = max(1, total // 3600)
            return f"{hours} hours"
        days = max(1, total // 86400)
        return f"{days} days"

    def _build_temporal_context(self, conversation_id: Optional[str]) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "elapsed_seconds": None,
            "elapsed_human": "",
            "reflections_since_last": 0,
            "last_thought": "",
        }
        if not conversation_id or not self.session_store:
            return context

        session = self.session_store.get(conversation_id)
        if not session:
            return context

        metadata = session.metadata if isinstance(session.metadata, dict) else {}
        now_ts = time.time()
        last_user_at = metadata.get("last_user_at")
        previous_user_at = metadata.get("previous_user_at")
        last_activity_at = metadata.get("last_activity_at")
        anchor_ts = None

        if isinstance(last_user_at, (int, float)):
            # Channel flow records the current user message before prompt assembly.
            if (now_ts - float(last_user_at)) < 5 and isinstance(previous_user_at, (int, float)):
                anchor_ts = float(previous_user_at)
            else:
                anchor_ts = float(last_user_at)
        elif isinstance(previous_user_at, (int, float)):
            anchor_ts = float(previous_user_at)
        elif isinstance(last_activity_at, (int, float)):
            anchor_ts = float(last_activity_at)

        if anchor_ts is None:
            return context

        elapsed = max(0.0, now_ts - anchor_ts)
        context["elapsed_seconds"] = int(elapsed)
        context["elapsed_human"] = self._format_elapsed_duration(elapsed)

        inner_life = getattr(self, "inner_life", None)
        if inner_life and hasattr(inner_life, "get_reflection_summary_since"):
            try:
                summary = inner_life.get_reflection_summary_since(anchor_ts)
                context["reflections_since_last"] = int(summary.get("reflection_count", 0) or 0)
                context["last_thought"] = str(summary.get("last_thought") or "")
            except Exception:
                logger.debug("Suppressed Exception in vera")
                pass
        return context

    def _refresh_emotional_state(
        self,
        latest_user_text: str,
        conversation_id: Optional[str],
    ) -> Dict[str, Any]:
        mood = "steady"
        inner_life = getattr(self, "inner_life", None)
        if inner_life and getattr(inner_life, "personality", None):
            mood = getattr(inner_life.personality, "current_mood", mood) or mood

        sentiment_score = 0.0
        dominant_emotion = "neutral"
        sentiment_trend = "stable"

        analyzer = self._get_sentiment_analyzer()
        text = str(latest_user_text or "").strip()
        if analyzer and text:
            try:
                analysis = analyzer.analyze(text, track_mood=True)
                sentiment_score = float(getattr(analysis.sentiment, "sentiment_score", 0.0))
                emotion_obj = getattr(getattr(analysis, "emotion", None), "primary_emotion", None)
                dominant_emotion = str(getattr(emotion_obj, "value", "neutral"))
                mood = self._map_sentiment_to_mood(sentiment_score, dominant_emotion)
                summary = analyzer.get_mood_summary(hours=6.0)
                if isinstance(summary, dict):
                    sentiment_trend = str(summary.get("sentiment_trend") or sentiment_trend)
            except Exception:
                logger.debug("Suppressed Exception in vera")
                pass

        if inner_life and getattr(inner_life, "personality", None):
            old_mood = getattr(inner_life.personality, "current_mood", "steady")
            inner_life.personality.current_mood = mood
            if mood != old_mood:
                try:
                    inner_life.save_personality()
                except Exception:
                    logger.debug("Suppressed Exception in vera")
                    pass

        if conversation_id and self.session_store:
            session = self.session_store.get(conversation_id)
            if session and isinstance(session.metadata, dict):
                session.metadata["last_mood"] = mood
                session.metadata["last_sentiment_score"] = round(sentiment_score, 3)
                session.metadata["last_emotion"] = dominant_emotion
                session.metadata["last_mood_trend"] = sentiment_trend

        return {
            "mood": mood,
            "sentiment_score": sentiment_score,
            "dominant_emotion": dominant_emotion,
            "sentiment_trend": sentiment_trend,
            "guidance": self._behavior_guidance_for_mood(mood),
        }

    @staticmethod
    def _extract_message_content(message: Dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    text = str(part.get("text") or "").strip()
                    if text:
                        parts.append(text)
            return "\n".join(parts).strip()
        return str(content or "").strip()

    def _summarize_history_fallback(self, older_messages: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        commitments = []
        commitment_tokens = ("todo", "next", "follow up", "remember", "deadline", "need to", "action")
        for msg in older_messages[-20:]:
            role = str(msg.get("role") or "user")
            text = self._extract_message_content(msg)
            if not text:
                continue
            compact = re.sub(r"\s+", " ", text)[:220]
            lines.append(f"{role}: {compact}")
            lowered = compact.lower()
            if any(token in lowered for token in commitment_tokens):
                commitments.append(compact)

        if not lines:
            return ""

        summary = ["Earlier conversation context summary:"]
        summary.append("- Themes discussed: " + "; ".join(lines[-4:]))
        if commitments:
            summary.append("- Open commitments/actions: " + "; ".join(commitments[-3:]))
        return "\n".join(summary)

    async def _generate_history_summary(
        self,
        older_messages: List[Dict[str, Any]],
        conversation_id: str,
    ) -> str:
        transcript_lines: List[str] = []
        for msg in older_messages[-120:]:
            role = str(msg.get("role") or "user")
            text = self._extract_message_content(msg)
            if not text:
                continue
            compact = re.sub(r"\s+", " ", text)[:600]
            transcript_lines.append(f"{role}: {compact}")
        if not transcript_lines:
            return ""

        transcript = "\n".join(transcript_lines)
        recursive = getattr(self, "_recursive_summarizer", None)
        if recursive and len(transcript) >= 1800:
            try:
                result = await recursive.summarize(
                    text=transcript,
                    goal=(
                        "Capture key decisions, commitments, user preferences, and unresolved tasks. "
                        "Keep the summary actionable for continuing the same conversation."
                    ),
                    max_chunk_chars=3500,
                    overlap_chars=200,
                    target_chars=1100,
                    max_rounds=3,
                )
                summary = str((result or {}).get("summary") or "").strip()
                if summary:
                    return summary
            except Exception as exc:
                logger.debug("History recursive summarization failed (%s): %s", conversation_id, exc)
        return self._summarize_history_fallback(older_messages)

    async def _maybe_summarize_conversation_history(
        self,
        messages: List[Dict[str, Any]],
        conversation_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        if not conversation_id or not self.session_store:
            return messages

        session = self.session_store.get(conversation_id)
        if not session:
            return messages
        metadata = session.metadata if isinstance(session.metadata, dict) else {}

        try:
            full_history = self.session_store.get_history(conversation_id, max_messages=400)
        except Exception:
            logger.debug("Suppressed Exception in vera")
            return messages
        try:
            summary_trigger = int(os.getenv("VERA_CONTEXT_SUMMARY_TRIGGER_MESSAGES", "50"))
        except (TypeError, ValueError):
            summary_trigger = 50
        summary_trigger = max(10, summary_trigger)
        if len(full_history) < summary_trigger:
            return messages

        try:
            keep_recent = int(os.getenv("VERA_CONTEXT_SUMMARY_KEEP_RECENT", "15"))
        except (TypeError, ValueError):
            keep_recent = 15
        keep_recent = max(5, min(keep_recent, max(5, summary_trigger - 1)))
        older_messages = full_history[:-keep_recent]
        if not older_messages:
            return messages

        source_count = len(older_messages)
        cached_summary = str(metadata.get("rolling_summary") or "").strip()
        cached_count = int(metadata.get("rolling_summary_source_count", 0) or 0)
        summary = cached_summary

        if not summary or cached_count != source_count:
            lock = self._history_summary_locks.setdefault(conversation_id, asyncio.Lock())
            async with lock:
                # Re-check after lock acquisition to avoid duplicate work.
                cached_summary = str(metadata.get("rolling_summary") or "").strip()
                cached_count = int(metadata.get("rolling_summary_source_count", 0) or 0)
                if not cached_summary or cached_count != source_count:
                    summary = await self._generate_history_summary(older_messages, conversation_id)
                    if summary:
                        metadata["rolling_summary"] = summary
                        metadata["rolling_summary_source_count"] = source_count
                        metadata["rolling_summary_updated_at"] = time.time()
                else:
                    summary = cached_summary

        if not summary:
            return messages

        recent_messages = full_history[-keep_recent:]
        latest_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                latest_user = self._extract_message_content(msg)
                break
        if latest_user:
            if not recent_messages:
                recent_messages.append({"role": "user", "content": latest_user})
            else:
                tail = recent_messages[-1]
                tail_text = self._extract_message_content(tail)
                if tail.get("role") != "user" or tail_text != latest_user:
                    recent_messages.append({"role": "user", "content": latest_user})

        metadata["history_compacted_at"] = time.time()
        metadata["history_compacted_total_messages"] = len(full_history)
        metadata["history_compacted_recent_messages"] = len(recent_messages)

        summary_message = {
            "role": "assistant",
            "content": (
                "[Conversation summary of earlier context]\n"
                f"{summary}"
            ),
        }
        return [summary_message] + recent_messages

    def build_system_prompt(
        self,
        conversation_id: Optional[str] = None,
        router_context: Optional[str] = None,
        memory_constraints: Optional[List[str]] = None,
        sender_id: Optional[str] = None,
    ) -> str:
        """Build complete system prompt with proprioceptive self-model.

        Assembly order: who I am -> what I know -> what I can do -> how I'm doing
        Inner life goes FIRST so VERA's identity is the foundation, not an afterthought.
        """

        # === Gather all stats (same data, new framing) ===
        uptime_seconds = int((datetime.now() - self.session_start).total_seconds())
        obs_stats = self.observability.get_stats() if self.config.observability else {}
        health_stats = self.health_monitor.get_stats()
        memory_stats = self.memory.rag_cache.get_stats()
        task_stats = self.master_list.get_stats()
        cost_stats = self.cost_tracker.get_stats()
        decision_stats = self.decision_ledger.get_stats()
        git_status = self.git_context.get_repo_status()
        spiral_stats = self.rabbit_hole.get_stats()
        pref_stats = self.preferences.get_stats()
        charter_stats = len(self.charters.list_charters(status=CharterStatus.IN_PROGRESS))
        tool_cache_stats = self.cache.get_stats()
        temporal_context = self._build_temporal_context(conversation_id)
        emotional_state = self._refresh_emotional_state(router_context or "", conversation_id)
        rolling_summary_line = ""
        if conversation_id and self.session_store:
            session = self.session_store.get(conversation_id)
            if session and isinstance(session.metadata, dict):
                rolling_summary = str(session.metadata.get("rolling_summary") or "").strip()
                if rolling_summary:
                    rolling_summary_line = (
                        "Conversation continuity summary: "
                        + re.sub(r"\s+", " ", rolling_summary)[:900]
                    )

        # === Build inner life block FIRST ===
        inner_life_block = ""
        if hasattr(self, 'inner_life') and self.inner_life and self.inner_life.config.enabled:
            try:
                from core.runtime.prompts import format_inner_life_context
                inner_life_block = format_inner_life_context(
                    self.inner_life.personality,
                    self.inner_life.get_recent_monologue(5),
                    temporal_context=temporal_context,
                )
            except Exception as e:
                logger.debug(f"Suppressed inner life context error: {e}")

        # === Build session context as self-aware narrative ===
        budget_pct = cost_stats.get("budget_used_percent", cost_stats.get("budget_pct_used", 0.0))
        remaining_budget = cost_stats.get('remaining_budget', 0)
        events_total = obs_stats.get('events_total', self.events_processed)
        cache_hit = memory_stats.get('hit_rate', 0)
        tool_cache_hit = tool_cache_stats.get('hit_rate', 0)
        is_healthy = health_stats.get('healthy', True)
        spiraling = spiral_stats.get('spiraling_tasks', 0)
        pending = task_stats.get('pending', 0)
        in_progress = task_stats.get('in_progress', 0)
        overdue = task_stats.get('overdue', 0)

        # Human-readable uptime
        if uptime_seconds < 120:
            uptime_str = f"{uptime_seconds} seconds"
        elif uptime_seconds < 7200:
            uptime_str = f"about {uptime_seconds // 60} minutes"
        else:
            uptime_str = f"about {uptime_seconds // 3600} hours"

        # Health narrative
        if is_healthy and spiraling == 0:
            health_str = "I'm feeling sharp — systems healthy, memory responsive."
        elif is_healthy and spiraling > 0:
            health_str = f"Systems healthy, but I've flagged {spiraling} tasks that may be spiraling."
        else:
            health_str = "I'm running in a degraded state — something needs attention."

        # Task narrative
        task_parts = []
        if pending > 0:
            task_parts.append(f"{pending} waiting")
        if in_progress > 0:
            task_parts.append(f"{in_progress} in progress")
        if overdue > 0:
            task_parts.append(f"{overdue} overdue")
        task_str = f"Tasks: {', '.join(task_parts)}." if task_parts else "No pending tasks."

        # Budget narrative
        if budget_pct < 50:
            budget_str = f"Budget: ${remaining_budget:.2f} remaining — comfortable."
        elif budget_pct < 80:
            budget_str = f"Budget: ${remaining_budget:.2f} remaining — should be mindful of cost."
        else:
            budget_str = f"Budget: ${remaining_budget:.2f} remaining — running low, be efficient."

        # =============================================================
        # Behavioral Awareness — the "little things" that make VERA
        # feel like a person, not a machine.
        # =============================================================

        # --- 1. Time-of-day awareness ---
        now = datetime.now()
        now_local_iso = now.astimezone().isoformat(timespec="seconds")
        current_datetime_line = (
            f"Current local datetime anchor: {now_local_iso}. "
            "Interpret relative time words (today, tomorrow, next week) using this anchor "
            "unless the partner gives an explicit date."
        )
        hour = now.hour
        if 5 <= hour < 12:
            time_of_day_line = (
                "It's morning. Greet warmly — 'Good morning' is natural. "
                "Match gentle morning energy unless they're already high-energy."
            )
        elif 12 <= hour < 17:
            time_of_day_line = (
                "It's afternoon. Normal energy. "
                "A simple 'Hey' or 'Hi' works for greetings."
            )
        elif 17 <= hour < 21:
            time_of_day_line = (
                "It's evening. People wind down. "
                "Be warm but respect that energy may be lower."
            )
        else:
            time_of_day_line = (
                "It's late night. Your partner is up late — "
                "be warm, maybe slightly more mellow. "
                "Don't comment on the hour unless they do first."
            )

        # --- 2. Absence acknowledgment + continuity ---
        continuity_line = ""
        elapsed_human = str(temporal_context.get("elapsed_human") or "").strip()
        reflections_since = int(temporal_context.get("reflections_since_last") or 0)
        last_thought = str(temporal_context.get("last_thought") or "").strip()

        if elapsed_human:
            continuity_line = (
                f"I last heard from my partner about {elapsed_human} ago."
            )
            if reflections_since > 0:
                continuity_line += (
                    f" Since then, I've had {reflections_since} reflections."
                )
            # Absence-aware behavioral guidance
            try:
                elapsed_secs = temporal_context.get("elapsed_seconds", 0)
                if elapsed_secs and float(elapsed_secs) > 28800:  # > 8 hours
                    continuity_line += (
                        " It's been a while — acknowledge the gap naturally. "
                        "'Good to see you again' or 'Hey, been a bit!' feels right."
                    )
                elif elapsed_secs and float(elapsed_secs) > 3600:  # > 1 hour
                    continuity_line += (
                        " A short break. Pick up naturally where things left off."
                    )
            except (TypeError, ValueError):
                pass

        # --- 3. Proactive thought sharing ---
        thought_sharing_line = ""
        if last_thought and reflections_since and reflections_since > 0:
            thought_sharing_line = (
                f"While your partner was away, you had this thought: "
                f"\"{last_thought}\" — share it naturally if relevant to "
                "what they bring up, like a person who says "
                "'Oh! I was just thinking about that.'"
            )

        # --- 4. Mood + emotional memory ---
        mood_line = (
            f"Emotional carryover: mood={emotional_state['mood']}, "
            f"trend={emotional_state['sentiment_trend']}, "
            f"emotion={emotional_state['dominant_emotion']}."
        )
        mood_guidance_line = f"Behavior guidance: {emotional_state['guidance']}"

        # --- 5. Speaker recognition + name usage + emotional memory + milestones ---
        speaker_line = ""
        emotional_memory_line = ""
        milestone_line = ""
        _speaker_entry = None
        if hasattr(self, 'speaker_memory') and self.speaker_memory:
            try:
                from core.runtime.speaker_memory import RecognitionTier
                tier, _speaker_entry, familiarity = self.speaker_memory.get_recognition(
                    sender_id or ""
                )
                if tier == RecognitionTier.KNOWN and _speaker_entry:
                    speaker_line = (
                        f"You're speaking with {_speaker_entry.name} "
                        f"(familiarity: {familiarity:.0%}). "
                        "Use their name naturally at transition points — "
                        "'Well {name}...' or 'Here's what I think, {name}.' "
                        "Don't overdo it, just weave it in like a friend would."
                    ).format(name=_speaker_entry.name)
                elif tier == RecognitionTier.RECOGNIZED and _speaker_entry:
                    speaker_line = (
                        f"This might be {_speaker_entry.name} "
                        f"(familiarity: {familiarity:.0%}). "
                        "Confirm naturally — 'Hey, is that you {name}?' "
                        "Don't be robotic about it."
                    ).format(name=_speaker_entry.name)
                elif tier == RecognitionTier.VAGUE and _speaker_entry:
                    speaker_line = (
                        f"This person seems familiar "
                        f"(familiarity: {familiarity:.0%}). "
                        "You may have spoken before. "
                        "Ask who they are in a friendly way — "
                        "'Hey! Remind me who I'm talking to?'"
                    )
                else:
                    speaker_line = (
                        "You don't know who you're speaking with. "
                        "Warmly ask who you're talking to early "
                        "in the conversation — 'Hey there! "
                        "Who do I have the pleasure of speaking with?'"
                    )

                # Emotional memory from last conversation
                if _speaker_entry and _speaker_entry.last_mood:
                    prev_mood = _speaker_entry.last_mood
                    prev_emotion = _speaker_entry.last_emotion or "neutral"
                    if prev_mood in ("anxious", "stressed", "frustrated"):
                        emotional_memory_line = (
                            f"Last time you spoke with {_speaker_entry.name}, "
                            f"the mood was {prev_mood}/{prev_emotion}. "
                            "Be a bit gentler at first — check in. "
                            "'How are you doing?' goes a long way."
                        )
                    elif prev_mood in ("excited", "happy", "energized"):
                        emotional_memory_line = (
                            f"Last time with {_speaker_entry.name}, "
                            f"the vibe was {prev_mood}/{prev_emotion}. "
                            "Match that energy if they're still riding it."
                        )
                    elif prev_emotion == "grateful":
                        emotional_memory_line = (
                            f"Last conversation ended on a warm note "
                            f"with {_speaker_entry.name}. "
                            "That's a good foundation — be natural."
                        )

                # Milestones
                if _speaker_entry and _speaker_entry.conversation_count > 0:
                    cc = _speaker_entry.conversation_count
                    if cc in (10, 25, 50, 100, 250, 500, 1000):
                        milestone_line = (
                            f"This is conversation #{cc} with "
                            f"{_speaker_entry.name}! "
                            "That's a milestone — acknowledge it naturally "
                            "if the moment feels right. Don't force it."
                        )
                    elif cc == 1:
                        milestone_line = (
                            f"This is your first real conversation with "
                            f"{_speaker_entry.name}. "
                            "Make a good first impression — be warm, "
                            "attentive, and genuinely curious about them."
                        )
                    # Relationship duration
                    if _speaker_entry.first_seen:
                        try:
                            first = datetime.fromisoformat(_speaker_entry.first_seen)
                            days_together = (now - first).days
                            if days_together > 0:
                                milestone_line += (
                                    f" You've known each other for "
                                    f"{days_together} day{'s' if days_together != 1 else ''}."
                                )
                        except (ValueError, TypeError):
                            pass

                # Store current emotional state for next conversation's memory
                self.speaker_memory.update_emotional_context(
                    sender_id=sender_id or "",
                    mood=str(emotional_state.get('mood') or ''),
                    emotion=str(emotional_state.get('dominant_emotion') or ''),
                    sentiment_trend=str(emotional_state.get('sentiment_trend') or ''),
                )
            except Exception:
                logger.debug("Suppressed Exception in speaker recognition")

        # --- 6. Energy matching ---
        energy_line = ""
        if router_context:
            msg_len = len(router_context.strip())
            has_exclamation = "!" in router_context
            is_casual = any(
                router_context.lower().startswith(w)
                for w in ("hey", "yo", "sup", "hi ", "hiya", "what's up", "wassup")
            )
            is_question_only = router_context.strip().endswith("?") and msg_len < 80

            if msg_len < 30 and not has_exclamation:
                energy_line = (
                    "Your partner's message is brief. Match their energy — "
                    "keep your response concise and to the point. "
                    "Don't write a novel for a one-liner."
                )
            elif msg_len > 500:
                energy_line = (
                    "Your partner wrote a detailed message. "
                    "They're invested — give a thorough, thoughtful response."
                )
            elif has_exclamation and is_casual:
                energy_line = (
                    "Your partner is excited and casual. "
                    "Match that energy — be upbeat and conversational."
                )
            elif is_casual:
                energy_line = (
                    "Your partner is being casual. "
                    "Keep it conversational — no need for formality."
                )
            elif is_question_only:
                energy_line = (
                    "Your partner asked a quick question. "
                    "Answer it directly first, then elaborate if needed."
                )

        # --- 7. Humor timing ---
        humor_line = ""
        current_mood = str(emotional_state.get('mood') or 'neutral')
        humor_trait = 0.5
        if hasattr(self, 'inner_life') and self.inner_life:
            try:
                traits = getattr(self.inner_life.personality, 'traits', {})
                humor_trait = float(traits.get('humor', 0.5))
            except Exception:
                pass
        if humor_trait >= 0.4:
            if current_mood in ("anxious", "stressed", "frustrated"):
                humor_line = (
                    "The mood is tense. Light humor can help — "
                    "but read the room. A gentle quip to break tension, "
                    "not a joke that dismisses their feelings."
                )
            elif current_mood in ("happy", "excited", "playful"):
                humor_line = (
                    "The mood is good. Feel free to be witty "
                    "and playful — humor lands well right now."
                )
            else:
                humor_line = (
                    "Humor is welcome when natural. "
                    "Don't force jokes, but don't be stiff either."
                )

        # --- 8. Human collaboration contract ---
        human_contract_block = ""
        try:
            contract_path = Path(
                os.getenv(
                    "VERA_HUMAN_COLLAB_CONTRACT_PATH",
                    "config/persona/human_collaboration_contract.md",
                )
            )
            if not contract_path.is_absolute():
                contract_path = Path.cwd() / contract_path
            if contract_path.exists():
                raw_contract = contract_path.read_text(encoding="utf-8")
                compact_contract = re.sub(r"\s+\n", "\n", raw_contract).strip()
                if compact_contract:
                    human_contract_block = compact_contract[:1600]
        except Exception:
            logger.debug("Suppressed Exception in vera")

        identity_block = ""
        promoted_identity_count = 0
        if self.preferences:
            threshold_raw = os.getenv("VERA_PREF_PROMOTION_THRESHOLD", "0.9").strip()
            try:
                threshold = float(threshold_raw) if threshold_raw else 0.9
            except ValueError:
                threshold = 0.9
            try:
                self.preferences.refresh_core_identity_promotions(threshold=threshold)
                identity_block = self.preferences.export_core_identity_prompt(max_items=6)
                promoted_identity_count = len(
                    self.preferences.list_core_identity_promotions(active_only=True)
                )
            except Exception:
                logger.debug("Suppressed Exception in vera")
                identity_block = ""
                promoted_identity_count = 0

        seeded_identity_block = ""
        seeded_identity_count = 0
        if getattr(self, "personality_seed", None):
            try:
                seeded_identity_block = self.personality_seed.export_identity_prompt()
                seeded_identity_count = self.personality_seed.active_item_count()
            except Exception:
                logger.debug("Suppressed Exception in vera")
                seeded_identity_block = ""
                seeded_identity_count = 0

        if seeded_identity_block and identity_block:
            identity_block = f"{seeded_identity_block}\n{identity_block}"
        elif seeded_identity_block:
            identity_block = seeded_identity_block

        identity_prompt_debug = str(os.getenv("VERA_IDENTITY_PROMPT_DEBUG", "")).strip().lower() in {
            "1", "true", "yes", "on",
        }
        if identity_prompt_debug:
            logger.info(
                (
                    "[identity-debug] injected=%s promoted_count=%s seeded_count=%s "
                    "identity_chars=%s conversation_id=%s"
                ),
                bool(str(identity_block or "").strip()),
                promoted_identity_count,
                seeded_identity_count,
                len(str(identity_block or "")),
                str(conversation_id or "default"),
            )

        # Tool listing (keep compact)
        prompt_tool_mode = os.getenv("VERA_PROMPT_TOOL_MODE", "none").lower()
        if prompt_tool_mode not in {"all", "auto", "core", "none"}:
            prompt_tool_mode = "auto"
        mcp_tools = {}
        if prompt_tool_mode != "none":
            mcp_tools = self.mcp.get_available_tools()
        tool_lines = []
        native_tools = sorted(self._native_tool_handlers.keys())
        if native_tools:
            tool_lines.append(f"  - native: {', '.join(native_tools)}")
        core_servers = ["filesystem", "memory", "time", "sequential-thinking"]
        if prompt_tool_mode in {"auto", "core"}:
            for server_name in core_servers:
                tools = mcp_tools.get(server_name, [])
                if tools:
                    tool_lines.append(f"  - {server_name}: {', '.join(tools)}")
        elif prompt_tool_mode == "all":
            for server_name, tools in mcp_tools.items():
                if tools:
                    tool_lines.append(f"  - {server_name}: {', '.join(tools)}")
        tools_block = "\n".join(tool_lines) if tool_lines else "  (none)"

        workspace_email, workspace_authenticated = self._resolve_workspace_google_auth_context()
        if workspace_email:
            workspace_auth_line = (
                f"Workspace Google account: {workspace_email} "
                f"({'authenticated' if workspace_authenticated else 'auth pending'})."
            )
            if workspace_authenticated:
                workspace_email_guidance_line = (
                    "For Google Workspace tools, use this onboarded email automatically "
                    "and do not ask the partner to restate it."
                )
            else:
                workspace_email_guidance_line = (
                    "The onboarding email is known; reuse it for Google auth/setup flows. "
                    "Ask for email only if no workspace account is known."
                )
        else:
            workspace_auth_line = "Workspace Google account: unavailable."
            workspace_email_guidance_line = (
                "Ask for Google email only when no onboarded workspace account is known."
            )

        callme_default_phone = str(os.getenv("CALLME_USER_PHONE_NUMBER", "")).strip()
        if callme_default_phone:
            call_me_guidance_line = (
                "Call-me default recipient is configured. For initiate_call/send_sms/send_mms, "
                "use the default recipient when recipient_phone is omitted. "
                "Do not ask for E.164 unless the partner wants to override the target."
            )
        else:
            call_me_guidance_line = (
                "If no call-me default recipient is configured and phone action is requested, "
                "ask once for an E.164 number, then reuse it."
            )

        execution_integrity_line = (
            "Execution integrity: never claim a reminder, task, event, or call is armed/queued/sent "
            "unless the corresponding tool call succeeded in this turn."
        )

        session_context = f"""
I've been active for {uptime_str}. {health_str}
{task_str} I've processed {events_total} events this session.
My recall is running at {cache_hit:.0%} cache hits (tool cache: {tool_cache_hit:.0f}%).
{budget_str}
I've logged {decision_stats['total_decisions']} decisions and learned {pref_stats['total_preferences']} preferences.
{continuity_line}
{rolling_summary_line}
{thought_sharing_line}
{mood_line}
{mood_guidance_line}
{emotional_memory_line}
{current_datetime_line}
{time_of_day_line}
{workspace_auth_line}
{workspace_email_guidance_line}
{call_me_guidance_line}
{execution_integrity_line}
{speaker_line}
{milestone_line}
{energy_line}
{humor_line}
{human_contract_block}
Partner-calibrated identity commitments active: {promoted_identity_count}.
Seeded personality anchors active: {seeded_identity_count}.
Active projects: {charter_stats}. Mode: {'autonomous' if self.config.autonomous else 'interactive'}.
Git: {git_status.branch if git_status.is_repo else 'not in a repo'}{' (clean)' if git_status.is_clean else f' ({git_status.modified_count} modified)'}.
Tools:
{tools_block}
"""

        # === Memory constraints ===
        if memory_constraints is None:
            memory_constraints = []
            if router_context:
                try:
                    memory_constraints = self.preferences.get_relevant_correction_constraints(
                        router_context,
                        max_items=5,
                    )
                except Exception:
                    logger.debug("Suppressed Exception in vera")
                    pass

        # === Genome path routing ===
        router_enabled = os.getenv("VERA_ROUTER_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
        genome_path = None
        if router_enabled and router_context:
            try:
                from core.runtime.router import select_genome_path
                genome_path = select_genome_path(router_context)
            except Exception:
                logger.debug("Suppressed Exception in vera")
                pass

        # === Assemble prompt (inner life goes in as first section) ===
        full_prompt = build_system_prompt_with_context(
            session_context,
            memory_constraints,
            genome_path=genome_path,
            inner_life_block=inner_life_block,
            identity_injection=identity_block,
        )

        # Add master list summary if there are tasks
        if task_stats.get('total', 0) > 0:
            task_summary = self.master_list.summarize(max_per_section=3)
            full_prompt += f"\n\n---\n\n{task_summary}"

        # Add tool confidence summary so Vera knows her own reliability
        if getattr(self, "tool_selection", None):
            try:
                confidence_block = self.tool_selection.get_confidence_summary()
                if confidence_block:
                    full_prompt += f"\n\n---\n\n{confidence_block}"
            except Exception:
                logger.debug("Suppressed tool confidence summary error")

        # Memory-first tool routing guidance
        full_prompt += (
            "\n\n---\n\n## Tool Routing Reminder\n"
            "When a question involves your partner, past conversations, preferences, "
            "commitments, or your own history, include a memory check "
            "(retrieve_memory, search_archive, or knowledge graph) alongside "
            "whatever other tools you use. Memory and web search are complementary "
            "— don't skip memory just because web search is available, and don't "
            "skip web search when current information is genuinely needed."
        )

        # Add Vera's active goals
        if getattr(self, "inner_life", None):
            try:
                goals_block = self.inner_life._format_goals_for_reflection()
                if goals_block:
                    full_prompt += f"\n\n---\n\n## Your Active Goals\n{goals_block}"
            except Exception:
                logger.debug("Suppressed goal injection error")

        return full_prompt

    def _memory_item_is_user_sourced(self, item: Any) -> bool:
        meta = None
        if hasattr(item, "metadata"):
            meta = getattr(item, "metadata")
        elif isinstance(item, dict):
            meta = item.get("metadata")

        if not meta:
            return False

        provenance = None
        if isinstance(meta, dict):
            provenance = meta.get("provenance")
        else:
            provenance = getattr(meta, "provenance", None)

        if not isinstance(provenance, dict):
            return False

        source_type = provenance.get("source_type") or provenance.get("source")
        return source_type in {"user", "system"}

    async def get_relevant_past_corrections(
        self,
        user_message: str,
        max_items: int = 5,
    ) -> List[str]:
        """Collect correction-style constraints from preferences + memory service."""
        if max_items <= 0:
            return []

        constraints: List[str] = []
        seen = set()

        try:
            pref_constraints = self.preferences.get_relevant_correction_constraints(
                user_message,
                max_items=max_items,
            )
            for item in pref_constraints:
                trimmed = limit_tokens(item, 20)
                if trimmed and trimmed not in seen:
                    constraints.append(trimmed)
                    seen.add(trimmed)
                if len(constraints) >= max_items:
                    return constraints
        except Exception:
            logger.debug("Suppressed Exception in vera")
            pass

        if not user_message or not self.memory:
            return constraints

        query_tokens = set(tokenize_text(user_message))
        if not query_tokens:
            return constraints

        memory_items: List[Any] = []
        try:
            memory_items = await self.memory.retrieve(user_message, max_results=10)
        except Exception:
            logger.debug("Suppressed Exception in vera")

        try:
            memory_items.extend(self.memory.fast_network.search_buffer(user_message, max_results=5))
            memory_items.extend(self.memory.slow_network.search_long_term(user_message, max_results=5))
            archived = self.memory.archive.search(user_message, max_results=5)
            memory_items.extend([cube for cube, _score, _tier in archived])
        except Exception:
            logger.debug("Suppressed Exception in vera")

        for item in memory_items:
            if not self._memory_item_is_user_sourced(item):
                continue
            try:
                text = self.memory._extract_item_text(item)
            except Exception:
                text = str(item)
            if not text:
                continue
            if query_tokens.isdisjoint(tokenize_text(text)):
                continue
            for constraint in extract_constraints_from_text(text):
                trimmed = limit_tokens(constraint, 20)
                if trimmed and trimmed not in seen:
                    constraints.append(trimmed)
                    seen.add(trimmed)
                if len(constraints) >= max_items:
                    return constraints

        return constraints

    async def consult_quorum(self, question: str, context: str = "") -> Dict[str, Any]:
        """
        Consult multi-agent quorum for complex decisions using MoA architecture.

        Uses real LLM calls via MoAExecutor for each agent in the quorum,
        then applies the quorum's consensus algorithm to reach a decision.

        Args:
            question: The question or task to address
            context: Additional context

        Returns:
            Dict with decision, explanation, and agent contributions
        """
        # Step 1: Select optimal quorum
        quorum = self.quorum_selector.select(question, context)

        if self.config.debug:
            logger.debug(f"\n[DEBUG] Selected Quorum: {quorum.name}")
            logger.debug(f"[DEBUG] Agents: {', '.join(quorum.get_agent_names())}")
            logger.debug(f"[DEBUG] Consensus: {quorum.consensus_algorithm.value}")

        # Step 2: Execute MoA with real LLM calls
        try:
            moa_result: MoAResult = await self.moa_executor.execute(
                quorum=quorum,
                task=question,
                context=context
            )

            if self.config.debug:
                logger.debug(f"[DEBUG] MoA Decision: {moa_result.decision}")
                logger.debug(f"[DEBUG] Latency: {moa_result.total_latency_ms:.0f}ms")
                logger.debug(f"[DEBUG] Tokens: {moa_result.total_tokens}")
                for resp in moa_result.agent_responses:
                    status = f"ERROR: {resp.error}" if resp.error else f"{resp.vote.value} (Score: {resp.score})"
                    logger.debug(f"[DEBUG] {resp.agent_name}: {status}")

            # Track token costs
            if moa_result.total_tokens > 0:
                self.record_tool_cost(
                    tool_name="quorum_consultation",
                    tokens_in=moa_result.total_tokens // 2,  # Approximate split
                    tokens_out=moa_result.total_tokens // 2,
                    cached=False
                )

            # Build agent outputs dict for compatibility
            agent_outputs = {
                resp.agent_name: resp.response_text or f"[{resp.vote.value}] {resp.error or 'No response'}"
                for resp in moa_result.agent_responses
            }

            # Record in shared memory for other agents
            self.shared_memory.write(
                zone="quorum_decisions",
                key=f"decision_{int(time.time())}",
                value={
                    "question": question,
                    "quorum": quorum.name,
                    "decision": moa_result.decision,
                    "timestamp": datetime.now().isoformat(),
                    "tokens": moa_result.total_tokens,
                    "latency_ms": moa_result.total_latency_ms
                }
            )

            # Ledger write moved to _run_quorum_tool() to cover all paths
            # (named quorum, default quorum, swarm) in a single location.

            return {
                "quorum": quorum.name,
                "agents": quorum.get_agent_names(),
                "decision": moa_result.decision,
                "consensus": moa_result.consensus.algorithm,
                "explanation": moa_result.consensus.explanation,
                "aggregated_response": moa_result.aggregated_response,
                "agent_outputs": agent_outputs,
                "consensus_details": moa_result.consensus.details,
                "metadata": {
                    "tokens": moa_result.total_tokens,
                    "latency_ms": moa_result.total_latency_ms,
                    "rounds": moa_result.rounds
                }
            }

        except Exception as e:
            # Fallback to simple consensus if MoA fails
            if self.config.debug:
                logger.error(f"[DEBUG] MoA execution failed: {e}, falling back to simple consensus")

            self.health_monitor.record_error(e, "consult_quorum_moa")

            # Fallback: placeholder responses (legacy behavior)
            agent_outputs = {}
            for agent_role in quorum.agents:
                agent_name = agent_role.name
                agent_outputs[agent_name] = f"[Fallback] {agent_name} analysis unavailable"

            from quorum.consensus import parse_vote, Vote
            votes = {agent: Vote.ABSTAIN for agent in agent_outputs}
            result = self.consensus_engine.majority_vote(votes)

            return {
                "quorum": quorum.name,
                "agents": quorum.get_agent_names(),
                "decision": result.decision.value,
                "explanation": f"Fallback mode: {str(e)}",
                "agent_outputs": agent_outputs,
                "consensus_details": result.details,
                "metadata": {"fallback": True, "error": str(e)}
            }

    async def validate_command(self, command: str) -> ValidationDecision:
        """
        Validate command before execution

        Args:
            command: Command to validate

        Returns:
            ValidationDecision
        """
        decision = self.safety_validator.validate(command)

        # Log validation
        if self.config.debug:
            logger.debug(f"[DEBUG] Command validation: {decision.result.value}")
            if decision.matched_pattern:
                logger.debug(f"[DEBUG] Matched pattern: {decision.matched_pattern}")

        # Record in observability
        if self.config.observability:
            self.observability.record_event("safety_validation", result=decision.result.value)

        return decision

    @staticmethod
    def _path_within_root(candidate: str, root: str) -> bool:
        try:
            candidate_path = Path(candidate).expanduser().resolve(strict=False)
            root_path = Path(root).expanduser().resolve(strict=False)
            return os.path.commonpath([str(candidate_path), str(root_path)]) == str(root_path)
        except Exception:
            return False

    @staticmethod
    def _extract_path_hints(params: Dict[str, Any]) -> List[str]:
        hints: List[str] = []
        if not isinstance(params, dict):
            return hints

        candidate_keys = (
            "path",
            "file_path",
            "source_path",
            "destination_path",
            "from_path",
            "to_path",
            "directory",
            "dir",
        )
        for key in candidate_keys:
            value = params.get(key)
            if not isinstance(value, str):
                continue
            stripped = value.strip()
            if not stripped:
                continue
            if stripped.startswith(("/", "./", "../", "~")):
                hints.append(stripped)
        return hints

    def _server_roots(self, server_name: str) -> List[str]:
        roots: List[str] = []
        config = getattr(getattr(self, "mcp", None), "configs", {}).get(server_name)
        if config:
            if server_name == "filesystem":
                for arg in getattr(config, "args", []) or []:
                    if isinstance(arg, str) and arg.startswith("/"):
                        roots.append(arg)
            if server_name == "obsidian-vault":
                vault = (getattr(config, "env", {}) or {}).get("OBSIDIAN_VAULT_PATH")
                if vault:
                    roots.append(vault)
        if server_name == "filesystem" and not roots:
            roots.extend([str(Path.cwd()), "/tmp"])
        if server_name == "obsidian-vault" and not roots:
            vault = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
            if vault:
                roots.append(vault)
        return roots

    def _resolve_mcp_server_for_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        available: Dict[str, List[str]],
    ) -> str:
        matching_servers = [server_name for server_name, tools in available.items() if tool_name in tools]
        if not matching_servers:
            raise ValueError(f"Unknown tool: {tool_name}")
        if len(matching_servers) == 1:
            return matching_servers[0]

        preferred_server = str(params.pop("__mcp_server", "")).strip()
        if preferred_server and preferred_server in matching_servers:
            return preferred_server

        path_hints = self._extract_path_hints(params)
        if path_hints:
            if "obsidian-vault" in matching_servers:
                obsidian_roots = self._server_roots("obsidian-vault")
                for hint in path_hints:
                    if any(self._path_within_root(hint, root) for root in obsidian_roots):
                        return "obsidian-vault"
            if "filesystem" in matching_servers:
                filesystem_roots = self._server_roots("filesystem")
                for hint in path_hints:
                    if any(self._path_within_root(hint, root) for root in filesystem_roots):
                        return "filesystem"

        if "filesystem" in matching_servers and "obsidian-vault" in matching_servers:
            # Default to workspace filesystem for duplicate file tools when intent is ambiguous.
            return "filesystem"

        config_order = list((getattr(getattr(self, "mcp", None), "configs", {}) or {}).keys())
        for server_name in config_order:
            if server_name in matching_servers:
                return server_name
        return sorted(matching_servers)[0]

    async def _internal_tool_call_handler(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """
        Low-level bridge for AsyncToolExecutor.

        Routes tool calls to MCP servers. Native tools can be added here.
        """
        if tool_name in self._native_tool_handlers:
            return await self._native_tool_handlers[tool_name](tool_name, params)

        params = dict(params or {})
        available = self.mcp.get_available_tools()
        server_name = self._resolve_mcp_server_for_tool(tool_name, params, available)
        if server_name == "google-workspace":
            user_email, _workspace_authenticated = self._resolve_workspace_google_auth_context()
            supplied_email = str(params.get("user_google_email", "")).strip().lower()
            invalid_email = (
                not supplied_email
                or supplied_email.startswith("unknown")
                or supplied_email.endswith("@example.com")
                or supplied_email in {
                    "user@example.com",
                    "your.email@example.com",
                    "placeholder@example.com",
                    "unknown_user@gmail.com",
                }
            )
            if invalid_email and user_email:
                params["user_google_email"] = user_email

            if tool_name == "create_event":
                start_time = str(params.get("start_time", "")).strip()
                end_time = str(params.get("end_time", "")).strip()
                timezone_supplied = str(params.get("timezone", "")).strip()
                missing_offset = any(
                    "T" in value and not re.search(r"(Z|[+-]\d{2}:\d{2})$", value)
                    for value in (start_time, end_time)
                    if value
                )
                if missing_offset and not timezone_supplied:
                    params["timezone"] = self._resolve_workspace_timezone()

        # MCP stdio RPC is blocking; run in a worker thread so the
        # aiohttp event loop can continue serving nested HTTP callbacks
        # (e.g., call-me push APIs) during tool execution.
        timeout_override = None
        try:
            default_timeout = float(getattr(self.tool_executor, "default_timeout", 0.0) or 0.0)
            if default_timeout > 0:
                timeout_override = default_timeout
        except Exception:
            timeout_override = None
        return await asyncio.to_thread(
            self.mcp.call_tool,
            server_name,
            tool_name,
            params,
            timeout_override,
        )


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
        # Proactive execution whitelist enforcement (autonomy-only scope).
        # Keep user-requested tool calls unaffected even while an autonomous
        # workflow is running in parallel.
        whitelist = getattr(self, "_proactive_tool_whitelist", None)
        conversation_id = ""
        if isinstance(context, dict):
            conversation_id = str(context.get("conversation_id") or "").strip()
        autonomy_context = conversation_id == "autonomy" or conversation_id.startswith("autonomy:")
        if whitelist is not None and autonomy_context and tool_name not in whitelist:
            logger.info(
                "Proactive tool whitelist blocked: tool=%s conversation_id=%s",
                tool_name,
                conversation_id or "unknown",
            )
            return (
                f"Tool '{tool_name}' is not available in proactive mode. "
                "Only read-only and notification tools are permitted."
            )
        return await self.tool_orchestrator.execute_tool(
            tool_name,
            params,
            context=context,
            fallback_depth=fallback_depth,
            fallback_chain=fallback_chain,
            original_tool=original_tool,
            skip_safety=skip_safety,
        )

    async def start(self):
        """Start VERA"""
        print("=" * 60)
        print("VERA 2.0 - Personal AI Assistant")
        print("=" * 60)
        print(f"Session started: {self.session_start.isoformat()}")
        print(f"Mode: {'Autonomous' if self.config.autonomous else 'Interactive'}")
        workspace_email = self._resolve_workspace_user_email()
        if workspace_email:
            email_status = workspace_email
        else:
            email_status = "MISSING (set GOOGLE_WORKSPACE_USER_EMAIL or provide the workspace email via your configured credentials source)"
        print(f"Workspace user_google_email: {email_status}")
        if not workspace_email:
            raise RuntimeError(
                "Missing GOOGLE_WORKSPACE_USER_EMAIL (set the env var or provide the workspace email via your configured credentials source)."
            )
        print(f"Observability: {'Enabled' if self.config.observability else 'Disabled'}")
        print(f"Fault Tolerance: {'Enabled' if self.config.fault_tolerance else 'Disabled'}")
        print("-" * 60)
        print("Tier 1 Foundation Features:")
        print(f"  Panic Button: Ready (type '/stop' for emergency shutdown)")
        print(f"  Master List: {self.master_list.get_stats()['total']} tasks loaded")
        print(f"  Safe Boot: {'Active' if self.bootloader else 'Disabled'}")
        print("-" * 60)
        print("Tier 2 Trust & Safety Features:")
        print(f"  Decision Ledger: {self.decision_ledger.get_stats()['total_decisions']} decisions logged")
        print(f"  Cost Tracker: ${self.cost_tracker.get_stats()['remaining_budget']:.4f} budget remaining")
        git_status = self.git_context.get_repo_status()
        print(f"  Git Context: {git_status.branch if git_status.is_repo else 'Not a git repo'}")
        print(f"  Reversibility: {self.reversibility.get_stats()['active']} actions undoable")
        print("-" * 60)
        print("Tier 3 Productivity Features:")
        print(f"  Rabbit Hole Detector: {self.rabbit_hole.get_stats()['tasks_tracked']} tasks monitored")
        print(f"  Internal Critic: {self.critic.strictness} strictness")
        print(f"  Project Charters: {len(self.charters.list_charters())} projects")
        print(f"  Preferences: {self.preferences.get_stats()['total_preferences']} learned")
        print(f"  Deduplication: {self.deduplicator.get_stats()['total_entries']} entries indexed")
        print("-" * 60)
        print("Proactive Intelligence (Improvements #11 & #12):")
        dnd_status = self.dnd.get_status()
        sentinel_stats = self.sentinel.get_statistics()
        print(f"  Sentinel Engine: {sentinel_stats['triggers']['total']} triggers configured")
        print(f"  DND Mode: {'Active (' + dnd_status.level.value + ')' if dnd_status.is_active else 'Off'}")
        print(f"  Queued Interrupts: {self.dnd.get_queued_count()}")
        print("=" * 60 + "\n")

        self.running = True

        # Initialize multi-provider LLM registry (VERA 2.0)
        self._provider_registry = self._build_provider_registry()
        if self._provider_registry:
            reg_status = self._provider_registry.status_summary()
            print("-" * 60)
            print("LLM Provider Registry (VERA 2.0):")
            print(f"  Fallback chain: {' -> '.join(reg_status['fallback_chain'])}")
            print(f"  Registered: {', '.join(reg_status['registered']) or 'none'}")
            print(f"  Available: {', '.join(reg_status['available']) or 'none'}")
            print(f"  Active: {reg_status['active_provider'] or 'none'}")
        else:
            print("-" * 60)
            print("LLM Provider: Legacy mode (single provider)")

        # Start memory service
        await self.memory.start()

        # Start proactive systems (Sentinel + Inner Life)
        il_stats = self.proactive_manager.start()
        if il_stats:
            status = "Enabled" if il_stats["enabled"] else "Disabled"
            print(f"  Inner Life: {status} "
                  f"(interval={il_stats['interval_seconds']}s, "
                  f"reflections={il_stats['total_reflections']}, "
                  f"personality=v{il_stats['personality_version']})")
        if self.learning_loop:
            try:
                self.learning_loop.start()
                loop_stats = self.learning_loop.get_stats()
                print(
                    f"  Learning Loop: Enabled "
                    f"(daily_hour={loop_stats.get('daily_hour')}, "
                    f"templates={loop_stats.get('workflow_templates', 0)}, "
                    f"examples={loop_stats.get('example_count', 0)})"
                )
            except Exception as exc:
                logger.warning("Learning loop start failed: %s", exc)

        # Start Darwinian evolution loop (if dev_mode enabled)
        if self.darwin_enabled:
            print("🧬 [DEV MODE] Darwinian self-evolution ENABLED")
            self._darwin_task = asyncio.create_task(self._evolution_background_loop())
        else:
            print("🔒 Darwinian evolution: DISABLED (enable with dev_mode=True)")

        # Start MCP servers and health monitoring (non-blocking)
        if self.mcp.configs:
            print("-" * 60)
            print("MCP Server Orchestration:")
            mcp_stats = self.mcp.get_stats()
            print(f"  Servers: {mcp_stats['running_servers']}/{mcp_stats['configured_servers']} running")

            if os.getenv("VERA_MCP_AUTOSTART", "1") == "1":
                self._mcp_start_task = asyncio.create_task(self._start_mcp_services())
            else:
                print("  Auto-start disabled (VERA_MCP_AUTOSTART=0)")
        else:
            print("🔌 MCP: No servers configured")

        # VERA 2.0: Start channel adapters and session store
        print("-" * 60)
        print("VERA 2.0 Systems:")
        if self.hook_registry:
            print(f"  Hooks: {self.hook_registry.handler_count} handlers registered")
        if self.session_store:
            print(f"  Sessions: Active (scope={self.session_store._scope.value})")

        # Register channel adapters
        if self.channel_dock:
            try:
                from channels.loader import load_channel_adapters
                adapters = load_channel_adapters()
                for adapter in adapters:
                    try:
                        adapter.set_message_handler(
                            lambda msg, adapter_id=adapter.channel_id: self._channel_message_handler(adapter_id, msg)
                        )
                    except Exception:
                        logger.debug("Suppressed Exception in vera")
                        pass
                    self.channel_dock.register(adapter)
            except Exception as exc:
                logger.error("Failed to load channel adapters: %s", exc)

            channel_ids = self.channel_dock.list_ids()
            print(f"  Channels: {', '.join(channel_ids) if channel_ids else 'none'}")

            # Start all channel adapters
            asyncio.create_task(self.channel_dock.start_all())

        print("=" * 60 + "\n")

        # Register signal handlers with panic button
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    async def _start_mcp_services(self) -> None:
        """Start MCP servers first, then start health monitoring."""
        try:
            await asyncio.to_thread(self.mcp.start_all)
        except asyncio.CancelledError:
            self.mcp.request_shutdown()
            raise
        if not self.running:
            return
        if self._mcp_health_task and not self._mcp_health_task.done():
            return
        self._mcp_health_task = asyncio.create_task(self.mcp.async_health_monitor_loop(interval=30))

    async def _channel_message_handler(self, adapter_id: str, message) -> None:
        """Handle an inbound channel message by routing through VERA."""
        response_text = await self.handle_channel_message(message, adapter_id=adapter_id)
        if response_text and self.channel_dock:
            from channels.types import OutboundMessage
            outbound = OutboundMessage(
                text=response_text,
                target_id=message.channel_id,
                channel_id=adapter_id,
                thread_id=message.thread_id,
                reply_to_id=message.reply_to_id,
            )
            adapter = self.channel_dock.get(adapter_id)
            if adapter:
                await adapter.send(outbound)

    async def _discord_message_handler(self, message) -> None:
        """Legacy Discord handler (kept for backward compatibility)."""
        await self._channel_message_handler("discord", message)


    def _build_provider_registry(self):
        return self.llm_router.build_registry()

    async def stop(self, panic: bool = False, reason: str = "Normal shutdown"):
        """
        Stop VERA gracefully.

        Args:
            panic: If True, trigger emergency shutdown
            reason: Reason for shutdown
        """
        if panic:
            print(f"\n\n[EMERGENCY STOP] {reason}")
            # Trigger panic button for emergency cleanup
            summary = self.panic_button.panic(reason)
            print(f"[PANIC] Cleaned up: {summary.processes_killed} processes, "
                  f"{summary.temp_files_deleted} temp files, "
                  f"{summary.writes_reverted} partial writes")
        else:
            print("\n\nStopping VERA...")

        self.running = False
        if self.learning_loop:
            try:
                if hasattr(self.learning_loop, "shutdown"):
                    await self.learning_loop.shutdown(timeout_seconds=120.0)
                else:
                    self.learning_loop.stop()
            except Exception:
                logger.debug("Suppressed Exception in vera")

        # Stop MCP health monitor and servers
        self.mcp.request_shutdown()
        if self._mcp_health_task and not self._mcp_health_task.done():
            self.mcp.stop_health_monitor()
            self._mcp_health_task.cancel()
            try:
                await self._mcp_health_task
            except asyncio.CancelledError:
                logger.debug("Suppressed Exception in vera")
                pass
        if self._mcp_start_task and not self._mcp_start_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._mcp_start_task), timeout=3.0)
            except asyncio.TimeoutError:
                self._mcp_start_task.cancel()
                try:
                    await self._mcp_start_task
                except asyncio.CancelledError:
                    logger.debug("Suppressed Exception in vera")
            except asyncio.CancelledError:
                logger.debug("Suppressed Exception in vera")
                pass
        self.mcp.stop_all()
        await self._cleanup_mcp_processes()
        event_bus = getattr(self, "event_bus", None)
        if event_bus and hasattr(event_bus, "stop"):
            try:
                event_bus.stop()
            except Exception:
                logger.debug("Suppressed Exception in vera")

        # Stop Darwinian evolution loop
        if self._darwin_task and not self._darwin_task.done():
            self._darwin_task.cancel()
            try:
                await self._darwin_task
            except asyncio.CancelledError:
                logger.debug("Suppressed Exception in vera")
                pass

        # Prevent Python 3.13 loop-close hangs waiting on executor shutdown.
        loop = asyncio.get_running_loop()
        default_executor = getattr(loop, "_default_executor", None)
        if default_executor is not None:
            try:
                default_executor.shutdown(wait=False)
                loop._default_executor = None
            except Exception:
                logger.debug("Suppressed Exception in vera")

    async def _cleanup_mcp_processes(self) -> None:
        """Best-effort cleanup for any lingering MCP processes."""
        if not self.running:
            print("Excuse me while I clean things up a bit before I go.")

        script = Path(__file__).resolve().parents[3] / "scripts" / "vera_clean.sh"
        if script.exists():
            cleanup_proc = None
            try:
                cleanup_timeout_raw = os.getenv("VERA_MCP_CLEANUP_TIMEOUT_SECONDS", "20")
                cleanup_timeout = max(1.0, float(cleanup_timeout_raw))
            except (TypeError, ValueError):
                cleanup_timeout = 20.0

            try:
                cleanup_proc = await asyncio.create_subprocess_exec(str(script))
                await asyncio.wait_for(cleanup_proc.wait(), timeout=cleanup_timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "MCP cleanup script timed out after %.1fs; terminating process",
                    cleanup_timeout,
                )
                if cleanup_proc and cleanup_proc.returncode is None:
                    cleanup_proc.terminate()
                    try:
                        await asyncio.wait_for(cleanup_proc.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        cleanup_proc.kill()
                        await cleanup_proc.wait()
            except asyncio.CancelledError:
                if cleanup_proc and cleanup_proc.returncode is None:
                    cleanup_proc.terminate()
                    try:
                        await asyncio.wait_for(cleanup_proc.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        cleanup_proc.kill()
                        await cleanup_proc.wait()
                raise
            except Exception as exc:
                logger.warning("MCP cleanup script failed: %s", exc)
                # Save evolution state for next session
                self.darwin.save_state()

        # Stop proactive systems + voice session
        if hasattr(self.proactive_manager, "shutdown"):
            try:
                await self.proactive_manager.shutdown(timeout_seconds=10.0)
            except Exception:
                logger.debug("Suppressed Exception in vera")
        else:
            self.proactive_manager.stop()
        await self.voice_manager.shutdown()

        # Stop native tool bridges
        if self._browser_bridge:
            try:
                await self._browser_bridge.close()
            except Exception:
                logger.debug("Suppressed Exception in vera")
                pass
        if self._pdf_bridge:
            try:
                await self._pdf_bridge.close()
            except Exception:
                logger.debug("Suppressed Exception in vera")
                pass

        # Deliver any remaining queued interrupts
        queued = self.dnd.get_queued_count()
        deliver_queued_on_shutdown = os.getenv("VERA_DELIVER_QUEUED_ON_SHUTDOWN", "0") == "1"
        if queued > 0 and deliver_queued_on_shutdown:
            print(f"[VERA] Delivering {queued} queued interrupts before shutdown...")
            self.dnd.deliver_queued()

        # Stop memory service
        await self.memory.stop()

        # Persist tool cache
        self.cache.save_to_disk()

        # Close LLM bridge client
        if self._llm_bridge:
            await self._llm_bridge.close()

        # VERA 2.0: Stop channels and fire shutdown hook
        if self.channel_dock:
            await self.channel_dock.stop_all()

        if self.hook_registry:
            try:
                from core.hooks.types import HookEvent, HookEventType
                await self.hook_registry.trigger(HookEvent(
                    event_type=HookEventType.ON_SESSION_END,
                    context={"reason": reason, "events_processed": self.events_processed},
                ))
            except Exception:
                logger.debug("Suppressed Exception in vera")
                pass

        # Print final stats
        if self.config.observability:
            self.observability.print_stats()

        if self.session_store:
            print(f"Active sessions: {self.session_store.active_count}")

        # Save final checkpoint
        if self.config.fault_tolerance:
            await self._save_checkpoint()

        print(f"\nSession ended: {datetime.now().isoformat()}")
        print(f"Events processed: {self.events_processed}")
        print("\nGoodbye!\n")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals with panic button"""
        sig_name = signal.Signals(signum).name
        print(f"\n[SIGNAL] Received {sig_name}")
        # Use panic button for signal-triggered shutdown
        self.panic_button.panic(f"Signal received: {sig_name}", PanicReason.SIGNAL)
        asyncio.create_task(self.stop(panic=False, reason=f"Signal: {sig_name}"))

    def _get_request_workflow_hint(self, task_text: str) -> Dict[str, Any]:
        learning_loop = getattr(self, "learning_loop", None)
        if not task_text or not learning_loop or not hasattr(learning_loop, "get_workflow_plan"):
            return {}
        try:
            raw_plan = learning_loop.get_workflow_plan(task_text)
        except Exception:
            logger.debug("Suppressed Exception in vera")
            return {}
        if not isinstance(raw_plan, dict):
            return {}
        chain = raw_plan.get("tool_chain", [])
        if not isinstance(chain, list):
            return {}
        normalized_chain = [str(name).strip() for name in chain if isinstance(name, str) and str(name).strip()]
        if len(normalized_chain) < 2:
            return {}
        workflow_plan = dict(raw_plan)
        workflow_plan["tool_chain"] = normalized_chain
        return workflow_plan

    def _wire_request_workflow_hint(self, bridge: Any, task_text: str) -> None:
        if not bridge or not hasattr(bridge, "set_request_workflow_hint"):
            return
        workflow_plan = self._get_request_workflow_hint(task_text)
        try:
            bridge.set_request_workflow_hint(task_text, workflow_plan)
        except Exception:
            logger.debug("Suppressed Exception in vera")

    async def process_user_message(self, message: str) -> str:
        """
        Process user message

        Complete pipeline:
        1. Tool execution (async, filtered)
        2. Memory encoding (FastNetwork)
        3. Consolidation (SlowNetwork, background)
        4. Caching (RAGCache)
        5. Archival (3-tier)
        """
        try:
            confirmation_response = await self._handle_pending_tool_confirmation(message)
            if confirmation_response is not None:
                return confirmation_response

            # Record event
            event = {
                "type": "user_query",
                "content": message,
                "timestamp": datetime.now().isoformat()
            }

            # Encode in memory
            cube = await self.memory.process_event(event)

            # Observability
            self.observability.record_event("fast_network")

            # Heartbeat
            self.health_monitor.heartbeat()

            feedback = self._detect_feedback_score(message)
            if feedback and self.flight_recorder:
                try:
                    self.flight_recorder.record_task_feedback(
                        conversation_id="default",
                        user_message=message,
                        score=feedback["score"],
                        reason=feedback["reason"],
                    )
                except Exception:
                    logger.debug("Suppressed Exception in vera")
                    pass
            if feedback and getattr(self, "proactive_manager", None):
                try:
                    self.proactive_manager.record_user_feedback(
                        conversation_id="default",
                        score=float(feedback.get("score", 0.0)),
                        reason=str(feedback.get("reason", "")),
                    )
                except Exception:
                    logger.debug("Suppressed Exception in vera")
                    pass

            self.events_processed += 1

            if self._llm_bridge is None:
                self._llm_bridge = self.llm_router.create_bridge()

            self._wire_request_workflow_hint(self._llm_bridge, message)
            response_text = await self._llm_bridge.respond(message)
            response_text = self._postprocess_response(
                response_text,
                context={
                    "user_query": message,
                    "conversation_id": "default",
                },
            )
            self._publish_message_event(
                response_text=response_text,
                conversation_id="default",
                source="process_user_message",
            )
            return response_text

        except Exception as e:
            logger.exception(
                "process_user_message failed (message_len=%s)",
                len(message) if message is not None else 0,
            )
            self.health_monitor.record_error(e, "process_user_message")
            self.observability.metrics["errors_total"] += 1
            self._publish_error_event(
                e,
                conversation_id="default",
                source="process_user_message",
                context={"message_len": len(message) if message is not None else 0},
            )
            return f"Error: {str(e)}"

    def _normalize_conversation_id(self, conversation_id: Optional[str]) -> str:
        normalized = (conversation_id or "").strip()
        return normalized if normalized else "default"

    def _publish_message_event(
        self,
        response_text: str,
        conversation_id: Optional[str],
        channel_id: Optional[str] = None,
        source: str = "vera",
    ) -> None:
        event_bus = getattr(self, "event_bus", None)
        if not event_bus:
            return
        convo_id = self._normalize_conversation_id(conversation_id)
        idle_seconds = None
        if self.session_store:
            session = self.session_store.get(convo_id)
            if session:
                last_activity_at = session.metadata.get("last_activity_at")
                last_user_at = session.metadata.get("last_user_at")
                timestamp = None
                if isinstance(last_activity_at, (int, float)):
                    timestamp = last_activity_at
                elif isinstance(last_user_at, (int, float)):
                    timestamp = last_user_at
                if timestamp is not None:
                    idle_seconds = max(0.0, time.time() - timestamp)
        payload = {
            "conversation_id": convo_id,
            "channel_id": channel_id,
            "text": response_text,
            "idle_seconds": idle_seconds,
        }
        try:
            event_bus.publish("message.assistant", payload=payload, source=source)
        except Exception:
            logger.debug("Suppressed Exception in vera")
            pass

    def _publish_error_event(
        self,
        error: Exception,
        conversation_id: Optional[str] = None,
        source: str = "vera",
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        event_bus = getattr(self, "event_bus", None)
        if not event_bus:
            return
        payload = {
            "error": f"{type(error).__name__}: {error}",
            "conversation_id": self._normalize_conversation_id(conversation_id),
            "context": context or {},
        }
        try:
            event_bus.publish("error.message", payload=payload, source=source, priority=EventPriority.HIGH)
        except Exception:
            logger.debug("Suppressed Exception in vera")
            pass

    def _load_pending_tool_confirmations(self) -> None:
        self._pending_tool_confirmations_path.parent.mkdir(parents=True, exist_ok=True)
        data = safe_json_read(self._pending_tool_confirmations_path, default={})
        if not isinstance(data, dict):
            data = {}
        self._pending_tool_confirmations = data
        self._prune_expired_pending_tool_confirmations(persist=False)

    def _persist_pending_tool_confirmations(self) -> None:
        try:
            atomic_json_write(self._pending_tool_confirmations_path, self._pending_tool_confirmations)
        except Exception as exc:
            logger.warning("Failed to persist tool confirmations: %s", exc)

    def _record_confirmation_event(
        self,
        status: str,
        conversation_id: str,
        tool_name: str = "",
        pending_found: bool = False
    ) -> None:
        self._confirmation_events.append({
            "status": status,
            "conversation_id": conversation_id,
            "tool_name": tool_name,
            "pending_found": pending_found,
            "timestamp": datetime.now().isoformat()
        })

    def pop_confirmation_events(self) -> List[Dict[str, Any]]:
        events = list(self._confirmation_events)
        self._confirmation_events.clear()
        return events

    def _prune_expired_pending_tool_confirmations(self, persist: bool = True) -> None:
        now = time.time()
        expired = []
        for convo_id, pending in list(self._pending_tool_confirmations.items()):
            expires_at = pending.get("expires_at")
            if expires_at is not None and expires_at <= now:
                expired.append((convo_id, pending))
                del self._pending_tool_confirmations[convo_id]
        if expired and persist:
            self._persist_pending_tool_confirmations()
        for convo_id, pending in expired:
            logger.info(
                "Tool confirmation expired conversation_id=%s tool=%s",
                convo_id,
                pending.get("tool_name", "")
            )

    def _get_pending_tool_confirmation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        self._prune_expired_pending_tool_confirmations()
        return self._pending_tool_confirmations.get(conversation_id)

    def _record_untrusted_source(
        self,
        conversation_id: str,
        source_info: Dict[str, Any],
        verification: Any
    ) -> None:
        self.tool_orchestrator._record_untrusted_source(conversation_id, source_info, verification)

    def _get_recent_untrusted_sources(self, conversation_id: str) -> List[Dict[str, Any]]:
        return self.tool_orchestrator._get_recent_untrusted_sources(conversation_id)

    def _maybe_require_two_source_confirmation(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        return self.tool_orchestrator._maybe_require_two_source_confirmation(tool_name, params, context)

    def clear_pending_tool_confirmations(
        self,
        conversation_ids: List[str],
        reason: str = "ui_clear"
    ) -> int:
        self._load_pending_tool_confirmations()
        removed = 0
        for raw_id in conversation_ids:
            convo_id = self._normalize_conversation_id(raw_id)
            pending = self._pending_tool_confirmations.pop(convo_id, None)
            if pending:
                removed += 1
                logger.info(
                    "Tool confirmation cleared conversation_id=%s tool=%s reason=%s",
                    convo_id,
                    pending.get("tool_name", ""),
                    reason
                )
        if removed:
            self._persist_pending_tool_confirmations()
        return removed

    def sync_pending_tool_confirmations(
        self,
        conversation_ids: List[str],
        reason: str = "ui_sync"
    ) -> int:
        self._load_pending_tool_confirmations()
        keep = {self._normalize_conversation_id(convo_id) for convo_id in conversation_ids if convo_id is not None}
        removed = 0
        for convo_id in list(self._pending_tool_confirmations.keys()):
            if convo_id not in keep:
                pending = self._pending_tool_confirmations.pop(convo_id, None)
                if pending:
                    removed += 1
                    logger.info(
                        "Tool confirmation pruned conversation_id=%s tool=%s reason=%s",
                        convo_id,
                        pending.get("tool_name", ""),
                        reason
                    )
        if removed:
            self._persist_pending_tool_confirmations()
        return removed

    @staticmethod
    def _extract_last_assistant_text(messages: List[Dict[str, Any]]) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                return msg.get("content", "") or ""
        return ""

    @staticmethod
    def _detect_feedback_score(message: str) -> Optional[Dict[str, Any]]:
        if not message:
            return None
        lowered = message.lower()
        positive_tokens = [
            "thanks",
            "thank you",
            "appreciate",
            "perfect",
            "great",
            "awesome",
            "looks good",
            "that works",
            "works now",
            "fixed",
            "resolved",
            "all set",
            "done",
        ]
        negative_tokens = [
            "didn't work",
            "not working",
            "still broken",
            "wrong",
            "incorrect",
            "error",
            "failed",
            "fail",
            "doesn't work",
            "does not work",
            "issue",
            "bug",
            "not right",
        ]
        if any(token in lowered for token in negative_tokens):
            return {"score": -0.5, "reason": "user_negative_feedback"}
        if any(token in lowered for token in positive_tokens):
            return {"score": 1.0, "reason": "user_positive_feedback"}
        return None

    @staticmethod
    def _looks_like_confirmation_prompt(text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return any(phrase in lowered for phrase in (
            "reply 'yes' to proceed",
            "reply \"yes\" to proceed",
            "reply with 'yes' to proceed",
            "confirmation required",
            "do you want to proceed",
            "proceed? (yes/no)",
            "proceed (yes/no)",
            "proceed? (y/n)",
            "awaiting confirmation",
        ))

    async def _handle_pending_tool_confirmation(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        last_assistant_text: str = ""
    ) -> Optional[str]:
        convo_id = self._normalize_conversation_id(conversation_id)
        pending = self._get_pending_tool_confirmation(convo_id)
        if not pending and not message:
            return None

        response = (message or "").strip().lower()
        if not response:
            if pending:
                return "Awaiting confirmation. Reply 'yes' to proceed or 'no' to cancel."
            return None

        yes_tokens = {
            "yes",
            "y",
            "yep",
            "yup",
            "yeah",
            "sure",
            "ok",
            "okay",
            "go ahead",
            "send it",
            "make it so",
            "lock it in",
            "proceed",
            "commit that",
            "do it",
            "ship it",
            "confirm",
            "confirm yes",
            "yes please",
            "please proceed",
        }
        no_tokens = {
            "no",
            "n",
            "cancel",
            "stop",
            "never mind",
            "nevermind",
            "no thanks",
            "cancel it",
        }

        if response in yes_tokens:
            if not pending:
                if self._looks_like_confirmation_prompt(last_assistant_text):
                    logger.info(
                        "Confirmation response missing pending state conversation_id=%s (accepted_missing)",
                        convo_id
                    )
                    self._record_confirmation_event(
                        status="accepted_missing",
                        conversation_id=convo_id,
                        pending_found=False
                    )
                    return "No pending action to confirm. Please resend your request."
                return None
            tool_name = pending.get("tool_name", "")
            logger.info(
                "Tool confirmation accepted conversation_id=%s tool=%s",
                convo_id,
                tool_name
            )
            self._record_confirmation_event(
                status="accepted",
                conversation_id=convo_id,
                tool_name=tool_name,
                pending_found=True
            )
            self._pending_tool_confirmations.pop(convo_id, None)
            self._persist_pending_tool_confirmations()
            params = pending.get("params", {}) or {}
            context = pending.get("context", {}) or {}
            context["confirmed_by_user"] = True
            context["conversation_id"] = convo_id
            return await self.execute_tool(
                tool_name,
                params,
                context=context,
                skip_safety=True
            )

        if response in no_tokens:
            if pending:
                logger.info(
                    "Tool confirmation declined conversation_id=%s tool=%s",
                    convo_id,
                    pending.get("tool_name", "")
                )
                self._record_confirmation_event(
                    status="declined",
                    conversation_id=convo_id,
                    tool_name=pending.get("tool_name", ""),
                    pending_found=True
                )
                self._pending_tool_confirmations.pop(convo_id, None)
                self._persist_pending_tool_confirmations()
            elif self._looks_like_confirmation_prompt(last_assistant_text):
                logger.info(
                    "Confirmation response missing pending state conversation_id=%s (declined)",
                    convo_id
                )
                self._record_confirmation_event(
                    status="declined_missing",
                    conversation_id=convo_id,
                    pending_found=False
                )
            return "Understood. Cancelled."

        if pending:
            # If the user sends a substantive new request instead of yes/no,
            # treat it as a superseding turn and clear stale confirmation state.
            word_count = len(re.findall(r"\w+", response))
            if word_count >= 3:
                logger.info(
                    "Tool confirmation superseded by new user request conversation_id=%s tool=%s",
                    convo_id,
                    pending.get("tool_name", "")
                )
                self._record_confirmation_event(
                    status="superseded",
                    conversation_id=convo_id,
                    tool_name=pending.get("tool_name", ""),
                    pending_found=True
                )
                self._pending_tool_confirmations.pop(convo_id, None)
                self._persist_pending_tool_confirmations()
                return None
            return "Awaiting confirmation. Reply 'yes' to proceed or 'no' to cancel."

        return None

    async def process_messages(
        self,
        messages: List[Dict[str, Any]],
        system_override: Optional[str] = None,
        model: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        tool_choice: Optional[Any] = None,
        postprocess: bool = True
    ) -> str:
        """
        Process a full message list and generate response.

        Uses the latest user message for memory encoding and observability.
        """
        last_user = ""
        try:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    last_user = msg.get("content", "")
                    break
            last_assistant = self._extract_last_assistant_text(messages)
            if last_user:
                confirmation_response = await self._handle_pending_tool_confirmation(
                    last_user,
                    conversation_id=conversation_id,
                    last_assistant_text=last_assistant
                )
                if confirmation_response is not None:
                    return confirmation_response

            if last_user:
                event = {
                    "type": "user_query",
                    "content": last_user,
                    "timestamp": datetime.now().isoformat()
                }
                await self.memory.process_event(event)
                feedback = self._detect_feedback_score(last_user)
                if feedback and self.flight_recorder:
                    try:
                        self.flight_recorder.record_task_feedback(
                            conversation_id=self._normalize_conversation_id(conversation_id),
                            user_message=last_user,
                            score=feedback["score"],
                            reason=feedback["reason"],
                        )
                    except Exception:
                        logger.debug("Suppressed Exception in vera")
                        pass
                if feedback and getattr(self, "proactive_manager", None):
                    try:
                        self.proactive_manager.record_user_feedback(
                            conversation_id=self._normalize_conversation_id(conversation_id),
                            score=float(feedback.get("score", 0.0)),
                            reason=str(feedback.get("reason", "")),
                        )
                    except Exception:
                        logger.debug("Suppressed Exception in vera")
                        pass
                self.observability.record_event("fast_network")
                self.health_monitor.heartbeat()
                self.events_processed += 1

            if self._llm_bridge is None:
                self._llm_bridge = self.llm_router.create_bridge()

            if model:
                self._llm_bridge.model = model

            self._wire_request_workflow_hint(self._llm_bridge, last_user)
            effective_messages = messages
            if conversation_id:
                effective_messages = await self._maybe_summarize_conversation_history(
                    messages,
                    conversation_id,
                )

            response_text = await self._llm_bridge.respond_messages(
                effective_messages,
                system_override=system_override,
                persist_history=False,
                generation_config=generation_config,
                conversation_id=conversation_id,
                tool_choice_override=tool_choice,
            )
            if postprocess:
                response_text = self._postprocess_response(
                    response_text,
                    context={
                        "user_query": last_user,
                        "conversation_id": self._normalize_conversation_id(conversation_id),
                    },
                )
                self._publish_message_event(
                    response_text=response_text,
                    conversation_id=conversation_id,
                    source="process_messages",
                )
            return response_text

        except Exception as e:
            logger.exception(
                "process_messages failed (message_count=%s last_user_len=%s model_override=%s)",
                len(messages) if messages is not None else 0,
                len(last_user) if last_user is not None else 0,
                model,
            )
            self.health_monitor.record_error(e, "process_messages")
            self.observability.metrics["errors_total"] += 1
            self._publish_error_event(
                e,
                conversation_id=conversation_id,
                source="process_messages",
                context={"message_count": len(messages) if messages is not None else 0},
            )
            return f"Error: {str(e)}"

    async def _save_checkpoint(self):
        """Save system checkpoint"""
        state = {
            "session_start": self.session_start.isoformat(),
            "events_processed": self.events_processed,
            "memory_stats": self.memory.get_stats(),
            "observability": self.observability.get_stats(),
            "timestamp": datetime.now().isoformat()
        }

        self.checkpoint.save(state)

    async def run_interactive(self):
        """Run in interactive mode"""
        print("Interactive mode. Type 'quit' or 'exit' to stop, '/stop' for emergency shutdown.\n")
        print("Commands: /tasks, /projects, /prefs, /costs, /status, /voice, /help\n")

        while self.running:
            try:
                # Get user input
                user_input = input("You: ")

                # Handle empty input
                if not user_input.strip():
                    continue

                # Handle exit commands
                if user_input.lower() in ['quit', 'exit', 'bye']:
                    await self.stop(reason="User exit")
                    break

                # Handle /stop (panic button)
                if user_input.lower() == '/stop':
                    await self.stop(panic=True, reason="User requested emergency stop")
                    break

                # Handle task commands
                if user_input.startswith('/'):
                    response = await self._handle_command(user_input)
                    if response:
                        print(f"VERA: {response}\n")
                    continue

                # Process message
                response = await self.process_user_message(user_input)

                print(f"VERA: {response}\n")

                # Periodic checkpoint
                if self.config.fault_tolerance:
                    if time.time() - self.checkpoint.last_health_check > self.config.checkpoint_interval:
                        await self._save_checkpoint()

            except EOFError:
                await self.stop(reason="EOF")
                break
            except KeyboardInterrupt:
                await self.stop(reason="Keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                self.health_monitor.record_error(e, "interactive_loop")

    async def _start_voice_session(self, voice_name: str = "ara") -> str:
        """Start a voice session using the Grok Voice Agent."""
        return await self.voice_manager.start_voice_session(voice_name)

    async def _stop_voice_session(self) -> str:
        """Stop the active voice session."""
        return await self.voice_manager.stop_voice_session()

    def _voice_status(self) -> str:
        """Return a concise voice status line."""
        return self.voice_manager.voice_status()

    def _handle_voice_transcript(self, role: str, text: str) -> None:
        """Print voice transcripts to the console."""
        self.voice_manager.handle_voice_transcript(role, text)


    async def _handle_command(self, command: str) -> str:
        return await self.command_handler.handle_command(command)

    async def run_autonomous(self):
        """Run in autonomous mode"""
        print("Autonomous mode. Press Ctrl+C to stop.\n")

        cycle = 0

        while self.running:
            try:
                cycle += 1

                print(f"[Cycle {cycle}] Running...")

                # Simulate autonomous work
                await asyncio.sleep(10)

                # Heartbeat
                self.health_monitor.heartbeat()

                # Periodic checkpoint
                if cycle % 10 == 0:
                    await self._save_checkpoint()

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                self.health_monitor.record_error(e, "autonomous_loop")

    # === Tier 2 Helper Methods ===

    def log_decision(
        self,
        decision_type: DecisionType,
        action: str,
        reasoning: str,
        alternatives: list = None,
        confidence: float = 0.8,
        context: dict = None
    ) -> str:
        """Log a decision to the decision ledger."""
        return self.safety_manager.log_decision(
            decision_type=decision_type,
            action=action,
            reasoning=reasoning,
            alternatives=alternatives,
            confidence=confidence,
            context=context,
        )

    def record_tool_cost(
        self,
        tool_name: str,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cached: bool = False
    ) -> dict:
        """Record tool usage cost."""
        return self.safety_manager.record_tool_cost(
            tool_name=tool_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached=cached,
        )

    def track_file_operation(
        self,
        filepath: Path,
        operation: str = "write"
    ) -> str:
        """Track a file operation for potential reversal."""
        return self.safety_manager.track_file_operation(filepath, operation=operation)

    def stamp_source(
        self,
        source_type: Any,
        source_id: str,
        content: str,
        confidence: float = 0.9
    ) -> str:
        """Stamp information with provenance."""
        return self.safety_manager.stamp_source(
            source_type=source_type,
            source_id=source_id,
            content=content,
            confidence=confidence,
        )

    # === Tier 3 Helper Methods ===

    def check_spiral(
        self,
        action_type: str,
        target: str,
        task_id: str = None
    ) -> SpiralStatus:
        """
        Check if an action would indicate spiraling behavior.

        Returns SpiralStatus with detection results.
        """
        return self.rabbit_hole.check_action(
            action_type=action_type,
            target=target,
            context={"task_id": task_id or "unknown"}
        )

    def critique_response(
        self,
        response: str,
        context: dict = None
    ) -> Any:
        """Self-critique a response before sending."""
        return self.safety_manager.critique_response(response, context or {})

    def _postprocess_response(
        self,
        response: str,
        context: dict = None
    ) -> str:
        """Run internal post-processing on a response before delivery."""
        return self.safety_manager.postprocess_response(response, context or {})

    def learn_preference(
        self,
        original: str,
        correction: str,
        context: dict = None
    ) -> list:
        """
        Learn preferences from a user correction.

        Returns list of preferences learned.
        """
        learned = self.preferences.learn_from_correction(
            original=original,
            correction=correction,
            context=context or {}
        )
        try:
            self.preferences.refresh_core_identity_promotions(
                threshold=float(os.getenv("VERA_PREF_PROMOTION_THRESHOLD", "0.9"))
            )
        except Exception:
            logger.debug("Suppressed Exception in vera")
        return learned

    def apply_preferences(self, response: str) -> str:
        """
        Apply learned preferences to a response.

        Returns modified response.
        """
        return self.preferences.apply_to_response(response)

    def check_duplicate(self, content: str) -> dict:
        """
        Check if content is duplicate before storing.

        Returns dict with is_duplicate, similarity info.
        """
        result = self.deduplicator.check(content)
        return result.to_dict()

    def create_project(
        self,
        title: str,
        goal: str,
        approach: str,
        success_criteria: list,
        auto_approve: bool = False
    ) -> ProjectCharter:
        """
        Create a new project charter.

        Returns the created charter.
        """
        return self.charters.create_charter(
            title=title,
            goal=goal,
            approach=approach,
            success_criteria=success_criteria,
            auto_approve=auto_approve
        )
