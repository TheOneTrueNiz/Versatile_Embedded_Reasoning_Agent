"""
Proactive Manager
=================

Encapsulates DND, Sentinel Engine, and Inner Life bindings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from context.dnd_mode import DNDManager, DNDLevel, InterruptUrgency
from core.atomic_io import atomic_json_write, safe_json_read
from core.foundation.master_list import TaskPriority, TaskStatus
from core.services.red_team_harness import run_red_team
from observability.self_improvement_budget import (
    SelfImprovementBudget,
    estimate_cost,
    estimate_tokens,
)
from planning.sentinel_engine import (
    ActionPriority,
    EventPattern,
    EventSource,
    EventType,
    FileSystemAdapter,
    RecommendedAction,
    SentinelEngine,
    TimerAdapter,
    TriggerCondition,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_iso_utc(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


class ProactiveManager:
    """Proactive intelligence extracted from VERA."""

    def __init__(self, owner: Any, memory_dir: Path) -> None:
        self._owner = owner
        self._memory_dir = Path(memory_dir)
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self.dnd = DNDManager(memory_dir=memory_dir)
        owner.dnd = self.dnd

        self.sentinel = SentinelEngine(storage_dir=str(memory_dir / "sentinel"))
        owner.sentinel = self.sentinel

        self._pending_proactive_actions: list = []
        owner._pending_proactive_actions = self._pending_proactive_actions

        self.inner_life = self._init_inner_life(memory_dir)
        owner.inner_life = self.inner_life

        self._red_team_state_path = self._memory_dir / "red_team_state.json"
        self._red_team_running = False

        self._autonomy_state_path = self._memory_dir / "autonomy_cadence_state.json"
        self._autonomy_event_log = self._memory_dir / "autonomy_cadence_events.jsonl"
        self._autonomy_config = self._load_autonomy_config()
        self._autonomy_cycle_running = False
        self._autonomy_cycle_future = None
        self._scheduled_futures: Set[Any] = set()
        self._stopping = False
        self._budget_guard = SelfImprovementBudget()
        self._initiative_state_path = self._memory_dir / "initiative_tuning_state.json"
        self._initiative_event_log = self._memory_dir / "initiative_tuning_events.jsonl"
        self._initiative_config = self._load_initiative_tuning_config()
        self._initiative_state = self._load_initiative_state()

        self.apply_startup_dnd()
        self.setup_sentinel_triggers()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner, name)

    def _init_inner_life(self, memory_dir: Path):
        from planning.inner_life_engine import InnerLifeEngine, InnerLifeConfig

        inner_life_config = InnerLifeConfig.from_env()
        try:
            genome_path = Path(os.getenv("VERA_GENOME_CONFIG_PATH", "config/vera_genome.json"))
            if genome_path.exists():
                genome_data = json.loads(genome_path.read_text())
            else:
                genome_data = {}
            genome_il = genome_data.get("inner_life", {})
            if genome_il:
                inner_life_config = InnerLifeConfig.from_dict(genome_il)
        except Exception:
            pass

        return InnerLifeEngine(
            config=inner_life_config,
            storage_dir=memory_dir / "personality",
        )

    def _load_autonomy_config(self) -> Dict[str, Any]:
        def _env_int(name: str, fallback: int) -> int:
            raw = os.getenv(name, "").strip()
            if not raw:
                return fallback
            try:
                return int(raw)
            except Exception:
                return fallback

        def _env_bool(name: str, fallback: bool) -> bool:
            raw = os.getenv(name, "").strip().lower()
            if not raw:
                return fallback
            return raw not in {"0", "false", "off", "no"}

        config: Dict[str, Any] = {
            "enabled": _env_bool("VERA_AUTONOMY_CADENCE_ENABLED", True),
            "pulse_interval_seconds": _env_int("VERA_AUTONOMY_PULSE_INTERVAL_SECONDS", 300),
            "active_minutes": _env_int("VERA_AUTONOMY_ACTIVE_MINUTES", 15),
            "idle_minutes": _env_int("VERA_AUTONOMY_IDLE_MINUTES", 45),
            "max_reflections_per_active_window": _env_int("VERA_AUTONOMY_MAX_REFLECTIONS_PER_WINDOW", 1),
            "max_workflows_per_active_window": _env_int("VERA_AUTONOMY_MAX_WORKFLOWS_PER_WINDOW", 1),
            "task_due_minutes": _env_int("VERA_AUTONOMY_TASK_DUE_MINUTES", 120),
            "followthrough_enabled": _env_bool("VERA_AUTONOMY_FOLLOWTHROUGH_ENABLED", True),
            "followthrough_cooldown_seconds": _env_int("VERA_AUTONOMY_FOLLOWTHROUGH_COOLDOWN_SECONDS", 900),
            "base_url": os.getenv("VERA_BASE_URL", "http://127.0.0.1:8788"),
        }
        try:
            genome_path = Path(os.getenv("VERA_GENOME_CONFIG_PATH", "config/vera_genome.json"))
            if genome_path.exists():
                genome_data = json.loads(genome_path.read_text(encoding="utf-8"))
                genome_autonomy = genome_data.get("autonomy_cadence", {})
                if isinstance(genome_autonomy, dict):
                    config.update({k: v for k, v in genome_autonomy.items() if v is not None})
        except Exception:
            logger.debug("Suppressed Exception in proactive_manager")

        def _coerce_bool(value: Any, fallback: bool) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() not in {"0", "false", "off", "no", ""}
            if isinstance(value, (int, float)):
                return value != 0
            return fallback

        def _coerce_int(value: Any, fallback: int, min_value: int) -> int:
            try:
                parsed = int(value)
            except Exception:
                parsed = fallback
            return max(min_value, parsed)

        config["enabled"] = _coerce_bool(config.get("enabled"), True)
        config["pulse_interval_seconds"] = _coerce_int(config.get("pulse_interval_seconds"), 300, 30)
        config["active_minutes"] = _coerce_int(config.get("active_minutes"), 15, 1)
        config["idle_minutes"] = _coerce_int(config.get("idle_minutes"), 45, 0)
        config["max_reflections_per_active_window"] = _coerce_int(
            config.get("max_reflections_per_active_window"), 1, 0
        )
        config["max_workflows_per_active_window"] = _coerce_int(
            config.get("max_workflows_per_active_window"), 1, 0
        )
        config["task_due_minutes"] = _coerce_int(config.get("task_due_minutes"), 120, 5)
        config["followthrough_enabled"] = _coerce_bool(config.get("followthrough_enabled"), True)
        config["followthrough_cooldown_seconds"] = _coerce_int(
            config.get("followthrough_cooldown_seconds"), 900, 60
        )
        config["base_url"] = str(config.get("base_url") or "http://127.0.0.1:8788").strip()
        return config

    def _default_autonomy_state(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "anchor_utc": _utc_iso(),
            "window_index": 0,
            "phase": "active",
            "phase_started_utc": _utc_iso(),
            "active_window_reflections": 0,
            "active_window_workflows": 0,
            "last_followthrough_utc": "",
            "last_cycle_utc": "",
            "last_cycle_result": {},
            "updated_at_utc": _utc_iso(),
        }

    def _load_autonomy_state(self) -> Dict[str, Any]:
        payload = safe_json_read(self._autonomy_state_path, default={}) or {}
        if not isinstance(payload, dict) or not payload:
            return self._default_autonomy_state()
        baseline = self._default_autonomy_state()
        baseline.update(payload)
        return baseline

    def _save_autonomy_state(self, state: Dict[str, Any]) -> None:
        state["updated_at_utc"] = _utc_iso()
        self._autonomy_state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(self._autonomy_state_path, state)

    def _append_autonomy_event(self, event: Dict[str, Any]) -> None:
        self._autonomy_event_log.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts_utc": _utc_iso(), **event}
        with self._autonomy_event_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _load_initiative_tuning_config(self) -> Dict[str, Any]:
        def _env_int(name: str, fallback: int) -> int:
            raw = os.getenv(name, "").strip()
            if not raw:
                return fallback
            try:
                return int(raw)
            except Exception:
                return fallback

        def _env_float(name: str, fallback: float) -> float:
            raw = os.getenv(name, "").strip()
            if not raw:
                return fallback
            try:
                return float(raw)
            except Exception:
                return fallback

        def _env_bool(name: str, fallback: bool) -> bool:
            raw = os.getenv(name, "").strip().lower()
            if not raw:
                return fallback
            return raw not in {"0", "false", "off", "no"}

        config: Dict[str, Any] = {
            "enabled": _env_bool("VERA_INITIATIVE_TUNING_ENABLED", True),
            "initial_score": _env_float("VERA_INITIATIVE_INITIAL_SCORE", 0.55),
            "min_score": _env_float("VERA_INITIATIVE_MIN_SCORE", 0.20),
            "max_score": _env_float("VERA_INITIATIVE_MAX_SCORE", 0.90),
            "normal_min_score": _env_float("VERA_INITIATIVE_NORMAL_MIN_SCORE", 0.30),
            "low_min_score": _env_float("VERA_INITIATIVE_LOW_MIN_SCORE", 0.45),
            "background_min_score": _env_float("VERA_INITIATIVE_BACKGROUND_MIN_SCORE", 0.55),
            "action_success_step": _env_float("VERA_INITIATIVE_ACTION_SUCCESS_STEP", 0.015),
            "action_failure_step": _env_float("VERA_INITIATIVE_ACTION_FAILURE_STEP", 0.050),
            "positive_feedback_step": _env_float("VERA_INITIATIVE_POSITIVE_FEEDBACK_STEP", 0.050),
            "negative_feedback_step": _env_float("VERA_INITIATIVE_NEGATIVE_FEEDBACK_STEP", 0.090),
            "feedback_window_seconds": _env_int("VERA_INITIATIVE_FEEDBACK_WINDOW_SECONDS", 1800),
            "max_action_memory": _env_int("VERA_INITIATIVE_MAX_ACTION_MEMORY", 40),
            "repeat_action_success_cooldown_seconds": _env_int(
                "VERA_INITIATIVE_REPEAT_ACTION_SUCCESS_COOLDOWN_SECONDS",
                240,
            ),
            "repeat_action_failure_cooldown_seconds": _env_int(
                "VERA_INITIATIVE_REPEAT_ACTION_FAILURE_COOLDOWN_SECONDS",
                120,
            ),
            "partner_recent_activity_gate_minutes": _env_int(
                "VERA_INITIATIVE_PARTNER_RECENT_ACTIVITY_GATE_MINUTES",
                2,
            ),
            "type_base_cooldown_seconds": _env_int(
                "VERA_INITIATIVE_TYPE_BASE_COOLDOWN_SECONDS",
                300,
            ),
            "type_max_cooldown_seconds": _env_int(
                "VERA_INITIATIVE_TYPE_MAX_COOLDOWN_SECONDS",
                14400,
            ),
            "type_backoff_factor": _env_float(
                "VERA_INITIATIVE_TYPE_BACKOFF_FACTOR",
                2.0,
            ),
            "type_feedback_penalty_floor": _env_int(
                "VERA_INITIATIVE_TYPE_FEEDBACK_PENALTY_FLOOR",
                3,
            ),
            "type_noop_streak_threshold": _env_int(
                "VERA_INITIATIVE_TYPE_NOOP_STREAK_THRESHOLD",
                5,
            ),
        }
        try:
            genome_path = Path(os.getenv("VERA_GENOME_CONFIG_PATH", "config/vera_genome.json"))
            if genome_path.exists():
                genome_data = json.loads(genome_path.read_text(encoding="utf-8"))
                genome_tuning = genome_data.get("initiative_tuning", {})
                if isinstance(genome_tuning, dict):
                    config.update({k: v for k, v in genome_tuning.items() if v is not None})
        except Exception:
            logger.debug("Suppressed Exception in proactive_manager")

        def _coerce_bool(value: Any, fallback: bool) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() not in {"0", "false", "off", "no", ""}
            if isinstance(value, (int, float)):
                return value != 0
            return fallback

        def _coerce_float(value: Any, fallback: float) -> float:
            try:
                return float(value)
            except Exception:
                return fallback

        def _coerce_int(value: Any, fallback: int, min_value: int) -> int:
            try:
                parsed = int(value)
            except Exception:
                parsed = fallback
            return max(min_value, parsed)

        config["enabled"] = _coerce_bool(config.get("enabled"), True)
        config["min_score"] = min(1.0, max(0.0, _coerce_float(config.get("min_score"), 0.20)))
        config["max_score"] = min(1.0, max(config["min_score"], _coerce_float(config.get("max_score"), 0.90)))
        config["initial_score"] = min(
            config["max_score"],
            max(config["min_score"], _coerce_float(config.get("initial_score"), 0.55)),
        )
        config["normal_min_score"] = min(
            config["max_score"],
            max(config["min_score"], _coerce_float(config.get("normal_min_score"), 0.30)),
        )
        config["low_min_score"] = min(
            config["max_score"],
            max(config["normal_min_score"], _coerce_float(config.get("low_min_score"), 0.45)),
        )
        config["background_min_score"] = min(
            config["max_score"],
            max(config["low_min_score"], _coerce_float(config.get("background_min_score"), 0.55)),
        )
        config["action_success_step"] = min(0.25, max(0.0, _coerce_float(config.get("action_success_step"), 0.015)))
        config["action_failure_step"] = min(0.50, max(0.0, _coerce_float(config.get("action_failure_step"), 0.050)))
        config["positive_feedback_step"] = min(
            0.50,
            max(0.0, _coerce_float(config.get("positive_feedback_step"), 0.050)),
        )
        config["negative_feedback_step"] = min(
            0.60,
            max(0.0, _coerce_float(config.get("negative_feedback_step"), 0.090)),
        )
        config["feedback_window_seconds"] = _coerce_int(config.get("feedback_window_seconds"), 1800, 60)
        config["max_action_memory"] = _coerce_int(config.get("max_action_memory"), 40, 5)
        config["repeat_action_success_cooldown_seconds"] = _coerce_int(
            config.get("repeat_action_success_cooldown_seconds"),
            240,
            0,
        )
        config["repeat_action_failure_cooldown_seconds"] = _coerce_int(
            config.get("repeat_action_failure_cooldown_seconds"),
            120,
            0,
        )
        config["partner_recent_activity_gate_minutes"] = _coerce_int(
            config.get("partner_recent_activity_gate_minutes"),
            2,
            0,
        )
        config["type_base_cooldown_seconds"] = _coerce_int(
            config.get("type_base_cooldown_seconds"), 300, 10,
        )
        config["type_max_cooldown_seconds"] = _coerce_int(
            config.get("type_max_cooldown_seconds"), 14400, 60,
        )
        config["type_backoff_factor"] = min(
            10.0, max(1.1, _coerce_float(config.get("type_backoff_factor"), 2.0))
        )
        config["type_feedback_penalty_floor"] = _coerce_int(
            config.get("type_feedback_penalty_floor"), 3, 1,
        )
        config["type_noop_streak_threshold"] = _coerce_int(
            config.get("type_noop_streak_threshold"), 5, 2,
        )
        return config

    @staticmethod
    def _safe_memory_dir(default_path: str = "vera_memory") -> Path:
        try:
            return Path(default_path)
        except Exception:
            return Path("vera_memory")

    @staticmethod
    def _local_attr(instance: Any, name: str, default: Any = None) -> Any:
        try:
            return object.__getattribute__(instance, name)
        except Exception:
            return default

    def _ensure_initiative_runtime(self) -> Dict[str, Any]:
        memory_dir = self._local_attr(self, "_memory_dir", None) or self._safe_memory_dir()
        if not isinstance(memory_dir, Path):
            memory_dir = Path(memory_dir)
        if self._local_attr(self, "_initiative_state_path", None) is None:
            self._initiative_state_path = memory_dir / "initiative_tuning_state.json"
        if self._local_attr(self, "_initiative_event_log", None) is None:
            self._initiative_event_log = memory_dir / "initiative_tuning_events.jsonl"
        if not isinstance(self._local_attr(self, "_initiative_config", None), dict):
            self._initiative_config = self._load_initiative_tuning_config()
        if not isinstance(self._local_attr(self, "_initiative_state", None), dict):
            self._initiative_state = self._load_initiative_state()
        return self._initiative_state

    def _default_initiative_state(self) -> Dict[str, Any]:
        cfg = self._local_attr(self, "_initiative_config", {}) or {}
        initial_score = float(cfg.get("initial_score", 0.55) or 0.55)
        return {
            "version": 2,
            "initiative_score": initial_score,
            "last_update_utc": _utc_iso(),
            "last_signal": {},
            "positive_feedback_count": 0,
            "negative_feedback_count": 0,
            "action_success_count": 0,
            "action_failure_count": 0,
            "suppressed_count": 0,
            "recent_actions": [],
            "action_type_stats": {},
        }

    @staticmethod
    def _default_action_type_stat() -> Dict[str, Any]:
        return {
            "consecutive_failures": 0,
            "consecutive_noops": 0,
            "cooldown_until_utc": None,
            "total_successes": 0,
            "total_failures": 0,
            "total_noops": 0,
            "last_attempt_utc": None,
            "last_outcome": None,
        }

    def _load_initiative_state(self) -> Dict[str, Any]:
        state_path = self._local_attr(self, "_initiative_state_path", None)
        if not isinstance(state_path, Path):
            state_path = self._safe_memory_dir() / "initiative_tuning_state.json"
            self._initiative_state_path = state_path
        if not isinstance(self._local_attr(self, "_initiative_config", None), dict):
            self._initiative_config = self._load_initiative_tuning_config()

        payload = safe_json_read(state_path, default={}) or {}
        if not isinstance(payload, dict) or not payload:
            return self._default_initiative_state()
        baseline = self._default_initiative_state()
        baseline.update(payload)
        baseline["initiative_score"] = self._clamp_initiative_score(baseline.get("initiative_score"))
        if not isinstance(baseline.get("recent_actions"), list):
            baseline["recent_actions"] = []
        # v1 → v2 migration: bootstrap action_type_stats from recent_actions
        if "action_type_stats" not in payload:
            baseline["action_type_stats"] = {}
            for row in baseline.get("recent_actions", []):
                if not isinstance(row, dict):
                    continue
                atype = str(row.get("action_type") or "").strip()
                if not atype:
                    continue
                if atype not in baseline["action_type_stats"]:
                    baseline["action_type_stats"][atype] = self._default_action_type_stat()
                stat = baseline["action_type_stats"][atype]
                was_success = bool(row.get("success"))
                stat["last_attempt_utc"] = str(row.get("ts_utc") or "")
                stat["last_outcome"] = "success" if was_success else "failure"
                if was_success:
                    stat["total_successes"] = int(stat.get("total_successes", 0)) + 1
                    stat["consecutive_failures"] = 0
                    stat["consecutive_noops"] = 0
                else:
                    stat["total_failures"] = int(stat.get("total_failures", 0)) + 1
                    stat["consecutive_failures"] = int(stat.get("consecutive_failures", 0)) + 1
            baseline["version"] = 2
        return baseline

    def _save_initiative_state(self, state: Dict[str, Any]) -> None:
        self._ensure_initiative_runtime()
        state["last_update_utc"] = _utc_iso()
        self._initiative_state = state
        self._initiative_state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(self._initiative_state_path, state)

    def _append_initiative_event(self, event: Dict[str, Any]) -> None:
        self._ensure_initiative_runtime()
        self._initiative_event_log.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts_utc": _utc_iso(), **event}
        with self._initiative_event_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _clamp_initiative_score(self, value: Any) -> float:
        cfg = self._local_attr(self, "_initiative_config", None)
        if not isinstance(cfg, dict):
            cfg = {
                "min_score": 0.20,
                "max_score": 0.90,
                "initial_score": 0.55,
            }
        min_score = float(cfg.get("min_score", 0.20))
        max_score = float(cfg.get("max_score", 0.90))
        try:
            parsed = float(value)
        except Exception:
            parsed = float(cfg.get("initial_score", 0.55))
        return min(max_score, max(min_score, parsed))

    def _required_score_for_priority(self, priority: ActionPriority) -> float:
        self._ensure_initiative_runtime()
        if priority == ActionPriority.BACKGROUND:
            return float(self._initiative_config.get("background_min_score", 0.55))
        if priority == ActionPriority.LOW:
            return float(self._initiative_config.get("low_min_score", 0.45))
        if priority == ActionPriority.NORMAL:
            return float(self._initiative_config.get("normal_min_score", 0.30))
        return float(self._initiative_config.get("min_score", 0.20))

    def _current_mood(self) -> str:
        inner_life = self._local_attr(self, "inner_life", None)
        personality = getattr(inner_life, "personality", None) if inner_life else None
        mood = str(getattr(personality, "current_mood", "") or "").strip().lower()
        return mood or "steady"

    @staticmethod
    def _initiative_threshold_delta_for_mood(mood: str) -> float:
        lowered = str(mood or "").strip().lower()
        if lowered == "strained":
            return 0.12
        if lowered == "cautious":
            return 0.08
        if lowered == "attentive":
            return 0.04
        if lowered == "focused":
            return 0.02
        if lowered == "energized":
            return -0.05
        if lowered in {"encouraged", "warm"}:
            return -0.03
        return 0.0

    def _compute_type_cooldown_seconds(self, consecutive_failures: int) -> float:
        """Compute exponential backoff cooldown for a given failure count."""
        if consecutive_failures <= 0:
            return 0.0
        base = float(self._initiative_config.get("type_base_cooldown_seconds", 300))
        factor = float(self._initiative_config.get("type_backoff_factor", 2.0))
        cap = float(self._initiative_config.get("type_max_cooldown_seconds", 14400))
        raw = base * (factor ** (consecutive_failures - 1))
        return min(raw, cap)

    @staticmethod
    def _cooldown_multiplier_for_mood(mood: str) -> float:
        """Convert mood into a cooldown duration multiplier.

        Anxious/strained moods make cooldowns longer (more cautious).
        Energized/warm moods shorten cooldowns (more willing to try).
        """
        lowered = str(mood or "").strip().lower()
        if lowered == "strained":
            return 1.50
        if lowered == "cautious":
            return 1.35
        if lowered == "attentive":
            return 1.15
        if lowered == "focused":
            return 1.05
        if lowered == "energized":
            return 0.75
        if lowered in {"encouraged", "warm"}:
            return 0.85
        return 1.0

    def _is_action_type_on_cooldown(self, action_type: str) -> Tuple[bool, str]:
        """Check if a specific action type is currently on cooldown."""
        state = self._ensure_initiative_runtime()
        stats = state.get("action_type_stats", {})
        type_stat = stats.get(action_type)
        if not isinstance(type_stat, dict):
            return False, ""
        cooldown_until = _parse_iso_utc(str(type_stat.get("cooldown_until_utc") or ""))
        if cooldown_until is None:
            return False, ""
        now = _utc_now()
        if now >= cooldown_until:
            return False, ""
        remaining = (cooldown_until - now).total_seconds()
        return True, (
            f"action_type_cooldown:{action_type};"
            f"remaining={int(remaining)}s;"
            f"until={type_stat['cooldown_until_utc']}"
        )

    def _is_internal_cadence_action(self, action_type: str) -> bool:
        return str(action_type or "").strip() in self.INTERNAL_DND_BYPASS_ACTIONS

    def _should_execute_recommendation(self, recommendation: RecommendedAction) -> Tuple[bool, str]:
        state = self._ensure_initiative_runtime()
        if not bool(self._initiative_config.get("enabled", True)):
            return True, "initiative_tuning_disabled"
        if recommendation.priority in {ActionPriority.HIGH, ActionPriority.URGENT}:
            return True, "priority_override"

        action_type = str(recommendation.action_type or "").strip()
        if self._is_internal_cadence_action(action_type):
            return True, "internal_cadence_bypass"

        # Per-type cooldown gate (replaces global score gate)
        on_cooldown, cooldown_reason = self._is_action_type_on_cooldown(action_type)
        if on_cooldown:
            return False, cooldown_reason

        # Global score: computed for observability, no longer gates execution
        score = self._clamp_initiative_score(state.get("initiative_score"))
        mood = self._current_mood()
        mood_delta = self._initiative_threshold_delta_for_mood(mood)
        score_info = (
            f"initiative_score_observed:{score:.3f}"
            f";mood={mood};delta={mood_delta:+.3f}"
        )

        # Partner activity gate (unchanged)
        partner_activity_gate_minutes = int(self._initiative_config.get("partner_recent_activity_gate_minutes", 0))
        if (
            recommendation.priority in {ActionPriority.BACKGROUND, ActionPriority.LOW}
            and partner_activity_gate_minutes > 0
        ):
            minutes_since_activity = self._minutes_since_last_partner_activity()
            if (
                minutes_since_activity is not None
                and minutes_since_activity < float(partner_activity_gate_minutes)
            ):
                return False, (
                    f"partner_recently_active:{minutes_since_activity:.1f}m<"
                    f"{partner_activity_gate_minutes}m"
                )

        # Duplicate action cooldown (unchanged)
        duplicated, duplicate_reason = self._is_duplicate_recent_action(recommendation)
        if duplicated:
            return False, duplicate_reason

        return True, f"allowed;{score_info}"

    def _minutes_since_last_partner_activity(self) -> Optional[float]:
        session_store = self._local_attr(self, "session_store", None)
        if session_store is None:
            return None
        try:
            sessions = session_store.list_sessions()
        except Exception:
            return None

        now_epoch = datetime.now(timezone.utc).timestamp()
        latest_epoch: Optional[float] = None
        for session in sessions:
            if not isinstance(session, dict):
                continue
            raw_last_active = session.get("last_active")
            if not isinstance(raw_last_active, (int, float)):
                continue
            epoch = float(raw_last_active)
            if epoch <= 0:
                continue
            if latest_epoch is None or epoch > latest_epoch:
                latest_epoch = epoch
        if latest_epoch is None:
            return None
        return max(0.0, (now_epoch - latest_epoch) / 60.0)

    @staticmethod
    def _extract_recommendation_conversation_id(recommendation: RecommendedAction) -> str:
        payload = recommendation.payload if isinstance(recommendation.payload, dict) else {}
        for key in ("conversation_id", "vera_conversation_id", "session_key"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        events = payload.get("events")
        if isinstance(events, list):
            for item in events:
                if not isinstance(item, dict):
                    continue
                event_payload = item.get("payload")
                if not isinstance(event_payload, dict):
                    continue
                for key in ("conversation_id", "vera_conversation_id", "session_key"):
                    value = str(event_payload.get(key) or "").strip()
                    if value:
                        return value
        return ""

    def _is_duplicate_recent_action(self, recommendation: RecommendedAction) -> Tuple[bool, str]:
        state = self._ensure_initiative_runtime()
        recent = list(state.get("recent_actions") or [])
        if not recent:
            return False, ""

        now_utc = _utc_now()
        recommendation_conversation_id = self._extract_recommendation_conversation_id(recommendation)
        action_type = str(recommendation.action_type or "").strip()
        trigger_id = str(recommendation.trigger_id or "").strip()
        if not action_type:
            return False, ""
        if self._is_internal_cadence_action(action_type):
            return False, ""

        for row in reversed(recent):
            if not isinstance(row, dict):
                continue
            if str(row.get("action_type") or "").strip() != action_type:
                continue

            row_trigger_id = str(row.get("trigger_id") or "").strip()
            if trigger_id and row_trigger_id and trigger_id != row_trigger_id:
                continue

            row_conversation_id = str(row.get("conversation_id") or "").strip()
            if (
                recommendation_conversation_id
                and row_conversation_id
                and recommendation_conversation_id != row_conversation_id
            ):
                continue

            ts = _parse_iso_utc(str(row.get("ts_utc") or ""))
            if ts is None:
                continue
            age_seconds = (now_utc - ts).total_seconds()
            if age_seconds < 0:
                continue

            was_success = bool(row.get("success"))
            if was_success:
                cooldown = int(self._initiative_config.get("repeat_action_success_cooldown_seconds", 240))
                if cooldown <= 0 or age_seconds >= cooldown:
                    continue
                return True, (
                    f"duplicate_action_success_cooldown:{action_type};"
                    f"age={int(age_seconds)}s<{cooldown}s"
                )

            cooldown = int(self._initiative_config.get("repeat_action_failure_cooldown_seconds", 120))
            if cooldown <= 0 or age_seconds >= cooldown:
                continue
            return True, (
                f"duplicate_action_failure_cooldown:{action_type};"
                f"age={int(age_seconds)}s<{cooldown}s"
            )
        return False, ""

    def _apply_initiative_signal(
        self,
        signal_type: str,
        delta: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = self._ensure_initiative_runtime()
        before = self._clamp_initiative_score(state.get("initiative_score"))
        after = self._clamp_initiative_score(before + float(delta))
        state["initiative_score"] = after
        state["last_signal"] = {
            "type": signal_type,
            "delta": round(float(delta), 4),
            "before": round(before, 4),
            "after": round(after, 4),
            "context": context or {},
            "at": _utc_iso(),
        }
        if signal_type == "feedback_positive":
            state["positive_feedback_count"] = int(state.get("positive_feedback_count", 0)) + 1
        elif signal_type == "feedback_negative":
            state["negative_feedback_count"] = int(state.get("negative_feedback_count", 0)) + 1
        elif signal_type == "action_success":
            state["action_success_count"] = int(state.get("action_success_count", 0)) + 1
        elif signal_type == "action_failure":
            state["action_failure_count"] = int(state.get("action_failure_count", 0)) + 1
        self._save_initiative_state(state)
        self._append_initiative_event({
            "type": "initiative_signal",
            "signal_type": signal_type,
            "delta": round(float(delta), 4),
            "before": round(before, 4),
            "after": round(after, 4),
            "context": context or {},
        })
        return dict(state["last_signal"])

    def _record_recent_proactive_action(
        self,
        recommendation: RecommendedAction,
        success: bool,
        result: Any,
    ) -> None:
        state = self._ensure_initiative_runtime()
        payload = recommendation.payload if isinstance(recommendation.payload, dict) else {}
        raw_conversation_id = payload.get("conversation_id") or payload.get("vera_conversation_id") or ""
        conversation_id = str(raw_conversation_id).strip()
        action_row = {
            "ts_utc": _utc_iso(),
            "action_id": recommendation.action_id,
            "trigger_id": recommendation.trigger_id,
            "action_type": recommendation.action_type,
            "priority": recommendation.priority.name,
            "conversation_id": conversation_id,
            "success": bool(success),
            "result_preview": str(result)[:120] if result is not None else "",
        }
        recent = list(state.get("recent_actions") or [])
        recent.append(action_row)
        limit = int(self._initiative_config.get("max_action_memory", 40))
        if len(recent) > limit:
            recent = recent[-limit:]
        state["recent_actions"] = recent
        self._save_initiative_state(state)
        self._append_initiative_event({
            "type": "proactive_action_recorded",
            "action_type": recommendation.action_type,
            "priority": recommendation.priority.name,
            "success": bool(success),
            "conversation_id": conversation_id,
        })

    def _update_action_type_stats(
        self,
        action_type: str,
        outcome: str,
        mood: Optional[str] = None,
    ) -> None:
        """Update per-type stats and compute cooldown after action execution."""
        state = self._ensure_initiative_runtime()
        stats = state.get("action_type_stats")
        if not isinstance(stats, dict):
            stats = {}
            state["action_type_stats"] = stats

        atype = str(action_type or "").strip()
        if not atype:
            return

        if atype not in stats:
            stats[atype] = self._default_action_type_stat()
        ts = stats[atype]

        ts["last_attempt_utc"] = _utc_iso()
        ts["last_outcome"] = outcome

        # Internal cadence actions (for example autonomy_cycle) must run on
        # schedule and should never self-throttle via initiative cooldown gates.
        if self._is_internal_cadence_action(atype):
            if outcome == "action_failure":
                ts["total_failures"] = int(ts.get("total_failures", 0)) + 1
            elif outcome == "action_success":
                ts["total_successes"] = int(ts.get("total_successes", 0)) + 1
            elif outcome in ("action_success_noop", "action_success_skipped", "action_success_not_due"):
                ts["total_noops"] = int(ts.get("total_noops", 0)) + 1
            ts["consecutive_failures"] = 0
            ts["consecutive_noops"] = 0
            ts["cooldown_until_utc"] = None
            self._save_initiative_state(state)
            self._append_initiative_event({
                "type": "action_type_stats_updated",
                "action_type": atype,
                "outcome": outcome,
                "consecutive_failures": ts["consecutive_failures"],
                "consecutive_noops": ts["consecutive_noops"],
                "cooldown_until_utc": ts.get("cooldown_until_utc"),
                "cooldown_bypassed": True,
            })
            return

        if outcome == "action_success":
            ts["consecutive_failures"] = 0
            ts["consecutive_noops"] = 0
            ts["cooldown_until_utc"] = None
            ts["total_successes"] = int(ts.get("total_successes", 0)) + 1

        elif outcome == "action_failure":
            ts["consecutive_failures"] = int(ts.get("consecutive_failures", 0)) + 1
            ts["total_failures"] = int(ts.get("total_failures", 0)) + 1
            cooldown_secs = self._compute_type_cooldown_seconds(ts["consecutive_failures"])
            if mood is None:
                mood = self._current_mood()
            multiplier = self._cooldown_multiplier_for_mood(mood)
            effective_secs = cooldown_secs * multiplier
            ts["cooldown_until_utc"] = (
                _utc_now() + timedelta(seconds=effective_secs)
            ).isoformat().replace("+00:00", "Z")

        elif outcome in ("action_success_noop", "action_success_skipped", "action_success_not_due"):
            ts["consecutive_noops"] = int(ts.get("consecutive_noops", 0)) + 1
            ts["total_noops"] = int(ts.get("total_noops", 0)) + 1
            noop_threshold = int(self._initiative_config.get("type_noop_streak_threshold", 5))
            if ts["consecutive_noops"] >= noop_threshold:
                base = float(self._initiative_config.get("type_base_cooldown_seconds", 300))
                if mood is None:
                    mood = self._current_mood()
                multiplier = self._cooldown_multiplier_for_mood(mood)
                ts["cooldown_until_utc"] = (
                    _utc_now() + timedelta(seconds=base * multiplier)
                ).isoformat().replace("+00:00", "Z")
                ts["consecutive_noops"] = 0

        self._save_initiative_state(state)
        self._append_initiative_event({
            "type": "action_type_stats_updated",
            "action_type": atype,
            "outcome": outcome,
            "consecutive_failures": ts["consecutive_failures"],
            "consecutive_noops": ts["consecutive_noops"],
            "cooldown_until_utc": ts.get("cooldown_until_utc"),
        })

    def _is_feedback_linked_to_recent_action(
        self,
        conversation_id: str,
        now: Optional[datetime] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        state = self._ensure_initiative_runtime()
        now_utc = now or _utc_now()
        window_seconds = int(self._initiative_config.get("feedback_window_seconds", 1800))
        recent = list(state.get("recent_actions") or [])
        if not recent:
            return False, {}

        convo_id = str(conversation_id or "").strip()
        latest_in_window: Dict[str, Any] = {}
        for row in reversed(recent):
            ts = _parse_iso_utc(str(row.get("ts_utc") or ""))
            if ts is None:
                continue
            age = (now_utc - ts).total_seconds()
            if age < 0:
                continue
            if age > window_seconds:
                continue
            latest_in_window = row
            action_convo = str(row.get("conversation_id") or "").strip()
            if convo_id and action_convo and convo_id == action_convo:
                return True, row

        if latest_in_window:
            return True, latest_in_window
        return False, {}

    def record_user_feedback(
        self,
        conversation_id: Optional[str],
        score: float,
        reason: str = "",
    ) -> Dict[str, Any]:
        state = self._ensure_initiative_runtime()
        if not bool(self._initiative_config.get("enabled", True)):
            return {"applied": False, "reason": "initiative_tuning_disabled"}

        linked, action_row = self._is_feedback_linked_to_recent_action(str(conversation_id or "").strip())
        if not linked:
            return {"applied": False, "reason": "no_recent_proactive_action"}

        numeric_score = float(score)
        if numeric_score > 0:
            delta = float(self._initiative_config.get("positive_feedback_step", 0.050))
            signal = "feedback_positive"
        elif numeric_score < 0:
            delta = -float(self._initiative_config.get("negative_feedback_step", 0.090))
            signal = "feedback_negative"
        else:
            return {"applied": False, "reason": "neutral_feedback"}

        signal_payload = self._apply_initiative_signal(
            signal_type=signal,
            delta=delta,
            context={
                "conversation_id": str(conversation_id or ""),
                "score": round(numeric_score, 3),
                "reason": str(reason or "")[:120],
                "related_action_type": action_row.get("action_type", ""),
            },
        )

        # Per-type cooldown effects from feedback
        related_action_type = str(action_row.get("action_type") or "").strip()
        if related_action_type:
            stats = state.get("action_type_stats")
            if not isinstance(stats, dict):
                stats = {}
                state["action_type_stats"] = stats
            if related_action_type not in stats:
                stats[related_action_type] = self._default_action_type_stat()

            if numeric_score > 0:
                # Positive feedback: clear cooldowns for ALL action types
                for atype_stat in stats.values():
                    atype_stat["cooldown_until_utc"] = None
                    atype_stat["consecutive_failures"] = 0
                    atype_stat["consecutive_noops"] = 0
                self._save_initiative_state(state)
                self._append_initiative_event({
                    "type": "feedback_cleared_all_cooldowns",
                    "trigger_action_type": related_action_type,
                })
            elif numeric_score < 0:
                # Negative feedback: penalize THIS action type only
                ts = stats[related_action_type]
                penalty_floor = int(self._initiative_config.get("type_feedback_penalty_floor", 3))
                ts["consecutive_failures"] = max(
                    int(ts.get("consecutive_failures", 0)),
                    penalty_floor,
                )
                cooldown_secs = self._compute_type_cooldown_seconds(ts["consecutive_failures"])
                mood = self._current_mood()
                multiplier = self._cooldown_multiplier_for_mood(mood)
                effective_secs = cooldown_secs * multiplier
                ts["cooldown_until_utc"] = (
                    _utc_now() + timedelta(seconds=effective_secs)
                ).isoformat().replace("+00:00", "Z")
                self._save_initiative_state(state)
                self._append_initiative_event({
                    "type": "feedback_penalized_action_type",
                    "action_type": related_action_type,
                    "consecutive_failures": ts["consecutive_failures"],
                    "cooldown_until_utc": ts["cooldown_until_utc"],
                })

        return {
            "applied": True,
            "signal": signal,
            "initiative_score": signal_payload.get("after"),
            "related_action": action_row,
        }

    def _evaluate_action_reward_signal(
        self,
        recommendation: RecommendedAction,
        success: bool,
        result: Any,
    ) -> Tuple[float, str]:
        if not bool(success):
            penalty = -float(self._initiative_config.get("action_failure_step", 0.050))
            return penalty, "action_failure"

        if recommendation.action_type == "check_tasks":
            overdue_count = int((result or {}).get("overdue_count", 0)) if isinstance(result, dict) else 0
            if overdue_count <= 0:
                return 0.0, "action_success_noop"
        if isinstance(result, dict):
            if result.get("skipped") is True:
                return 0.0, "action_success_skipped"
            if result.get("ran") is False:
                return 0.0, "action_success_not_due"
        reward = float(self._initiative_config.get("action_success_step", 0.015))
        return reward, "action_success"

    def get_initiative_tuning_status(self) -> Dict[str, Any]:
        state = self._ensure_initiative_runtime()
        mood = self._current_mood()
        mood_delta = self._initiative_threshold_delta_for_mood(mood)
        return {
            "config": dict(self._initiative_config),
            "initiative_score": self._clamp_initiative_score(state.get("initiative_score")),
            "current_mood": mood,
            "mood_threshold_delta": mood_delta,
            "last_signal": state.get("last_signal", {}),
            "positive_feedback_count": int(state.get("positive_feedback_count", 0)),
            "negative_feedback_count": int(state.get("negative_feedback_count", 0)),
            "action_success_count": int(state.get("action_success_count", 0)),
            "action_failure_count": int(state.get("action_failure_count", 0)),
            "suppressed_count": int(state.get("suppressed_count", 0)),
            "recent_actions": list(state.get("recent_actions", [])[-10:]),
            "action_type_stats": dict(state.get("action_type_stats", {})),
        }

    def _compute_cadence_phase(self, state: Dict[str, Any]) -> Tuple[str, int, int]:
        active_seconds = max(60, int(self._autonomy_config["active_minutes"]) * 60)
        idle_seconds = max(0, int(self._autonomy_config["idle_minutes"]) * 60)
        cycle_seconds = active_seconds + idle_seconds
        now = _utc_now()
        anchor = _parse_iso_utc(str(state.get("anchor_utc") or "")) or now
        if cycle_seconds <= 0:
            return "active", 0, 0
        elapsed = max(0.0, (now - anchor).total_seconds())
        window_index = int(elapsed // cycle_seconds)
        offset = int(elapsed % cycle_seconds)
        if idle_seconds <= 0:
            return "active", window_index, max(1, active_seconds - offset)
        if offset < active_seconds:
            return "active", window_index, max(1, active_seconds - offset)
        return "idle", window_index, max(1, cycle_seconds - offset)

    def _schedule_coroutine(self, coro):
        if self._stopping:
            try:
                coro.close()
            except Exception:
                logger.debug("Suppressed Exception in proactive_manager")
            return None
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if self._loop is None and running_loop is not None:
            self._loop = running_loop
        if not self._loop or self._loop.is_closed():
            try:
                coro.close()
            except Exception:
                logger.debug("Suppressed Exception in proactive_manager")
            return None
        if running_loop and running_loop is self._loop:
            task = self._loop.create_task(coro)
            self._track_scheduled_future(task)
            return task
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            self._track_scheduled_future(future)
            return future
        except Exception:
            try:
                coro.close()
            except Exception:
                logger.debug("Suppressed Exception in proactive_manager")
            logger.debug("Suppressed Exception in proactive_manager")
            return None

    def _track_scheduled_future(self, future: Any) -> None:
        if future is None:
            return
        self._scheduled_futures.add(future)
        try:
            future.add_done_callback(lambda done: self._scheduled_futures.discard(done))
        except Exception:
            logger.debug("Suppressed Exception in proactive_manager")

    def _can_spend(self, category: str, estimated_tokens: int) -> Tuple[bool, str]:
        return self._budget_guard.check(
            category=category,
            estimated_tokens=max(1, int(estimated_tokens)),
            estimated_cost=estimate_cost(max(1, estimated_tokens // 2), max(1, estimated_tokens // 2)),
            calls=1,
        )

    def _record_estimated_usage(self, category: str, text_in: str, text_out: str) -> None:
        tokens_in = estimate_tokens(text_in)
        tokens_out = estimate_tokens(text_out)
        self._budget_guard.record_usage(
            category=category,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=estimate_cost(tokens_in, tokens_out),
            calls=1,
        )

    def _derive_task_title(self, action_text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(action_text or "").strip())
        if not cleaned:
            return "Autonomy task"
        sentence = re.split(r"[.!?\n]", cleaned)[0].strip()
        if len(sentence) > 96:
            sentence = sentence[:93].rstrip() + "..."
        return sentence or "Autonomy task"

    def _infer_due_from_action(self, action_text: str) -> datetime:
        now = datetime.now()
        text = str(action_text or "").lower()
        due = now + timedelta(minutes=int(self._autonomy_config.get("task_due_minutes", 120)))
        if "tomorrow" in text:
            due = due + timedelta(days=1)
        match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            if hour <= 23 and minute <= 59:
                candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if candidate <= now:
                    candidate += timedelta(days=1)
                due = candidate
        return due

    async def _run_followthrough_executor_once(self) -> Dict[str, Any]:
        root = Path(__file__).resolve().parents[3]
        script = root / "scripts" / "vera_followthrough_executor.py"
        if not script.exists():
            return {"ok": False, "reason": "missing_followthrough_executor"}
        python_bin = root / ".venv" / "bin" / "python"
        if not python_bin.exists():
            python_bin = Path("python3")
        cmd = [
            str(python_bin),
            str(script),
            "--vera-root",
            str(root),
            "--base-url",
            str(self._autonomy_config.get("base_url") or "http://127.0.0.1:8788"),
            "--max-runs-per-pass",
            "1",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(root),
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=900)
            except asyncio.TimeoutError:
                if proc.returncode is None:
                    proc.kill()
                    stdout, stderr = await proc.communicate()
                else:
                    stdout = b""
                    stderr = b""
                return {
                    "ok": False,
                    "reason": "timeout",
                    "returncode": int(proc.returncode if proc.returncode is not None else -9),
                    "stdout": (stdout.decode(errors="replace") if isinstance(stdout, (bytes, bytearray)) else str(stdout or ""))[:500],
                    "stderr": (stderr.decode(errors="replace") if isinstance(stderr, (bytes, bytearray)) else str(stderr or ""))[:500],
                }
            except asyncio.CancelledError:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                raise
            return {
                "ok": proc.returncode == 0,
                "returncode": int(proc.returncode),
                "stdout": (stdout.decode(errors="replace") if isinstance(stdout, (bytes, bytearray)) else str(stdout or ""))[:500],
                "stderr": (stderr.decode(errors="replace") if isinstance(stderr, (bytes, bytearray)) else str(stderr or ""))[:500],
            }
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    async def _execute_inner_action_workflow(self, action_text: str, run_id: str) -> Dict[str, Any]:
        if not action_text.strip():
            return {"ok": False, "reason": "empty_action_text"}
        title = self._derive_task_title(action_text)
        due = self._infer_due_from_action(action_text)
        task = self.master_list.add_task(
            title=title,
            priority=TaskPriority.HIGH,
            description=action_text[:800],
            due=due,
            tags=["inner-life", "autonomy", "workflow"],
            notes=f"Generated by inner life run {run_id}",
        )
        self.master_list.update_status(task.id, TaskStatus.IN_PROGRESS, notes="Autonomy workflow execution started")

        execution_prompt = (
            "You initiated this ACTION during inner life reflection:\n"
            f"{action_text}\n\n"
            "Execute it now using available tools when appropriate. "
            "If blocked by missing auth/permissions or requiring user confirmation, respond with "
            "`BLOCKED:` then reason. If completed, respond with `COMPLETED:` then concise summary."
        )

        allowed, reason = self._can_spend("autonomy_workflow", self.inner_life.config.max_tokens_per_turn)
        if not allowed:
            self.master_list.update_status(task.id, TaskStatus.BLOCKED, notes=f"Budget guard: {reason}")
            return {"ok": False, "task_id": task.id, "reason": f"budget_guard:{reason}"}

        try:
            response_text = await self._owner.process_messages(
                messages=[{"role": "user", "content": execution_prompt}],
                conversation_id=f"autonomy:{run_id}:{task.id}",
            )
        except Exception as exc:
            self.master_list.update_status(task.id, TaskStatus.BLOCKED, notes=f"Workflow execution error: {exc}")
            return {"ok": False, "task_id": task.id, "reason": str(exc)}

        self._record_estimated_usage("autonomy_workflow", execution_prompt, response_text or "")
        response_lower = str(response_text or "").lower()
        if response_lower.startswith("blocked:") or "requires user" in response_lower or "need user" in response_lower:
            self.master_list.update_status(task.id, TaskStatus.BLOCKED, notes=(response_text or "")[:1200])
            status = "blocked"
        else:
            self.master_list.update_status(task.id, TaskStatus.COMPLETED, notes=(response_text or "")[:1200])
            status = "completed"

        if getattr(self, "decision_ledger", None):
            try:
                self.decision_ledger.log_decision(
                    decision_type="autonomous_action",
                    action=f"Autonomy workflow task {task.id} -> {status}",
                    reasoning=(response_text or "")[:500],
                    confidence=0.7,
                    context={"task_id": task.id, "run_id": run_id},
                )
            except Exception:
                logger.debug("Suppressed Exception in proactive_manager")

        return {"ok": True, "task_id": task.id, "status": status, "response_preview": (response_text or "")[:280]}

    # -----------------------------------------------------------------
    # Calendar Proactive Check
    # -----------------------------------------------------------------

    PROACTIVE_SAFE_TOOLS = frozenset({
        # Time/info
        "time", "calculate", "sequentialthinking",
        # Search (read-only)
        "search_wikipedia", "searxng_search", "brave_web_search",
        # Memory (read-only)
        "read_graph", "search_nodes",
        # Calendar (read-only)
        "get_events", "list_calendars",
        # Notifications (outbound to owner only)
        "send_native_push", "send_mobile_push",
        # Filesystem (read-only)
        "list_allowed_directories", "read_file",
    })
    # Internal cadence/maintenance actions should continue even during DND.
    INTERNAL_DND_BYPASS_ACTIONS = frozenset({
        "autonomy_cycle",
    })

    async def _check_calendar_proactive(self) -> Optional[Dict[str, Any]]:
        """Poll Google Calendar for upcoming events and alert if near."""
        # Default-on for out-of-box proactive reliability; operators can disable with VERA_CALENDAR_PROACTIVE=0.
        if os.getenv("VERA_CALENDAR_PROACTIVE", "1") != "1":
            return None

        # Rate limit: skip if polled < 30 min ago
        state_path = self._memory_dir / "calendar_alerts_state.json"
        state = safe_json_read(state_path, default={})
        last_poll = _parse_iso_utc(str(state.get("last_poll_utc") or ""))
        now_utc = _utc_now()
        if last_poll and (now_utc - last_poll).total_seconds() < 1800:
            return {"ok": True, "skipped": True, "reason": "cooldown_active"}

        # Clear expired alerted event IDs daily
        expiry = _parse_iso_utc(str(state.get("alerted_event_ids_expiry") or ""))
        if not expiry or now_utc > expiry:
            state["alerted_event_ids"] = []
            state["alerted_event_ids_expiry"] = (
                now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1)
            ).isoformat().replace("+00:00", "Z")

        alerted_ids = set(state.get("alerted_event_ids") or [])
        lookahead = int(os.getenv("VERA_CALENDAR_LOOKAHEAD_MINUTES", "120"))
        alert_minutes = int(os.getenv("VERA_CALENDAR_ALERT_MINUTES", "15"))

        # Use process_messages to call get_events via the LLM
        time_max = (now_utc + timedelta(minutes=lookahead)).strftime("%Y-%m-%dT%H:%M:%SZ")
        calendar_prompt = (
            f"Check my calendar for events in the next {lookahead} minutes "
            f"(up to {time_max}). Use the get_events tool with time_max='{time_max}' "
            f"and max_results=10 and detailed=true. "
            f"Return a JSON array of events with fields: id, summary, start_time (ISO), "
            f"end_time (ISO), location. If no events, return an empty array []."
        )

        try:
            response_text = await self._owner.process_messages(
                messages=[{"role": "user", "content": calendar_prompt}],
                conversation_id="autonomy:calendar_check",
            )
        except Exception as exc:
            logger.debug("Calendar proactive check error: %s", exc)
            return {"ok": False, "reason": "calendar_tool_unavailable", "error": str(exc)}

        # Update poll timestamp
        state["last_poll_utc"] = _utc_iso()

        # Try to parse events from the response for near-term alerts
        alerts_sent = []
        try:
            # Extract JSON array from response
            text = str(response_text or "")
            import re as _re
            json_match = _re.search(r"\[.*\]", text, _re.DOTALL)
            if json_match:
                events = json.loads(json_match.group())
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    event_id = str(event.get("id") or event.get("summary") or "")
                    if event_id in alerted_ids:
                        continue
                    start_str = str(event.get("start_time") or event.get("start") or "")
                    start_dt = _parse_iso_utc(start_str)
                    if start_dt and (start_dt - now_utc).total_seconds() <= alert_minutes * 60:
                        summary = event.get("summary", "Upcoming event")
                        minutes_away = max(0, int((start_dt - now_utc).total_seconds() / 60))
                        alert_msg = f"Reminder: '{summary}' starts in {minutes_away} minutes."
                        location = event.get("location")
                        if location:
                            alert_msg += f" Location: {location}"

                        # Send notification via push
                        try:
                            await self._owner.process_messages(
                                messages=[{"role": "user", "content": f"Send a push notification to my human: {alert_msg}"}],
                                conversation_id="autonomy:calendar_alert",
                            )
                        except Exception:
                            logger.debug("Calendar alert delivery failed for: %s", summary)

                        alerted_ids.add(event_id)
                        alerts_sent.append({"event_id": event_id, "summary": summary, "minutes_away": minutes_away})
        except (json.JSONDecodeError, ValueError):
            logger.debug("Could not parse calendar events from response")

        state["alerted_event_ids"] = list(alerted_ids)
        atomic_json_write(state_path, state)

        bus = getattr(self._owner, "event_bus", None)
        if bus:
            try:
                bus.publish("innerlife.calendar_check", payload={
                    "alerts_sent": len(alerts_sent),
                    "events_checked": True,
                    "skipped": False,
                }, source="proactive_manager")
            except Exception:
                logger.debug("Failed to publish calendar_check event")

        return {
            "ok": True,
            "alerts_sent": alerts_sent,
            "events_checked": True,
        }

    # -----------------------------------------------------------------
    # Sentinel Recommendation Processing (Proactive Execution)
    # -----------------------------------------------------------------

    async def _process_sentinel_recommendations(self) -> Optional[Dict[str, Any]]:
        """Check sentinel for pending recommendations and execute high-priority safe ones."""
        # Default-on for out-of-box proactive reliability; operators can disable with VERA_PROACTIVE_EXECUTION=0.
        if os.getenv("VERA_PROACTIVE_EXECUTION", "1") != "1":
            return None

        # Respect DND
        if hasattr(self, "dnd") and not self.dnd.can_interrupt(InterruptUrgency.HIGH):
            return {"skipped": True, "reason": "dnd_active"}

        pending = self.sentinel.recommender.get_pending_recommendations()
        if not pending:
            return {"processed": 0, "pending": 0}

        max_per_cycle = int(os.getenv("VERA_PROACTIVE_MAX_PER_CYCLE", "3"))
        executed = []
        notified = []
        logged = []

        for rec in pending[: max_per_cycle * 2]:
            if rec.priority in (ActionPriority.URGENT, ActionPriority.HIGH):
                # AUTO-EXECUTE via _execute_inner_action_workflow
                # Set proactive tool whitelist on owner to constrain tool selection
                try:
                    self._owner._proactive_tool_whitelist = self.PROACTIVE_SAFE_TOOLS
                    result = await self._execute_inner_action_workflow(
                        action_text=rec.description,
                        run_id=f"sentinel:{rec.action_id}",
                    )
                finally:
                    self._owner._proactive_tool_whitelist = None
                self.sentinel.recommender.mark_executed(rec.action_id)

                # Log to decision ledger
                if getattr(self, "decision_ledger", None):
                    try:
                        self.decision_ledger.log_decision(
                            decision_type="PROACTIVE_EXECUTION",
                            action=rec.description[:300],
                            reasoning=f"Auto-executed sentinel recommendation {rec.action_id} (priority={rec.priority.name})",
                            confidence=0.7,
                            context={"action_id": rec.action_id, "priority": rec.priority.name},
                        )
                    except Exception:
                        logger.debug("Suppressed decision ledger error in proactive execution")

                executed.append({"action_id": rec.action_id, "result": result})

            elif rec.priority == ActionPriority.NORMAL:
                # NOTIFY via push or compose message
                try:
                    await self._owner.process_messages(
                        messages=[{"role": "user", "content": (
                            f"Send a push notification about this pending recommendation: "
                            f"{rec.description[:300]}"
                        )}],
                        conversation_id=f"autonomy:sentinel_notify:{rec.action_id}",
                    )
                except Exception:
                    logger.debug("Sentinel notification delivery failed for: %s", rec.action_id)
                self.sentinel.recommender.acknowledge(rec.action_id)
                notified.append(rec.action_id)

            else:  # LOW, BACKGROUND
                # LOG only
                self.sentinel.recommender.acknowledge(rec.action_id)
                logged.append(rec.action_id)

            if len(executed) >= max_per_cycle:
                break

        bus = getattr(self._owner, "event_bus", None)
        if bus:
            try:
                bus.publish("innerlife.proactive_execution", payload={
                    "processed": len(executed) + len(notified) + len(logged),
                    "executed": len(executed),
                    "notified": len(notified),
                    "logged": len(logged),
                }, source="proactive_manager")
            except Exception:
                logger.debug("Failed to publish proactive_execution event")

        return {
            "processed": len(executed) + len(notified) + len(logged),
            "executed": executed,
            "notified": notified,
            "logged": logged,
            "pending_remaining": max(0, len(pending) - len(executed) - len(notified) - len(logged)),
        }

    async def _run_autonomy_cycle_async(self, trigger: str = "sentinel", force: bool = False) -> Dict[str, Any]:
        if self._autonomy_cycle_running:
            return {"scheduled": False, "skipped": True, "reason": "cycle_already_running"}
        self._autonomy_cycle_running = True
        try:
            state = self._load_autonomy_state()
            phase, window_index, seconds_until_transition = self._compute_cadence_phase(state)
            previous_window = int(state.get("window_index") or 0)
            if window_index != previous_window:
                state["active_window_reflections"] = 0
                state["active_window_workflows"] = 0
            state["window_index"] = window_index
            state["phase"] = phase
            state["phase_started_utc"] = _utc_iso()

            result: Dict[str, Any] = {
                "scheduled": True,
                "trigger": trigger,
                "force": bool(force),
                "phase": phase,
                "window_index": window_index,
                "seconds_until_transition": seconds_until_transition,
            }
            if not bool(self._autonomy_config.get("enabled", True)):
                result["skipped"] = True
                result["reason"] = "autonomy_cadence_disabled"
                state["last_cycle_result"] = result
                state["last_cycle_utc"] = _utc_iso()
                self._save_autonomy_state(state)
                self._append_autonomy_event({"type": "autonomy_cycle_skipped", **result})
                return result
            if phase != "active" and not force:
                result["skipped"] = True
                result["reason"] = "idle_window"
                state["last_cycle_result"] = result
                state["last_cycle_utc"] = _utc_iso()
                self._save_autonomy_state(state)
                self._append_autonomy_event({"type": "autonomy_cycle_idle", **result})
                return result
            if phase != "active" and force:
                result["phase_override"] = "forced_active_override"

            reflection_result = None
            reflection_reason = "reflection_not_attempted"
            reflections_used = int(state.get("active_window_reflections") or 0)
            if reflections_used < int(self._autonomy_config.get("max_reflections_per_active_window", 1)):
                allowed, reason = self._can_spend("inner_life_reflection", self.inner_life.config.max_tokens_per_turn)
                if allowed:
                    reflection_result = await self.run_reflection_cycle(trigger="autonomy_cycle", force=bool(force))
                    state["active_window_reflections"] = reflections_used + 1
                    if reflection_result and getattr(reflection_result, "entries", None):
                        text_out = "\n".join(entry.thought for entry in reflection_result.entries if getattr(entry, "thought", ""))
                        self._record_estimated_usage("inner_life_reflection", "autonomy_cycle_reflection", text_out)
                    reflection_reason = "reflection_executed"
                else:
                    reflection_reason = f"budget_guard:{reason}"
            else:
                reflection_reason = "reflection_window_cap_reached"

            workflow_result: Dict[str, Any] = {"ok": False, "reason": "workflow_not_attempted"}
            workflows_used = int(state.get("active_window_workflows") or 0)
            if (
                reflection_result
                and getattr(reflection_result, "outcome", "") == "action"
                and workflows_used < int(self._autonomy_config.get("max_workflows_per_active_window", 1))
            ):
                last_entry = reflection_result.entries[-1] if reflection_result.entries else None
                action_text = str(getattr(last_entry, "thought", "") or "")
                workflow_result = await self._execute_inner_action_workflow(
                    action_text=action_text,
                    run_id=getattr(reflection_result, "run_id", "autonomy"),
                )
                state["active_window_workflows"] = workflows_used + 1
            elif reflection_result and getattr(reflection_result, "outcome", "") == "action":
                workflow_result = {"ok": False, "reason": "workflow_window_cap_reached"}

            followthrough_result: Dict[str, Any] = {
                "ok": False,
                "reason": "followthrough_disabled",
                "attempted": False,
            }
            if bool(self._autonomy_config.get("followthrough_enabled", True)):
                last_follow = _parse_iso_utc(str(state.get("last_followthrough_utc") or ""))
                cooldown_seconds = int(self._autonomy_config.get("followthrough_cooldown_seconds", 900))
                now_utc = _utc_now()
                seconds_since_last_follow = (
                    (now_utc - last_follow).total_seconds() if last_follow is not None else None
                )
                cooldown_ok = (
                    last_follow is None
                    or (seconds_since_last_follow is not None and seconds_since_last_follow >= cooldown_seconds)
                )
                if cooldown_ok:
                    followthrough_result = await self._run_followthrough_executor_once()
                    if not isinstance(followthrough_result, dict):
                        followthrough_result = {"ok": False, "reason": "invalid_followthrough_result"}
                    followthrough_result["attempted"] = True
                    followthrough_result["cooldown_seconds"] = cooldown_seconds
                    followthrough_result["seconds_since_last_followthrough"] = (
                        round(seconds_since_last_follow, 3)
                        if seconds_since_last_follow is not None
                        else None
                    )
                    followthrough_result["cooldown_remaining_seconds"] = 0
                    if followthrough_result.get("ok"):
                        state["last_followthrough_utc"] = _utc_iso()
                else:
                    cooldown_remaining = max(
                        0,
                        cooldown_seconds - int(seconds_since_last_follow or 0),
                    )
                    followthrough_result = {
                        "ok": False,
                        "reason": "followthrough_cooldown_active",
                        "attempted": False,
                        "cooldown_seconds": cooldown_seconds,
                        "seconds_since_last_followthrough": (
                            round(seconds_since_last_follow, 3)
                            if seconds_since_last_follow is not None
                            else None
                        ),
                        "cooldown_remaining_seconds": int(cooldown_remaining),
                    }

            # --- Calendar proactive check ---
            calendar_result: Optional[dict] = None
            try:
                calendar_result = await self._check_calendar_proactive()
            except Exception as exc:
                logger.debug("Calendar proactive check error: %s", exc)

            # --- Sentinel recommendation processing ---
            sentinel_result: Optional[dict] = None
            try:
                sentinel_result = await self._process_sentinel_recommendations()
            except Exception as exc:
                logger.debug("Sentinel recommendation processing error: %s", exc)

            # --- Self-improvement auto-trigger (red-team) ---
            self_improvement_result: Optional[dict] = None
            if os.getenv("VERA_SELF_IMPROVEMENT_AUTO", "0") == "1":
                try:
                    rt_state = self.load_red_team_state()
                    last_run_at = rt_state.get("last_run_at", "")
                    hours_since = 999.0
                    if last_run_at:
                        try:
                            last_dt = datetime.fromisoformat(last_run_at)
                            if last_dt.tzinfo is None:
                                last_dt = last_dt.replace(tzinfo=timezone.utc)
                            hours_since = (
                                datetime.now(timezone.utc) - last_dt
                            ).total_seconds() / 3600
                        except Exception:
                            pass
                    min_hours = float(os.getenv("VERA_SELF_IMPROVEMENT_INTERVAL_HOURS", "12"))
                    if hours_since >= min_hours and not self._red_team_running:
                        logger.info(
                            "Self-improvement auto-trigger: %.1fh since last red-team run (threshold %.0fh)",
                            hours_since, min_hours,
                        )
                        loop = asyncio.get_running_loop()
                        self_improvement_result = await loop.run_in_executor(
                            None, self.action_red_team, {},
                        )
                    else:
                        self_improvement_result = {
                            "ran": False,
                            "reason": "not_due" if hours_since < min_hours else "already_running",
                            "hours_since_last": round(hours_since, 1),
                        }
                except Exception as exc:
                    logger.debug("Self-improvement auto-trigger error: %s", exc)
                    self_improvement_result = {"ran": False, "reason": "error", "error": str(exc)}

            result.update(
                {
                    "reflection_reason": reflection_reason,
                    "reflection_outcome": getattr(reflection_result, "outcome", None) if reflection_result else None,
                    "workflow_result": workflow_result,
                    "followthrough_result": followthrough_result,
                    "calendar_result": calendar_result,
                    "sentinel_result": sentinel_result,
                    "self_improvement_result": self_improvement_result,
                    "active_window_reflections": int(state.get("active_window_reflections") or 0),
                    "active_window_workflows": int(state.get("active_window_workflows") or 0),
                }
            )
            state["last_cycle_result"] = result
            state["last_cycle_utc"] = _utc_iso()
            self._save_autonomy_state(state)
            self._append_autonomy_event({"type": "autonomy_cycle_executed", **result})
            return result
        finally:
            self._autonomy_cycle_running = False

    def start(self) -> Optional[dict]:
        """Start proactive systems and bind inner life."""
        self._stopping = False
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        self.sentinel.start()
        if bool(self._autonomy_config.get("enabled", True)):
            self._autonomy_cycle_future = self._schedule_coroutine(self._run_autonomy_cycle_async(trigger="startup"))

        if hasattr(self, "inner_life") and self.inner_life:
            self.inner_life.bind(
                vera_instance=self._owner,
                channel_dock=self.channel_dock,
                event_bus=getattr(self, "event_bus", None),
                session_store=self.session_store,
                decision_ledger=self.decision_ledger,
                preference_manager=self.preferences,
                cost_tracker=getattr(self, "cost_tracker", None),
                flight_recorder=getattr(self._owner, "flight_recorder", None),
            )
            try:
                seed_manager = getattr(self._owner, "personality_seed", None)
                seed_compass = ""
                if seed_manager and hasattr(seed_manager, "export_reflection_compass"):
                    seed_compass = seed_manager.export_reflection_compass()
                if hasattr(self.inner_life, "set_seed_identity_compass"):
                    self.inner_life.set_seed_identity_compass(seed_compass)
            except Exception:
                logger.debug("Suppressed Exception in proactive_manager")
            return self.inner_life.get_statistics()
        return None

    def stop(self) -> None:
        """Stop proactive systems and persist state."""
        self._stopping = True
        pending_futures = list(self._scheduled_futures)
        for future in pending_futures:
            try:
                future.cancel()
            except Exception:
                logger.debug("Suppressed Exception in proactive_manager")

        if self._autonomy_cycle_future is not None:
            try:
                self._autonomy_cycle_future.cancel()
            except Exception:
                logger.debug("Suppressed Exception in proactive_manager")
        self._autonomy_cycle_future = None

        if hasattr(self, "inner_life") and self.inner_life:
            try:
                self.inner_life.save_personality()
            except Exception as exc:
                logger.warning("Failed to save inner life state: %s", exc)
        self.sentinel.stop()

    async def shutdown(self, timeout_seconds: float = 5.0) -> None:
        """Stop proactive systems and await cancellation of in-loop autonomy tasks."""
        autonomy_future = self._autonomy_cycle_future
        scheduled_futures = list(self._scheduled_futures)
        self.stop()

        async_tasks = [future for future in scheduled_futures if isinstance(future, asyncio.Task)]
        if async_tasks:
            try:
                await asyncio.wait(async_tasks, timeout=max(0.1, float(timeout_seconds)))
            except Exception:
                logger.debug("Suppressed Exception in proactive_manager")

        if isinstance(autonomy_future, asyncio.Task) and not autonomy_future.done():
            try:
                await asyncio.wait_for(asyncio.shield(autonomy_future), timeout=max(0.1, float(timeout_seconds)))
            except asyncio.TimeoutError:
                logger.debug("Autonomy cycle did not finish within shutdown timeout")
            except asyncio.CancelledError:
                logger.debug("Suppressed Exception in proactive_manager")
            except Exception:
                logger.debug("Suppressed Exception in proactive_manager")

    def setup_sentinel_triggers(self) -> None:
        """Configure proactive triggers for Sentinel Engine."""
        fs_adapter = FileSystemAdapter(watch_paths=["vera_memory"])
        self.sentinel.add_source(fs_adapter)

        existing_trigger_names = {t.name for t in self.sentinel.trigger_engine.list_triggers()}

        tasks_enabled = os.getenv("VERA_TASK_CHECK_ENABLED", "1") != "0"
        try:
            task_check_interval = int(os.getenv("VERA_TASK_CHECK_INTERVAL", "300"))
        except (ValueError, TypeError):
            task_check_interval = 300
        task_check_cooldown = int(os.getenv("VERA_TASK_CHECK_COOLDOWN", "900"))
        config_watch_enabled = os.getenv("VERA_CONFIG_WATCH_ENABLED", "1") != "0"
        red_team_interval = int(os.getenv("VERA_RED_TEAM_INTERVAL", "900"))
        autonomy_enabled = bool(self._autonomy_config.get("enabled", True))
        autonomy_pulse_interval = int(self._autonomy_config.get("pulse_interval_seconds", 300))

        timer_adapter = TimerAdapter()
        if tasks_enabled:
            timer_adapter.add_interval(
                name="task_check",
                interval_seconds=task_check_interval,
                payload={"action": "check_overdue_tasks"},
            )
        if red_team_interval > 0:
            timer_adapter.add_interval(
                name="red_team_check",
                interval_seconds=red_team_interval,
                payload={"action": "red_team_check"},
            )
        if autonomy_enabled:
            timer_adapter.add_interval(
                name="autonomy_cycle",
                interval_seconds=autonomy_pulse_interval,
                payload={"action": "autonomy_cycle"},
            )
        timer_adapter.add_interval(
            name="health_check",
            interval_seconds=60,
            payload={"action": "system_health"},
        )
        self.sentinel.add_source(timer_adapter)

        overdue_pattern = EventPattern(
            pattern_id="overdue_tasks",
            name="Overdue Tasks",
            sources=[EventSource.TIMER],
            payload_patterns={"action": "check_overdue_tasks"},
        )
        if tasks_enabled and "Overdue Task Alert" not in existing_trigger_names:
            self.sentinel.add_trigger(
                name="Overdue Task Alert",
                description="Fires when scheduled task check runs",
                pattern=overdue_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.NORMAL,
                cooldown_seconds=task_check_cooldown,
                action_template={"type": "check_tasks", "urgency": "medium"},
            )

        file_pattern = EventPattern(
            pattern_id="config_changes",
            name="Config Changes",
            sources=[EventSource.FILE_SYSTEM],
            event_types=[EventType.FILE_MODIFIED],
            payload_patterns={"path": "glob:*.json"},
        )
        if config_watch_enabled and "Config File Changed" not in existing_trigger_names:
            self.sentinel.add_trigger(
                name="Config File Changed",
                description="Fires when JSON config files change",
                pattern=file_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.LOW,
                cooldown_seconds=10,
                action_template={"type": "reload_config", "urgency": "low"},
            )

        red_team_pattern = EventPattern(
            pattern_id="red_team_check",
            name="Red Team Check",
            sources=[EventSource.TIMER],
            payload_patterns={"action": "red_team_check"},
        )
        if "Red Team Check" not in existing_trigger_names:
            self.sentinel.add_trigger(
                name="Red Team Check",
                description="Periodic red-team generation from flight recorder",
                pattern=red_team_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.LOW,
                cooldown_seconds=10,
                action_template={"type": "red_team_check", "urgency": "low"},
            )
        autonomy_pattern = EventPattern(
            pattern_id="autonomy_cycle",
            name="Autonomy Cadence Pulse",
            sources=[EventSource.TIMER],
            payload_patterns={"action": "autonomy_cycle"},
        )
        if autonomy_enabled and "Autonomy Cadence Pulse" not in existing_trigger_names:
            self.sentinel.add_trigger(
                name="Autonomy Cadence Pulse",
                description="Periodic active/idle cadence for proactive autonomy",
                pattern=autonomy_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.BACKGROUND,
                cooldown_seconds=max(10, autonomy_pulse_interval // 2),
                action_template={"type": "autonomy_cycle", "urgency": "low"},
            )

        if hasattr(self, "inner_life") and self.inner_life and self.inner_life.config.enabled:
            il_interval = self.inner_life.config.reflection_interval_seconds
            il_cooldown = self.inner_life.config.cooldown_seconds
            timer_adapter.add_interval(
                name="inner_life_reflection",
                interval_seconds=il_interval,
                payload={"action": "reflect"},
            )
            reflection_pattern = EventPattern(
                pattern_id="inner_life_reflection",
                name="Inner Life Reflection",
                sources=[EventSource.TIMER],
                payload_patterns={"action": "reflect"},
            )
            if "Inner Life Reflection" not in existing_trigger_names:
                self.sentinel.add_trigger(
                    name="Inner Life Reflection",
                    description="Periodic inner monologue and reflection cycle",
                    pattern=reflection_pattern,
                    condition=TriggerCondition.IMMEDIATE,
                    priority=ActionPriority.NORMAL,
                    cooldown_seconds=il_cooldown,
                    action_template={"type": "reflect", "urgency": "medium"},
                )

        self.sentinel.on_recommendation = self.handle_proactive_recommendation
        self.sentinel.register_action_handler("check_tasks", self.action_check_tasks)
        self.sentinel.register_action_handler("reload_config", self.action_reload_config)
        self.sentinel.register_action_handler("notify", self.action_notify)
        self.sentinel.register_action_handler("red_team_check", self.action_red_team)
        self.sentinel.register_action_handler("reflect", self.action_reflect)
        self.sentinel.register_action_handler("autonomy_cycle", self.action_autonomy_cycle)

    def apply_startup_dnd(self) -> None:
        """Apply any DND configuration from environment on startup."""
        level_raw = os.getenv("VERA_DND_LEVEL", "").strip().lower()
        if not level_raw:
            return
        try:
            level = DNDLevel(level_raw)
        except ValueError:
            if self.config.debug:
                logger.debug("[DEBUG] Invalid VERA_DND_LEVEL: %s", level_raw)
            return
        minutes_raw = os.getenv("VERA_DND_MINUTES", "").strip()
        duration = None
        if minutes_raw:
            try:
                duration = int(minutes_raw)
            except ValueError:
                if self.config.debug:
                    logger.debug("[DEBUG] Invalid VERA_DND_MINUTES: %s", minutes_raw)
        reason = os.getenv("VERA_DND_REASON", "Startup DND")
        self.dnd.enable_dnd(level=level, duration_minutes=duration, reason=reason)

    def handle_proactive_recommendation(self, recommendation: RecommendedAction):
        """Handle proactive recommendations from Sentinel Engine."""
        allowed, gate_reason = self._should_execute_recommendation(recommendation)
        if not allowed:
            state = self._ensure_initiative_runtime()
            state["suppressed_count"] = int(state.get("suppressed_count", 0)) + 1
            self._save_initiative_state(state)
            self._append_initiative_event({
                "type": "proactive_recommendation_suppressed",
                "action_type": recommendation.action_type,
                "priority": recommendation.priority.name,
                "reason": gate_reason,
                "description": recommendation.description[:160],
            })
            if self.config.debug:
                logger.debug("[DEBUG] Proactive action suppressed: %s (%s)", recommendation.description, gate_reason)
            return

        action_type = str(getattr(recommendation, "action_type", "") or "")
        if action_type in self.INTERNAL_DND_BYPASS_ACTIONS:
            self.execute_proactive_action(recommendation)
            if self.config.debug:
                logger.debug("[DEBUG] Internal proactive action bypassed DND: %s", recommendation.description)
            return

        priority_to_urgency = {
            ActionPriority.BACKGROUND: InterruptUrgency.ROUTINE,
            ActionPriority.LOW: InterruptUrgency.LOW,
            ActionPriority.NORMAL: InterruptUrgency.MEDIUM,
            ActionPriority.HIGH: InterruptUrgency.HIGH,
            ActionPriority.URGENT: InterruptUrgency.CRITICAL,
        }
        urgency = priority_to_urgency.get(recommendation.priority, InterruptUrgency.MEDIUM)

        if self.dnd.can_interrupt(urgency):
            self.execute_proactive_action(recommendation)
            return

        self._pending_proactive_actions.append(recommendation)
        action_id = str(getattr(recommendation, "action_id", "") or "")

        def _drain_and_execute(_message: str) -> None:
            self._drain_pending_recommendation(action_id)
            self.execute_proactive_action(recommendation)

        self.dnd.queue_interrupt(
            message=recommendation.description,
            urgency=urgency,
            callback=_drain_and_execute,
        )
        if self.config.debug:
            logger.debug("[DEBUG] Proactive action queued (DND active): %s", recommendation.description)

    def _drain_pending_recommendation(self, action_id: str) -> int:
        target = str(action_id or "").strip()
        if not target:
            return 0
        pending = getattr(self, "_pending_proactive_actions", None)
        if not isinstance(pending, list) or not pending:
            return 0

        kept: List[RecommendedAction] = []
        removed = 0
        for row in pending:
            row_action_id = str(getattr(row, "action_id", "") or "").strip()
            if row_action_id == target:
                removed += 1
                continue
            kept.append(row)
        if removed:
            self._pending_proactive_actions[:] = kept
        return removed

    def execute_proactive_action(self, recommendation: RecommendedAction):
        """Execute a proactive action recommendation."""
        self._drain_pending_recommendation(str(getattr(recommendation, "action_id", "") or ""))
        success, result = self.sentinel.execute_recommendation(recommendation.action_id)
        self._record_recent_proactive_action(recommendation, success=bool(success), result=result)
        delta, signal = self._evaluate_action_reward_signal(recommendation, success=bool(success), result=result)
        if delta != 0.0:
            self._apply_initiative_signal(
                signal_type=signal,
                delta=delta,
                context={
                    "action_type": recommendation.action_type,
                    "priority": recommendation.priority.name,
                    "action_id": recommendation.action_id,
                },
            )

        # Update per-type adaptive cooldowns
        self._update_action_type_stats(
            action_type=recommendation.action_type,
            outcome=signal,
        )

        if success:
            if recommendation.action_type == "check_tasks":
                overdue_count = 0
                if isinstance(result, dict):
                    overdue_count = result.get("overdue_count", 0)
                if overdue_count <= 0:
                    return
            if self.config.debug:
                logger.debug("[DEBUG] Proactive action executed: %s", recommendation.description)
            if self.config.observability:
                self.observability.record_event(
                    "proactive_action",
                    action_type=recommendation.action_type,
                    priority=recommendation.priority.value,
                )
            return

        if self.config.debug:
            logger.error("[DEBUG] Proactive action failed: %s", result)

    def action_check_tasks(self, payload: dict) -> dict:
        """Handler for checking overdue tasks."""
        stats = self.master_list.get_stats()
        if stats.get("overdue", 0) > 0:
            overdue_tasks = [t for t in self.master_list.list_tasks() if t.is_overdue()]
            return {
                "overdue_count": len(overdue_tasks),
                "tasks": [{"id": t.id, "title": t.title} for t in overdue_tasks[:3]],
            }
        return {"overdue_count": 0}

    def action_reload_config(self, payload: dict) -> dict:
        """Handler for reloading config files."""
        self.preferences._load()
        self.dnd._load()
        return {"reloaded": True}

    def action_notify(self, payload: dict) -> dict:
        """Handler for generic notifications."""
        message = payload.get("message", "Notification from VERA")
        print(f"[VERA Notification] {message}")
        return {"notified": True}

    def action_reflect(self, payload: dict) -> dict:
        """Handler for inner life reflection triggers. Schedules async reflection."""
        if not hasattr(self, "inner_life") or not self.inner_life:
            return {"skipped": True, "reason": "inner life not available"}
        if not self.inner_life.config.enabled:
            return {"skipped": True, "reason": "inner life disabled"}

        future = self._schedule_coroutine(self.run_reflection_cycle())
        if future is None:
            return {"skipped": True, "reason": "no_event_loop"}
        return {"scheduled": True}

    def action_autonomy_cycle(self, payload: dict) -> dict:
        """Handler for autonomy cadence cycle triggers."""
        if not bool(self._autonomy_config.get("enabled", True)):
            return {"scheduled": False, "skipped": True, "reason": "autonomy_cadence_disabled"}
        trigger = str((payload or {}).get("trigger") or "sentinel")
        force = bool((payload or {}).get("force", False))
        self._autonomy_cycle_future = self._schedule_coroutine(
            self._run_autonomy_cycle_async(trigger=trigger, force=force)
        )
        if self._autonomy_cycle_future is None:
            return {"scheduled": False, "skipped": True, "reason": "no_event_loop"}
        return {"scheduled": True, "trigger": trigger, "force": force}

    def get_autonomy_status(self) -> Dict[str, Any]:
        """Return active/idle cadence and latest autonomy cycle state."""
        state = self._load_autonomy_state()
        phase, window_index, seconds_until_transition = self._compute_cadence_phase(state)
        initiative_status = self.get_initiative_tuning_status()
        future_state = "none"
        if self._autonomy_cycle_future is not None:
            try:
                if self._autonomy_cycle_future.cancelled():
                    future_state = "cancelled"
                elif self._autonomy_cycle_future.done():
                    future_state = "done"
                else:
                    future_state = "running"
            except Exception:
                future_state = "unknown"
        return {
            "config": dict(self._autonomy_config),
            "phase": phase,
            "window_index": window_index,
            "seconds_until_transition": seconds_until_transition,
            "cycle_running": bool(self._autonomy_cycle_running),
            "scheduled_future": future_state,
            "last_cycle_utc": state.get("last_cycle_utc"),
            "last_cycle_result": state.get("last_cycle_result", {}),
            "active_window_reflections": int(state.get("active_window_reflections") or 0),
            "active_window_workflows": int(state.get("active_window_workflows") or 0),
            "last_followthrough_utc": state.get("last_followthrough_utc", ""),
            "initiative_tuning": initiative_status,
        }

    async def run_reflection_cycle(self, trigger: str = "heartbeat", force: bool = False):
        """Execute an inner life reflection cycle with error handling."""
        if self._stopping:
            return None
        try:
            result = await self.inner_life.execute_reflection_cycle(
                trigger=trigger,
                force=force,
            )
            if self.config.debug:
                logger.debug(
                    "[INNER LIFE] run_id=%s outcome=%s chain=%s duration=%sms",
                    result.run_id,
                    result.outcome,
                    result.total_chain_depth,
                    f"{result.duration_ms:.0f}",
                )
            return result
        except Exception as exc:
            logger.error("Inner life reflection failed: %s", exc)
            return None

    def load_red_team_state(self) -> Dict[str, Any]:
        return safe_json_read(self._red_team_state_path, default={})

    def save_red_team_state(self, state: Dict[str, Any]) -> None:
        self._red_team_state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(self._red_team_state_path, state)

    def get_transition_count(self) -> int:
        transitions_path = Path("vera_memory") / "flight_recorder" / "transitions.ndjson"
        if not transitions_path.exists():
            return 0
        try:
            with transitions_path.open("r", encoding="utf-8") as handle:
                return sum(1 for _ in handle)
        except Exception:
            return 0

    def action_red_team(self, payload: dict) -> dict:
        """Run red-team harness on a threshold or daily schedule."""
        try:
            threshold = int(os.getenv("VERA_RED_TEAM_THRESHOLD", "200"))
        except (ValueError, TypeError):
            threshold = 200
        daily_hour = int(os.getenv("VERA_RED_TEAM_DAILY_HOUR", "2"))
        use_llm = os.getenv("VERA_RED_TEAM_USE_LLM", "1").lower() not in {"0", "false", "off"}
        failure_limit = int(os.getenv("VERA_RED_TEAM_FAILURE_LIMIT", "10"))
        try:
            hard_count = int(os.getenv("VERA_RED_TEAM_HARD_COUNT", "10"))
        except (ValueError, TypeError):
            hard_count = 10
        regression_count = int(os.getenv("VERA_RED_TEAM_REGRESSION_COUNT", "20"))

        now = datetime.now()
        today = now.date().isoformat()

        state = self.load_red_team_state()
        last_count = int(state.get("last_transition_count", 0))
        last_daily = state.get("last_daily_run_date", "")

        current_count = self.get_transition_count()
        delta = max(0, current_count - last_count)

        daily_due = now.hour >= daily_hour and last_daily != today
        threshold_due = delta >= threshold

        if current_count == 0:
            return {"ran": False, "reason": "no_transitions"}
        if not (threshold_due or daily_due):
            return {"ran": False, "reason": "not_due", "delta": delta, "current": current_count}
        if self._red_team_running:
            return {"ran": False, "reason": "already_running"}

        result = {"hard_cases": 0, "regression_cases": 0}
        try:
            self._red_team_running = True
            result = run_red_team(
                failure_limit=failure_limit,
                hard_count=hard_count,
                regression_count=regression_count,
                use_llm=use_llm,
            )
            state["last_transition_count"] = current_count
            state["last_run_at"] = now.isoformat()
            if daily_due or now.hour >= daily_hour:
                state["last_daily_run_date"] = today
                state["last_daily_run_at"] = now.isoformat()
            state["last_run_reason"] = "threshold" if threshold_due else "daily"
            self.save_red_team_state(state)
        except Exception as exc:
            state["last_error"] = str(exc)
            state["last_error_at"] = now.isoformat()
            self.save_red_team_state(state)
            return {"ran": False, "reason": "error", "error": str(exc)}
        finally:
            self._red_team_running = False

        return {
            "ran": True,
            "reason": state.get("last_run_reason", ""),
            "delta": delta,
            "current": current_count,
            **result,
        }
