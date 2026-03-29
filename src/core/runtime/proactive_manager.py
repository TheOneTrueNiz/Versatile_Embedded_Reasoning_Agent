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
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from context.dnd_mode import DNDManager, DNDLevel, InterruptUrgency
from core.atomic_io import atomic_json_write, safe_json_read
from core.foundation.master_list import TaskPriority, TaskStatus
from core.runtime.autonomy_runplane import AutonomyRunplane, run_requires_ack
from core.services.red_team_harness import run_red_team
from observability.self_improvement_budget import (
    SelfImprovementBudget,
    estimate_cost,
    estimate_tokens,
)
from planning.sentinel_engine import (
    ActionPriority,
    Event,
    EventPattern,
    EventSource,
    EventType,
    FileSystemAdapter,
    RecommendedAction,
    SentinelEngine,
    TimerAdapter,
    Trigger,
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
        self._week1_due_check_future = None
        self._scheduled_futures: Set[Any] = set()
        self._stopping = False
        self._budget_guard = SelfImprovementBudget()
        self._initiative_state_path = self._memory_dir / "initiative_tuning_state.json"
        self._initiative_event_log = self._memory_dir / "initiative_tuning_events.jsonl"
        self._failure_learning_event_log = self._memory_dir / "failure_learning_events.jsonl"
        self._week1_progress_state_path = self._memory_dir / "week1_autonomy_progress.json"
        self._state_sync_verifier_state_path = self._memory_dir / "autonomy_state_sync_verifier.json"
        self._state_sync_verifier_event_log = self._memory_dir / "autonomy_state_sync_verifier_events.jsonl"
        self._initiative_config = self._load_initiative_tuning_config()
        self._initiative_state = self._load_initiative_state()
        self._proactive_lane_lock = threading.RLock()
        self._active_proactive_lanes: Dict[str, str] = {}
        queue_raw = str(os.getenv("VERA_PROACTIVE_LANE_QUEUE_MAX", "8") or "8").strip()
        try:
            self._proactive_lane_queue_max = max(1, int(queue_raw))
        except Exception:
            self._proactive_lane_queue_max = 8
        self._proactive_lane_queues: Dict[str, List[RecommendedAction]] = {}
        stale_raw = str(os.getenv("VERA_AUTONOMY_LANE_STALE_SECONDS", "1800") or "1800").strip()
        try:
            stale_lane_seconds = max(60, int(stale_raw))
        except Exception:
            stale_lane_seconds = 1800
        self.runplane = AutonomyRunplane(
            storage_dir=self._memory_dir / "autonomy_runplane",
            stale_lane_seconds=stale_lane_seconds,
        )
        owner.autonomy_runplane = self.runplane

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
            "week1_executor_enabled": _env_bool("VERA_AUTONOMY_WEEK1_EXECUTOR_ENABLED", True),
            "week1_executor_cooldown_seconds": _env_int("VERA_AUTONOMY_WEEK1_EXECUTOR_COOLDOWN_SECONDS", 900),
            "week1_executor_timeout_seconds": _env_int("VERA_AUTONOMY_WEEK1_EXECUTOR_TIMEOUT_SECONDS", 600),
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
        config["week1_executor_enabled"] = _coerce_bool(config.get("week1_executor_enabled"), True)
        config["week1_executor_cooldown_seconds"] = _coerce_int(
            config.get("week1_executor_cooldown_seconds"), 900, 60
        )
        config["week1_executor_timeout_seconds"] = _coerce_int(
            config.get("week1_executor_timeout_seconds"), 600, 120
        )
        config["base_url"] = str(config.get("base_url") or "http://127.0.0.1:8788").strip()
        return config

    def _reflection_runtime_uptime_seconds(self) -> float:
        session_start = getattr(self, "session_start", None)
        if not isinstance(session_start, datetime):
            return 0.0
        try:
            delta = datetime.now() - session_start
            return max(0.0, float(delta.total_seconds()))
        except Exception:
            return 0.0

    def _classify_reflection_error(self, error_text: str) -> Tuple[str, str]:
        error = str(error_text or "").strip()
        if not error:
            return "reflection_error", ""
        if not error.startswith("reflection_turn_timeout:"):
            return "reflection_error", "steady_state"

        warmup_seconds_raw = str(os.getenv("VERA_REFLECTION_TIMEOUT_WARMUP_SECONDS", "180") or "180").strip()
        try:
            warmup_seconds = max(30.0, float(warmup_seconds_raw))
        except Exception:
            warmup_seconds = 180.0
        uptime_seconds = self._reflection_runtime_uptime_seconds()
        if uptime_seconds < warmup_seconds:
            return "reflection_error_runtime_warmup", "runtime_warmup"

        try:
            status = self.mcp.get_status()
        except Exception:
            status = {}
        servers = status.get("servers") if isinstance(status, dict) else {}
        if isinstance(servers, dict):
            for info in servers.values():
                if not isinstance(info, dict):
                    continue
                if bool(info.get("starting")):
                    return "reflection_error_mcp_startup_disruption", "mcp_startup_disruption"
                health = str(info.get("health") or "").strip().lower()
                effective_health = str(info.get("effective_health") or "").strip().lower()
                if health in {"starting", "initializing"}:
                    return "reflection_error_mcp_startup_disruption", "mcp_startup_disruption"
                if effective_health in {"starting", "initializing"}:
                    return "reflection_error_mcp_startup_disruption", "mcp_startup_disruption"

        return "reflection_error", "steady_state"

    def _default_autonomy_state(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "anchor_utc": _utc_iso(),
            "window_index": 0,
            "phase": "active",
            "phase_started_utc": _utc_iso(),
            "active_window_reflections": 0,
            "active_window_workflows": 0,
            "startup_window_reflection_index": -1,
            "startup_window_workflow_index": -1,
            "last_followthrough_utc": "",
            "last_week1_executor_utc": "",
            "last_cycle_utc": "",
            "last_cycle_result": {},
            "dead_letter_replay": {},
            "last_dead_letter_replay_result": {},
            "last_dead_letter_replay_slo": {},
            "last_delivery_escalation_result": {},
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
        self._reconcile_initiative_state(baseline)
        return baseline

    def _reconcile_initiative_state(self, state: Dict[str, Any]) -> None:
        """Normalize stale initiative counters from older runtime behavior."""
        if not isinstance(state, dict):
            return
        stats = state.get("action_type_stats")
        if not isinstance(stats, dict):
            return

        noop_threshold = int(self._initiative_config.get("type_noop_streak_threshold", 5) or 5)
        noop_outcomes = {
            "action_success_noop",
            "action_success_skipped",
            "action_success_not_due",
        }

        for atype, raw_stat in list(stats.items()):
            if not isinstance(raw_stat, dict):
                continue
            stat = raw_stat
            total_noops = int(stat.get("total_noops", 0) or 0)
            consecutive_noops = int(stat.get("consecutive_noops", 0) or 0)
            last_outcome = str(stat.get("last_outcome") or "").strip()

            if self._is_internal_cadence_action(str(atype or "")):
                if total_noops > 0:
                    stat["total_noops"] = 0
                continue

            if self._is_maintenance_scan_action(str(atype or "")):
                if last_outcome in noop_outcomes and consecutive_noops >= noop_threshold:
                    stat["total_noops"] = min(total_noops, noop_threshold)

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

    def _append_failure_learning_event(self, event: Dict[str, Any]) -> None:
        path = self._local_attr(self, "_failure_learning_event_log", None)
        if not path:
            memory_dir = self._local_attr(self, "_memory_dir", Path("vera_memory"))
            path = Path(memory_dir) / "failure_learning_events.jsonl"
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            row = {"ts_utc": _utc_iso(), **dict(event or {})}
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=True) + "\n")
        except Exception:
            logger.debug("Suppressed Exception in proactive_manager")

    @staticmethod
    def _preview_failure_payload(value: Any, limit: int = 300) -> str:
        try:
            text = json.dumps(value, ensure_ascii=True, sort_keys=True)
        except Exception:
            text = str(value)
        return text[:max(40, int(limit))]

    @staticmethod
    def _parse_bool_env(name: str, default: bool) -> bool:
        raw = str(os.getenv(name, "") or "").strip().lower()
        if not raw:
            return bool(default)
        return raw not in {"0", "false", "off", "no"}

    @staticmethod
    def _parse_int_env(name: str, default: int, minimum: int = 0) -> int:
        raw = str(os.getenv(name, "") or "").strip()
        if not raw:
            return max(minimum, int(default))
        try:
            parsed = int(raw)
        except Exception:
            parsed = int(default)
        return max(minimum, parsed)

    @staticmethod
    def _parse_csv_env(name: str, default: str = "") -> List[str]:
        raw = str(os.getenv(name, default) or "").strip()
        if not raw:
            return []
        return [item.strip().lower() for item in raw.split(",") if item.strip()]

    def _allowed_dead_letter_replay_classes(self) -> Set[str]:
        raw = str(
            os.getenv(
                "VERA_AUTONOMY_DEAD_LETTER_REPLAY_ALLOW",
                "delivery_unroutable,stale_lane,transport_error,rate_limited,transient_timeout,executor_failure,executor_nonzero_exit",
            )
            or ""
        ).strip()
        if not raw:
            return set()
        return {
            token.strip().lower()
            for token in raw.split(",")
            if token.strip()
        }

    @staticmethod
    def _normalize_dead_letter_replay_entry(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, str):
            return {
                "last_replay_utc": str(raw).strip(),
                "replay_count": 0,
                "consecutive_replay_failures": 0,
                "escalated": False,
                "last_failure_class": "",
                "last_result_preview": "",
            }
        if isinstance(raw, dict):
            entry = {
                "last_replay_utc": str(raw.get("last_replay_utc") or "").strip(),
                "replay_count": int(raw.get("replay_count") or 0),
                "consecutive_replay_failures": int(raw.get("consecutive_replay_failures") or 0),
                "escalated": bool(raw.get("escalated", False)),
                "last_failure_class": str(raw.get("last_failure_class") or "").strip().lower(),
                "last_result_preview": str(raw.get("last_result_preview") or "")[:320],
            }
            if not entry["last_replay_utc"]:
                legacy_ts = str(raw.get("last_attempt_utc") or raw.get("updated_at_utc") or "").strip()
                entry["last_replay_utc"] = legacy_ts
            return entry
        return {
            "last_replay_utc": "",
            "replay_count": 0,
            "consecutive_replay_failures": 0,
            "escalated": False,
            "last_failure_class": "",
            "last_result_preview": "",
        }

    def _mark_dead_letter_escalated(
        self,
        *,
        runplane: Any,
        job_id: str,
        run_id: str,
        reason: str,
        failure_class: str,
    ) -> Dict[str, Any]:
        mark_result: Dict[str, Any] = {"ok": False, "reason": "mark_unavailable"}
        if runplane and hasattr(runplane, "mark_run_status"):
            try:
                mark_result = runplane.mark_run_status(
                    run_id=run_id,
                    status="escalated",
                    source="autonomy_auto_replay",
                    note=reason[:220],
                )
            except Exception as exc:
                mark_result = {"ok": False, "reason": f"mark_exception:{exc.__class__.__name__}"}
        self._append_failure_learning_event(
            {
                "type": "dead_letter_auto_escalate",
                "ok": bool(mark_result.get("ok")),
                "job_id": job_id,
                "run_id": run_id,
                "failure_class": failure_class,
                "reason": reason[:220],
                "mark_result": self._preview_failure_payload(mark_result, limit=320),
            }
        )
        return mark_result

    def _audit_dead_letter_replay_slo(self, replay_summary: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        runplane = self._local_attr(self, "runplane", None)
        min_success_rate = float(os.getenv("VERA_AUTONOMY_DEAD_LETTER_SLO_MIN_SUCCESS_RATE", "0.50") or 0.50)
        max_backlog = self._parse_int_env("VERA_AUTONOMY_DEAD_LETTER_SLO_MAX_BACKLOG", 20, minimum=0)
        max_cycle_failures = self._parse_int_env("VERA_AUTONOMY_DEAD_LETTER_SLO_MAX_CYCLE_FAILURES", 3, minimum=0)
        max_escalated_cycle = self._parse_int_env("VERA_AUTONOMY_DEAD_LETTER_SLO_MAX_ESCALATED_PER_CYCLE", 2, minimum=0)

        attempted = int(replay_summary.get("attempted", 0) or 0)
        replayed = int(replay_summary.get("replayed", 0) or 0)
        replay_failures = int(replay_summary.get("replay_failures", 0) or 0)
        escalated_jobs = int(replay_summary.get("escalated_jobs", 0) or 0)
        backlog = 0
        if runplane and hasattr(runplane, "list_dead_letters"):
            try:
                backlog = len(runplane.list_dead_letters(limit=5000))
            except Exception:
                backlog = 0

        success_rate = 1.0 if attempted <= 0 else (float(replayed) / float(max(1, attempted)))
        violations: List[str] = []
        if attempted > 0 and success_rate < float(min_success_rate):
            violations.append(
                f"success_rate:{success_rate:.3f}<{float(min_success_rate):.3f}"
            )
        if backlog > int(max_backlog):
            violations.append(f"dead_letter_backlog:{backlog}>{int(max_backlog)}")
        if replay_failures > int(max_cycle_failures):
            violations.append(f"cycle_replay_failures:{replay_failures}>{int(max_cycle_failures)}")
        if escalated_jobs > int(max_escalated_cycle):
            violations.append(f"cycle_escalations:{escalated_jobs}>{int(max_escalated_cycle)}")

        audit = {
            "pass": len(violations) == 0,
            "violations": violations,
            "metrics": {
                "attempted": attempted,
                "replayed": replayed,
                "success_rate": round(success_rate, 4),
                "replay_failures": replay_failures,
                "escalated_jobs": escalated_jobs,
                "dead_letter_backlog": backlog,
            },
            "thresholds": {
                "min_success_rate": float(min_success_rate),
                "max_backlog": int(max_backlog),
                "max_cycle_failures": int(max_cycle_failures),
                "max_escalated_per_cycle": int(max_escalated_cycle),
            },
            "ts_utc": _utc_iso(),
        }
        state["last_dead_letter_replay_slo"] = audit
        self._append_autonomy_event(
            {
                "type": "dead_letter_replay_slo_audit",
                "pass": bool(audit["pass"]),
                "violations": list(violations),
                "metrics": dict(audit["metrics"]),
            }
        )
        if violations:
            self._append_failure_learning_event(
                {
                    "type": "dead_letter_replay_slo_violation",
                    "ok": False,
                    "violations": list(violations),
                    "metrics": dict(audit["metrics"]),
                }
            )
        return audit

    def _auto_escalate_stale_deliveries(self, state: Dict[str, Any]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "enabled": False,
            "considered": 0,
            "eligible": 0,
            "escalated": 0,
            "skipped_ack_not_expected": 0,
            "skipped_not_due": 0,
            "skipped_non_delivery": 0,
            "mark_failures": 0,
            "reason": "",
        }
        enabled = self._parse_bool_env("VERA_AUTONOMY_ACK_SLA_ESCALATION_ENABLED", True)
        if not enabled:
            summary["reason"] = "ack_sla_escalation_disabled"
            state["last_delivery_escalation_result"] = dict(summary)
            return summary

        runplane = self._local_attr(self, "runplane", None)
        if not runplane or not hasattr(runplane, "list_runs") or not hasattr(runplane, "mark_run_status"):
            summary["reason"] = "runplane_unavailable"
            state["last_delivery_escalation_result"] = dict(summary)
            return summary

        sla_seconds = self._parse_int_env("VERA_AUTONOMY_ACK_SLA_SECONDS", 900, minimum=30)
        max_per_cycle = self._parse_int_env("VERA_AUTONOMY_ACK_SLA_MAX_ESCALATIONS_PER_CYCLE", 3, minimum=1)
        scan_limit = self._parse_int_env("VERA_AUTONOMY_ACK_SLA_SCAN_LIMIT", 400, minimum=20)
        allowed_kind_prefixes = self._parse_csv_env(
            "VERA_AUTONOMY_ACK_SLA_KIND_PREFIXES",
            "delivery",
        )

        rows = runplane.list_runs(limit=scan_limit, status_filter="delivered")
        now = _utc_now()
        eligible_rows: List[Tuple[datetime, Dict[str, Any], float]] = []
        summary["enabled"] = True
        summary["sla_seconds"] = int(sla_seconds)
        summary["max_per_cycle"] = int(max_per_cycle)
        summary["scan_limit"] = int(scan_limit)
        summary["considered"] = len(rows) if isinstance(rows, list) else 0
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("kind") or "").strip().lower()
            if allowed_kind_prefixes:
                if not any(kind.startswith(prefix) for prefix in allowed_kind_prefixes):
                    summary["skipped_non_delivery"] = int(summary.get("skipped_non_delivery", 0)) + 1
                    continue
            if not run_requires_ack(row):
                summary["skipped_ack_not_expected"] = int(summary.get("skipped_ack_not_expected", 0)) + 1
                continue
            delivered_at = (
                _parse_iso_utc(str(row.get("finished_at_utc") or ""))
                or _parse_iso_utc(str(row.get("status_updated_at_utc") or ""))
                or _parse_iso_utc(str(row.get("started_at_utc") or ""))
            )
            if delivered_at is None:
                summary["skipped_not_due"] = int(summary.get("skipped_not_due", 0)) + 1
                continue
            age_seconds = max(0.0, (now - delivered_at).total_seconds())
            if age_seconds < float(sla_seconds):
                summary["skipped_not_due"] = int(summary.get("skipped_not_due", 0)) + 1
                continue
            eligible_rows.append((delivered_at, row, age_seconds))

        summary["eligible"] = len(eligible_rows)
        for delivered_at, row, age_seconds in sorted(eligible_rows, key=lambda item: item[0]):
            if int(summary.get("escalated", 0)) >= int(max_per_cycle):
                break
            run_id = str(row.get("run_id") or "").strip()
            if not run_id:
                continue
            reason = f"ack_timeout_sla_exceeded:{int(age_seconds)}s>={int(sla_seconds)}s"
            mark_result = runplane.mark_run_status(
                run_id=run_id,
                status="escalated",
                source="autonomy_ack_sla",
                note=reason,
            )
            if mark_result.get("ok"):
                summary["escalated"] = int(summary.get("escalated", 0)) + 1
                self._append_failure_learning_event(
                    {
                        "type": "delivery_ack_timeout_escalated",
                        "ok": True,
                        "run_id": run_id,
                        "job_id": str(row.get("job_id") or ""),
                        "kind": str(row.get("kind") or ""),
                        "age_seconds": round(age_seconds, 3),
                        "reason": reason,
                    }
                )
            else:
                summary["mark_failures"] = int(summary.get("mark_failures", 0)) + 1
                self._append_failure_learning_event(
                    {
                        "type": "delivery_ack_timeout_escalated",
                        "ok": False,
                        "run_id": run_id,
                        "job_id": str(row.get("job_id") or ""),
                        "kind": str(row.get("kind") or ""),
                        "age_seconds": round(age_seconds, 3),
                        "reason": reason,
                        "mark_result": self._preview_failure_payload(mark_result, limit=280),
                    }
                )

        if not summary.get("reason"):
            summary["reason"] = "processed"
        state["last_delivery_escalation_result"] = dict(summary)
        self._append_autonomy_event(
            {
                "type": "delivery_ack_sla_scan",
                "summary": dict(summary),
            }
        )
        return summary

    def _auto_replay_dead_letters(self, state: Dict[str, Any]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {
            "enabled": False,
            "attempted": 0,
            "replayed": 0,
            "skipped_disallowed": 0,
            "skipped_cooldown": 0,
            "skipped_replay_limit": 0,
            "skipped_already_escalated": 0,
            "escalated_jobs": 0,
            "replay_failures": 0,
            "reason": "",
        }
        enabled = self._parse_bool_env("VERA_AUTONOMY_DEAD_LETTER_AUTO_REPLAY", True)
        if not enabled:
            summary["reason"] = "auto_replay_disabled"
            return summary
        runplane = self._local_attr(self, "runplane", None)
        if not runplane:
            summary["reason"] = "runplane_unavailable"
            return summary

        max_per_cycle = self._parse_int_env("VERA_AUTONOMY_DEAD_LETTER_REPLAY_MAX_PER_CYCLE", 2, minimum=1)
        cooldown_seconds = self._parse_int_env("VERA_AUTONOMY_DEAD_LETTER_REPLAY_COOLDOWN_SECONDS", 1800, minimum=30)
        max_replays_per_job = self._parse_int_env("VERA_AUTONOMY_DEAD_LETTER_MAX_REPLAYS_PER_JOB", 3, minimum=1)
        escalation_failures = self._parse_int_env(
            "VERA_AUTONOMY_DEAD_LETTER_REPLAY_FAIL_ESCALATION_THRESHOLD",
            2,
            minimum=1,
        )
        allowed_classes = self._allowed_dead_letter_replay_classes()
        dead_rows = runplane.list_dead_letters(limit=max(20, max_per_cycle * 20))
        summary["enabled"] = True
        summary["cooldown_seconds"] = int(cooldown_seconds)
        summary["max_per_cycle"] = int(max_per_cycle)
        summary["max_replays_per_job"] = int(max_replays_per_job)
        summary["fail_escalation_threshold"] = int(escalation_failures)
        summary["allowed_failure_classes"] = sorted(allowed_classes)
        summary["dead_letter_candidates"] = len(dead_rows)
        if not dead_rows:
            summary["reason"] = "no_dead_letters"
            return summary

        raw_replay_state = state.get("dead_letter_replay", {})
        replay_state: Dict[str, Dict[str, Any]] = {}
        if isinstance(raw_replay_state, dict):
            for job_id, entry in raw_replay_state.items():
                jid = str(job_id or "").strip()
                if not jid:
                    continue
                replay_state[jid] = self._normalize_dead_letter_replay_entry(entry)
        now = _utc_now()

        for row in dead_rows:
            if summary["replayed"] >= max_per_cycle:
                break
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("job_id") or "").strip()
            run_id = str(row.get("run_id") or "").strip()
            failure_class = str(row.get("failure_class") or "unknown").strip().lower()
            if not job_id or not run_id:
                continue
            if allowed_classes and failure_class not in allowed_classes:
                summary["skipped_disallowed"] = int(summary.get("skipped_disallowed", 0)) + 1
                continue
            entry = replay_state.get(job_id) or self._normalize_dead_letter_replay_entry({})
            if bool(entry.get("escalated", False)):
                summary["skipped_already_escalated"] = int(summary.get("skipped_already_escalated", 0)) + 1
                replay_state[job_id] = entry
                continue
            replay_count = int(entry.get("replay_count", 0) or 0)
            if replay_count >= int(max_replays_per_job):
                summary["skipped_replay_limit"] = int(summary.get("skipped_replay_limit", 0)) + 1
                entry["escalated"] = True
                reason = f"max_replays_exceeded:{replay_count}>={int(max_replays_per_job)}"
                self._mark_dead_letter_escalated(
                    runplane=runplane,
                    job_id=job_id,
                    run_id=run_id,
                    reason=reason,
                    failure_class=failure_class,
                )
                summary["escalated_jobs"] = int(summary.get("escalated_jobs", 0)) + 1
                entry["last_failure_class"] = failure_class
                replay_state[job_id] = entry
                continue
            last_replay = _parse_iso_utc(str(entry.get("last_replay_utc") or ""))
            if last_replay is not None:
                if (now - last_replay).total_seconds() < float(cooldown_seconds):
                    summary["skipped_cooldown"] = int(summary.get("skipped_cooldown", 0)) + 1
                    replay_state[job_id] = entry
                    continue

            summary["attempted"] = int(summary.get("attempted", 0)) + 1
            replay_result = runplane.replay_dead_letter(run_id=run_id, trigger="autonomy_auto_replay")
            if replay_result.get("ok"):
                summary["replayed"] = int(summary.get("replayed", 0)) + 1
                entry["last_replay_utc"] = _utc_iso()
                entry["replay_count"] = replay_count + 1
                entry["consecutive_replay_failures"] = 0
                entry["last_failure_class"] = failure_class
                entry["last_result_preview"] = self._preview_failure_payload(replay_result)
                replay_state[job_id] = entry
                self._append_failure_learning_event(
                    {
                        "type": "dead_letter_auto_replay",
                        "ok": True,
                        "job_id": job_id,
                        "run_id": run_id,
                        "failure_class": failure_class,
                        "result_preview": self._preview_failure_payload(replay_result),
                    }
                )
            else:
                summary["replay_failures"] = int(summary.get("replay_failures", 0)) + 1
                consecutive_failures = int(entry.get("consecutive_replay_failures", 0) or 0) + 1
                entry["last_replay_utc"] = _utc_iso()
                entry["replay_count"] = replay_count + 1
                entry["consecutive_replay_failures"] = consecutive_failures
                entry["last_failure_class"] = failure_class
                entry["last_result_preview"] = self._preview_failure_payload(replay_result)
                if consecutive_failures >= int(escalation_failures):
                    entry["escalated"] = True
                    reason = (
                        f"replay_failures_exceeded:{consecutive_failures}>="
                        f"{int(escalation_failures)}"
                    )
                    self._mark_dead_letter_escalated(
                        runplane=runplane,
                        job_id=job_id,
                        run_id=run_id,
                        reason=reason,
                        failure_class=failure_class,
                    )
                    summary["escalated_jobs"] = int(summary.get("escalated_jobs", 0)) + 1
                replay_state[job_id] = entry
                self._append_failure_learning_event(
                    {
                        "type": "dead_letter_auto_replay",
                        "ok": False,
                        "job_id": job_id,
                        "run_id": run_id,
                        "failure_class": failure_class,
                        "result_preview": self._preview_failure_payload(replay_result),
                    }
                )

        if len(replay_state) > 600:
            sortable = []
            for job_id, entry in replay_state.items():
                ts = ""
                if isinstance(entry, dict):
                    ts = str(entry.get("last_replay_utc") or "")
                dt = _parse_iso_utc(ts) or datetime.fromtimestamp(0, tz=timezone.utc)
                sortable.append((job_id, dt))
            keep = {job_id for job_id, _ in sorted(sortable, key=lambda item: item[1], reverse=True)[:400]}
            replay_state = {job_id: replay_state[job_id] for job_id in keep}
        state["dead_letter_replay"] = replay_state
        state["last_dead_letter_replay_result"] = dict(summary)
        summary["tracked_jobs"] = len(replay_state)
        if not summary.get("reason"):
            summary["reason"] = "processed"
        return summary

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

    def _compute_noop_cooldown_seconds(self, consecutive_noops: int) -> float:
        """Compute exponential backoff cooldown once noop streak reaches threshold."""
        if consecutive_noops <= 0:
            return 0.0
        threshold = int(self._initiative_config.get("type_noop_streak_threshold", 5))
        if consecutive_noops < threshold:
            return 0.0
        base = float(self._initiative_config.get("type_base_cooldown_seconds", 300))
        factor = float(self._initiative_config.get("type_backoff_factor", 2.0))
        cap = float(self._initiative_config.get("type_max_cooldown_seconds", 14400))
        streak_index = max(0, consecutive_noops - threshold)
        raw = base * (factor ** streak_index)
        return min(raw, cap)

    @staticmethod
    def _is_maintenance_scan_action(action_type: str) -> bool:
        return str(action_type or "").strip() in {"check_tasks", "red_team_check"}

    def _should_roll_up_maintenance_noop(
        self,
        action_type: str,
        outcome: str,
        state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        atype = str(action_type or "").strip()
        if not self._is_maintenance_scan_action(atype):
            return False
        normalized_outcome = str(outcome or "").strip()
        if normalized_outcome not in {
            "action_success_noop",
            "action_success_skipped",
            "action_success_not_due",
        }:
            return False
        if state is None:
            state = self._ensure_initiative_runtime()
        stats = state.get("action_type_stats")
        if not isinstance(stats, dict):
            return False
        type_stat = stats.get(atype)
        if not isinstance(type_stat, dict):
            return False
        if str(type_stat.get("last_outcome") or "").strip() != normalized_outcome:
            return False
        threshold = int(self._initiative_config.get("type_noop_streak_threshold", 5))
        return int(type_stat.get("consecutive_noops", 0) or 0) >= threshold

    def _should_suppress_maintenance_skip_event(self, action_type: str, outcome: str) -> bool:
        try:
            state = self._ensure_initiative_runtime()
        except Exception:
            return False
        return self._should_roll_up_maintenance_noop(action_type, outcome, state=state)

    def _should_skip_sentinel_recommendation(self, action_type: str) -> Tuple[bool, str]:
        atype = str(action_type or "").strip()
        if atype == "check_tasks":
            probe = self._probe_check_tasks_due_work()
            if not bool(probe.get("due")):
                return True, str(probe.get("reason") or "no_overdue_tasks")
        elif atype == "red_team_check":
            probe = self._probe_red_team_due_work()
            if not bool(probe.get("due")):
                return True, str(probe.get("reason") or "not_due")
        else:
            return False, ""

        on_cooldown, cooldown_reason = self._is_action_type_on_cooldown(atype)
        if on_cooldown:
            return True, cooldown_reason
        return False, ""

    def _handle_sentinel_trigger(
        self,
        trigger: Optional[Trigger],
        events: Optional[List[Event]],
    ) -> Dict[str, Any]:
        if not isinstance(trigger, Trigger):
            return {"skip_recommendation": False}
        action_template = getattr(trigger, "action_template", None)
        action_type = ""
        if isinstance(action_template, dict):
            action_type = str(action_template.get("type") or action_template.get("action_type") or "").strip()
        skip_recommendation, reason = self._should_skip_sentinel_recommendation(action_type)
        if not skip_recommendation:
            return {"skip_recommendation": False}
        if self.config.debug:
            logger.debug(
                "[DEBUG] Sentinel recommendation skipped before creation: %s (%s)",
                action_type,
                reason,
            )
        return {"skip_recommendation": True, "reason": reason, "action_type": action_type}

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
        signal_type: str = "",
    ) -> None:
        state = self._ensure_initiative_runtime()
        action_type = str(recommendation.action_type or "").strip()
        suppress_noop_event = self._should_suppress_internal_cadence_noop_event(
            action_type=action_type,
            outcome=str(signal_type or "").strip(),
            state=state,
        )
        payload = recommendation.payload if isinstance(recommendation.payload, dict) else {}
        raw_conversation_id = payload.get("conversation_id") or payload.get("vera_conversation_id") or ""
        conversation_id = str(raw_conversation_id).strip()
        noop_signals = {
            "action_success_noop",
            "action_success_skipped",
            "action_success_not_due",
        }
        if self._is_internal_cadence_action(action_type) and str(signal_type or "").strip() in noop_signals:
            self._save_initiative_state(state)
            return
        action_row = {
            "ts_utc": _utc_iso(),
            "action_id": recommendation.action_id,
            "trigger_id": recommendation.trigger_id,
            "action_type": recommendation.action_type,
            "priority": recommendation.priority.name,
            "conversation_id": conversation_id,
            "success": bool(success),
            "signal_type": str(signal_type or "").strip(),
            "result_preview": str(result)[:120] if result is not None else "",
        }
        recent = list(state.get("recent_actions") or [])
        recent.append(action_row)
        limit = int(self._initiative_config.get("max_action_memory", 40))
        if len(recent) > limit:
            recent = recent[-limit:]
        state["recent_actions"] = recent
        self._save_initiative_state(state)
        if not suppress_noop_event:
            self._append_initiative_event({
                "type": "proactive_action_recorded",
                "action_type": recommendation.action_type,
                "priority": recommendation.priority.name,
                "success": bool(success),
                "conversation_id": conversation_id,
            })

    def _recent_action_feedback_eligible(self, row: Dict[str, Any]) -> bool:
        if not isinstance(row, dict):
            return False
        action_type = str(row.get("action_type") or "").strip()
        if not self._is_internal_cadence_action(action_type):
            return True
        signal_type = str(row.get("signal_type") or "").strip()
        if signal_type in {
            "action_success_noop",
            "action_success_skipped",
            "action_success_not_due",
        }:
            return False
        preview = str(row.get("result_preview") or "")
        if "attempted': False" in preview and ("no_due_work" in preview or "not_due" in preview):
            return False
        if "'skipped': True" in preview:
            return False
        return True

    def _should_suppress_internal_cadence_noop_event(
        self,
        action_type: str,
        outcome: str,
        state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        atype = str(action_type or "").strip()
        if not self._is_internal_cadence_action(atype):
            return False
        if str(outcome or "").strip() not in {
            "action_success_noop",
            "action_success_skipped",
            "action_success_not_due",
        }:
            return False
        if state is None:
            state = self._ensure_initiative_runtime()
        stats = state.get("action_type_stats")
        if not isinstance(stats, dict):
            return False
        type_stat = stats.get(atype)
        if not isinstance(type_stat, dict):
            return False
        last_outcome = str(type_stat.get("last_outcome") or "").strip()
        if last_outcome != str(outcome or "").strip():
            return False
        last_attempt = _parse_iso_utc(str(type_stat.get("last_attempt_utc") or ""))
        if last_attempt is None:
            return False
        interval_seconds = self._parse_int_env(
            "VERA_INTERNAL_CADENCE_NOOP_EVENT_INTERVAL_SECONDS",
            300,
            minimum=30,
        )
        age_seconds = (_utc_now() - last_attempt).total_seconds()
        return 0 <= age_seconds < float(interval_seconds)

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
        suppress_noop_event = self._should_suppress_internal_cadence_noop_event(
            atype,
            outcome,
            state=state,
        )
        roll_up_maintenance_noop = self._should_roll_up_maintenance_noop(
            atype,
            outcome,
            state=state,
        )

        ts["last_attempt_utc"] = _utc_iso()
        ts["last_outcome"] = outcome

        # Internal cadence actions (for example autonomy_cycle) must run on
        # schedule and should never self-throttle via initiative cooldown gates.
        if self._is_internal_cadence_action(atype):
            if outcome == "action_failure":
                ts["total_failures"] = int(ts.get("total_failures", 0)) + 1
            elif outcome == "action_success":
                ts["total_successes"] = int(ts.get("total_successes", 0)) + 1
            ts["consecutive_failures"] = 0
            ts["consecutive_noops"] = 0
            ts["cooldown_until_utc"] = None
            self._save_initiative_state(state)
            if not suppress_noop_event:
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
            if not roll_up_maintenance_noop:
                ts["total_noops"] = int(ts.get("total_noops", 0)) + 1
            cooldown_secs = self._compute_noop_cooldown_seconds(ts["consecutive_noops"])
            if cooldown_secs > 0:
                if mood is None:
                    mood = self._current_mood()
                multiplier = self._cooldown_multiplier_for_mood(mood)
                ts["cooldown_until_utc"] = (
                    _utc_now() + timedelta(seconds=cooldown_secs * multiplier)
                ).isoformat().replace("+00:00", "Z")

        self._save_initiative_state(state)
        if not suppress_noop_event and not roll_up_maintenance_noop:
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
            if not self._recent_action_feedback_eligible(row):
                continue
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

        if (
            str(getattr(recommendation, "action_type", "") or "").strip() == "autonomy_cycle"
            and isinstance(result, dict)
            and result.get("scheduled") is True
        ):
            return 0.0, "action_success_skipped"

        if recommendation.action_type == "check_tasks":
            overdue_count = int((result or {}).get("overdue_count", 0)) if isinstance(result, dict) else 0
            if overdue_count <= 0:
                return 0.0, "action_success_noop"
        if isinstance(result, dict):
            if result.get("attempted") is False:
                reason = str(result.get("reason") or "").strip().lower()
                if reason in {"no_due_work", "not_due"}:
                    return 0.0, "action_success_not_due"
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

    def _workflow_call_reserve_active(self) -> Tuple[bool, int, int]:
        guard = object.__getattribute__(self, "__dict__").get("_budget_guard")
        if guard is None:
            return False, 0, 0
        reserve_raw = str(os.getenv("VERA_AUTONOMY_WORKFLOW_CALL_RESERVE", "8") or "8").strip()
        try:
            reserve = max(0, int(reserve_raw))
        except Exception:
            reserve = 8
        if reserve <= 0:
            return False, 0, 0
        try:
            if hasattr(guard, "_refresh_config"):
                guard._refresh_config()
            config = getattr(guard, "config", None)
            daily_calls = int(getattr(config, "daily_call_budget", -1))
            if daily_calls < 0:
                return False, 0, reserve
            state = guard._load_state() if hasattr(guard, "_load_state") else {}
            used_calls = int((state or {}).get("calls", 0) or 0)
        except Exception:
            return False, 0, reserve
        remaining_calls = max(0, daily_calls - used_calls)
        return remaining_calls <= reserve, remaining_calls, reserve

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

    @staticmethod
    def _classify_workflow_response(response_text: str) -> str:
        text = str(response_text or "").strip()
        if not text:
            return "completed"
        lowered = text.lower()
        if re.match(r"^\s*\**\s*blocked\s*:", lowered):
            return "blocked"
        if re.match(r"^\s*\**\s*completed\s*:", lowered):
            return "completed"
        if "requires user" in lowered or "need user" in lowered or "missing auth" in lowered:
            return "blocked"
        return "completed"

    @staticmethod
    def _autonomy_task_tokens(text: str) -> set[str]:
        stopwords = {
            "the", "and", "for", "with", "that", "this", "from", "into", "then",
            "use", "using", "first", "current", "determine", "concrete", "step",
            "steps", "take", "now", "safe", "helpful", "inspect", "reviewed",
            "review", "status", "task", "surface", "week1", "external",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(token) >= 4 and token not in stopwords
        }

    def _autonomy_workflow_stale_seconds(self) -> int:
        raw = str(os.getenv("VERA_AUTONOMY_WORKFLOW_STALE_SECONDS", "180") or "180").strip()
        try:
            return max(30, int(raw))
        except Exception:
            return 180

    def _is_stale_autonomy_workflow_task(self, task: Any) -> bool:
        if task is None:
            return False
        status_value = str(getattr(task, "status", "") or "").split(".")[-1].lower()
        if status_value != TaskStatus.IN_PROGRESS.value:
            return False
        updated = getattr(task, "updated", None)
        if not isinstance(updated, datetime):
            return False
        try:
            age_seconds = (datetime.now() - updated).total_seconds()
        except Exception:
            return False
        return age_seconds >= float(self._autonomy_workflow_stale_seconds())

    def _recover_stale_autonomy_workflow_task(self, task: Any, *, reason: str) -> Any:
        master_list = getattr(self, "master_list", None)
        if master_list is None or not hasattr(master_list, "update_status") or task is None:
            return task
        if not self._is_stale_autonomy_workflow_task(task):
            return task
        task_id = str(getattr(task, "id", "") or "").strip()
        if not task_id:
            return task
        note = f"Recovered stale autonomy workflow before reuse ({reason})"
        try:
            master_list.update_status(task_id, TaskStatus.PENDING, notes=note)
            refreshed = master_list.get_by_id(task_id) if hasattr(master_list, "get_by_id") else None
            return refreshed if refreshed is not None else task
        except Exception:
            return task

    def _ensure_task_surface_verifier_note(
        self,
        task_id: str,
        *,
        outcome: str,
        autonomy_work_item_id: str = "",
        week1_stage: str = "",
    ) -> bool:
        normalized_task_id = str(task_id or "").strip()
        master_list = getattr(self, "master_list", None)
        if not normalized_task_id or master_list is None or not hasattr(master_list, "get_by_id") or not hasattr(master_list, "update_task"):
            return False
        try:
            task = master_list.get_by_id(normalized_task_id)
        except Exception:
            task = None
        if task is None:
            return False
        existing_notes = str(getattr(task, "notes", "") or "")
        marker = f"[STATE-SYNC-VERIFIED:{normalized_task_id}]"
        if marker in existing_notes:
            return False
        details: List[str] = [marker, f"outcome={outcome}"]
        if autonomy_work_item_id:
            details.append(f"awj={autonomy_work_item_id}")
        if week1_stage:
            details.append(f"stage={week1_stage}")
        line = " ".join(details)
        new_notes = f"{existing_notes.rstrip()}\n\n{line}".strip() if existing_notes.strip() else line
        try:
            master_list.update_task(normalized_task_id, notes=new_notes)
            return True
        except Exception:
            return False

    def _find_reusable_autonomy_task(self, action_text: str) -> Optional[Any]:
        master_list = getattr(self, "master_list", None)
        if master_list is None or not hasattr(master_list, "parse"):
            return None
        try:
            tasks = list(master_list.parse() or [])
        except Exception:
            return None
        if not tasks:
            return None

        action_tokens = self._autonomy_task_tokens(action_text)
        if not action_tokens:
            return None

        best_task = None
        best_score = 0.0
        for task in tasks:
            if getattr(task, "status", None) != TaskStatus.IN_PROGRESS:
                continue
            tags = {str(tag).strip().lower() for tag in (getattr(task, "tags", None) or [])}
            if not {"inner-life", "autonomy", "workflow"}.issubset(tags):
                continue
            task = self._recover_stale_autonomy_workflow_task(task, reason="token_overlap_reuse")
            task_text = " ".join(
                str(value or "")
                for value in (
                    getattr(task, "title", ""),
                    getattr(task, "description", ""),
                    getattr(task, "notes", ""),
                )
            )
            task_tokens = self._autonomy_task_tokens(task_text)
            if not task_tokens:
                continue
            overlap = len(action_tokens & task_tokens)
            if overlap <= 0:
                continue
            score = overlap / max(1, min(len(action_tokens), len(task_tokens)))
            if score > best_score:
                best_task = task
                best_score = score

        if best_task is not None:
            task_text = " ".join(
                str(value or "")
                for value in (
                    getattr(best_task, "title", ""),
                    getattr(best_task, "description", ""),
                    getattr(best_task, "notes", ""),
                )
            )
            overlap_count = len(action_tokens & self._autonomy_task_tokens(task_text))
            if overlap_count >= 2 and best_score >= 0.18:
                return best_task
        return None

    def _resolve_preferred_autonomy_task(self, task_id: str) -> Optional[Any]:
        preferred_id = str(task_id or "").strip()
        if not preferred_id:
            return None
        master_list = getattr(self, "master_list", None)
        if master_list is None or not hasattr(master_list, "get_by_id"):
            return None
        try:
            task = master_list.get_by_id(preferred_id)
        except Exception:
            return None
        if task is None:
            return None
        task = self._recover_stale_autonomy_workflow_task(task, reason="preferred_task_reuse")
        status_value = str(getattr(task, "status", "") or "").split(".")[-1].lower()
        if status_value not in {
            TaskStatus.PENDING.value,
            TaskStatus.IN_PROGRESS.value,
            TaskStatus.BLOCKED.value,
        }:
            return None
        tags = {str(tag).strip().lower() for tag in (getattr(task, "tags", None) or [])}
        if not {"inner-life", "autonomy", "workflow"}.issubset(tags):
            return None
        return task

    def _classify_executor_failure(self, result: Dict[str, Any]) -> Dict[str, Any]:
        reason = str(result.get("reason") or "").strip().lower()
        stderr = str(result.get("stderr") or "").strip().lower()
        stdout = str(result.get("stdout") or "").strip().lower()
        returncode = int(result.get("returncode") or 0)
        merged = " ".join([reason, stderr, stdout]).strip()

        if "timeout" in reason:
            return {"failure_class": "transient_timeout", "retryable": True}
        if any(token in merged for token in ("oauth", "auth", "unauthorized", "forbidden", "401", "403")):
            return {"failure_class": "auth_failure", "retryable": False}
        if "429" in merged or "rate limit" in merged:
            return {"failure_class": "rate_limited", "retryable": True}
        if any(token in merged for token in ("connection refused", "connection reset", "temporarily unavailable", "name or service not known", "network")):
            return {"failure_class": "transport_error", "retryable": True}
        if any(token in reason for token in ("missing_", "not_found")) or any(token in merged for token in ("no such file", "not found")):
            return {"failure_class": "permanent_missing_dependency", "retryable": False}
        if returncode in {-15, -9} and not merged:
            return {"failure_class": "executor_cancelled", "retryable": True}
        if returncode != 0 and not merged:
            return {"failure_class": "executor_nonzero_exit", "retryable": True}
        return {"failure_class": "executor_failure", "retryable": False}

    async def _run_followthrough_executor_once(self) -> Dict[str, Any]:
        job_id = "executor.followthrough"
        lane_key = "executor:followthrough"
        root = Path(__file__).resolve().parents[3]
        script = root / "scripts" / "vera_followthrough_executor.py"
        begin = self.runplane.begin_run(
            job_id=job_id,
            lane_key=lane_key,
            trigger="autonomy_cycle",
            kind="followthrough_executor",
            metadata={"script_path": str(script)},
            max_attempts=4,
        )
        if not bool(begin.get("ok")):
            return {
                "ok": False,
                "reason": str(begin.get("reason") or "lane_busy"),
                "lane_key": lane_key,
                "job_id": job_id,
                "active_run_id": begin.get("active_run_id", ""),
            }
        run_id = str(begin.get("run_id") or "")

        if not script.exists():
            result = {"ok": False, "reason": "missing_followthrough_executor"}
            summary = self.runplane.complete_run(
                job_id=job_id,
                run_id=run_id,
                ok=False,
                result=result,
                failure_class="permanent_missing_dependency",
                retryable=False,
                status="failed",
            )
            result["run_id"] = run_id
            result["runplane"] = summary
            return result
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
                result = {
                    "ok": False,
                    "reason": "timeout",
                    "returncode": int(proc.returncode if proc.returncode is not None else -9),
                    "stdout": (stdout.decode(errors="replace") if isinstance(stdout, (bytes, bytearray)) else str(stdout or ""))[:500],
                    "stderr": (stderr.decode(errors="replace") if isinstance(stderr, (bytes, bytearray)) else str(stderr or ""))[:500],
                }
                summary = self.runplane.complete_run(
                    job_id=job_id,
                    run_id=run_id,
                    ok=False,
                    result=result,
                    failure_class="transient_timeout",
                    retryable=True,
                    status="failed",
                )
                result["run_id"] = run_id
                result["runplane"] = summary
                return result
            except asyncio.CancelledError:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                raise
            result = {
                "ok": proc.returncode == 0,
                "returncode": int(proc.returncode),
                "stdout": (stdout.decode(errors="replace") if isinstance(stdout, (bytes, bytearray)) else str(stdout or ""))[:500],
                "stderr": (stderr.decode(errors="replace") if isinstance(stderr, (bytes, bytearray)) else str(stderr or ""))[:500],
            }
            if result["ok"]:
                summary = self.runplane.complete_run(
                    job_id=job_id,
                    run_id=run_id,
                    ok=True,
                    result=result,
                    status="delivered",
                )
            else:
                classification = self._classify_executor_failure(result)
                status_value = "deferred" if str(classification.get("failure_class") or "") == "executor_cancelled" else "failed"
                summary = self.runplane.complete_run(
                    job_id=job_id,
                    run_id=run_id,
                    ok=False,
                    result=result,
                    failure_class=str(classification.get("failure_class") or "executor_failure"),
                    retryable=bool(classification.get("retryable")),
                    status=status_value,
                )
            result["run_id"] = run_id
            result["runplane"] = summary
            return result
        except Exception as exc:
            result = {"ok": False, "reason": str(exc)}
            classification = self._classify_executor_failure(result)
            status_value = "deferred" if str(classification.get("failure_class") or "") == "executor_cancelled" else "failed"
            summary = self.runplane.complete_run(
                job_id=job_id,
                run_id=run_id,
                ok=False,
                result=result,
                failure_class=str(classification.get("failure_class") or "executor_failure"),
                retryable=bool(classification.get("retryable")),
                status=status_value,
            )
            result["run_id"] = run_id
            result["runplane"] = summary
            return result

    async def _run_week1_executor_once(self, trigger: str = "autonomy_cycle") -> Dict[str, Any]:
        job_id = "executor.week1"
        lane_key = "executor:week1"
        root = Path(__file__).resolve().parents[3]
        script = root / "scripts" / "vera_week1_executor.py"
        begin = self.runplane.begin_run(
            job_id=job_id,
            lane_key=lane_key,
            trigger=trigger,
            kind="week1_executor",
            metadata={"script_path": str(script)},
            max_attempts=6,
        )
        if not bool(begin.get("ok")):
            return {
                "ok": False,
                "reason": str(begin.get("reason") or "lane_busy"),
                "lane_key": lane_key,
                "job_id": job_id,
                "active_run_id": begin.get("active_run_id", ""),
            }
        run_id = str(begin.get("run_id") or "")

        if not script.exists():
            result = {"ok": False, "reason": "missing_week1_executor"}
            summary = self.runplane.complete_run(
                job_id=job_id,
                run_id=run_id,
                ok=False,
                result=result,
                failure_class="permanent_missing_dependency",
                retryable=False,
                status="failed",
            )
            result["run_id"] = run_id
            result["runplane"] = summary
            return result
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
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(root),
            )
            timeout_seconds = max(120, int(self._autonomy_config.get("week1_executor_timeout_seconds", 600)))
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                if proc.returncode is None:
                    proc.kill()
                    stdout, stderr = await proc.communicate()
                else:
                    stdout = b""
                    stderr = b""
                result = {
                    "ok": False,
                    "reason": "timeout",
                    "returncode": int(proc.returncode if proc.returncode is not None else -9),
                    "stdout": (
                        stdout.decode(errors="replace")
                        if isinstance(stdout, (bytes, bytearray))
                        else str(stdout or "")
                    )[:500],
                    "stderr": (
                        stderr.decode(errors="replace")
                        if isinstance(stderr, (bytes, bytearray))
                        else str(stderr or "")
                    )[:500],
                }
                summary = self.runplane.complete_run(
                    job_id=job_id,
                    run_id=run_id,
                    ok=False,
                    result=result,
                    failure_class="transient_timeout",
                    retryable=True,
                    status="failed",
                )
                result["run_id"] = run_id
                result["runplane"] = summary
                return result
            except asyncio.CancelledError:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                raise
            result = {
                "ok": proc.returncode == 0,
                "returncode": int(proc.returncode),
                "stdout": (
                    stdout.decode(errors="replace")
                    if isinstance(stdout, (bytes, bytearray))
                    else str(stdout or "")
                )[:500],
                "stderr": (
                    stderr.decode(errors="replace")
                    if isinstance(stderr, (bytes, bytearray))
                    else str(stderr or "")
                )[:500],
            }
            stdout_text = (
                stdout.decode(errors="replace")
                if isinstance(stdout, (bytes, bytearray))
                else str(stdout or "")
            )
            try:
                parsed = json.loads(stdout_text)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                result["executor_summary"] = parsed
                for key in (
                    "actions_attempted",
                    "events_report",
                    "top_tasks",
                    "timezone",
                    "local_now",
                    "import_result",
                    "state_path",
                    "event_log_path",
                    "dry_run",
                ):
                    if key in parsed:
                        result[key] = parsed.get(key)
                events_report = parsed.get("events_report")
                if isinstance(events_report, list):
                    delivery_summary = {
                        "ok_count": 0,
                        "partial_ok_count": 0,
                        "failed_count": 0,
                        "deferred_count": 0,
                        "stale_count": 0,
                    }
                    for row in events_report:
                        if not isinstance(row, dict):
                            continue
                        status_value = str(row.get("status") or "")
                        if status_value == "ok":
                            delivery_summary["ok_count"] += 1
                        elif status_value.startswith("partial_ok"):
                            delivery_summary["partial_ok_count"] += 1
                        elif status_value == "deferred_not_ready":
                            delivery_summary["deferred_count"] += 1
                        elif status_value.startswith("skipped_stale"):
                            delivery_summary["stale_count"] += 1
                        elif status_value:
                            delivery_summary["failed_count"] += 1
                    result["delivery_summary"] = delivery_summary
                    if delivery_summary["failed_count"] > 0:
                        result["delivery_status"] = "failed"
                    elif delivery_summary["deferred_count"] > 0:
                        result["delivery_status"] = "deferred_not_ready"
                    elif delivery_summary["partial_ok_count"] > 0:
                        result["delivery_status"] = "partial_ok"
                    elif delivery_summary["ok_count"] > 0:
                        result["delivery_status"] = "ok"
                    elif delivery_summary["stale_count"] > 0:
                        result["delivery_status"] = "skipped_stale"
            delivery_summary = result.get("delivery_summary") if isinstance(result.get("delivery_summary"), dict) else {}
            delivery_status = str(result.get("delivery_status") or "").strip()
            if result["ok"] and delivery_summary:
                if int(delivery_summary.get("failed_count", 0) or 0) > 0:
                    summary = self.runplane.complete_run(
                        job_id=job_id,
                        run_id=run_id,
                        ok=False,
                        result=result,
                        failure_class="delivery_failed",
                        retryable=True,
                        status="failed",
                    )
                elif int(delivery_summary.get("deferred_count", 0) or 0) > 0:
                    summary = self.runplane.complete_run(
                        job_id=job_id,
                        run_id=run_id,
                        ok=False,
                        result=result,
                        failure_class="delivery_not_ready",
                        retryable=True,
                        status="deferred",
                    )
                else:
                    summary = self.runplane.complete_run(
                        job_id=job_id,
                        run_id=run_id,
                        ok=True,
                        result=result,
                        status="delivered",
                    )
            elif result["ok"]:
                summary = self.runplane.complete_run(
                    job_id=job_id,
                    run_id=run_id,
                    ok=True,
                    result=result,
                    status="delivered",
                )
            else:
                classification = self._classify_executor_failure(result)
                status_value = "deferred" if str(classification.get("failure_class") or "") == "executor_cancelled" else "failed"
                summary = self.runplane.complete_run(
                    job_id=job_id,
                    run_id=run_id,
                    ok=False,
                    result=result,
                    failure_class=str(classification.get("failure_class") or "executor_failure"),
                    retryable=bool(classification.get("retryable")),
                    status=status_value,
                )
            result["run_id"] = run_id
            result["runplane"] = summary
            return result
        except Exception as exc:
            result = {"ok": False, "reason": str(exc)}
            classification = self._classify_executor_failure(result)
            status_value = "deferred" if str(classification.get("failure_class") or "") == "executor_cancelled" else "failed"
            summary = self.runplane.complete_run(
                job_id=job_id,
                run_id=run_id,
                ok=False,
                result=result,
                failure_class=str(classification.get("failure_class") or "executor_failure"),
                retryable=bool(classification.get("retryable")),
                status=status_value,
            )
            result["run_id"] = run_id
            result["runplane"] = summary
            return result

    async def _probe_week1_executor_due_work(self) -> Dict[str, Any]:
        root = Path(__file__).resolve().parents[3]
        script = root / "scripts" / "vera_week1_executor.py"
        if not script.exists():
            return {"ok": False, "reason": "missing_week1_executor"}
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
            "--probe-due",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(root),
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
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
                    "stdout": (
                        stdout.decode(errors="replace")
                        if isinstance(stdout, (bytes, bytearray))
                        else str(stdout or "")
                    )[:500],
                    "stderr": (
                        stderr.decode(errors="replace")
                        if isinstance(stderr, (bytes, bytearray))
                        else str(stderr or "")
                    )[:500],
                }
            result = {
                "ok": proc.returncode == 0,
                "returncode": int(proc.returncode),
                "stdout": (
                    stdout.decode(errors="replace")
                    if isinstance(stdout, (bytes, bytearray))
                    else str(stdout or "")
                )[:4000],
                "stderr": (
                    stderr.decode(errors="replace")
                    if isinstance(stderr, (bytes, bytearray))
                    else str(stderr or "")
                )[:1000],
            }
            if result["ok"]:
                try:
                    parsed = json.loads(result["stdout"] or "{}")
                except Exception:
                    parsed = {}
                if isinstance(parsed, dict):
                    result.update(parsed)
                else:
                    result["ok"] = False
                    result["reason"] = "invalid_probe_output"
            return result
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    def _probe_week1_executor_due_work_sync(self) -> Dict[str, Any]:
        root = Path(__file__).resolve().parents[3]
        script = root / "scripts" / "vera_week1_executor.py"
        if not script.exists():
            return {"ok": False, "reason": "missing_week1_executor"}
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
            "--probe-due",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
                cwd=str(root),
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "reason": "timeout",
                "returncode": 124,
                "stdout": str(exc.stdout or "")[:500],
                "stderr": str(exc.stderr or "")[:500],
            }
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}
        result = {
            "ok": proc.returncode == 0,
            "returncode": int(proc.returncode),
            "stdout": str(proc.stdout or "")[:4000],
            "stderr": str(proc.stderr or "")[:1000],
        }
        if result["ok"]:
            try:
                parsed = json.loads(result["stdout"] or "{}")
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                result.update(parsed)
            else:
                result["ok"] = False
                result["reason"] = "invalid_probe_output"
        return result

    async def _run_week1_due_check_async(self, trigger: str = "week1_due_check") -> Dict[str, Any]:
        due_probe = await self._probe_week1_executor_due_work()
        due_count = 0
        if isinstance(due_probe, dict):
            try:
                due_count = int(due_probe.get("due_count", 0) or 0)
            except Exception:
                due_count = 0
        if due_count <= 0:
            return {
                "ok": True,
                "reason": "no_due_work",
                "attempted": False,
                "due_probe": due_probe if isinstance(due_probe, dict) else {},
            }
        delivery_dependency_probe = self._probe_week1_delivery_dependencies_ready()
        if not bool(delivery_dependency_probe.get("ready")):
            return {
                "ok": False,
                "reason": str(
                    delivery_dependency_probe.get("reason") or "delivery_dependencies_pending"
                ),
                "attempted": False,
                "due_probe": due_probe if isinstance(due_probe, dict) else {},
                "delivery_dependencies": delivery_dependency_probe,
            }

        min_spacing_seconds = self._parse_int_env(
            "VERA_WEEK1_DUE_CHECK_MIN_SPACING_SECONDS",
            45,
            minimum=5,
        )
        state = self._load_autonomy_state()
        last_week1 = _parse_iso_utc(str(state.get("last_week1_executor_utc") or ""))
        now_utc = _utc_now()
        seconds_since_last_week1 = (
            (now_utc - last_week1).total_seconds() if last_week1 is not None else None
        )
        if (
            seconds_since_last_week1 is not None
            and seconds_since_last_week1 < float(min_spacing_seconds)
        ):
            return {
                "ok": True,
                "reason": "min_spacing_active",
                "attempted": False,
                "seconds_since_last_week1_executor": round(seconds_since_last_week1, 3),
                "min_spacing_seconds": int(min_spacing_seconds),
                "due_probe": due_probe if isinstance(due_probe, dict) else {},
            }

        week1_result = await self._run_week1_executor_once(trigger=trigger)
        if not isinstance(week1_result, dict):
            week1_result = {"ok": False, "reason": "invalid_week1_executor_result"}
        week1_result["attempted"] = True
        week1_result["due_probe"] = {
            "due_count": due_count,
            "due_events": list(due_probe.get("due_events", [])[:3]) if isinstance(due_probe, dict) else [],
        }
        state["last_week1_executor_utc"] = _utc_iso()
        self._save_autonomy_state(state)
        return week1_result

    async def _probe_followthrough_due_work(self) -> Dict[str, Any]:
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
            "--probe-due",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(root),
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
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
                    "stdout": (
                        stdout.decode(errors="replace")
                        if isinstance(stdout, (bytes, bytearray))
                        else str(stdout or "")
                    )[:500],
                    "stderr": (
                        stderr.decode(errors="replace")
                        if isinstance(stderr, (bytes, bytearray))
                        else str(stderr or "")
                    )[:500],
                }
            result = {
                "ok": proc.returncode == 0,
                "returncode": int(proc.returncode),
                "stdout": (
                    stdout.decode(errors="replace")
                    if isinstance(stdout, (bytes, bytearray))
                    else str(stdout or "")
                )[:4000],
                "stderr": (
                    stderr.decode(errors="replace")
                    if isinstance(stderr, (bytes, bytearray))
                    else str(stderr or "")
                )[:1000],
            }
            if result["ok"]:
                try:
                    parsed = json.loads(result["stdout"] or "{}")
                except Exception:
                    parsed = {}
                if isinstance(parsed, dict):
                    result.update(parsed)
                else:
                    result["ok"] = False
                    result["reason"] = "invalid_probe_output"
            return result
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    async def _execute_inner_action_workflow(
        self,
        action_text: str,
        run_id: str,
        *,
        additional_context: str = "",
        preferred_task_id: str = "",
        tool_choice: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if not action_text.strip():
            return {"ok": False, "reason": "empty_action_text"}
        title = self._derive_task_title(action_text)
        due = self._infer_due_from_action(action_text)
        task = self._resolve_preferred_autonomy_task(preferred_task_id)
        if task is None:
            task = self._find_reusable_autonomy_task(action_text)
        if task is None:
            task = self.master_list.add_task(
                title=title,
                priority=TaskPriority.HIGH,
                description=action_text[:800],
                due=due,
                tags=["inner-life", "autonomy", "workflow"],
                notes=f"Generated by inner life run {run_id}",
            )
        else:
            try:
                self.master_list.update_task(
                    task.id,
                    due=due,
                    notes=f"Autonomy workflow resumed by inner life run {run_id}",
                )
                refreshed = self.master_list.get_by_id(task.id)
                if refreshed is not None:
                    task = refreshed
            except Exception:
                logger.debug("Suppressed Exception in proactive_manager")
        self.master_list.update_status(task.id, TaskStatus.IN_PROGRESS, notes="Autonomy workflow execution started")

        context_block = str(additional_context or "").strip()
        execution_prompt = (
            "You initiated this ACTION during inner life reflection:\n"
            f"{action_text}\n\n"
        )
        if context_block:
            execution_prompt += (
                "Canonical task/task-surface context to use directly for this execution:\n"
                f"{context_block}\n\n"
            )
        execution_prompt += (
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
                tool_choice=tool_choice,
            )
        except Exception as exc:
            self.master_list.update_status(task.id, TaskStatus.BLOCKED, notes=f"Workflow execution error: {exc}")
            return {"ok": False, "task_id": task.id, "reason": str(exc)}

        self._record_estimated_usage("autonomy_workflow", execution_prompt, response_text or "")
        workflow_status = self._classify_workflow_response(response_text or "")
        if workflow_status == "blocked":
            self.master_list.update_status(task.id, TaskStatus.BLOCKED, notes=(response_text or "")[:1200])
            status = "blocked"
            ok = False
        else:
            self.master_list.update_status(task.id, TaskStatus.COMPLETED, notes=(response_text or "")[:1200])
            status = "completed"
            ok = True

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

        result: Dict[str, Any] = {
            "ok": ok,
            "task_id": task.id,
            "status": status,
            "response_preview": (response_text or "")[:280],
        }
        if not ok:
            result["reason"] = "blocked"
        return result

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
        "reflect",
        "week1_due_check",
    })

    @staticmethod
    def _extract_tool_result_text(result: Any) -> str:
        if isinstance(result, str):
            return result
        if not isinstance(result, dict):
            return ""
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            for key in ("result", "content", "text"):
                value = structured.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        content = result.get("content")
        if isinstance(content, list):
            for entry in content:
                if isinstance(entry, dict):
                    text = entry.get("text")
                    if isinstance(text, str) and text.strip():
                        return text
        for key in ("result", "text", "message"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    @staticmethod
    def _parse_calendar_event_listing(text: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None
        header = re.compile(r'^- "(?P<summary>.+?)" \(Starts: (?P<start>.+?), Ends: (?P<end>.+?)\)$')
        event_id = re.compile(r"^ID:\s*(?P<event_id>[^|]+?)\s+\|\s+Link:\s*(?P<link>.+)$")

        for raw_line in str(text or "").splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            header_match = header.match(stripped)
            if header_match:
                if current:
                    rows.append(current)
                current = {
                    "summary": header_match.group("summary").strip(),
                    "start_time": header_match.group("start").strip(),
                    "end_time": header_match.group("end").strip(),
                    "location": "",
                    "id": "",
                    "link": "",
                }
                continue
            if current is None:
                continue
            if stripped.startswith("Location: "):
                current["location"] = stripped.split("Location: ", 1)[1].strip()
                continue
            id_match = event_id.match(stripped)
            if id_match:
                current["id"] = id_match.group("event_id").strip()
                current["link"] = id_match.group("link").strip()

        if current:
            rows.append(current)
        return rows

    async def _check_calendar_proactive(self) -> Optional[Dict[str, Any]]:
        """Poll Google Calendar for upcoming events and alert if near."""
        # Default-on for out-of-box proactive reliability; operators can disable with VERA_CALENDAR_PROACTIVE=0.
        if os.getenv("VERA_CALENDAR_PROACTIVE", "1") != "1":
            return None

        lookahead = int(os.getenv("VERA_CALENDAR_LOOKAHEAD_MINUTES", "120"))
        alert_minutes = int(os.getenv("VERA_CALENDAR_ALERT_MINUTES", "15"))
        default_calendar_cooldown = min(
            max(60, int(self._autonomy_config.get("pulse_interval_seconds", 300))),
            max(60, alert_minutes * 60),
        )
        calendar_cooldown_seconds = self._parse_int_env(
            "VERA_CALENDAR_PROACTIVE_COOLDOWN_SECONDS",
            default_calendar_cooldown,
            minimum=60,
        )

        # Rate limit: keep polling cadence compatible with the alert window.
        state_path = self._memory_dir / "calendar_alerts_state.json"
        state = safe_json_read(state_path, default={})
        last_poll = _parse_iso_utc(str(state.get("last_poll_utc") or ""))
        now_utc = _utc_now()
        if last_poll and (now_utc - last_poll).total_seconds() < calendar_cooldown_seconds:
            return {
                "ok": True,
                "skipped": True,
                "reason": "cooldown_active",
                "cooldown_seconds": int(calendar_cooldown_seconds),
            }

        # Clear expired alerted event IDs daily
        expiry = _parse_iso_utc(str(state.get("alerted_event_ids_expiry") or ""))
        if not expiry or now_utc > expiry:
            state["alerted_event_ids"] = []
            state["alerted_event_ids_expiry"] = (
                now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1)
            ).isoformat().replace("+00:00", "Z")

        alerted_ids = set(state.get("alerted_event_ids") or [])

        time_max = (now_utc + timedelta(minutes=lookahead)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            tool_result = await self._owner._internal_tool_call_handler(
                "get_events",
                {
                    "time_max": time_max,
                    "max_results": 10,
                    "detailed": True,
                },
            )
        except Exception as exc:
            logger.debug("Calendar proactive check error: %s", exc)
            return {"ok": False, "reason": "calendar_tool_unavailable", "error": str(exc)}

        # Update poll timestamp
        state["last_poll_utc"] = _utc_iso()

        # Try to parse events from the response for near-term alerts
        alerts_sent = []
        try:
            response_text = self._extract_tool_result_text(tool_result)
            events = self._parse_calendar_event_listing(response_text)
            for event in events:
                event_id = str(event.get("id") or event.get("summary") or "")
                if event_id in alerted_ids:
                    continue
                start_str = str(event.get("start_time") or "")
                start_dt = _parse_iso_utc(start_str)
                if start_dt and (start_dt - now_utc).total_seconds() <= alert_minutes * 60:
                    summary = event.get("summary", "Upcoming event")
                    minutes_away = max(0, int((start_dt - now_utc).total_seconds() / 60))
                    alert_msg = f"Reminder: '{summary}' starts in {minutes_away} minutes."
                    location = event.get("location")
                    if location and location != "No Location":
                        alert_msg += f" Location: {location}"

                    try:
                        await self._owner._internal_tool_call_handler(
                            "send_native_push",
                            {
                                "title": "VERA Calendar Alert",
                                "message": alert_msg,
                            },
                        )
                    except Exception:
                        logger.debug("Calendar native push failed for: %s", summary)
                        try:
                            await self._owner._internal_tool_call_handler(
                                "send_mobile_push",
                                {
                                    "title": "VERA Calendar Alert",
                                    "message": alert_msg,
                                },
                            )
                        except Exception:
                            logger.debug("Calendar alert delivery failed for: %s", summary)
                            continue

                    alerted_ids.add(event_id)
                    alerts_sent.append({"event_id": event_id, "summary": summary, "minutes_away": minutes_away})
        except Exception:
            logger.debug("Could not parse calendar events from direct tool response")

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
        queued = []
        suppressed = []
        failed = []
        notified = []
        logged = []
        deferred = []

        for rec in pending[: max_per_cycle * 2]:
            retry_deferred, retry_reason = self._is_recommendation_retry_deferred(rec)
            if retry_deferred:
                deferred.append({"action_id": rec.action_id, "reason": retry_reason})
                continue
            if rec.priority in (ActionPriority.URGENT, ActionPriority.HIGH):
                handlers = getattr(self.sentinel.recommender, "recommendation_handlers", None)
                handler = None
                if isinstance(handlers, dict):
                    handler = handlers.get(rec.action_type)
                if handler is not None:
                    outcome = self.handle_proactive_recommendation(rec) or {}
                    outcome_type = str(outcome.get("outcome") or "logged")
                    if outcome_type in {"executed", "executed_noop"}:
                        executed.append({"action_id": rec.action_id, "result": outcome.get("result", {})})
                    elif outcome_type in {"queued_dnd", "queued_lane"}:
                        queued.append({"action_id": rec.action_id, "reason": str(outcome.get("reason") or outcome_type)})
                    elif outcome_type == "suppressed":
                        suppressed_row = self._record_suppressed_recommendation(
                            rec,
                            str(outcome.get("reason") or ""),
                        )
                        suppressed.append(suppressed_row)
                    elif outcome_type == "deferred":
                        deferred.append(
                            {
                                "action_id": rec.action_id,
                                "reason": str(outcome.get("reason") or "retry_deferred"),
                            }
                        )
                    elif outcome_type == "failed":
                        failed.append({"action_id": rec.action_id, "result": outcome.get("result", {})})
                    else:
                        logged.append(rec.action_id)
                    if len(executed) >= max_per_cycle:
                        break
                    continue
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

            else:
                outcome = self.handle_proactive_recommendation(rec) or {}
                outcome_type = str(outcome.get("outcome") or "logged")
                if outcome_type in {"executed", "executed_noop"}:
                    executed.append({"action_id": rec.action_id, "result": outcome.get("result", {})})
                elif outcome_type in {"queued_dnd", "queued_lane"}:
                    queued.append({"action_id": rec.action_id, "reason": str(outcome.get("reason") or outcome_type)})
                elif outcome_type == "suppressed":
                    suppressed_row = self._record_suppressed_recommendation(
                        rec,
                        str(outcome.get("reason") or ""),
                    )
                    suppressed.append(suppressed_row)
                elif outcome_type == "deferred":
                    deferred.append(
                        {
                            "action_id": rec.action_id,
                            "reason": str(outcome.get("reason") or "retry_deferred"),
                        }
                    )
                elif outcome_type == "failed":
                    failed.append({"action_id": rec.action_id, "result": outcome.get("result", {})})
                elif rec.priority == ActionPriority.NORMAL:
                    notified.append(rec.action_id)
                else:
                    logged.append(rec.action_id)

            if len(executed) >= max_per_cycle:
                break

        bus = getattr(self._owner, "event_bus", None)
        if bus:
            try:
                bus.publish("innerlife.proactive_execution", payload={
                    "processed": len(executed) + len(queued) + len(suppressed) + len(failed) + len(notified) + len(logged),
                    "executed": len(executed),
                    "queued": len(queued),
                    "suppressed": len(suppressed),
                    "failed": len(failed),
                    "notified": len(notified),
                    "logged": len(logged),
                    "deferred": len(deferred),
                }, source="proactive_manager")
            except Exception:
                logger.debug("Failed to publish proactive_execution event")

        pending_after = self.sentinel.recommender.get_pending_recommendations()

        return {
            "processed": len(executed) + len(queued) + len(suppressed) + len(failed) + len(notified) + len(logged),
            "executed": executed,
            "queued": queued,
            "suppressed": suppressed,
            "failed": failed,
            "notified": notified,
            "logged": logged,
            "deferred": deferred,
            "pending_remaining": len(pending_after) if isinstance(pending_after, list) else max(0, len(pending)),
        }

    def _record_suppressed_recommendation(self, recommendation: RecommendedAction, reason: str) -> Dict[str, Any]:
        normalized_reason = str(reason or "").strip()
        recommendation.suppression_count = int(getattr(recommendation, "suppression_count", 0) or 0) + 1
        recommendation.last_suppressed_at = _utc_iso()
        recommendation.last_suppression_reason = normalized_reason

        suppressions_to_ack = self._parse_int_env(
            "VERA_PROACTIVE_SUPPRESSION_AUTO_ACK_COUNT",
            3,
            minimum=1,
        )
        max_age_seconds = self._parse_int_env(
            "VERA_PROACTIVE_SUPPRESSION_AUTO_ACK_MAX_AGE_SECONDS",
            900,
            minimum=60,
        )
        created_at = _parse_iso_utc(str(getattr(recommendation, "created_at", "") or ""))
        age_seconds = 0.0
        if created_at is not None:
            age_seconds = max(0.0, (_utc_now() - created_at).total_seconds())

        transient_suppression = normalized_reason.startswith(
            (
                "duplicate_action_success_cooldown:",
                "duplicate_action_failure_cooldown:",
                "action_type_cooldown:",
                "partner_recently_active:",
            )
        )
        action_type_cooldown_suppression = normalized_reason.startswith("action_type_cooldown:")
        auto_acked = False
        if transient_suppression and not action_type_cooldown_suppression and (
            recommendation.suppression_count >= int(suppressions_to_ack)
            or age_seconds >= float(max_age_seconds)
        ):
            try:
                auto_acked = bool(self.sentinel.recommender.acknowledge(recommendation.action_id))
            except Exception:
                auto_acked = False
        if auto_acked:
            recommendation.retry_not_before = None
        elif transient_suppression:
            recommendation.retry_not_before = self._compute_recommendation_retry_not_before(normalized_reason)
        else:
            recommendation.retry_not_before = None

        row = {
            "action_id": recommendation.action_id,
            "reason": normalized_reason,
            "suppression_count": int(recommendation.suppression_count),
        }
        if age_seconds > 0:
            row["age_seconds"] = int(age_seconds)
        if auto_acked:
            row["auto_acked"] = True
        elif recommendation.retry_not_before:
            row["retry_not_before"] = recommendation.retry_not_before
        return row

    def _is_recommendation_retry_deferred(self, recommendation: RecommendedAction) -> Tuple[bool, str]:
        retry_not_before = _parse_iso_utc(str(getattr(recommendation, "retry_not_before", "") or ""))
        if retry_not_before is None:
            return False, ""
        remaining_seconds = int((retry_not_before - _utc_now()).total_seconds())
        if remaining_seconds <= 0:
            recommendation.retry_not_before = None
            return False, ""
        return True, f"retry_deferred:{remaining_seconds}s_remaining"

    def _compute_recommendation_retry_not_before(self, reason: str) -> Optional[str]:
        base_backoff_seconds = self._parse_int_env(
            "VERA_PROACTIVE_SUPPRESSION_RETRY_BACKOFF_SECONDS",
            60,
            minimum=5,
        )
        cooldown_until_match = re.search(r"until=([0-9T:\-+.Z]+)", str(reason or ""))
        if cooldown_until_match:
            cooldown_until = _parse_iso_utc(cooldown_until_match.group(1))
            if cooldown_until is not None and cooldown_until > _utc_now():
                return cooldown_until.isoformat().replace("+00:00", "Z")
        backoff_seconds = int(base_backoff_seconds)
        match = re.search(r"age=(\d+)s<(\d+)s", str(reason or ""))
        if match:
            try:
                age_seconds = int(match.group(1))
                cooldown_seconds = int(match.group(2))
                remaining_seconds = max(0, cooldown_seconds - age_seconds)
                if remaining_seconds > 0:
                    backoff_seconds = max(5, min(int(base_backoff_seconds), remaining_seconds))
            except ValueError:
                backoff_seconds = int(base_backoff_seconds)
        return (_utc_now() + timedelta(seconds=backoff_seconds)).isoformat().replace("+00:00", "Z")

    async def _run_autonomy_cycle_async(self, trigger: str = "sentinel", force: bool = False) -> Dict[str, Any]:
        if self._autonomy_cycle_running:
            return {"scheduled": False, "skipped": True, "reason": "cycle_already_running"}
        self._autonomy_cycle_running = True
        try:
            state = self._load_autonomy_state()
            phase, window_index, seconds_until_transition = self._compute_cadence_phase(state)
            normalized_trigger = str(trigger or "").strip().lower()
            startup_trigger = normalized_trigger == "startup"
            phase_policy = ""
            within_active_hours = True
            try:
                if self.inner_life is not None and hasattr(self.inner_life, "is_within_active_hours"):
                    within_active_hours = bool(self.inner_life.is_within_active_hours())
            except Exception:
                within_active_hours = True
            if phase == "active" and not force and not within_active_hours:
                phase = "idle"
                phase_policy = "outside_active_hours"
            previous_window = int(state.get("window_index") or 0)
            if window_index != previous_window:
                state["active_window_reflections"] = 0
                state["active_window_workflows"] = 0
                state["startup_window_reflection_index"] = -1
                state["startup_window_workflow_index"] = -1
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
            result["state_sync_verifier"] = self._run_periodic_state_sync_verifier(limit=3)
            if phase_policy:
                result["phase_policy"] = phase_policy
            actionable_surface: Dict[str, Any] = {}
            if not bool(self._autonomy_config.get("enabled", True)):
                result["skipped"] = True
                result["reason"] = "autonomy_cadence_disabled"
                state["last_cycle_result"] = result
                state["last_cycle_utc"] = _utc_iso()
                self._save_autonomy_state(state)
                self._append_autonomy_event({"type": "autonomy_cycle_skipped", **result})
                return result
            idle_window = phase != "active" and not force
            manual_trigger = str(trigger or "").strip().lower().startswith("manual")
            non_consumptive_manual_cycle = bool(force) and manual_trigger
            if phase != "active" and force:
                result["phase_override"] = "forced_active_override"
            if non_consumptive_manual_cycle:
                result["budget_mode"] = "non_consumptive_manual"
            if idle_window:
                result["idle_window"] = True

            reflection_result = None
            reflection_reason = "reflection_not_attempted"
            reflection_error_classification = ""
            startup_dependency_probe: Optional[Dict[str, Any]] = None
            actionable_work_present = False
            explicit_autonomy_work_present = False
            task_state_sync_monitor_present = False
            week1_validation_monitor_present = False
            if idle_window:
                reflection_reason = "idle_window"
            else:
                if startup_trigger and not force:
                    startup_dependency_probe = self._probe_startup_dependencies_ready()
                    if not bool(startup_dependency_probe.get("ready")):
                        reflection_reason = str(
                            startup_dependency_probe.get("reason") or "startup_dependencies_pending"
                        )
                sentinel_obj = object.__getattribute__(self, "__dict__").get("sentinel")
                sentinel_recommender = getattr(sentinel_obj, "recommender", None)
                if (
                    normalized_trigger == "sentinel"
                    and not force
                    and sentinel_recommender is not None
                ):
                    try:
                        pending_recommendations = sentinel_recommender.get_pending_recommendations()
                    except Exception:
                        pending_recommendations = None
                    pending_count = 0
                    if isinstance(pending_recommendations, list):
                        pending_count = len(pending_recommendations)
                    elif pending_recommendations is not None:
                        try:
                            pending_count = len(pending_recommendations)
                        except Exception:
                            pending_count = 0
                    if pending_count <= 0:
                        reflection_reason = "sentinel_no_actionable_work"

                if reflection_reason == "reflection_not_attempted":
                    if normalized_trigger in {"autonomy_cycle", "startup"} and not force:
                        reflection_probe = self._probe_autonomy_reflection_needed()
                        actionable_surface = dict(reflection_probe.get("surface") or {})
                        actionable_work_present = self._surface_has_actionable_work(actionable_surface)
                        explicit_autonomy_work_present = self._surface_has_explicit_autonomy_work(actionable_surface)
                        task_state_sync_monitor_present = self._surface_has_task_state_sync_monitor_work(
                            actionable_surface
                        )
                        week1_ops_backlog_present = self._surface_has_week1_ops_backlog_work(actionable_surface)
                        week1_validation_monitor_present = self._surface_has_week1_validation_monitor_work(
                            actionable_surface
                        )
                        if not bool(reflection_probe.get("needed")):
                            reflection_reason = str(reflection_probe.get("reason") or "autonomy_no_actionable_work")

                if reflection_reason == "reflection_not_attempted":
                    reflections_used = int(state.get("active_window_reflections") or 0)
                    max_reflections = int(self._autonomy_config.get("max_reflections_per_active_window", 1))
                    workflows_used = int(state.get("active_window_workflows") or 0)
                    workflow_cap = int(self._autonomy_config.get("max_workflows_per_active_window", 1))
                    startup_reflection_used = int(state.get("startup_window_reflection_index", -1) or -1) == window_index
                    startup_workflow_used = int(state.get("startup_window_workflow_index", -1) or -1) == window_index
                    force_cap_override = bool(force) and reflections_used >= max_reflections
                    workflow_slot_available = (
                        workflows_used < workflow_cap
                        or non_consumptive_manual_cycle
                        or startup_trigger
                    ) and not (startup_trigger and startup_workflow_used and not force)
                    if startup_trigger and startup_reflection_used and not force:
                        reflection_reason = "startup_window_reflection_already_used"
                    elif (
                        normalized_trigger in {"autonomy_cycle", "startup"}
                        and not force
                        and explicit_autonomy_work_present
                        and workflow_slot_available
                    ):
                        reflection_reason = "autonomy_work_jar_direct_workflow"
                    elif (
                        normalized_trigger in {"autonomy_cycle", "startup"}
                        and not force
                        and week1_ops_backlog_present
                        and not bool(str((actionable_surface or {}).get("week1_next_stage") or "").strip())
                        and workflow_slot_available
                    ):
                        reflection_reason = "week1_ops_backlog_direct_workflow"
                    elif (
                        normalized_trigger in {"autonomy_cycle", "startup"}
                        and not force
                        and task_state_sync_monitor_present
                        and workflow_slot_available
                    ):
                        reflection_reason = "task_state_sync_monitor_direct_workflow"
                    elif (
                        normalized_trigger in {"autonomy_cycle", "startup"}
                        and not force
                        and week1_validation_monitor_present
                        and workflow_slot_available
                    ):
                        reflection_reason = "week1_validation_monitor_direct_workflow"
                    elif (
                        normalized_trigger == "autonomy_cycle"
                        and not force
                        and actionable_work_present
                        and workflows_used >= workflow_cap
                    ):
                        reflection_reason = "workflow_window_cap_reached_on_actionable_surface"
                    elif (
                        normalized_trigger in {"autonomy_cycle", "startup"}
                        and not force
                        and actionable_work_present
                        and self._workflow_call_reserve_active()[0]
                    ):
                        reflection_reason = "workflow_call_reserve_active"
                    elif reflections_used < max_reflections or force_cap_override or startup_trigger:
                        allowed, reason = self._can_spend("inner_life_reflection", self.inner_life.config.max_tokens_per_turn)
                        if allowed:
                            reflection_result = await self.run_reflection_cycle(trigger="autonomy_cycle", force=bool(force))
                            reflection_outcome = getattr(reflection_result, "outcome", "") if reflection_result else ""
                            if reflection_outcome == "outside_hours":
                                reflection_reason = "reflection_outside_hours"
                            elif reflection_outcome == "error" or not reflection_result:
                                reflection_error_text = getattr(reflection_result, "error", "") if reflection_result else ""
                                reflection_reason, reflection_error_classification = self._classify_reflection_error(
                                    reflection_error_text
                                )
                            else:
                                if not non_consumptive_manual_cycle:
                                    if startup_trigger:
                                        state["startup_window_reflection_index"] = window_index
                                    elif not (
                                        normalized_trigger in {"autonomy_cycle", "startup"}
                                        and actionable_work_present
                                        and reflection_outcome in {"internal", "reached_out"}
                                    ):
                                        state["active_window_reflections"] = reflections_used + 1
                            if (
                                reflection_result
                                and getattr(reflection_result, "entries", None)
                                and reflection_outcome not in {"outside_hours", "error"}
                            ):
                                text_out = "\n".join(entry.thought for entry in reflection_result.entries if getattr(entry, "thought", ""))
                                self._record_estimated_usage("inner_life_reflection", "autonomy_cycle_reflection", text_out)
                            if reflection_outcome not in {"outside_hours", "error"}:
                                if (
                                    normalized_trigger in {"autonomy_cycle", "startup"}
                                    and isinstance(actionable_surface, dict)
                                    and self._surface_has_actionable_work(actionable_surface)
                                    and reflection_outcome in {"internal", "reached_out"}
                                ):
                                    reflection_reason = (
                                        "reflection_reached_out_on_actionable_surface"
                                        if reflection_outcome == "reached_out"
                                        else "reflection_internal_on_actionable_surface"
                                    )
                                else:
                                    reflection_reason = (
                                        "reflection_executed_forced_cap_override"
                                        if force_cap_override
                                        else "reflection_executed"
                                    )
                        else:
                            reflection_reason = f"budget_guard:{reason}"
                    else:
                        reflection_reason = "reflection_window_cap_reached"

            workflow_result: Dict[str, Any] = {"ok": False, "reason": "workflow_not_attempted"}
            if idle_window:
                workflow_result = {"ok": False, "reason": "idle_window"}
            else:
                workflows_used = int(state.get("active_window_workflows") or 0)
                workflow_cap_override = non_consumptive_manual_cycle
                workflow_cap = int(self._autonomy_config.get("max_workflows_per_active_window", 1))
                startup_workflow_used = int(state.get("startup_window_workflow_index", -1) or -1) == window_index
                if (
                    reflection_reason == "workflow_window_cap_reached_on_actionable_surface"
                    and normalized_trigger == "autonomy_cycle"
                ):
                    workflow_result = {"ok": False, "reason": "workflow_window_cap_reached_on_actionable_surface"}
                if (
                    reflection_reason == "autonomy_work_jar_direct_workflow"
                    and normalized_trigger in {"autonomy_cycle", "startup"}
                    and (
                        workflows_used < workflow_cap
                        or workflow_cap_override
                        or startup_trigger
                    )
                ):
                    if startup_trigger and startup_workflow_used and not force:
                        workflow_result = {"ok": False, "reason": "startup_window_workflow_already_used"}
                    else:
                        workflow_result = await self._execute_autonomy_work_jar_fallback_workflow(
                            run_id=f"{normalized_trigger}:autonomy_work_jar"
                        )
                        if not non_consumptive_manual_cycle:
                            if startup_trigger:
                                state["startup_window_workflow_index"] = window_index
                            else:
                                state["active_window_workflows"] = workflows_used + 1
                elif (
                    reflection_reason == "task_state_sync_monitor_direct_workflow"
                    and normalized_trigger in {"autonomy_cycle", "startup"}
                    and (
                        workflows_used < workflow_cap
                        or workflow_cap_override
                        or startup_trigger
                    )
                ):
                    if startup_trigger and startup_workflow_used and not force:
                        workflow_result = {"ok": False, "reason": "startup_window_workflow_already_used"}
                    else:
                        workflow_result = await self._execute_task_state_sync_monitor_fallback_workflow(
                            actionable_surface,
                            run_id=f"{normalized_trigger}:task_state_sync_monitor",
                        )
                        if not non_consumptive_manual_cycle:
                            if startup_trigger:
                                state["startup_window_workflow_index"] = window_index
                            else:
                                state["active_window_workflows"] = workflows_used + 1
                elif (
                    reflection_reason == "week1_ops_backlog_direct_workflow"
                    and normalized_trigger in {"autonomy_cycle", "startup"}
                    and (
                        workflows_used < workflow_cap
                        or workflow_cap_override
                        or startup_trigger
                    )
                ):
                    if startup_trigger and startup_workflow_used and not force:
                        workflow_result = {"ok": False, "reason": "startup_window_workflow_already_used"}
                    else:
                        workflow_result = await self._execute_week1_ops_backlog_fallback_workflow(
                            actionable_surface,
                            run_id=f"{normalized_trigger}:week1_ops_backlog",
                        )
                        if not non_consumptive_manual_cycle:
                            if startup_trigger:
                                state["startup_window_workflow_index"] = window_index
                            else:
                                state["active_window_workflows"] = workflows_used + 1
                elif (
                    reflection_reason == "week1_validation_monitor_direct_workflow"
                    and normalized_trigger in {"autonomy_cycle", "startup"}
                    and (
                        workflows_used < workflow_cap
                        or workflow_cap_override
                        or startup_trigger
                    )
                ):
                    if startup_trigger and startup_workflow_used and not force:
                        workflow_result = {"ok": False, "reason": "startup_window_workflow_already_used"}
                    else:
                        workflow_result = await self._execute_week1_validation_monitor_fallback_workflow(
                            actionable_surface,
                            run_id=f"{normalized_trigger}:week1_validation_monitor",
                        )
                        if not non_consumptive_manual_cycle:
                            if startup_trigger:
                                state["startup_window_workflow_index"] = window_index
                            else:
                                state["active_window_workflows"] = workflows_used + 1
                elif (
                    reflection_result
                    and getattr(reflection_result, "outcome", "") == "action"
                    and (
                        workflows_used < workflow_cap
                        or workflow_cap_override
                        or startup_trigger
                    )
                ):
                    if startup_trigger and startup_workflow_used and not force:
                        workflow_result = {"ok": False, "reason": "startup_window_workflow_already_used"}
                    else:
                        last_entry = reflection_result.entries[-1] if reflection_result.entries else None
                        action_text = str(getattr(last_entry, "thought", "") or "")
                        workflow_result = await self._execute_inner_action_workflow(
                            action_text=action_text,
                            run_id=getattr(reflection_result, "run_id", "autonomy"),
                        )
                        if not non_consumptive_manual_cycle:
                            if startup_trigger:
                                state["startup_window_workflow_index"] = window_index
                            else:
                                state["active_window_workflows"] = workflows_used + 1
                elif (
                    reflection_reason == "workflow_call_reserve_active"
                    and normalized_trigger in {"autonomy_cycle", "startup"}
                    and actionable_work_present
                    and (
                        workflows_used < workflow_cap
                        or workflow_cap_override
                        or startup_trigger
                    )
                ):
                    if startup_trigger and startup_workflow_used and not force:
                        workflow_result = {"ok": False, "reason": "startup_window_workflow_already_used"}
                    else:
                        workflow_result = await self._execute_week1_surface_fallback_workflow(
                            actionable_surface,
                            run_id=f"{normalized_trigger}:workflow_reserve",
                        )
                        if not non_consumptive_manual_cycle:
                            if startup_trigger:
                                state["startup_window_workflow_index"] = window_index
                            else:
                                state["active_window_workflows"] = workflows_used + 1
                elif (
                    reflection_result
                    and getattr(reflection_result, "outcome", "") in {"internal", "reached_out"}
                    and normalized_trigger in {"autonomy_cycle", "startup"}
                    and (
                        workflows_used < workflow_cap
                        or workflow_cap_override
                        or startup_trigger
                    )
                ):
                    if startup_trigger and startup_workflow_used and not force:
                        workflow_result = {"ok": False, "reason": "startup_window_workflow_already_used"}
                    else:
                        workflow_result = await self._execute_week1_surface_fallback_workflow(
                            actionable_surface,
                            run_id=getattr(reflection_result, "run_id", "autonomy"),
                        )
                        if not non_consumptive_manual_cycle:
                            if startup_trigger:
                                state["startup_window_workflow_index"] = window_index
                            else:
                                state["active_window_workflows"] = workflows_used + 1
                elif reflection_result and getattr(reflection_result, "outcome", "") == "action":
                    workflow_result = {"ok": False, "reason": "workflow_window_cap_reached"}

            followthrough_result: Dict[str, Any] = {
                "ok": False,
                "reason": "followthrough_disabled",
                "attempted": False,
            }
            if non_consumptive_manual_cycle:
                followthrough_result = {
                    "ok": False,
                    "reason": "manual_verification_skip",
                    "attempted": False,
                }
            elif bool(self._autonomy_config.get("followthrough_enabled", True)):
                last_follow = _parse_iso_utc(str(state.get("last_followthrough_utc") or ""))
                cooldown_seconds = int(self._autonomy_config.get("followthrough_cooldown_seconds", 900))
                now_utc = _utc_now()
                seconds_since_last_follow = (
                    (now_utc - last_follow).total_seconds() if last_follow is not None else None
                )
                due_probe = await self._probe_followthrough_due_work()
                due_pending = bool(
                    due_probe.get("ok")
                    and int(due_probe.get("due_count") or 0) > 0
                )
                cooldown_ok = (
                    last_follow is None
                    or (seconds_since_last_follow is not None and seconds_since_last_follow >= cooldown_seconds)
                )
                if cooldown_ok and due_pending:
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
                elif cooldown_ok:
                    followthrough_result = {
                        "ok": True,
                        "reason": "no_due_work",
                        "attempted": False,
                        "cooldown_seconds": cooldown_seconds,
                        "seconds_since_last_followthrough": (
                            round(seconds_since_last_follow, 3)
                            if seconds_since_last_follow is not None
                            else None
                        ),
                        "cooldown_remaining_seconds": 0,
                        "due_work_pending": False,
                        "due_probe_reason": str(due_probe.get("reason") or ""),
                    }
                else:
                    if due_pending:
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
                        followthrough_result["cooldown_override"] = "due_work_pending"
                        followthrough_result["due_probe"] = {
                            "due_count": int(due_probe.get("due_count") or 0),
                            "due_actions": list(due_probe.get("due_actions") or []),
                        }
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
                            "due_work_pending": bool(due_pending),
                            "due_probe_reason": str(due_probe.get("reason") or ""),
                        }

            week1_result: Dict[str, Any] = {
                "ok": False,
                "reason": "week1_executor_disabled",
                "attempted": False,
            }
            if non_consumptive_manual_cycle:
                week1_result = {
                    "ok": False,
                    "reason": "manual_verification_skip",
                    "attempted": False,
                }
            elif bool(self._autonomy_config.get("week1_executor_enabled", True)):
                last_week1 = _parse_iso_utc(str(state.get("last_week1_executor_utc") or ""))
                cooldown_seconds = int(self._autonomy_config.get("week1_executor_cooldown_seconds", 900))
                now_utc = _utc_now()
                seconds_since_last_week1 = (
                    (now_utc - last_week1).total_seconds() if last_week1 is not None else None
                )
                due_probe = await self._probe_week1_executor_due_work()
                due_count = 0
                if isinstance(due_probe, dict):
                    try:
                        due_count = int(due_probe.get("due_count", 0) or 0)
                    except Exception:
                        due_count = 0
                delivery_dependency_probe = (
                    self._probe_week1_delivery_dependencies_ready()
                    if due_count > 0
                    else {"ready": True}
                )
                cooldown_ok = (
                    last_week1 is None
                    or (seconds_since_last_week1 is not None and seconds_since_last_week1 >= cooldown_seconds)
                )
                if due_count > 0 and not bool(delivery_dependency_probe.get("ready")):
                    week1_result = {
                        "ok": False,
                        "reason": str(
                            delivery_dependency_probe.get("reason") or "delivery_dependencies_pending"
                        ),
                        "attempted": False,
                        "cooldown_seconds": cooldown_seconds,
                        "seconds_since_last_week1_executor": (
                            round(seconds_since_last_week1, 3)
                            if seconds_since_last_week1 is not None
                            else None
                        ),
                        "delivery_dependencies": delivery_dependency_probe,
                        "due_work_pending": True,
                        "due_probe_reason": str(due_probe.get("reason") or ""),
                    }
                elif cooldown_ok and due_count > 0:
                    week1_result = await self._run_week1_executor_once()
                    if not isinstance(week1_result, dict):
                        week1_result = {"ok": False, "reason": "invalid_week1_executor_result"}
                    week1_result["attempted"] = True
                    week1_result["cooldown_seconds"] = cooldown_seconds
                    week1_result["seconds_since_last_week1_executor"] = (
                        round(seconds_since_last_week1, 3)
                        if seconds_since_last_week1 is not None
                        else None
                    )
                    week1_result["cooldown_remaining_seconds"] = 0
                    state["last_week1_executor_utc"] = _utc_iso()
                elif cooldown_ok:
                    week1_result = {
                        "ok": True,
                        "reason": "no_due_work",
                        "attempted": False,
                        "cooldown_seconds": cooldown_seconds,
                        "seconds_since_last_week1_executor": (
                            round(seconds_since_last_week1, 3)
                            if seconds_since_last_week1 is not None
                            else None
                        ),
                        "cooldown_remaining_seconds": 0,
                        "due_work_pending": False,
                        "due_probe_reason": str(due_probe.get("reason") or ""),
                    }
                else:
                    if bool(due_probe.get("ok")) and due_count > 0:
                        week1_result = await self._run_week1_executor_once()
                        if not isinstance(week1_result, dict):
                            week1_result = {"ok": False, "reason": "invalid_week1_executor_result"}
                        week1_result["attempted"] = True
                        week1_result["cooldown_seconds"] = cooldown_seconds
                        week1_result["seconds_since_last_week1_executor"] = (
                            round(seconds_since_last_week1, 3)
                            if seconds_since_last_week1 is not None
                            else None
                        )
                        week1_result["cooldown_remaining_seconds"] = 0
                        week1_result["cooldown_override"] = "due_work_pending"
                        week1_result["due_probe"] = {
                            "due_count": due_count,
                            "due_events": list(due_probe.get("due_events", [])[:3])
                            if isinstance(due_probe.get("due_events"), list)
                            else [],
                        }
                        state["last_week1_executor_utc"] = _utc_iso()
                    else:
                        cooldown_remaining = max(
                            0,
                            cooldown_seconds - int(seconds_since_last_week1 or 0),
                        )
                        week1_result = {
                            "ok": False,
                            "reason": "week1_executor_cooldown_active",
                            "attempted": False,
                            "cooldown_seconds": cooldown_seconds,
                            "seconds_since_last_week1_executor": (
                                round(seconds_since_last_week1, 3)
                                if seconds_since_last_week1 is not None
                                else None
                            ),
                            "cooldown_remaining_seconds": int(cooldown_remaining),
                            "due_work_pending": bool(due_count > 0),
                        }
                        if isinstance(due_probe, dict):
                            week1_result["due_probe_reason"] = str(due_probe.get("reason") or "")

            # --- Calendar proactive check ---
            calendar_result: Optional[dict] = None
            if non_consumptive_manual_cycle:
                calendar_result = {"ok": False, "skipped": True, "reason": "manual_verification_skip"}
            elif startup_trigger and startup_dependency_probe and not bool(startup_dependency_probe.get("ready")):
                calendar_result = {
                    "ok": False,
                    "skipped": True,
                    "reason": "startup_dependencies_pending",
                    "dependencies": startup_dependency_probe,
                }
            else:
                try:
                    calendar_result = await self._check_calendar_proactive()
                except Exception as exc:
                    logger.debug("Calendar proactive check error: %s", exc)

            # --- Sentinel recommendation processing ---
            sentinel_result: Optional[dict] = None
            if non_consumptive_manual_cycle:
                sentinel_result = {
                    "processed": 0,
                    "executed": [],
                    "notified": [],
                    "logged": [],
                    "pending_remaining": 0,
                    "reason": "manual_verification_skip",
                }
            else:
                try:
                    sentinel_result = await self._process_sentinel_recommendations()
                except Exception as exc:
                    logger.debug("Sentinel recommendation processing error: %s", exc)

            dead_letter_replay_result: Dict[str, Any] = {}
            if non_consumptive_manual_cycle:
                dead_letter_replay_result = {
                    "enabled": False,
                    "attempted": 0,
                    "replayed": 0,
                    "reason": "manual_verification_skip",
                }
            else:
                try:
                    dead_letter_replay_result = self._auto_replay_dead_letters(state)
                except Exception as exc:
                    logger.debug("Dead-letter auto-replay error: %s", exc)
                    dead_letter_replay_result = {
                        "enabled": False,
                        "reason": "error",
                        "error": str(exc),
                    }
            dead_letter_replay_slo: Dict[str, Any] = {}
            if non_consumptive_manual_cycle:
                dead_letter_replay_slo = {
                    "pass": True,
                    "violations": [],
                    "reason": "manual_verification_skip",
                    "ts_utc": _utc_iso(),
                }
            else:
                try:
                    dead_letter_replay_slo = self._audit_dead_letter_replay_slo(
                        dead_letter_replay_result,
                        state,
                    )
                except Exception as exc:
                    logger.debug("Dead-letter replay SLO audit error: %s", exc)
                    dead_letter_replay_slo = {
                        "pass": False,
                        "violations": [f"audit_error:{exc.__class__.__name__}"],
                        "ts_utc": _utc_iso(),
                    }
                    state["last_dead_letter_replay_slo"] = dead_letter_replay_slo

            delivery_escalation_result: Dict[str, Any] = {}
            if non_consumptive_manual_cycle:
                delivery_escalation_result = {
                    "enabled": False,
                    "reason": "manual_verification_skip",
                }
            else:
                try:
                    delivery_escalation_result = self._auto_escalate_stale_deliveries(state)
                except Exception as exc:
                    logger.debug("Delivery ACK-SLA escalation error: %s", exc)
                    delivery_escalation_result = {
                        "enabled": False,
                        "reason": "error",
                        "error": str(exc),
                    }
                    state["last_delivery_escalation_result"] = dict(delivery_escalation_result)

            # --- Self-improvement auto-trigger (red-team) ---
            self_improvement_result: Optional[dict] = None
            if non_consumptive_manual_cycle:
                self_improvement_result = {"ran": False, "reason": "manual_verification_skip"}
            elif os.getenv("VERA_SELF_IMPROVEMENT_AUTO", "0") == "1":
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
                    "actionable_surface": actionable_surface,
                    "startup_dependencies": startup_dependency_probe,
                    "reflection_reason": reflection_reason,
                    "reflection_outcome": getattr(reflection_result, "outcome", None) if reflection_result else None,
                    "reflection_error": getattr(reflection_result, "error", None) if reflection_result else None,
                    "reflection_error_classification": reflection_error_classification or None,
                    "workflow_result": workflow_result,
                    "followthrough_result": followthrough_result,
                    "week1_result": week1_result,
                    "calendar_result": calendar_result,
                    "sentinel_result": sentinel_result,
                    "dead_letter_replay_result": dead_letter_replay_result,
                    "dead_letter_replay_slo": dead_letter_replay_slo,
                    "delivery_escalation_result": delivery_escalation_result,
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

        existing_triggers = {t.name: t for t in self.sentinel.trigger_engine.list_triggers()}

        def _ensure_trigger(
            *,
            name: str,
            description: str,
            pattern: EventPattern,
            condition: TriggerCondition,
            priority: ActionPriority,
            enabled: bool,
            cooldown_seconds: int = 0,
            threshold: int = 1,
            window_seconds: int = 60,
            action_template: Optional[Dict[str, Any]] = None,
        ) -> None:
            trigger = existing_triggers.get(name)
            if trigger is None:
                if not enabled:
                    return
                created = self.sentinel.add_trigger(
                    name=name,
                    description=description,
                    pattern=pattern,
                    condition=condition,
                    threshold=threshold,
                    window_seconds=window_seconds,
                    cooldown_seconds=cooldown_seconds,
                    action_template=action_template,
                    priority=priority,
                )
                existing_triggers[name] = created
                return

            changed = False
            if trigger.description != description:
                trigger.description = description
                changed = True
            if trigger.pattern.to_dict() != pattern.to_dict():
                trigger.pattern = pattern
                changed = True
            if trigger.condition != condition:
                trigger.condition = condition
                changed = True
            if int(trigger.threshold) != int(threshold):
                trigger.threshold = int(threshold)
                changed = True
            if int(trigger.window_seconds) != int(window_seconds):
                trigger.window_seconds = int(window_seconds)
                changed = True
            if int(trigger.cooldown_seconds) != int(cooldown_seconds):
                trigger.cooldown_seconds = int(cooldown_seconds)
                changed = True
            if bool(trigger.enabled) != bool(enabled):
                trigger.enabled = bool(enabled)
                changed = True
            if trigger.action_template != action_template:
                trigger.action_template = dict(action_template or {})
                changed = True
            if trigger.priority != priority:
                trigger.priority = priority
                changed = True
            if changed:
                self.sentinel._save_state()

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
        week1_due_check_interval = self._parse_int_env(
            "VERA_WEEK1_DUE_CHECK_INTERVAL_SECONDS",
            60,
            minimum=30,
        )
        week1_enabled = bool(self._autonomy_config.get("week1_executor_enabled", True))

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
        if week1_enabled:
            timer_adapter.add_interval(
                name="week1_due_check",
                interval_seconds=week1_due_check_interval,
                payload={"action": "week1_due_check"},
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
        if tasks_enabled:
            _ensure_trigger(
                name="Overdue Task Alert",
                description="Fires when scheduled task check runs",
                pattern=overdue_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.NORMAL,
                enabled=bool(tasks_enabled),
                cooldown_seconds=task_check_cooldown,
                action_template={"type": "check_tasks", "urgency": "medium"},
            )

        config_watch_regex = str(
            os.getenv(
                "VERA_CONFIG_WATCH_PATH_REGEX",
                r"(^|/)vera_memory/(preferences|dnd_config)\.json$",
            )
        ).strip() or r"(^|/)vera_memory/(preferences|dnd_config)\.json$"
        file_pattern = EventPattern(
            pattern_id="config_changes",
            name="Config Changes",
            sources=[EventSource.FILE_SYSTEM],
            event_types=[EventType.FILE_MODIFIED],
            payload_patterns={"path": f"regex:{config_watch_regex}"},
        )
        if config_watch_enabled:
            _ensure_trigger(
                name="Config File Changed",
                description="Fires when JSON config files change",
                pattern=file_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.LOW,
                enabled=True,
                cooldown_seconds=10,
                action_template={"type": "reload_config", "urgency": "low"},
            )
        else:
            _ensure_trigger(
                name="Config File Changed",
                description="Fires when JSON config files change",
                pattern=file_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.LOW,
                enabled=False,
                cooldown_seconds=10,
                action_template={"type": "reload_config", "urgency": "low"},
            )

        red_team_pattern = EventPattern(
            pattern_id="red_team_check",
            name="Red Team Check",
            sources=[EventSource.TIMER],
            payload_patterns={"action": "red_team_check"},
        )
        _ensure_trigger(
            name="Red Team Check",
            description="Periodic red-team generation from flight recorder",
            pattern=red_team_pattern,
            condition=TriggerCondition.IMMEDIATE,
            priority=ActionPriority.LOW,
            enabled=bool(red_team_interval > 0),
            cooldown_seconds=10,
            action_template={"type": "red_team_check", "urgency": "low"},
        )
        autonomy_pattern = EventPattern(
            pattern_id="autonomy_cycle",
            name="Autonomy Cadence Pulse",
            sources=[EventSource.TIMER],
            payload_patterns={"action": "autonomy_cycle"},
        )
        if autonomy_enabled:
            _ensure_trigger(
                name="Autonomy Cadence Pulse",
                description="Periodic active/idle cadence for proactive autonomy",
                pattern=autonomy_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.BACKGROUND,
                enabled=True,
                cooldown_seconds=max(10, autonomy_pulse_interval // 2),
                action_template={"type": "autonomy_cycle", "urgency": "low"},
            )
        else:
            _ensure_trigger(
                name="Autonomy Cadence Pulse",
                description="Periodic active/idle cadence for proactive autonomy",
                pattern=autonomy_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.BACKGROUND,
                enabled=False,
                cooldown_seconds=max(10, autonomy_pulse_interval // 2),
                action_template={"type": "autonomy_cycle", "urgency": "low"},
            )

        week1_pattern = EventPattern(
            pattern_id="week1_due_check",
            name="Week1 Due Check",
            sources=[EventSource.TIMER],
            payload_patterns={"action": "week1_due_check"},
        )
        _ensure_trigger(
            name="Week1 Due Check",
            description="Minute-level due check for exact-time Week1 commitments",
            pattern=week1_pattern,
            condition=TriggerCondition.IMMEDIATE,
            priority=ActionPriority.HIGH,
            enabled=bool(week1_enabled),
            cooldown_seconds=10,
            action_template={"type": "week1_due_check", "urgency": "high"},
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
            _ensure_trigger(
                name="Inner Life Reflection",
                description="Periodic inner monologue and reflection cycle",
                pattern=reflection_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.NORMAL,
                enabled=True,
                cooldown_seconds=il_cooldown,
                action_template={"type": "reflect", "urgency": "medium"},
            )
        else:
            reflection_pattern = EventPattern(
                pattern_id="inner_life_reflection",
                name="Inner Life Reflection",
                sources=[EventSource.TIMER],
                payload_patterns={"action": "reflect"},
            )
            _ensure_trigger(
                name="Inner Life Reflection",
                description="Periodic inner monologue and reflection cycle",
                pattern=reflection_pattern,
                condition=TriggerCondition.IMMEDIATE,
                priority=ActionPriority.NORMAL,
                enabled=False,
                cooldown_seconds=0,
                action_template={"type": "reflect", "urgency": "medium"},
            )

        self.sentinel.on_trigger = self._handle_sentinel_trigger
        self.sentinel.on_recommendation = self.handle_proactive_recommendation
        self.sentinel.register_action_handler("check_tasks", self.action_check_tasks)
        self.sentinel.register_action_handler("reload_config", self.action_reload_config)
        self.sentinel.register_action_handler("notify", self.action_notify)
        self.sentinel.register_action_handler("red_team_check", self.action_red_team)
        self.sentinel.register_action_handler("reflect", self.action_reflect)
        self.sentinel.register_action_handler("autonomy_cycle", self.action_autonomy_cycle)
        self.sentinel.register_action_handler("week1_due_check", self.action_week1_due_check)

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

    def handle_proactive_recommendation(self, recommendation: RecommendedAction) -> Dict[str, Any]:
        """Handle proactive recommendations from Sentinel Engine."""
        reload_probe: Optional[Dict[str, Any]] = None
        if str(getattr(recommendation, "action_type", "") or "") == "reload_config":
            reload_probe = self._probe_reload_config_needed(recommendation)
            probe = reload_probe
            if not bool(probe.get("needed")):
                try:
                    self.sentinel.recommender.acknowledge(recommendation.action_id)
                except Exception:
                    logger.debug("Suppressed Exception in proactive_manager")
                self._update_action_type_stats(
                    action_type="reload_config",
                    outcome="action_success_skipped",
                )
                self._append_initiative_event(
                    {
                        "type": "proactive_recommendation_skipped",
                        "action_type": "reload_config",
                        "priority": recommendation.priority.name,
                        "reason": str(probe.get("reason") or "recent_local_write"),
                        "action_id": recommendation.action_id,
                        "paths": list(probe.get("paths") or []),
                    }
                )
                return {"outcome": "executed_noop", "result": probe}
        if str(getattr(recommendation, "action_type", "") or "") == "check_tasks":
            probe = self._probe_check_tasks_due_work()
            if not bool(probe.get("due")):
                try:
                    self.sentinel.recommender.acknowledge(recommendation.action_id)
                except Exception:
                    logger.debug("Suppressed Exception in proactive_manager")
                self._update_action_type_stats(
                    action_type="check_tasks",
                    outcome="action_success_noop",
                )
                if not self._should_suppress_maintenance_skip_event("check_tasks", "action_success_noop"):
                    self._append_initiative_event(
                        {
                            "type": "proactive_recommendation_skipped",
                            "action_type": "check_tasks",
                            "priority": recommendation.priority.name,
                            "reason": str(probe.get("reason") or "no_overdue_tasks"),
                            "action_id": recommendation.action_id,
                        }
                    )
                return {"outcome": "executed_noop", "result": probe}
        if str(getattr(recommendation, "action_type", "") or "") == "red_team_check":
            probe = self._probe_red_team_due_work()
            if not bool(probe.get("due")):
                try:
                    self.sentinel.recommender.acknowledge(recommendation.action_id)
                except Exception:
                    logger.debug("Suppressed Exception in proactive_manager")
                self._update_action_type_stats(
                    action_type="red_team_check",
                    outcome="action_success_not_due",
                )
                if not self._should_suppress_maintenance_skip_event("red_team_check", "action_success_not_due"):
                    self._append_initiative_event(
                        {
                            "type": "proactive_recommendation_skipped",
                            "action_type": "red_team_check",
                            "priority": recommendation.priority.name,
                            "reason": str(probe.get("reason") or "not_due"),
                            "action_id": recommendation.action_id,
                        }
                    )
                return {"outcome": "executed_noop", "result": probe}

        retry_deferred, retry_reason = self._is_recommendation_retry_deferred(recommendation)
        if retry_deferred:
            self._append_initiative_event(
                {
                    "type": "proactive_recommendation_deferred",
                    "action_type": recommendation.action_type,
                    "priority": recommendation.priority.name,
                    "reason": retry_reason,
                    "description": recommendation.description[:160],
                }
            )
            if self.config.debug:
                logger.debug("[DEBUG] Proactive action deferred: %s (%s)", recommendation.description, retry_reason)
            return {"outcome": "deferred", "reason": retry_reason}

        allowed, gate_reason = self._should_execute_recommendation(recommendation)
        if (
            not allowed
            and reload_probe
            and bool(reload_probe.get("needed"))
            and str(gate_reason or "").startswith("duplicate_action_")
        ):
            allowed = True
            gate_reason = "allowed;reload_config_external_change_override"
        if not allowed:
            suppressed_row = self._record_suppressed_recommendation(recommendation, gate_reason)
            state = self._ensure_initiative_runtime()
            state["suppressed_count"] = int(state.get("suppressed_count", 0)) + 1
            self._save_initiative_state(state)
            event_payload = {
                "type": "proactive_recommendation_suppressed",
                "action_type": recommendation.action_type,
                "priority": recommendation.priority.name,
                "reason": gate_reason,
                "description": recommendation.description[:160],
                "action_id": suppressed_row.get("action_id", recommendation.action_id),
                "suppression_count": suppressed_row.get("suppression_count", 0),
            }
            if suppressed_row.get("retry_not_before"):
                event_payload["retry_not_before"] = suppressed_row["retry_not_before"]
            if suppressed_row.get("auto_acked"):
                event_payload["auto_acked"] = True
            self._append_initiative_event(event_payload)
            if self.config.debug:
                logger.debug("[DEBUG] Proactive action suppressed: %s (%s)", recommendation.description, gate_reason)
            return {"outcome": "suppressed", "reason": gate_reason}

        action_type = str(getattr(recommendation, "action_type", "") or "")
        if action_type in self.INTERNAL_DND_BYPASS_ACTIONS:
            result = self.execute_proactive_action(recommendation)
            if self.config.debug:
                logger.debug("[DEBUG] Internal proactive action bypassed DND: %s", recommendation.description)
            return result

        priority_to_urgency = {
            ActionPriority.BACKGROUND: InterruptUrgency.ROUTINE,
            ActionPriority.LOW: InterruptUrgency.LOW,
            ActionPriority.NORMAL: InterruptUrgency.MEDIUM,
            ActionPriority.HIGH: InterruptUrgency.HIGH,
            ActionPriority.URGENT: InterruptUrgency.CRITICAL,
        }
        urgency = priority_to_urgency.get(recommendation.priority, InterruptUrgency.MEDIUM)

        if self.dnd.can_interrupt(urgency):
            return self.execute_proactive_action(recommendation)

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
        return {"outcome": "queued_dnd", "reason": "dnd_active"}

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

    @staticmethod
    def _derive_proactive_lane_scope(payload: Dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return "global"
        for key in (
            "session_link_id",
            "conversation_id",
            "sender_id",
            "target_id",
            "user_id",
            "channel_id",
        ):
            value = str(payload.get(key) or "").strip()
            if value:
                return value[:96]
        return "global"

    def _build_proactive_lane_key(self, recommendation: RecommendedAction) -> str:
        action_type = str(getattr(recommendation, "action_type", "") or "unknown").strip().lower() or "unknown"
        scope = self._derive_proactive_lane_scope(getattr(recommendation, "payload", {}) or {})
        return f"{action_type}:{scope}"

    def _try_enter_proactive_lane(self, lane_key: str, action_id: str) -> Tuple[bool, str]:
        key = str(lane_key or "").strip().lower()
        aid = str(action_id or "").strip()
        if not key:
            return True, ""
        with self._proactive_lane_lock:
            current = str(self._active_proactive_lanes.get(key) or "").strip()
            if current and current != aid:
                return False, current
            self._active_proactive_lanes[key] = aid or "anonymous"
            return True, ""

    def _leave_proactive_lane(self, lane_key: str, action_id: str) -> None:
        key = str(lane_key or "").strip().lower()
        aid = str(action_id or "").strip()
        if not key:
            return
        with self._proactive_lane_lock:
            current = str(self._active_proactive_lanes.get(key) or "").strip()
            if not current:
                return
            if aid and current != aid:
                return
            self._active_proactive_lanes.pop(key, None)

    def _enqueue_proactive_lane_action(self, lane_key: str, recommendation: RecommendedAction) -> int:
        key = str(lane_key or "").strip().lower()
        if not key:
            return 0
        action_id = str(getattr(recommendation, "action_id", "") or "").strip()
        with self._proactive_lane_lock:
            queue_rows = self._proactive_lane_queues.setdefault(key, [])
            if action_id:
                for existing in queue_rows:
                    existing_id = str(getattr(existing, "action_id", "") or "").strip()
                    if existing_id == action_id:
                        return len(queue_rows)
            queue_rows.append(recommendation)
            if len(queue_rows) > int(self._proactive_lane_queue_max):
                self._proactive_lane_queues[key] = queue_rows[-int(self._proactive_lane_queue_max) :]
                queue_rows = self._proactive_lane_queues[key]
            return len(queue_rows)

    def _pop_queued_proactive_lane_action(self, lane_key: str) -> Optional[RecommendedAction]:
        key = str(lane_key or "").strip().lower()
        if not key:
            return None
        with self._proactive_lane_lock:
            queue_rows = self._proactive_lane_queues.get(key)
            if not queue_rows:
                return None
            next_item = queue_rows.pop(0)
            if not queue_rows:
                self._proactive_lane_queues.pop(key, None)
            return next_item

    def _drain_queued_proactive_lane(self, lane_key: str, just_completed_action_id: str = "") -> None:
        next_item = self._pop_queued_proactive_lane_action(lane_key)
        if not next_item:
            return
        next_action_id = str(getattr(next_item, "action_id", "") or "").strip()
        if next_action_id and next_action_id == str(just_completed_action_id or "").strip():
            return
        self.execute_proactive_action(next_item)

    def execute_proactive_action(self, recommendation: RecommendedAction) -> Dict[str, Any]:
        """Execute a proactive action recommendation."""
        lane_key = self._build_proactive_lane_key(recommendation)
        action_id = str(getattr(recommendation, "action_id", "") or "")
        acquired, holder = self._try_enter_proactive_lane(lane_key, action_id)
        if not acquired:
            queue_depth = self._enqueue_proactive_lane_action(lane_key, recommendation)
            self._append_initiative_event(
                {
                    "type": "proactive_lane_busy",
                    "action_id": action_id,
                    "action_type": recommendation.action_type,
                    "lane_key": lane_key,
                    "active_action_id": holder,
                    "queued_depth": queue_depth,
                }
            )
            self._append_failure_learning_event(
                {
                    "type": "proactive_lane_busy",
                    "ok": False,
                    "action_id": action_id,
                    "action_type": recommendation.action_type,
                    "lane_key": lane_key,
                    "active_action_id": holder,
                    "queued_depth": queue_depth,
                }
            )
            if self.config.debug:
                logger.debug(
                    "[DEBUG] Proactive action queued (lane busy): %s lane=%s active=%s queue=%s",
                    recommendation.description,
                    lane_key,
                    holder,
                    queue_depth,
                )
            return {
                "outcome": "queued_lane",
                "lane_key": lane_key,
                "active_action_id": holder,
                "queued_depth": queue_depth,
            }

        self._drain_pending_recommendation(str(getattr(recommendation, "action_id", "") or ""))
        final_result: Dict[str, Any] = {"outcome": "unknown"}
        try:
            try:
                success, result = self.sentinel.execute_recommendation(recommendation.action_id)
            except Exception as exc:
                success = False
                result = {
                    "error": f"execute_recommendation_exception:{exc.__class__.__name__}",
                    "detail": str(exc)[:240],
                }

            delta, signal = self._evaluate_action_reward_signal(recommendation, success=bool(success), result=result)
            self._record_recent_proactive_action(
                recommendation,
                success=bool(success),
                result=result,
                signal_type=signal,
            )
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
                        final_result = {"outcome": "executed_noop", "result": result}
                        return final_result
                if self.config.debug:
                    logger.debug("[DEBUG] Proactive action executed: %s", recommendation.description)
                if self.config.observability:
                    self.observability.record_event(
                        "proactive_action",
                        action_type=recommendation.action_type,
                        priority=recommendation.priority.value,
                    )
                final_result = {"outcome": "executed", "result": result}
                return final_result

            if self.config.debug:
                logger.error("[DEBUG] Proactive action failed: %s", result)
            self._append_failure_learning_event(
                {
                    "type": "proactive_action_failure",
                    "ok": False,
                    "action_id": action_id,
                    "action_type": recommendation.action_type,
                    "lane_key": lane_key,
                    "result_preview": self._preview_failure_payload(result),
                }
            )
            final_result = {"outcome": "failed", "result": result}
        finally:
            self._leave_proactive_lane(lane_key, action_id)
            self._drain_queued_proactive_lane(lane_key, just_completed_action_id=action_id)
        return final_result

    def action_check_tasks(self, payload: dict) -> dict:
        """Handler for checking overdue tasks."""
        probe = self._probe_check_tasks_due_work()
        if bool(probe.get("due")):
            tasks = [dict(t) for t in probe.get("tasks") or []]
            self._schedule_coroutine(self._send_overdue_tasks_push(tasks))
            return {
                "overdue_count": int(probe.get("overdue_count", 0) or 0),
                "tasks": tasks,
            }
        return {
            "overdue_count": 0,
            "reason": str(probe.get("reason") or "no_overdue_tasks"),
        }

    async def _send_overdue_tasks_push(self, tasks: List[Dict[str, Any]]) -> None:
        if not tasks:
            return
        titles = [str(task.get("title") or "untitled") for task in tasks[:3]]
        message_lines = [f"- {title}" for title in titles]
        more_count = max(0, len(tasks) - len(titles))
        if more_count:
            message_lines.append(f"...and {more_count} more overdue tasks.")
        payload = {
            "title": "Overdue Tasks",
            "message": "You have overdue tasks:\n" + "\n".join(message_lines),
        }
        try:
            await self._owner._internal_tool_call_handler("send_native_push", payload)
            return
        except Exception as exc:
            logger.debug("Native push failed for overdue tasks: %s", exc)
        try:
            await self._owner._internal_tool_call_handler("send_mobile_push", payload)
        except Exception as exc:
            logger.debug("Mobile push fallback failed for overdue tasks: %s", exc)

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

    def _probe_heartbeat_reflection_needed(self) -> Dict[str, Any]:
        inner_life = self._local_attr(self, "inner_life", None)
        if inner_life is None:
            return {"needed": True, "reason": "inner_life_unavailable"}

        recent_entries = list(getattr(inner_life, "_recent_monologue", []) or [])
        required_streak = self._parse_int_env(
            "VERA_HEARTBEAT_INTERNAL_STREAK_SKIP_COUNT",
            3,
            minimum=2,
        )
        skip_window_seconds = self._parse_int_env(
            "VERA_HEARTBEAT_INTERNAL_STREAK_SKIP_WINDOW_SECONDS",
            7200,
            minimum=300,
        )

        recent_heartbeat_entries: List[Any] = []
        for entry in reversed(recent_entries):
            if str(getattr(entry, "trigger", "") or "").strip() != "heartbeat":
                continue
            recent_heartbeat_entries.append(entry)
            if len(recent_heartbeat_entries) >= required_streak:
                break

        if len(recent_heartbeat_entries) < required_streak:
            return {
                "needed": True,
                "reason": "heartbeat_internal_streak_below_threshold",
                "streak_count": len(recent_heartbeat_entries),
            }

        if any(str(getattr(entry, "intent", "") or "").strip() != "INTERNAL" for entry in recent_heartbeat_entries):
            return {
                "needed": True,
                "reason": "heartbeat_recent_entries_include_non_internal",
                "streak_count": len(recent_heartbeat_entries),
            }

        latest_ts = _parse_iso_utc(str(getattr(recent_heartbeat_entries[0], "timestamp", "") or ""))
        age_seconds: Optional[float] = None
        if latest_ts is not None:
            age_seconds = max(0.0, (_utc_now() - latest_ts).total_seconds())
            if age_seconds > float(skip_window_seconds):
                return {
                    "needed": True,
                    "reason": "heartbeat_internal_streak_window_expired",
                    "streak_count": len(recent_heartbeat_entries),
                    "last_heartbeat_age_seconds": round(age_seconds, 3),
                }

        return {
            "needed": False,
            "reason": "heartbeat_internal_echo_streak",
            "streak_count": len(recent_heartbeat_entries),
            "last_heartbeat_age_seconds": round(age_seconds or 0.0, 3),
        }

    def action_reflect(self, payload: dict) -> dict:
        """Handler for inner life reflection triggers. Schedules async reflection."""
        if not hasattr(self, "inner_life") or not self.inner_life:
            return {"skipped": True, "reason": "inner life not available"}
        if not self.inner_life.config.enabled:
            return {"skipped": True, "reason": "inner life disabled"}
        trigger = str((payload or {}).get("trigger") or "heartbeat").strip() or "heartbeat"
        force = bool((payload or {}).get("force", False))
        if trigger == "heartbeat" and not force:
            probe = self._probe_heartbeat_reflection_needed()
            if not bool(probe.get("needed")):
                return {"skipped": True, **probe}

        future = self._schedule_coroutine(self.run_reflection_cycle(trigger=trigger, force=force))
        if future is None:
            return {"skipped": True, "reason": "no_event_loop"}
        return {"scheduled": True, "trigger": trigger, "force": force}

    def action_autonomy_cycle(self, payload: dict) -> dict:
        """Handler for autonomy cadence cycle triggers."""
        if not bool(self._autonomy_config.get("enabled", True)):
            return {"scheduled": False, "skipped": True, "reason": "autonomy_cadence_disabled"}
        trigger = str((payload or {}).get("trigger") or (payload or {}).get("action") or "autonomy_cycle")
        force = bool((payload or {}).get("force", False))
        self._autonomy_cycle_future = self._schedule_coroutine(
            self._run_autonomy_cycle_async(trigger=trigger, force=force)
        )
        if self._autonomy_cycle_future is None:
            return {"scheduled": False, "skipped": True, "reason": "no_event_loop"}
        return {"scheduled": True, "trigger": trigger, "force": force}

    def action_week1_due_check(self, payload: dict) -> dict:
        """Run the Week1 executor on a minute-level exact-time rail."""
        if not bool(self._autonomy_config.get("week1_executor_enabled", True)):
            return {"scheduled": False, "skipped": True, "reason": "week1_executor_disabled"}
        future = self._week1_due_check_future
        try:
            if future is not None and not future.done():
                return {"scheduled": False, "skipped": True, "reason": "week1_due_check_running"}
        except Exception:
            logger.debug("Suppressed Exception in proactive_manager")
        trigger = str((payload or {}).get("trigger") or "week1_due_check")
        due_probe = self._probe_week1_executor_due_work_sync()
        due_count = 0
        if isinstance(due_probe, dict):
            try:
                due_count = int(due_probe.get("due_count", 0) or 0)
            except Exception:
                due_count = 0
        if due_count <= 0:
            return {
                "scheduled": False,
                "attempted": False,
                "reason": str(due_probe.get("reason") or "no_due_work"),
                "due_probe": due_probe if isinstance(due_probe, dict) else {},
            }
        delivery_dependency_probe = self._probe_week1_delivery_dependencies_ready()
        if not bool(delivery_dependency_probe.get("ready")):
            return {
                "scheduled": False,
                "attempted": False,
                "reason": str(
                    delivery_dependency_probe.get("reason") or "delivery_dependencies_pending"
                ),
                "due_probe": due_probe if isinstance(due_probe, dict) else {},
                "delivery_dependencies": delivery_dependency_probe,
            }
        self._week1_due_check_future = self._schedule_coroutine(
            self._run_week1_due_check_async(trigger=trigger)
        )
        if self._week1_due_check_future is None:
            return {"scheduled": False, "skipped": True, "reason": "no_event_loop"}
        return {"scheduled": True, "trigger": trigger}

    def get_autonomy_status(self) -> Dict[str, Any]:
        """Return active/idle cadence and latest autonomy cycle state."""
        state = self._load_autonomy_state()
        phase, window_index, seconds_until_transition = self._compute_cadence_phase(state)
        initiative_status = self.get_initiative_tuning_status()
        with self._proactive_lane_lock:
            active_lane_snapshot = dict(self._active_proactive_lanes)
            lane_queue_depths = {
                key: len(rows)
                for key, rows in self._proactive_lane_queues.items()
                if isinstance(rows, list) and rows
            }
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
            "last_dead_letter_replay_result": state.get("last_dead_letter_replay_result", {}),
            "last_dead_letter_replay_slo": state.get("last_dead_letter_replay_slo", {}),
            "last_delivery_escalation_result": state.get("last_delivery_escalation_result", {}),
            "active_window_reflections": int(state.get("active_window_reflections") or 0),
            "active_window_workflows": int(state.get("active_window_workflows") or 0),
            "last_followthrough_utc": state.get("last_followthrough_utc", ""),
            "last_week1_executor_utc": state.get("last_week1_executor_utc", ""),
            "initiative_tuning": initiative_status,
            "proactive_lane_status": {
                "active_lanes": active_lane_snapshot,
                "queue_depths": lane_queue_depths,
                "queued_total": sum(int(v) for v in lane_queue_depths.values()),
                "queue_max_per_lane": int(self._proactive_lane_queue_max),
            },
            "runplane": self.runplane.status_snapshot(),
            "slo": self.runplane.slo_snapshot(),
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
                    "[INNER LIFE] run_id=%s outcome=%s chain=%s duration=%sms error=%s",
                    result.run_id,
                    result.outcome,
                    result.total_chain_depth,
                    f"{result.duration_ms:.0f}",
                    getattr(result, "error", "") or "",
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
        probe = self._probe_red_team_due_work()
        use_llm = os.getenv("VERA_RED_TEAM_USE_LLM", "1").lower() not in {"0", "false", "off"}
        failure_limit = int(os.getenv("VERA_RED_TEAM_FAILURE_LIMIT", "10"))
        try:
            hard_count = int(os.getenv("VERA_RED_TEAM_HARD_COUNT", "10"))
        except (ValueError, TypeError):
            hard_count = 10
        regression_count = int(os.getenv("VERA_RED_TEAM_REGRESSION_COUNT", "20"))
        try:
            daily_hour = int(os.getenv("VERA_RED_TEAM_DAILY_HOUR", "2"))
        except (ValueError, TypeError):
            daily_hour = 2

        if not bool(probe.get("due")):
            return {
                "ran": False,
                "reason": str(probe.get("reason") or "not_due"),
                "delta": int(probe.get("delta", 0) or 0),
                "current": int(probe.get("current", 0) or 0),
            }

        now = datetime.now()
        today = now.date().isoformat()
        state = probe.get("state") if isinstance(probe.get("state"), dict) else self.load_red_team_state()
        current_count = int(probe.get("current", 0) or 0)
        threshold_due = bool(probe.get("threshold_due"))
        daily_due = bool(probe.get("daily_due"))

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
            "delta": int(probe.get("delta", 0) or 0),
            "current": current_count,
            **result,
        }

    def _probe_red_team_due_work(self) -> Dict[str, Any]:
        try:
            threshold = int(os.getenv("VERA_RED_TEAM_THRESHOLD", "200"))
        except (ValueError, TypeError):
            threshold = 200
        try:
            daily_hour = int(os.getenv("VERA_RED_TEAM_DAILY_HOUR", "2"))
        except (ValueError, TypeError):
            daily_hour = 2

        now = datetime.now()
        today = now.date().isoformat()
        state = self.load_red_team_state()
        last_count = int(state.get("last_transition_count", 0))
        last_daily = str(state.get("last_daily_run_date", "") or "")
        current_count = self.get_transition_count()
        delta = max(0, current_count - last_count)
        daily_due = now.hour >= daily_hour and last_daily != today
        threshold_due = delta >= threshold

        if current_count == 0:
            return {"due": False, "reason": "no_transitions", "delta": delta, "current": current_count, "state": state}
        if self._red_team_running:
            return {"due": False, "reason": "already_running", "delta": delta, "current": current_count, "state": state}
        if not (threshold_due or daily_due):
            return {
                "due": False,
                "reason": "not_due",
                "delta": delta,
                "current": current_count,
                "daily_due": daily_due,
                "threshold_due": threshold_due,
                "state": state,
            }
        return {
            "due": True,
            "reason": "threshold" if threshold_due else "daily",
            "delta": delta,
            "current": current_count,
            "daily_due": daily_due,
            "threshold_due": threshold_due,
            "state": state,
        }

    def _probe_mcp_dependencies_ready(
        self,
        *,
        dependency_name: str,
        critical_servers: List[str],
        required_tools: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        ready = True
        pending_servers: List[str] = []
        blocked_servers: List[str] = []
        missing_servers: List[str] = []
        missing_tools: Dict[str, List[str]] = {}

        try:
            local_state = object.__getattribute__(self, "__dict__")
        except Exception:
            local_state = {}
        mcp_obj = local_state.get("mcp")
        if mcp_obj is None:
            owner = local_state.get("_owner")
            mcp_obj = getattr(owner, "mcp", None) if owner is not None else None
        status_getter = getattr(mcp_obj, "get_status", None)
        tools_getter = getattr(mcp_obj, "get_available_tools", None)
        if mcp_obj is None or not callable(status_getter) or not callable(tools_getter):
            return {
                "ready": True,
                "reason": "ready",
                "critical_servers": critical_servers,
                "pending_servers": [],
                "blocked_servers": [],
                "missing_servers": [],
                "missing_tools": {},
            }
        status = status_getter() if callable(status_getter) else {"servers": {}}
        servers = status.get("servers", {}) if isinstance(status, dict) else {}
        available_tools = tools_getter() if callable(tools_getter) else {}
        if not isinstance(available_tools, dict):
            available_tools = {}

        for name in critical_servers:
            info = servers.get(name)
            if not isinstance(info, dict):
                ready = False
                missing_servers.append(name)
                continue
            if info.get("missing_env"):
                ready = False
                blocked_servers.append(name)
                continue

            running = bool(info.get("running"))
            health = str(info.get("health") or "").strip().lower()
            effective_health = str(info.get("effective_health") or health).strip().lower()
            runtime_status = info.get("runtime_status")
            runtime_phase = ""
            if isinstance(runtime_status, dict):
                runtime_phase = str(runtime_status.get("phase") or "").strip().lower()
            effectively_ready = bool(
                running
                and (
                    effective_health == "healthy"
                    or runtime_phase == "ready"
                )
            )
            if not running or (
                not effectively_ready
                and health not in {"healthy", "unknown", "starting", "initializing"}
            ):
                ready = False
                pending_servers.append(name)
                continue

            required = list(required_tools.get(name) or [])
            if required:
                current_tools = {str(tool).strip() for tool in available_tools.get(name, []) if str(tool).strip()}
                missing = [tool for tool in required if tool not in current_tools]
                if missing:
                    if effectively_ready:
                        continue
                    ready = False
                    missing_tools[name] = missing

        reason = "ready"
        if blocked_servers:
            reason = f"{dependency_name}_blocked"
        elif missing_servers or pending_servers or missing_tools:
            reason = f"{dependency_name}_pending"
        return {
            "ready": ready,
            "reason": reason,
            "critical_servers": critical_servers,
            "pending_servers": pending_servers,
            "blocked_servers": blocked_servers,
            "missing_servers": missing_servers,
            "missing_tools": missing_tools,
        }

    def _probe_startup_dependencies_ready(self) -> Dict[str, Any]:
        critical_raw = str(os.getenv("VERA_STARTUP_CRITICAL_SERVERS", "google-workspace,time") or "")
        critical_servers = [item.strip() for item in critical_raw.split(",") if item.strip()]
        if not critical_servers:
            critical_servers = ["google-workspace", "time"]
        return self._probe_mcp_dependencies_ready(
            dependency_name="startup_dependencies",
            critical_servers=critical_servers,
            required_tools={
                "google-workspace": ["get_events"],
                "time": [],
            },
        )

    def _probe_week1_delivery_dependencies_ready(self) -> Dict[str, Any]:
        return self._probe_mcp_dependencies_ready(
            dependency_name="delivery_dependencies",
            critical_servers=["call-me"],
            required_tools={
                "call-me": ["send_native_push", "send_mobile_push", "initiate_call"],
            },
        )

    def _extract_reload_config_targets(self, recommendation: Optional[RecommendedAction]) -> List[str]:
        payload = getattr(recommendation, "payload", {}) if recommendation is not None else {}
        targets: List[str] = []

        def _add_path(value: Any) -> None:
            text = str(value or "").strip()
            if text:
                targets.append(text)

        if isinstance(payload, dict):
            _add_path(payload.get("path"))
            events = payload.get("events")
            if isinstance(events, list):
                for row in events:
                    if not isinstance(row, dict):
                        continue
                    event_payload = row.get("payload")
                    if not isinstance(event_payload, dict):
                        continue
                    _add_path(event_payload.get("path"))

        deduped: List[str] = []
        seen: Set[str] = set()
        for target in targets:
            if target in seen:
                continue
            seen.add(target)
            deduped.append(target)
        return deduped

    def _probe_reload_config_needed(self, recommendation: Optional[RecommendedAction] = None) -> Dict[str, Any]:
        tolerance_seconds = 2.0
        local_matches: List[str] = []
        target_paths = self._extract_reload_config_targets(recommendation)
        target_labels: List[str] = []

        def _check_local_write(
            path: Any,
            last_saved_epoch: Any,
            label: str,
            candidate_paths: List[str],
        ) -> None:
            try:
                saved_epoch = float(last_saved_epoch or 0.0)
            except Exception:
                saved_epoch = 0.0
            try:
                file_path = Path(path)
            except Exception:
                return
            match_found = False
            if candidate_paths:
                for candidate in candidate_paths:
                    try:
                        if Path(candidate).resolve() == file_path.resolve():
                            match_found = True
                            break
                    except Exception:
                        if str(candidate).strip() == str(file_path):
                            match_found = True
                            break
                if not match_found:
                    return
            target_labels.append(label)
            if saved_epoch <= 0.0:
                return
            try:
                mtime = float(file_path.stat().st_mtime)
            except Exception:
                return
            if abs(mtime - saved_epoch) <= tolerance_seconds:
                local_matches.append(label)

        prefs = getattr(self, "preferences", None)
        if prefs is not None:
            _check_local_write(
                getattr(prefs, "storage_path", ""),
                getattr(prefs, "_last_saved_epoch", 0.0),
                "preferences",
                target_paths,
            )
        dnd = getattr(self, "dnd", None)
        if dnd is not None:
            _check_local_write(
                getattr(dnd, "config_path", ""),
                getattr(dnd, "_last_saved_epoch", 0.0),
                "dnd_config",
                target_paths,
            )

        if target_paths:
            matched_count = len(set(target_labels))
            local_count = len(set(local_matches))
            if matched_count > 0 and local_count >= matched_count:
                return {
                    "needed": False,
                    "reason": f"recent_local_write:{','.join(sorted(set(local_matches)))}",
                    "paths": sorted(set(local_matches)),
                    "targets": list(target_paths),
                }
            return {
                "needed": True,
                "reason": "external_change_or_unknown",
                "paths": sorted(set(local_matches)),
                "targets": list(target_paths),
            }

        if local_matches:
            return {
                "needed": False,
                "reason": f"recent_local_write:{','.join(sorted(set(local_matches)))}",
                "paths": sorted(set(local_matches)),
            }
        return {"needed": True, "reason": "external_change_or_unknown", "paths": []}

    def _probe_check_tasks_due_work(self) -> Dict[str, Any]:
        stats = self.master_list.get_stats()
        try:
            overdue_hint = int(stats.get("overdue", 0) or 0)
        except Exception:
            overdue_hint = 0
        if overdue_hint <= 0:
            return {"due": False, "reason": "no_overdue_tasks", "overdue_count": 0, "tasks": []}

        overdue_tasks = list(self.master_list.get_overdue())
        if not overdue_tasks:
            return {"due": False, "reason": "no_overdue_tasks", "overdue_count": 0, "tasks": []}
        return {
            "due": True,
            "reason": "overdue_tasks",
            "overdue_count": len(overdue_tasks),
            "tasks": [{"id": t.id, "title": t.title} for t in overdue_tasks[:3]],
        }

    def _probe_autonomy_reflection_needed(self) -> Dict[str, Any]:
        week1_top_tasks: List[str] = []
        pending_task_titles: List[str] = []
        autonomy_work_titles: List[str] = []
        task_state_sync_monitor_titles: List[str] = []
        task_state_sync_monitor_task_ids: List[str] = []
        week1_validation_monitor_titles: List[str] = []
        week1_procurement_prerequisite_pending = 0
        pending_tasks = 0
        in_progress_tasks = 0
        overdue_tasks = 0
        stats: Dict[str, Any] = {}
        try:
            stats = self.master_list.get_stats()
            pending_tasks = int((stats or {}).get("pending", 0) or 0)
            in_progress_tasks = int((stats or {}).get("in_progress", 0) or 0)
            overdue_tasks = int((stats or {}).get("overdue", 0) or 0)
            tasks = list(self.master_list.parse() or [])
            if tasks:
                pending_tasks = 0
                in_progress_tasks = 0
                overdue_tasks = 0
                for task in tasks:
                    status = getattr(task, "status", None)
                    if self._is_non_actionable_autonomy_workflow_task(task):
                        continue
                    if status == TaskStatus.PENDING:
                        pending_tasks += 1
                        title = str(getattr(task, "title", "") or "").strip()
                        if title and title not in pending_task_titles:
                            pending_task_titles.append(title)
                        tags = set(getattr(task, "tags", []) or [])
                        if "week1_procurement_prerequisite" in tags:
                            week1_procurement_prerequisite_pending += 1
                    elif status == TaskStatus.IN_PROGRESS:
                        in_progress_tasks += 1
                    try:
                        if bool(getattr(task, "is_overdue", lambda: False)()):
                            overdue_tasks += 1
                    except Exception:
                        continue
        except Exception:
            pass

        active_goals = 0
        try:
            inner_life = getattr(self, "inner_life", None)
            if inner_life is not None and hasattr(inner_life, "_load_goals"):
                goal_state = inner_life._load_goals()
                goals = goal_state.get("goals", []) if isinstance(goal_state, dict) else []
                active_goals = sum(
                    1
                    for goal in goals
                    if isinstance(goal, dict) and str(goal.get("status") or "").strip().lower() == "active"
                )
        except Exception:
            active_goals = 0

        dnd_pending = 0
        try:
            dnd = getattr(self, "dnd", None)
            if dnd is not None and hasattr(dnd, "get_pending"):
                pending_interrupts = dnd.get_pending()
                dnd_pending = len(pending_interrupts) if isinstance(pending_interrupts, list) else 0
        except Exception:
            dnd_pending = 0

        dead_letter_backlog = 0
        try:
            runplane = getattr(self, "runplane", None)
            if runplane is not None and hasattr(runplane, "list_dead_letters"):
                dead_rows = runplane.list_dead_letters(limit=500)
                dead_letter_backlog = len(dead_rows) if isinstance(dead_rows, list) else 0
        except Exception:
            dead_letter_backlog = 0

        try:
            runplane = getattr(self, "runplane", None)
            if runplane is not None and hasattr(runplane, "list_runs"):
                recent_week1_runs = runplane.list_runs(limit=8, job_id="executor.week1")
                for row in recent_week1_runs:
                    if not isinstance(row, dict):
                        continue
                    result = row.get("result")
                    if not isinstance(result, dict):
                        continue
                    top_tasks = result.get("top_tasks")
                    if isinstance(top_tasks, list):
                        week1_top_tasks = [
                            str(item).strip()
                            for item in top_tasks
                            if str(item).strip()
                        ][:3]
                    if week1_top_tasks:
                        break
        except Exception:
            week1_top_tasks = []
        if not week1_top_tasks:
            try:
                week1_top_tasks = self._load_week1_structured_top_tasks(limit=3)
            except Exception:
                week1_top_tasks = []

        week1_progress_state: Dict[str, Any] = {}
        if week1_top_tasks:
            try:
                week1_progress_state = self._reconcile_week1_progress_state_from_tasks()
            except Exception:
                week1_progress_state = self._load_week1_progress_state()
        completed_week1_stages = self._week1_completed_stages(week1_progress_state)
        next_week1_stage = self._week1_next_pending_stage(week1_progress_state)
        autonomy_work_items = self._eligible_autonomy_work_items(limit=3)
        autonomy_work_titles = [
            str(item.get("title") or item.get("objective") or "").strip()
            for item in autonomy_work_items
            if str(item.get("title") or item.get("objective") or "").strip()
        ]
        try:
            verifier_state = self._load_state_sync_verifier_state()
            monitor_candidates = verifier_state.get("monitor_candidates")
            if isinstance(monitor_candidates, dict):
                surfaced_rows = [
                    (str(task_id or "").strip(), dict(row or {}))
                    for task_id, row in monitor_candidates.items()
                    if str(task_id or "").strip() and isinstance(row, dict) and bool(row.get("surfaced"))
                ]
                surfaced_rows.sort(
                    key=lambda item: (
                        -int((item[1] or {}).get("consecutive_cycle_scans") or 0),
                        str((item[1] or {}).get("last_seen_utc") or ""),
                    )
                )
                master_list = getattr(self, "master_list", None)
                for task_id, row in surfaced_rows[:3]:
                    title = str((row or {}).get("task_title") or "").strip()
                    if not title and master_list is not None and hasattr(master_list, "get_by_id"):
                        try:
                            task = master_list.get_by_id(task_id)
                        except Exception:
                            task = None
                        if task is not None:
                            title = str(getattr(task, "title", "") or "").strip()
                    if not title:
                        title = f"Resolve recurring post-completion state-sync mismatch for {task_id}"
                    task_state_sync_monitor_task_ids.append(task_id)
                    task_state_sync_monitor_titles.append(title)
        except Exception:
            task_state_sync_monitor_titles = []
            task_state_sync_monitor_task_ids = []
        try:
            validation_probe = self._refresh_week1_validation_monitor_state()
            if bool(validation_probe.get("surfaced")):
                week1_validation_monitor_titles = [
                    str(validation_probe.get("title") or "Produce a Week1 validation snapshot")
                ]
        except Exception:
            week1_validation_monitor_titles = []

        eligible_week1_ops_titles = self._eligible_week1_ops_backlog_titles(week1_top_tasks)
        week1_stage_actionable = bool(week1_top_tasks) and bool(next_week1_stage)
        week1_ops_backlog_actionable = bool(eligible_week1_ops_titles)

        surface = {
            "pending_tasks": pending_tasks,
            "pending_task_titles": pending_task_titles[:3],
            "in_progress_tasks": in_progress_tasks,
            "overdue_tasks": overdue_tasks,
            "active_goals": active_goals,
            "dnd_pending": dnd_pending,
            "dead_letter_backlog": dead_letter_backlog,
            "week1_top_tasks": len(week1_top_tasks),
            "week1_task_titles": list(week1_top_tasks),
            "week1_ops_backlog_items": len(eligible_week1_ops_titles),
            "week1_ops_backlog_titles": list(eligible_week1_ops_titles),
            "week1_completed_stages": completed_week1_stages,
            "week1_next_stage": next_week1_stage,
            "week1_procurement_prerequisite_pending": week1_procurement_prerequisite_pending,
            "autonomy_work_jar_items": len(autonomy_work_items),
            "autonomy_work_jar_titles": autonomy_work_titles,
            "task_state_sync_monitor_items": len(task_state_sync_monitor_task_ids),
            "task_state_sync_monitor_titles": task_state_sync_monitor_titles,
            "task_state_sync_monitor_task_ids": task_state_sync_monitor_task_ids,
            "week1_validation_monitor_items": len(week1_validation_monitor_titles),
            "week1_validation_monitor_titles": week1_validation_monitor_titles,
        }

        if (
            pending_tasks > 0
            or in_progress_tasks > 0
            or overdue_tasks > 0
            or active_goals > 0
            or dnd_pending > 0
            or dead_letter_backlog > 0
            or week1_stage_actionable
            or week1_ops_backlog_actionable
            or len(autonomy_work_items) > 0
            or len(task_state_sync_monitor_task_ids) > 0
            or len(week1_validation_monitor_titles) > 0
        ):
            return {
                "needed": True,
                "reason": "actionable_work_present",
                "surface": surface,
            }
        return {
            "needed": False,
            "reason": "autonomy_no_actionable_work",
            "surface": surface,
        }

    def _surface_has_actionable_work(self, surface: Dict[str, Any]) -> bool:
        if not isinstance(surface, dict):
            return False
        numeric_keys = (
            "pending_tasks",
            "in_progress_tasks",
            "overdue_tasks",
            "active_goals",
            "dnd_pending",
            "dead_letter_backlog",
            "week1_procurement_prerequisite_pending",
            "autonomy_work_jar_items",
            "task_state_sync_monitor_items",
            "week1_validation_monitor_items",
        )
        for key in numeric_keys:
            try:
                if float(surface.get(key) or 0) > 0:
                    return True
            except Exception:
                continue
        if str(surface.get("week1_next_stage") or "").strip():
            return True
        pending_titles = surface.get("pending_task_titles")
        if isinstance(pending_titles, (list, tuple)) and pending_titles:
            return True
        work_titles = surface.get("autonomy_work_jar_titles")
        if isinstance(work_titles, (list, tuple)) and work_titles:
            return True
        sync_titles = surface.get("task_state_sync_monitor_titles")
        if isinstance(sync_titles, (list, tuple)) and sync_titles:
            return True
        validation_titles = surface.get("week1_validation_monitor_titles")
        if isinstance(validation_titles, (list, tuple)) and validation_titles:
            return True
        if self._select_week1_ops_backlog_candidate(surface):
            return True
        return False

    @staticmethod
    def _surface_has_explicit_autonomy_work(surface: Dict[str, Any]) -> bool:
        if not isinstance(surface, dict):
            return False
        try:
            if float(surface.get("autonomy_work_jar_items") or 0) > 0:
                return True
        except Exception:
            pass
        titles = surface.get("autonomy_work_jar_titles")
        return isinstance(titles, (list, tuple)) and bool(titles)

    def _is_non_actionable_autonomy_workflow_task(self, task: Any) -> bool:
        if task is None:
            return False
        tags = {str(tag).strip().lower() for tag in (getattr(task, "tags", None) or [])}
        if not {"inner-life", "autonomy", "workflow"}.issubset(tags):
            return False
        status_value = str(getattr(task, "status", "") or "").split(".")[-1].lower()
        if status_value == TaskStatus.BLOCKED.value:
            return True
        return status_value == TaskStatus.IN_PROGRESS.value and self._is_stale_autonomy_workflow_task(task)

    @staticmethod
    def _surface_has_task_state_sync_monitor_work(surface: Dict[str, Any]) -> bool:
        if not isinstance(surface, dict):
            return False
        try:
            if float(surface.get("task_state_sync_monitor_items") or 0) > 0:
                return True
        except Exception:
            pass
        titles = surface.get("task_state_sync_monitor_titles")
        return isinstance(titles, (list, tuple)) and bool(titles)

    @staticmethod
    def _surface_has_week1_validation_monitor_work(surface: Dict[str, Any]) -> bool:
        if not isinstance(surface, dict):
            return False
        try:
            if float(surface.get("week1_validation_monitor_items") or 0) > 0:
                return True
        except Exception:
            pass
        titles = surface.get("week1_validation_monitor_titles")
        return isinstance(titles, (list, tuple)) and bool(titles)

    def _surface_has_week1_ops_backlog_work(self, surface: Dict[str, Any]) -> bool:
        if not isinstance(surface, dict):
            return False
        return bool(self._select_week1_ops_backlog_candidate(surface))

    @staticmethod
    def _autonomy_work_priority_rank(priority: str) -> int:
        normalized = str(priority or "").strip().lower()
        ranks = {
            "urgent": 0,
            "high": 1,
            "normal": 2,
            "medium": 2,
            "low": 3,
            "background": 4,
        }
        return ranks.get(normalized, 2)

    def _default_autonomy_work_jar_state(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "items": [],
            "archived_items": [],
            "updated_at_utc": _utc_iso(),
        }

    def _get_week1_validation_monitor_path(self) -> Path:
        path = self._local_attr(self, "_week1_validation_monitor_path", None)
        if isinstance(path, Path):
            return path
        memory_dir = self._local_attr(self, "_memory_dir", None) or self._safe_memory_dir()
        if not isinstance(memory_dir, Path):
            memory_dir = Path(memory_dir)
        path = memory_dir / "week1_validation_monitor.json"
        self._week1_validation_monitor_path = path
        return path

    def _get_week1_task_schedule_path(self) -> Path:
        path = self._local_attr(self, "_week1_task_schedule_path", None)
        if isinstance(path, Path):
            return path
        memory_dir = self._local_attr(self, "_memory_dir", None) or self._safe_memory_dir()
        if not isinstance(memory_dir, Path):
            memory_dir = Path(memory_dir)
        path = memory_dir / "week1_task_schedule.json"
        self._week1_task_schedule_path = path
        return path

    def _get_week1_ops_backlog_state_path(self) -> Path:
        path = self._local_attr(self, "_week1_ops_backlog_state_path", None)
        if isinstance(path, Path):
            return path
        memory_dir = self._local_attr(self, "_memory_dir", None) or self._safe_memory_dir()
        if not isinstance(memory_dir, Path):
            memory_dir = Path(memory_dir)
        path = memory_dir / "week1_ops_backlog_state.json"
        self._week1_ops_backlog_state_path = path
        return path

    @staticmethod
    def _default_week1_ops_backlog_state() -> Dict[str, Any]:
        return {
            "version": 1,
            "updated_at_utc": _utc_iso(),
            "items": {},
        }

    def _load_week1_ops_backlog_state(self) -> Dict[str, Any]:
        payload = safe_json_read(self._get_week1_ops_backlog_state_path(), default={}) or {}
        state = self._default_week1_ops_backlog_state()
        if isinstance(payload, dict):
            state.update(payload)
        items = state.get("items")
        if not isinstance(items, dict):
            items = {}
        normalized: Dict[str, Dict[str, Any]] = {}
        now = _utc_now()
        for key, row in items.items():
            if not isinstance(row, dict):
                continue
            title = str(key or "").strip()
            if not title:
                continue
            next_eligible_utc = str(row.get("next_eligible_utc") or "")
            last_status = str(row.get("last_status") or "")
            awaiting_human_followthrough = bool(row.get("awaiting_human_followthrough"))
            resume_after_utc = str(row.get("resume_after_utc") or "")
            if not awaiting_human_followthrough and not resume_after_utc and last_status.strip().lower() == "completed":
                next_eligible_dt = _parse_iso_utc(next_eligible_utc)
                if next_eligible_dt is not None and next_eligible_dt > now:
                    awaiting_human_followthrough = True
                    resume_after_utc = next_eligible_utc
            normalized[title] = {
                "next_eligible_utc": next_eligible_utc,
                "last_status": last_status,
                "last_task_id": str(row.get("last_task_id") or ""),
                "last_reason": str(row.get("last_reason") or ""),
                "awaiting_human_followthrough": awaiting_human_followthrough,
                "resume_after_utc": resume_after_utc,
                "updated_at_utc": str(row.get("updated_at_utc") or ""),
            }
        state["items"] = normalized
        return state

    def _save_week1_ops_backlog_state(self, state: Dict[str, Any]) -> None:
        payload = self._default_week1_ops_backlog_state()
        if isinstance(state, dict):
            payload.update(state)
        payload["updated_at_utc"] = _utc_iso()
        path = self._get_week1_ops_backlog_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, payload)

    @staticmethod
    def _week1_ops_backlog_item_cooldown(status: str) -> timedelta:
        normalized = str(status or "").strip().lower()
        if normalized == "completed":
            return timedelta(hours=6)
        if normalized == "blocked":
            return timedelta(minutes=90)
        return timedelta(minutes=30)

    def _week1_ops_backlog_resume_after_utc(
        self,
        candidate: Dict[str, Any],
        status: str,
    ) -> Tuple[str, bool]:
        now = _utc_now()
        cooldown_until = now + self._week1_ops_backlog_item_cooldown(status)
        normalized = str(status or "").strip().lower()
        row = dict(candidate.get("schedule_row") or {})
        scheduled_dt = _parse_iso_utc(str(row.get("scheduled_local") or ""))
        if normalized == "completed" and scheduled_dt is not None and scheduled_dt > now:
            return scheduled_dt.isoformat().replace("+00:00", "Z"), True
        return cooldown_until.isoformat().replace("+00:00", "Z"), False

    def _load_week1_structured_schedule_items(self) -> List[Dict[str, Any]]:
        path = self._get_week1_task_schedule_path()
        raw = safe_json_read(path, default={}) or {}
        items = raw.get("items") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            return []
        out: List[Dict[str, Any]] = []
        for row in items:
            if not isinstance(row, dict):
                continue
            title = str(row.get("parent_title") or "").strip()
            scheduled_local = str(row.get("scheduled_local") or "").strip()
            if not title or not scheduled_local:
                continue
            out.append(dict(row))
        return out

    def _load_week1_structured_top_tasks(self, limit: int = 3) -> List[str]:
        items = self._load_week1_structured_schedule_items()
        now = _utc_now()
        ranked: List[Tuple[Tuple[int, float, int, str], str]] = []
        seen: Set[str] = set()
        priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        for row in items:
            if not isinstance(row, dict):
                continue
            title = str(row.get("parent_title") or "").strip()
            if not title or title in seen:
                continue
            scheduled_dt = _parse_iso_utc(str(row.get("scheduled_local") or ""))
            if scheduled_dt is None:
                continue
            delta_minutes = (scheduled_dt - now).total_seconds() / 60.0
            abs_delta = abs(delta_minutes)
            if abs_delta <= 18 * 60:
                bucket = 0
            elif 0 < delta_minutes <= 48 * 60:
                bucket = 1
            elif -48 * 60 <= delta_minutes < 0:
                bucket = 2
            elif delta_minutes > 0:
                bucket = 3
            else:
                bucket = 4
            ranked.append(
                (
                    (
                        bucket,
                        abs_delta,
                        priority_rank.get(str(row.get("priority") or "").strip(), 9),
                        title.lower(),
                    ),
                    title,
                )
            )
            seen.add(title)
        ranked.sort(key=lambda item: item[0])
        return [title for _, title in ranked[: max(1, int(limit))]]

    def _eligible_week1_ops_backlog_titles(self, titles: Sequence[str]) -> List[str]:
        visible_titles = [str(item).strip() for item in titles if str(item).strip()]
        if not visible_titles:
            return []
        schedule_items = self._load_week1_structured_schedule_items()
        by_title = {
            str(row.get("parent_title") or "").strip(): row
            for row in schedule_items
            if isinstance(row, dict) and str(row.get("parent_title") or "").strip()
        }
        state = self._load_week1_ops_backlog_state()
        item_state = state.get("items") if isinstance(state.get("items"), dict) else {}
        now = _utc_now()
        eligible: List[str] = []
        for title in visible_titles:
            row = by_title.get(title)
            if not isinstance(row, dict):
                continue
            meta = dict(item_state.get(title) or {})
            next_eligible = _parse_iso_utc(str(meta.get("next_eligible_utc") or ""))
            resume_after = _parse_iso_utc(str(meta.get("resume_after_utc") or ""))
            awaiting_followthrough = bool(meta.get("awaiting_human_followthrough"))
            if awaiting_followthrough and resume_after is not None and resume_after > now:
                continue
            if next_eligible is None or next_eligible <= now:
                eligible.append(title)
        return eligible

    def _default_week1_validation_monitor_state(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "updated_at_utc": _utc_iso(),
            "last_snapshot_task_id": "",
            "last_snapshot_utc": "",
            "last_snapshot_reason": "",
            "candidate": {},
        }

    def _load_week1_validation_monitor_state(self) -> Dict[str, Any]:
        payload = safe_json_read(self._get_week1_validation_monitor_path(), default={}) or {}
        default = self._default_week1_validation_monitor_state()
        if not isinstance(payload, dict):
            payload = {}
        state = dict(default)
        state.update(payload)
        candidate = dict(state.get("candidate") or {})
        normalized_candidate: Dict[str, Any] = {}
        if candidate:
            normalized_candidate = {
                "first_seen_utc": str(candidate.get("first_seen_utc") or ""),
                "last_seen_utc": str(candidate.get("last_seen_utc") or ""),
                "consecutive_cycle_scans": int(candidate.get("consecutive_cycle_scans") or 0),
                "surfaced": bool(candidate.get("surfaced")),
                "reason": str(candidate.get("reason") or ""),
                "title": str(candidate.get("title") or ""),
                "latest_event_utc": str(candidate.get("latest_event_utc") or ""),
                "recent_event_count": int(candidate.get("recent_event_count") or 0),
                "recent_ack_count": int(candidate.get("recent_ack_count") or 0),
                "latest_ack_utc": str(candidate.get("latest_ack_utc") or ""),
            }
        state["candidate"] = normalized_candidate
        state["last_snapshot_task_id"] = str(state.get("last_snapshot_task_id") or "")
        state["last_snapshot_utc"] = str(state.get("last_snapshot_utc") or "")
        state["last_snapshot_reason"] = str(state.get("last_snapshot_reason") or "")
        return state

    def _save_week1_validation_monitor_state(self, state: Dict[str, Any]) -> None:
        payload = self._default_week1_validation_monitor_state()
        if isinstance(state, dict):
            payload.update(state)
        payload["updated_at_utc"] = _utc_iso()
        path = self._get_week1_validation_monitor_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, payload)

    def _week1_validation_monitor_confirmation_cycles(self) -> int:
        config = getattr(self, "_autonomy_config", {}) or {}
        try:
            return max(1, int(config.get("week1_validation_monitor_confirmation_cycles", 3) or 3))
        except Exception:
            return 3

    def _week1_validation_snapshot_interval_hours(self) -> int:
        config = getattr(self, "_autonomy_config", {}) or {}
        try:
            return max(1, int(config.get("week1_validation_snapshot_interval_hours", 24) or 24))
        except Exception:
            return 24

    def _collect_recent_week1_validation_signal(self, *, lookback_hours: int = 72) -> Dict[str, Any]:
        now = _utc_now()
        cutoff = now - timedelta(hours=max(1, int(lookback_hours)))
        memory_dir = self._local_attr(self, "_memory_dir", None) or self._safe_memory_dir()
        if not isinstance(memory_dir, Path):
            memory_dir = Path(memory_dir)
        event_path = memory_dir / "week1_executor_events.jsonl"
        ack_path = memory_dir / "push_user_ack.jsonl"
        recent_events: List[Dict[str, Any]] = []
        latest_event_utc = ""
        latest_event_dt: Optional[datetime] = None
        ok_count = 0
        failed_count = 0
        deferred_count = 0

        if event_path.exists():
            try:
                for line in event_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        continue
                    ts = _parse_iso_utc(str(row.get("ts_utc") or ""))
                    if ts is None or ts < cutoff:
                        continue
                    recent_events.append(row)
                    if latest_event_dt is None or ts > latest_event_dt:
                        latest_event_dt = ts
                        latest_event_utc = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                    status = str(row.get("status") or "").strip().lower()
                    if status in {"ok", "partial_ok_fallback_push"}:
                        ok_count += 1
                    elif status.startswith("deferred"):
                        deferred_count += 1
                    else:
                        failed_count += 1
            except Exception:
                recent_events = []
                latest_event_utc = ""
                latest_event_dt = None
                ok_count = 0
                failed_count = 0
                deferred_count = 0

        recent_ack_count = 0
        latest_ack_utc = ""
        latest_ack_dt: Optional[datetime] = None
        if ack_path.exists():
            try:
                for line in ack_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        continue
                    ts = _parse_iso_utc(str(row.get("timestamp_utc") or ""))
                    if ts is None or ts < cutoff:
                        continue
                    recent_ack_count += 1
                    if latest_ack_dt is None or ts > latest_ack_dt:
                        latest_ack_dt = ts
                        latest_ack_utc = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            except Exception:
                recent_ack_count = 0
                latest_ack_utc = ""

        return {
            "lookback_hours": int(lookback_hours),
            "recent_event_count": len(recent_events),
            "recent_ok_count": ok_count,
            "recent_failed_count": failed_count,
            "recent_deferred_count": deferred_count,
            "latest_event_utc": latest_event_utc,
            "recent_ack_count": recent_ack_count,
            "latest_ack_utc": latest_ack_utc,
        }

    def _refresh_week1_validation_monitor_state(self) -> Dict[str, Any]:
        signal = self._collect_recent_week1_validation_signal()
        state = self._load_week1_validation_monitor_state()
        snapshot_dt = _parse_iso_utc(str(state.get("last_snapshot_utc") or ""))
        latest_event_dt = _parse_iso_utc(str(signal.get("latest_event_utc") or ""))
        due = False
        reason = ""
        if latest_event_dt is not None:
            min_interval = timedelta(hours=self._week1_validation_snapshot_interval_hours())
            if snapshot_dt is None:
                due = True
                reason = "week1_validation_snapshot_missing"
            elif snapshot_dt < latest_event_dt and (_utc_now() - snapshot_dt) >= min_interval:
                due = True
                reason = "week1_validation_snapshot_stale"
            elif snapshot_dt < latest_event_dt and (_utc_now() - latest_event_dt) >= timedelta(hours=1):
                due = True
                reason = "week1_activity_since_last_snapshot"

        candidate = dict(state.get("candidate") or {})
        if due:
            consecutive = int(candidate.get("consecutive_cycle_scans") or 0) + 1
            title = "Produce a Week1 validation snapshot from recent executor and ACK evidence"
            candidate = {
                "first_seen_utc": str(candidate.get("first_seen_utc") or _utc_iso()),
                "last_seen_utc": _utc_iso(),
                "consecutive_cycle_scans": consecutive,
                "surfaced": consecutive >= self._week1_validation_monitor_confirmation_cycles(),
                "reason": reason,
                "title": title,
                "latest_event_utc": str(signal.get("latest_event_utc") or ""),
                "recent_event_count": int(signal.get("recent_event_count") or 0),
                "recent_ack_count": int(signal.get("recent_ack_count") or 0),
                "latest_ack_utc": str(signal.get("latest_ack_utc") or ""),
            }
        else:
            candidate = {}
        state["candidate"] = candidate
        self._save_week1_validation_monitor_state(state)
        return {
            "due": due,
            "reason": reason,
            "surfaced": bool(candidate.get("surfaced")),
            "title": str(candidate.get("title") or ""),
            "signal": signal,
            "candidate": candidate,
            "last_snapshot_utc": str(state.get("last_snapshot_utc") or ""),
            "last_snapshot_task_id": str(state.get("last_snapshot_task_id") or ""),
        }

    @staticmethod
    def _normalize_autonomy_work_tool_choice(value: Any) -> Optional[str]:
        raw = str(value or "").strip().lower()
        if raw in {"none", "auto"}:
            return raw
        return None

    def _default_state_sync_verifier_state(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "updated_at_utc": _utc_iso(),
            "last_cycle_scan_utc": "",
            "verified_tasks": {},
            "pending_followup_task_ids": [],
            "monitor_candidates": {},
        }

    def _get_state_sync_verifier_state_path(self) -> Path:
        path = self._local_attr(self, "_state_sync_verifier_state_path", None)
        if isinstance(path, Path):
            return path
        memory_dir = self._local_attr(self, "_memory_dir", None) or self._safe_memory_dir()
        if not isinstance(memory_dir, Path):
            memory_dir = Path(memory_dir)
        path = memory_dir / "autonomy_state_sync_verifier.json"
        self._state_sync_verifier_state_path = path
        return path

    def _get_state_sync_verifier_event_log_path(self) -> Path:
        path = self._local_attr(self, "_state_sync_verifier_event_log", None)
        if isinstance(path, Path):
            return path
        memory_dir = self._local_attr(self, "_memory_dir", None) or self._safe_memory_dir()
        if not isinstance(memory_dir, Path):
            memory_dir = Path(memory_dir)
        path = memory_dir / "autonomy_state_sync_verifier_events.jsonl"
        self._state_sync_verifier_event_log = path
        return path

    def _load_state_sync_verifier_state(self) -> Dict[str, Any]:
        payload = safe_json_read(self._get_state_sync_verifier_state_path(), default={}) or {}
        default = self._default_state_sync_verifier_state()
        if not isinstance(payload, dict):
            return default
        verified_tasks = payload.get("verified_tasks")
        normalized_verified: Dict[str, Dict[str, Any]] = {}
        if isinstance(verified_tasks, dict):
            for task_id, row in verified_tasks.items():
                key = str(task_id or "").strip()
                if not key or not isinstance(row, dict):
                    continue
                normalized_verified[key] = {
                    "verified_at_utc": str(row.get("verified_at_utc") or ""),
                    "last_trigger": str(row.get("last_trigger") or ""),
                    "autonomy_work_item_id": str(row.get("autonomy_work_item_id") or ""),
                    "week1_stage": str(row.get("week1_stage") or ""),
                    "completion_contract_satisfied": bool(row.get("completion_contract_satisfied")),
                    "last_reason": str(row.get("last_reason") or ""),
                    "last_ok": bool(row.get("last_ok")),
                    "last_repaired": bool(row.get("last_repaired")),
                }
        pending = payload.get("pending_followup_task_ids")
        pending_ids: List[str] = []
        if isinstance(pending, list):
            for item in pending:
                task_id = str(item or "").strip()
                if task_id and task_id not in pending_ids:
                    pending_ids.append(task_id)
        raw_candidates = payload.get("monitor_candidates")
        normalized_candidates: Dict[str, Dict[str, Any]] = {}
        if isinstance(raw_candidates, dict):
            for task_id, row in raw_candidates.items():
                key = str(task_id or "").strip()
                if not key or not isinstance(row, dict):
                    continue
                normalized_candidates[key] = {
                    "first_seen_utc": str(row.get("first_seen_utc") or ""),
                    "last_seen_utc": str(row.get("last_seen_utc") or ""),
                    "consecutive_cycle_scans": int(row.get("consecutive_cycle_scans") or 0),
                    "last_reason": str(row.get("last_reason") or ""),
                    "autonomy_work_item_id": str(row.get("autonomy_work_item_id") or ""),
                    "week1_stage": str(row.get("week1_stage") or ""),
                    "task_title": str(row.get("task_title") or ""),
                    "surfaced": bool(row.get("surfaced")),
                }
        payload["version"] = int(payload.get("version") or 1)
        payload["updated_at_utc"] = str(payload.get("updated_at_utc") or "")
        payload["last_cycle_scan_utc"] = str(payload.get("last_cycle_scan_utc") or "")
        payload["verified_tasks"] = normalized_verified
        payload["pending_followup_task_ids"] = pending_ids
        payload["monitor_candidates"] = normalized_candidates
        return payload

    def _save_state_sync_verifier_state(self, state: Dict[str, Any]) -> None:
        if not isinstance(state, dict):
            state = self._default_state_sync_verifier_state()
        verified = state.get("verified_tasks")
        if isinstance(verified, dict) and len(verified) > 200:
            ordered = sorted(
                verified.items(),
                key=lambda item: str((item[1] or {}).get("verified_at_utc") or ""),
                reverse=True,
            )
            state["verified_tasks"] = dict(ordered[:200])
        candidates = state.get("monitor_candidates")
        if isinstance(candidates, dict) and len(candidates) > 200:
            ordered_candidates = sorted(
                candidates.items(),
                key=lambda item: str((item[1] or {}).get("last_seen_utc") or (item[1] or {}).get("first_seen_utc") or ""),
                reverse=True,
            )
            state["monitor_candidates"] = dict(ordered_candidates[:200])
        state["updated_at_utc"] = _utc_iso()
        path = self._get_state_sync_verifier_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, state)

    def _append_state_sync_verifier_event(self, payload: Dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        path = self._get_state_sync_verifier_event_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts_utc": _utc_iso(), **payload}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True))
            handle.write("\n")

    def _get_autonomy_work_jar_path(self) -> Path:
        path = self._local_attr(self, "_autonomy_work_jar_path", None)
        if isinstance(path, Path):
            return path
        memory_dir = self._local_attr(self, "_memory_dir", None) or self._safe_memory_dir()
        if not isinstance(memory_dir, Path):
            memory_dir = Path(memory_dir)
        path = memory_dir / "autonomy_work_jar.json"
        self._autonomy_work_jar_path = path
        return path

    def _load_autonomy_work_jar(self) -> Dict[str, Any]:
        payload = safe_json_read(self._get_autonomy_work_jar_path(), default={}) or {}
        default = self._default_autonomy_work_jar_state()
        if not isinstance(payload, dict):
            return default
        def _normalize_row(row: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(row, dict):
                return None
            return {
                "id": str(row.get("id") or "").strip(),
                "title": str(row.get("title") or "").strip(),
                "objective": str(row.get("objective") or "").strip(),
                "context": str(row.get("context") or "").strip(),
                "source": str(row.get("source") or "").strip(),
                "priority": str(row.get("priority") or "normal").strip().lower(),
                "tool_choice": self._normalize_autonomy_work_tool_choice(row.get("tool_choice")),
                "status": str(row.get("status") or "pending").strip().lower(),
                "next_eligible_utc": str(row.get("next_eligible_utc") or "").strip(),
                "retry_count": int(row.get("retry_count") or 0),
                "created_at_utc": str(row.get("created_at_utc") or "").strip(),
                "updated_at_utc": str(row.get("updated_at_utc") or "").strip(),
                "last_attempt_utc": str(row.get("last_attempt_utc") or "").strip(),
                "completion_contract": dict(row.get("completion_contract") or {}),
                "metadata": dict(row.get("metadata") or {}),
            }

        items = payload.get("items")
        if not isinstance(items, list):
            payload["items"] = []
            items = payload["items"]
        normalized_items: List[Dict[str, Any]] = []
        for row in items:
            normalized = _normalize_row(row)
            if normalized is None:
                continue
            normalized_items.append(normalized)
        archived_items = payload.get("archived_items")
        if not isinstance(archived_items, list):
            payload["archived_items"] = []
            archived_items = payload["archived_items"]
        normalized_archived: List[Dict[str, Any]] = []
        for row in archived_items:
            normalized = _normalize_row(row)
            if normalized is None:
                continue
            normalized_archived.append(normalized)
        payload["version"] = int(payload.get("version") or 1)
        payload["updated_at_utc"] = str(payload.get("updated_at_utc") or "")
        payload["items"] = normalized_items
        payload["archived_items"] = normalized_archived
        return payload

    def _save_autonomy_work_jar(self, state: Dict[str, Any]) -> None:
        if not isinstance(state, dict):
            state = self._default_autonomy_work_jar_state()
        archived = state.get("archived_items")
        if isinstance(archived, list) and len(archived) > 200:
            archived = sorted(
                archived,
                key=lambda row: str((row or {}).get("metadata", {}).get("archived_at_utc") or (row or {}).get("updated_at_utc") or ""),
                reverse=True,
            )[:200]
            state["archived_items"] = archived
        state["updated_at_utc"] = _utc_iso()
        path = self._get_autonomy_work_jar_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(path, state)

    def _archive_autonomy_work_jar_item(
        self,
        item_id: str,
        *,
        archive_reason: str,
    ) -> bool:
        target_id = str(item_id or "").strip()
        if not target_id:
            return False
        state = self._load_autonomy_work_jar()
        items = list(state.get("items") or [])
        archived_items = list(state.get("archived_items") or [])
        archived = False
        kept: List[Dict[str, Any]] = []
        for row in items:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "").strip() != target_id:
                kept.append(row)
                continue
            archived_row = dict(row)
            metadata = dict(archived_row.get("metadata") or {})
            metadata["archived_at_utc"] = _utc_iso()
            metadata["archive_reason"] = str(archive_reason or "verifier_archive")
            archived_row["metadata"] = metadata
            archived_row["updated_at_utc"] = _utc_iso()
            archived_items.append(archived_row)
            archived = True
        if not archived:
            return False
        state["items"] = kept
        state["archived_items"] = archived_items
        self._save_autonomy_work_jar(state)
        return True

    def _archive_verified_completed_autonomy_work_items(self, *, limit: int = 10) -> Dict[str, Any]:
        state = self._load_autonomy_work_jar()
        items = list(state.get("items") or [])
        verified = dict(self._load_state_sync_verifier_state().get("verified_tasks") or {})
        archived_ids: List[str] = []
        for row in items:
            if len(archived_ids) >= max(1, int(limit or 1)):
                break
            if not isinstance(row, dict):
                continue
            if str(row.get("status") or "").strip().lower() != "completed":
                continue
            item_id = str(row.get("id") or "").strip()
            task_id = str((row.get("metadata") or {}).get("completed_by_task_id") or "").strip()
            if not item_id or not task_id:
                continue
            verified_row = dict(verified.get(task_id) or {})
            if not bool(verified_row.get("last_ok")):
                continue
            if self._archive_autonomy_work_jar_item(item_id, archive_reason="verified_complete"):
                archived_ids.append(item_id)
        return {
            "attempted": len(items),
            "archived": len(archived_ids),
            "archived_item_ids": archived_ids,
        }

    def _eligible_autonomy_work_items(self, limit: int = 3) -> List[Dict[str, Any]]:
        state = self._load_autonomy_work_jar()
        items = list((state.get("items") or []))
        now = _utc_now()
        eligible: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "pending").strip().lower() != "pending":
                continue
            next_eligible = _parse_iso_utc(str(item.get("next_eligible_utc") or ""))
            if next_eligible is not None and next_eligible > now:
                continue
            eligible.append(item)
        eligible.sort(
            key=lambda row: (
                self._autonomy_work_priority_rank(str(row.get("priority") or "")),
                str(row.get("created_at_utc") or ""),
                str(row.get("id") or ""),
            )
        )
        return eligible[: max(1, int(limit or 1))]

    def _mark_autonomy_work_item_status(
        self,
        item_id: str,
        *,
        status: str,
        retry_count: Optional[int] = None,
        next_eligible_utc: str = "",
        metadata_patch: Optional[Dict[str, Any]] = None,
    ) -> None:
        target_id = str(item_id or "").strip()
        if not target_id:
            return
        state = self._load_autonomy_work_jar()
        changed = False
        for row in state.get("items") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "").strip() != target_id:
                continue
            row["status"] = str(status or row.get("status") or "pending").strip().lower()
            row["updated_at_utc"] = _utc_iso()
            row["last_attempt_utc"] = _utc_iso()
            if retry_count is not None:
                row["retry_count"] = int(retry_count)
            if next_eligible_utc:
                row["next_eligible_utc"] = str(next_eligible_utc)
            elif row["status"] != "pending":
                row["next_eligible_utc"] = ""
            if metadata_patch:
                metadata = dict(row.get("metadata") or {})
                metadata.update(metadata_patch)
                row["metadata"] = metadata
            changed = True
            break
        if changed:
            self._save_autonomy_work_jar(state)

    def _run_post_completion_state_sync_verifier(
        self,
        *,
        task_id: str,
        trigger: str,
        autonomy_work_item_id: str = "",
        week1_stage: str = "",
        completion_evaluation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_task_id = str(task_id or "").strip()
        report: Dict[str, Any] = {
            "task_id": normalized_task_id,
            "trigger": str(trigger or "").strip() or "post_completion",
            "autonomy_work_item_id": str(autonomy_work_item_id or "").strip(),
            "week1_stage": str(week1_stage or "").strip(),
            "completion_contract_satisfied": bool((completion_evaluation or {}).get("satisfied")),
            "ok": False,
            "repaired": False,
            "needs_followup": False,
        }
        master_list = getattr(self, "master_list", None)
        if not normalized_task_id or master_list is None or not hasattr(master_list, "get_by_id"):
            report["reason"] = "task_unavailable"
            self._append_state_sync_verifier_event({"type": "state_sync_verifier", **report})
            return report
        try:
            task = master_list.get_by_id(normalized_task_id)
        except Exception:
            task = None
        if task is None:
            report["reason"] = "task_not_found"
            report["needs_followup"] = True
            self._append_state_sync_verifier_event({"type": "state_sync_verifier", **report})
            return report

        task_status = getattr(task, "status", None)
        task_status_value = str(task_status or "").split(".")[-1].lower()
        report["task_title"] = str(getattr(task, "title", "") or "").strip()
        report["task_status"] = task_status_value
        if task_status_value != TaskStatus.COMPLETED.value:
            report["reason"] = "task_not_completed"
            report["needs_followup"] = True
        else:
            report["ok"] = True

        repairs: List[str] = []
        if report["autonomy_work_item_id"]:
            item_status = ""
            item_eligible = False
            item_state = self._load_autonomy_work_jar()
            target_item = None
            for row in item_state.get("items") or []:
                if str((row or {}).get("id") or "").strip() == report["autonomy_work_item_id"]:
                    target_item = dict(row or {})
                    break
            if target_item is None:
                report["ok"] = False
                report["reason"] = "autonomy_work_item_missing"
                report["needs_followup"] = True
            else:
                item_status = str(target_item.get("status") or "").strip().lower()
                if item_status != "completed" and report["completion_contract_satisfied"] and task_status_value == TaskStatus.COMPLETED.value:
                    self._mark_autonomy_work_item_status(
                        report["autonomy_work_item_id"],
                        status="completed",
                        metadata_patch={
                            "completed_by_task_id": normalized_task_id,
                            "completion_reason": "state_sync_verifier_repair",
                        },
                    )
                    repairs.append("autonomy_work_item_completed")
                    report["repaired"] = True
                    item_state = self._load_autonomy_work_jar()
                    target_item = next(
                        (
                            dict(row or {})
                            for row in item_state.get("items") or []
                            if str((row or {}).get("id") or "").strip() == report["autonomy_work_item_id"]
                        ),
                        target_item,
                    )
                    item_status = str((target_item or {}).get("status") or "").strip().lower()
                next_eligible = _parse_iso_utc(str((target_item or {}).get("next_eligible_utc") or ""))
                item_eligible = item_status == "pending" and (next_eligible is None or next_eligible <= _utc_now())
                report["autonomy_work_item_status"] = item_status
                report["autonomy_work_item_still_actionable"] = bool(item_eligible)
                if report["completion_contract_satisfied"] and item_eligible:
                    report["ok"] = False
                    report["reason"] = "autonomy_work_item_still_actionable"
                    report["needs_followup"] = True

        if report["week1_stage"]:
            stage_state = self._load_week1_progress_state()
            stage_row = dict((stage_state.get("stages") or {}).get(report["week1_stage"]) or {})
            stage_done = bool(stage_row.get("done"))
            if not stage_done and report["completion_contract_satisfied"] and task_status_value == TaskStatus.COMPLETED.value:
                self._mark_week1_stage_completed(
                    report["week1_stage"],
                    task_id=normalized_task_id,
                    source="state_sync_verifier_repair",
                )
                repairs.append("week1_stage_completed")
                report["repaired"] = True
                stage_state = self._load_week1_progress_state()
                stage_row = dict((stage_state.get("stages") or {}).get(report["week1_stage"]) or {})
                stage_done = bool(stage_row.get("done"))
            report["week1_stage_done"] = stage_done
            report["week1_next_stage"] = self._week1_next_pending_stage(stage_state)
            if report["completion_contract_satisfied"] and not stage_done:
                report["ok"] = False
                report["reason"] = "week1_stage_not_completed"
                report["needs_followup"] = True
            elif report["completion_contract_satisfied"] and report["week1_next_stage"] == report["week1_stage"]:
                report["ok"] = False
                report["reason"] = "week1_stage_still_actionable"
                report["needs_followup"] = True

        if report["ok"] and not repairs and not str(report.get("reason") or "").strip():
            report["reason"] = "aligned"
        elif report["ok"] and repairs:
            report["reason"] = "repaired"
        note_written = False
        if report["ok"] and normalized_task_id:
            note_written = self._ensure_task_surface_verifier_note(
                normalized_task_id,
                outcome=str(report.get("reason") or "aligned"),
                autonomy_work_item_id=report["autonomy_work_item_id"],
                week1_stage=report["week1_stage"],
            )
        report["task_surface_note_written"] = bool(note_written)
        archived = False
        if report["ok"] and report["autonomy_work_item_id"] and report["completion_contract_satisfied"]:
            archived = self._archive_autonomy_work_jar_item(
                report["autonomy_work_item_id"],
                archive_reason="verified_complete",
            )
            if archived:
                repairs.append("autonomy_work_item_archived")
                report["repaired"] = True
        report["autonomy_work_item_archived"] = bool(archived)
        report["repairs"] = repairs

        state = self._load_state_sync_verifier_state()
        verified = dict(state.get("verified_tasks") or {})
        verified[normalized_task_id] = {
            "verified_at_utc": _utc_iso(),
            "last_trigger": report["trigger"],
            "autonomy_work_item_id": report["autonomy_work_item_id"],
            "week1_stage": report["week1_stage"],
            "completion_contract_satisfied": bool(report.get("completion_contract_satisfied")),
            "last_reason": str(report.get("reason") or ""),
            "last_ok": bool(report.get("ok")),
            "last_repaired": bool(report.get("repaired")),
        }
        state["verified_tasks"] = verified
        pending_ids = [
            str(item).strip()
            for item in (state.get("pending_followup_task_ids") or [])
            if str(item).strip() and str(item).strip() != normalized_task_id
        ]
        if report["needs_followup"]:
            pending_ids.append(normalized_task_id)
        state["pending_followup_task_ids"] = pending_ids
        monitor_candidates = dict(state.get("monitor_candidates") or {})
        if report["needs_followup"]:
            existing_candidate = dict(monitor_candidates.get(normalized_task_id) or {})
            first_seen_utc = str(existing_candidate.get("first_seen_utc") or _utc_iso())
            consecutive_cycle_scans = int(existing_candidate.get("consecutive_cycle_scans") or 0)
            if report["trigger"] == "cycle_scan":
                consecutive_cycle_scans += 1
            else:
                consecutive_cycle_scans = 0
            surfaced = consecutive_cycle_scans >= self._task_state_sync_monitor_confirmation_cycles()
            monitor_candidates[normalized_task_id] = {
                "first_seen_utc": first_seen_utc,
                "last_seen_utc": _utc_iso(),
                "consecutive_cycle_scans": consecutive_cycle_scans,
                "last_reason": str(report.get("reason") or ""),
                "autonomy_work_item_id": report["autonomy_work_item_id"],
                "week1_stage": report["week1_stage"],
                "task_title": str(report.get("task_title") or ""),
                "surfaced": surfaced,
            }
            report["monitor_candidate_cycle_scans"] = consecutive_cycle_scans
            report["monitor_candidate_surfaced"] = surfaced
        else:
            monitor_candidates.pop(normalized_task_id, None)
            report["monitor_candidate_cycle_scans"] = 0
            report["monitor_candidate_surfaced"] = False
        state["monitor_candidates"] = monitor_candidates
        self._save_state_sync_verifier_state(state)
        self._append_state_sync_verifier_event({"type": "state_sync_verifier", **report})
        return report

    def _run_periodic_state_sync_verifier(self, *, limit: int = 3) -> Dict[str, Any]:
        archive_summary = self._archive_verified_completed_autonomy_work_items(limit=max(3, int(limit or 0)))
        state = self._load_state_sync_verifier_state()
        pending_ids = [
            str(item).strip()
            for item in (state.get("pending_followup_task_ids") or [])
            if str(item).strip()
        ]
        attempted_ids = pending_ids[: max(0, int(limit or 0))]
        if not attempted_ids:
            state["last_cycle_scan_utc"] = _utc_iso()
            self._save_state_sync_verifier_state(state)
            surfaced_candidates = sum(
                1
                for row in (state.get("monitor_candidates") or {}).values()
                if isinstance(row, dict) and bool(row.get("surfaced"))
            )
            return {
                "attempted": 0,
                "verified": 0,
                "archived_items": int(archive_summary.get("archived") or 0),
                "remaining_followups": 0,
                "surfaced_monitor_candidates": surfaced_candidates,
                "reason": "no_pending_followups",
            }
        verified_context = dict(state.get("verified_tasks") or {})
        reports: List[Dict[str, Any]] = []
        for task_id in attempted_ids:
            row = dict(verified_context.get(task_id) or {})
            reports.append(
                self._run_post_completion_state_sync_verifier(
                    task_id=task_id,
                    trigger="cycle_scan",
                    autonomy_work_item_id=str(row.get("autonomy_work_item_id") or ""),
                    week1_stage=str(row.get("week1_stage") or ""),
                    completion_evaluation={
                        "satisfied": bool(row.get("completion_contract_satisfied"))
                    },
                )
            )
        refreshed_state = self._load_state_sync_verifier_state()
        refreshed_state["last_cycle_scan_utc"] = _utc_iso()
        self._save_state_sync_verifier_state(refreshed_state)
        surfaced_candidates = sum(
            1
            for row in (refreshed_state.get("monitor_candidates") or {}).values()
            if isinstance(row, dict) and bool(row.get("surfaced"))
        )
        return {
            "attempted": len(attempted_ids),
            "verified": sum(1 for row in reports if bool((row or {}).get("ok"))),
            "archived_items": int(archive_summary.get("archived") or 0),
            "remaining_followups": len(refreshed_state.get("pending_followup_task_ids") or []),
            "surfaced_monitor_candidates": surfaced_candidates,
            "reason": "processed",
        }

    def _task_state_sync_monitor_confirmation_cycles(self) -> int:
        config = getattr(self, "_autonomy_config", {}) or {}
        try:
            return max(1, int(config.get("task_state_sync_monitor_confirmation_cycles", 3) or 3))
        except Exception:
            return 3

    def _build_autonomy_work_completion_contract(self, item: Dict[str, Any]) -> Dict[str, Any]:
        contract = dict((item or {}).get("completion_contract") or {})
        if not isinstance(contract, dict):
            contract = {}
        contract.setdefault("kind", "task_completed")
        contract.setdefault("match_mode", "any")
        contract.setdefault("required_markers", [])
        contract.setdefault("title", str((item or {}).get("title") or ""))
        return contract

    def _evaluate_autonomy_work_completion_contract(
        self,
        contract: Dict[str, Any],
        workflow_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        evaluation: Dict[str, Any] = {
            "kind": str(contract.get("kind") or "task_completed"),
            "satisfied": False,
            "task_id": str(workflow_result.get("task_id") or ""),
            "decision": "hold_item",
        }
        if not bool(workflow_result.get("ok")):
            evaluation["reason"] = str(workflow_result.get("reason") or workflow_result.get("status") or "workflow_not_ok")
            return evaluation
        if str(workflow_result.get("status") or "").strip().lower() == "blocked":
            evaluation["reason"] = "workflow_blocked"
            return evaluation

        task_id = str(workflow_result.get("task_id") or "").strip()
        if not task_id:
            evaluation["reason"] = "missing_task_id"
            return evaluation
        master_list = getattr(self, "master_list", None)
        if master_list is None or not hasattr(master_list, "get_by_id"):
            evaluation["reason"] = "master_list_unavailable"
            return evaluation
        try:
            task = master_list.get_by_id(task_id)
        except Exception:
            task = None
        if task is None:
            evaluation["reason"] = "task_not_found"
            return evaluation

        status_value = str(getattr(task, "status", "") or "").split(".")[-1].lower()
        evaluation["task_status"] = status_value
        if status_value != TaskStatus.COMPLETED.value:
            evaluation["reason"] = f"task_status:{status_value or 'unknown'}"
            return evaluation

        contract_kind = str(contract.get("kind") or "task_completed").strip().lower()
        if contract_kind == "task_completed":
            evaluation["satisfied"] = True
            evaluation["decision"] = "complete_item"
            evaluation["reason"] = "task_completed"
            return evaluation

        required_markers = [
            str(item).strip().lower()
            for item in (contract.get("required_markers") or [])
            if str(item).strip()
        ]
        task_text = "\n".join(
            str(value or "")
            for value in (
                getattr(task, "title", ""),
                getattr(task, "description", ""),
                getattr(task, "notes", ""),
            )
        ).lower()
        present = [marker for marker in required_markers if marker in task_text]
        missing = [marker for marker in required_markers if marker not in task_text]
        match_mode = str(contract.get("match_mode") or "any").strip().lower()
        if match_mode == "all":
            satisfied = not missing
        else:
            satisfied = bool(present) if required_markers else True
        evaluation["required_markers"] = required_markers
        evaluation["present_markers"] = present
        evaluation["missing_markers"] = missing
        evaluation["match_mode"] = match_mode
        evaluation["satisfied"] = satisfied
        evaluation["decision"] = "complete_item" if satisfied else "hold_item"
        evaluation["reason"] = "markers_satisfied" if satisfied else "missing_required_markers"
        return evaluation

    def _recent_week1_progress_text(self, limit: int = 8) -> str:
        master_list = getattr(self, "master_list", None)
        if master_list is None or not hasattr(master_list, "parse"):
            return ""
        try:
            tasks = list(master_list.parse() or [])
        except Exception:
            return ""
        if not tasks:
            return ""
        rows: List[str] = []
        for task in sorted(tasks, key=lambda item: getattr(item, "updated", datetime.min), reverse=True)[:limit]:
            for value in (
                getattr(task, "title", ""),
                getattr(task, "notes", ""),
                getattr(task, "description", ""),
            ):
                text = str(value or "").strip()
                if text:
                    rows.append(text[:1200])
        return "\n".join(rows)

    @staticmethod
    def _week1_stage_order() -> List[str]:
        return [
            "fan_shortlist",
            "contractor_brief",
            "pressure_wash_plan",
            "contractor_outreach",
            "procurement_packet",
        ]

    def _default_week1_progress_state(self) -> Dict[str, Any]:
        stages = {
            stage: {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""}
            for stage in self._week1_stage_order()
        }
        return {
            "version": 1,
            "stages": stages,
            "updated_at_utc": _utc_iso(),
        }

    def _get_week1_progress_state_path(self) -> Path:
        path = self._local_attr(self, "_week1_progress_state_path", None)
        if isinstance(path, Path):
            return path
        memory_dir = self._local_attr(self, "_memory_dir", None) or self._safe_memory_dir()
        if not isinstance(memory_dir, Path):
            memory_dir = Path(memory_dir)
        path = memory_dir / "week1_autonomy_progress.json"
        self._week1_progress_state_path = path
        return path

    def _load_week1_progress_state(self) -> Dict[str, Any]:
        payload = safe_json_read(self._get_week1_progress_state_path(), default={}) or {}
        default = self._default_week1_progress_state()
        if not isinstance(payload, dict):
            return default
        stages = payload.get("stages")
        if not isinstance(stages, dict):
            payload["stages"] = default["stages"]
            return payload
        for stage in self._week1_stage_order():
            current = stages.get(stage)
            if not isinstance(current, dict):
                stages[stage] = dict(default["stages"][stage])
                continue
            stages[stage] = {
                "done": bool(current.get("done")),
                "updated_at_utc": str(current.get("updated_at_utc") or ""),
                "source_task_id": str(current.get("source_task_id") or ""),
                "source": str(current.get("source") or ""),
            }
        payload["version"] = int(payload.get("version") or 1)
        payload["updated_at_utc"] = str(payload.get("updated_at_utc") or "")
        return payload

    def _save_week1_progress_state(self, state: Dict[str, Any]) -> None:
        if not isinstance(state, dict):
            state = self._default_week1_progress_state()
        state["updated_at_utc"] = _utc_iso()
        state_path = self._get_week1_progress_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(state_path, state)

    def _mark_week1_stage_completed(
        self,
        stage: str,
        *,
        task_id: str = "",
        source: str = "autonomy_fallback",
    ) -> None:
        if stage not in self._week1_stage_order():
            return
        state = self._load_week1_progress_state()
        stage_row = dict((state.get("stages") or {}).get(stage) or {})
        stage_row["done"] = True
        stage_row["updated_at_utc"] = _utc_iso()
        stage_row["source_task_id"] = str(task_id or "")
        stage_row["source"] = str(source or "autonomy_fallback")
        state.setdefault("stages", {})[stage] = stage_row
        self._save_week1_progress_state(state)

    @staticmethod
    def _classify_week1_surface_title(title: str) -> str:
        lowered = str(title or "").strip().lower()
        if any(token in lowered for token in ("fan", "light fixture", "light fixtures", "lighting")):
            return "fan_lighting"
        if any(token in lowered for token in ("contractor", "remodel")):
            return "contractor_scope"
        if "pressure wash" in lowered or "pressure-wash" in lowered:
            return "pressure_wash"
        return "generic"

    @staticmethod
    def _week1_domain_progress_markers(domain: str) -> List[str]:
        if domain == "fan_lighting":
            return [
                "concrete shortlist",
                "shortlist for ceiling fan",
                "candidate replacements",
                "recommended first pick",
                "energy star",
                "dc motor",
                "bldc",
                "whisperwind",
                "surespeed",
                "hunter fan",
                "smafan",
                "artika",
                "dimmable led",
            ]
        if domain == "contractor_scope":
            return [
                "contractor call brief",
                "questions for contractor",
                "scope checklist",
                "remodel call prep",
                "contractor coordination brief",
                "scope bullets",
                "dependencies:",
            ]
        if domain == "pressure_wash":
            return [
                "pressure wash plan",
                "order of operations",
                "surface sequence",
                "safety checklist",
                "cleanup checklist",
                "supplies list",
            ]
        return []

    @staticmethod
    def _week1_stage_progress_markers(stage: str) -> List[str]:
        if stage == "contractor_outreach":
            return [
                "outreach draft",
                "email draft",
                "text draft",
                "voicemail draft",
                "contractor outreach",
                "call agenda",
            ]
        if stage == "procurement_packet":
            return [
                "procurement packet",
                "shopping checklist",
                "buy list",
                "purchase checklist",
                "quote request packet",
                "buy-list table",
                "missing-information checklist",
            ]
        return []

    def _week1_stage_markers(self, stage: str) -> List[str]:
        if stage == "fan_shortlist":
            return self._week1_domain_progress_markers("fan_lighting")
        if stage == "contractor_brief":
            return self._week1_domain_progress_markers("contractor_scope")
        if stage == "pressure_wash_plan":
            return self._week1_domain_progress_markers("pressure_wash")
        return self._week1_stage_progress_markers(stage)

    def _week1_next_pending_stage(self, state: Dict[str, Any]) -> str:
        stages = (state.get("stages") or {}) if isinstance(state, dict) else {}
        for stage in self._week1_stage_order():
            row = stages.get(stage)
            if not isinstance(row, dict) or not bool(row.get("done")):
                return stage
        return ""

    def _week1_completed_stages(self, state: Dict[str, Any]) -> List[str]:
        stages = (state.get("stages") or {}) if isinstance(state, dict) else {}
        completed: List[str] = []
        for stage in self._week1_stage_order():
            row = stages.get(stage)
            if isinstance(row, dict) and bool(row.get("done")):
                completed.append(stage)
        return completed

    @staticmethod
    def _week1_task_stage_match_allowed(stage: str, task: Any, combined: str) -> bool:
        if stage != "procurement_packet":
            return True
        title = str(getattr(task, "title", "") or "").strip().lower()
        notes = str(getattr(task, "notes", "") or "").strip().lower()
        description = str(getattr(task, "description", "") or "").strip().lower()
        tags = {str(item).strip().lower() for item in (getattr(task, "tags", []) or []) if str(item).strip()}
        text = "\n".join(part for part in (title, notes, description, combined) if part)
        negative_markers = (
            "procurement prerequisite",
            "inventory template",
            "room-by-room fan/light inventory",
            "room-by-room inventory",
            "missing-spec checklist",
            "unblock the procurement packet",
            "unblock task-017",
        )
        if "week1_procurement_prerequisite" in tags:
            return False
        return not any(marker in text for marker in negative_markers)

    def _reconcile_week1_progress_state_from_tasks(self) -> Dict[str, Any]:
        state = self._load_week1_progress_state()
        master_list = getattr(self, "master_list", None)
        if master_list is None or not hasattr(master_list, "parse"):
            return state
        try:
            tasks = list(master_list.parse() or [])
        except Exception:
            return state
        for task in tasks:
            if getattr(task, "status", None) != TaskStatus.COMPLETED:
                continue
            text_parts = []
            for value in (
                getattr(task, "title", ""),
                getattr(task, "notes", ""),
                getattr(task, "description", ""),
            ):
                piece = str(value or "").strip()
                if piece:
                    text_parts.append(piece.lower())
            combined = "\n".join(text_parts)
            if not combined:
                continue
            task_id = str(getattr(task, "id", "") or "")
            for stage in self._week1_stage_order():
                stage_row = dict((state.get("stages") or {}).get(stage) or {})
                if bool(stage_row.get("done")):
                    continue
                markers = self._week1_stage_markers(stage)
                if any(marker in combined for marker in markers) and self._week1_task_stage_match_allowed(stage, task, combined):
                    stage_row["done"] = True
                    stage_row["updated_at_utc"] = _utc_iso()
                    stage_row["source_task_id"] = task_id
                    stage_row["source"] = "master_task_reconcile"
                    state.setdefault("stages", {})[stage] = stage_row
        self._save_week1_progress_state(state)
        return state

    def _select_autonomy_work_jar_item(self) -> Dict[str, Any]:
        eligible = self._eligible_autonomy_work_items(limit=1)
        if not eligible:
            return {}
        return dict(eligible[0])

    def _build_autonomy_work_jar_action(self, item: Dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return ""
        title = str(item.get("title") or "").strip()
        objective = str(item.get("objective") or "").strip()
        context = str(item.get("context") or "").strip()
        lines = [
            "Advance the highest-priority queued autonomy work item.",
        ]
        if title:
            lines.append(f"Work item: {title}")
        if objective:
            lines.append(f"Objective: {objective}")
        if context:
            lines.append("Context:")
            lines.append(context[:5000])
        lines.append(
            "Use existing local context first. Produce the smallest concrete artifact or task update that materially advances the objective."
        )
        return "\n".join(lines).strip()

    def _select_task_state_sync_monitor_candidate(self, surface: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(surface, dict):
            return {}
        candidate_ids = [
            str(item).strip()
            for item in (surface.get("task_state_sync_monitor_task_ids") or [])
            if str(item).strip()
        ]
        if not candidate_ids:
            return {}
        state = self._load_state_sync_verifier_state()
        candidates = dict(state.get("monitor_candidates") or {})
        ranked: List[Dict[str, Any]] = []
        for task_id in candidate_ids:
            row = dict(candidates.get(task_id) or {})
            if not row or not bool(row.get("surfaced")):
                continue
            ranked.append(
                {
                    "task_id": task_id,
                    "task_title": str(row.get("task_title") or "").strip(),
                    "consecutive_cycle_scans": int(row.get("consecutive_cycle_scans") or 0),
                    "last_reason": str(row.get("last_reason") or "").strip(),
                    "autonomy_work_item_id": str(row.get("autonomy_work_item_id") or "").strip(),
                    "week1_stage": str(row.get("week1_stage") or "").strip(),
                }
            )
        ranked.sort(
            key=lambda row: (
                -int(row.get("consecutive_cycle_scans") or 0),
                str(row.get("task_id") or ""),
            )
        )
        return ranked[0] if ranked else {}

    def _resolve_task_state_sync_monitor_context(self, candidate: Dict[str, Any]) -> Dict[str, str]:
        task_id = str((candidate or {}).get("task_id") or "").strip()
        if not task_id:
            return {}
        master_list = getattr(self, "master_list", None)
        if master_list is None or not hasattr(master_list, "get_by_id"):
            return {
                "task_id": task_id,
                "title": str((candidate or {}).get("task_title") or "").strip(),
                "context": "",
            }
        try:
            task = master_list.get_by_id(task_id)
        except Exception:
            task = None
        title = str((candidate or {}).get("task_title") or "").strip()
        if task is None:
            return {
                "task_id": task_id,
                "title": title,
                "context": "",
            }
        title = str(getattr(task, "title", "") or title).strip()
        description = str(getattr(task, "description", "") or "").strip()
        notes = str(getattr(task, "notes", "") or "").strip()
        context_lines = [
            f"Original completed task ID: {task_id}",
            f"Title: {title}",
        ]
        if description:
            context_lines.append("Description:")
            context_lines.append(description[:5000])
        if notes:
            context_lines.append("Notes:")
            context_lines.append(notes[:4000])
        return {
            "task_id": task_id,
            "title": title,
            "context": "\n".join(context_lines).strip(),
        }

    def _build_task_state_sync_monitor_action(self, candidate: Dict[str, Any], context: Dict[str, str]) -> str:
        task_id = str((candidate or {}).get("task_id") or (context or {}).get("task_id") or "").strip()
        title = str((context or {}).get("title") or (candidate or {}).get("task_title") or "").strip()
        if not task_id:
            return ""
        last_reason = str((candidate or {}).get("last_reason") or "").strip()
        cycle_scans = int((candidate or {}).get("consecutive_cycle_scans") or 0)
        lines = [
            "Resolve a recurring post-completion state-sync mismatch after repeated verifier confirmation.",
            f"Original task ID: {task_id}",
        ]
        if title:
            lines.append(f"Original task title: {title}")
        if last_reason:
            lines.append(f"Current mismatch reason: {last_reason}")
        lines.append(f"Confirmation streak: {cycle_scans} cycle scans")
        lines.append(
            "Use the existing task surface and local state first. Repair the mismatch directly if safe, or produce the smallest concrete follow-up artifact that explains the mismatch and the exact repair needed."
        )
        return "\n".join(lines).strip()

    def _select_week1_validation_monitor_candidate(self, surface: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(surface, dict):
            return {}
        titles = [
            str(item).strip()
            for item in (surface.get("week1_validation_monitor_titles") or [])
            if str(item).strip()
        ]
        if not titles:
            return {}
        state = self._load_week1_validation_monitor_state()
        candidate = dict(state.get("candidate") or {})
        if not candidate or not bool(candidate.get("surfaced")):
            return {}
        candidate.setdefault("title", titles[0])
        return candidate

    def _resolve_week1_validation_monitor_context(self, candidate: Dict[str, Any]) -> Dict[str, str]:
        signal = self._collect_recent_week1_validation_signal()
        last_snapshot_utc = str(self._load_week1_validation_monitor_state().get("last_snapshot_utc") or "")
        memory_dir = self._local_attr(self, "_memory_dir", None) or self._safe_memory_dir()
        if not isinstance(memory_dir, Path):
            memory_dir = Path(memory_dir)
        event_path = memory_dir / "week1_executor_events.jsonl"
        metrics_path = Path("ops/week1/WEEK1_VALIDATION_METRICS.md")
        checklist_path = Path("ops/week1/DAY1_OPERATOR_CHECKLIST.txt")
        lines = [
            "Week1 validation metrics source: ops/week1/WEEK1_VALIDATION_METRICS.md",
            "Suggested operator checklist: ops/week1/DAY1_OPERATOR_CHECKLIST.txt",
            "Recent Week1 signal summary:",
            f"- recent executor events: {int(signal.get('recent_event_count') or 0)}",
            f"- recent ok events: {int(signal.get('recent_ok_count') or 0)}",
            f"- recent deferred events: {int(signal.get('recent_deferred_count') or 0)}",
            f"- recent failed events: {int(signal.get('recent_failed_count') or 0)}",
            f"- latest event utc: {str(signal.get('latest_event_utc') or '')}",
            f"- recent ack rows: {int(signal.get('recent_ack_count') or 0)}",
            f"- latest ack utc: {str(signal.get('latest_ack_utc') or '')}",
            f"- last validation snapshot utc: {last_snapshot_utc}",
        ]
        reason = str((candidate or {}).get("reason") or "").strip()
        if reason:
            lines.append(f"- validation monitor reason: {reason}")
        metrics_text = ""
        checklist_text = ""
        event_rows: List[Dict[str, Any]] = []
        if metrics_path.exists():
            try:
                metrics_text = metrics_path.read_text(encoding="utf-8").strip()
            except Exception:
                metrics_text = ""
        if checklist_path.exists():
            try:
                checklist_text = checklist_path.read_text(encoding="utf-8").strip()
            except Exception:
                checklist_text = ""
        if event_path.exists():
            try:
                for line in event_path.read_text(encoding="utf-8").splitlines()[-12:]:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    if isinstance(row, dict):
                        event_rows.append(row)
            except Exception:
                event_rows = []
        if metrics_text:
            lines.extend(
                [
                    "",
                    "Week1 validation metrics excerpt:",
                    metrics_text[:2400],
                ]
            )
        if checklist_text:
            lines.extend(
                [
                    "",
                    "Day 1 operator checklist excerpt:",
                    checklist_text[:2400],
                ]
            )
        if event_rows:
            lines.append("")
            lines.append("Recent Week1 executor event sample:")
            for row in event_rows[-8:]:
                lines.append(
                    "- "
                    + json.dumps(
                        {
                            "ts_utc": str(row.get("ts_utc") or ""),
                            "event_id": str(row.get("event_id") or ""),
                            "status": str(row.get("status") or ""),
                            "delivery_channel": str(row.get("delivery_channel") or ""),
                            "detail": str(row.get("detail") or "")[:220],
                        },
                        ensure_ascii=True,
                    )
                )
        return {
            "context": "\n".join(lines).strip(),
            "title": str((candidate or {}).get("title") or "").strip(),
            "reason": reason,
        }

    def _build_week1_validation_monitor_action(self, candidate: Dict[str, Any], context: Dict[str, str]) -> str:
        title = str((candidate or {}).get("title") or (context or {}).get("title") or "").strip()
        reason = str((candidate or {}).get("reason") or (context or {}).get("reason") or "").strip()
        lines = [
            "Produce a concise Week1 validation snapshot from recent runtime evidence.",
            "Use local evidence first: recent Week1 executor events, push ACK activity, and the shipped validation metrics/checklist docs.",
            "Output a concrete artifact that includes: signal summary, likely weak spots, noise/risk notes, and the top 3 Week2 tuning recommendations.",
        ]
        if title:
            lines.append(f"Validation target: {title}")
        if reason:
            lines.append(f"Why now: {reason}")
        lines.append(
            "Keep it bounded. Do not invent new data sources. If evidence is insufficient, say exactly what is missing."
        )
        return "\n".join(lines).strip()

    def _select_week1_surface_fallback(self, surface: Dict[str, Any]) -> Dict[str, str]:
        if not isinstance(surface, dict):
            return {}
        titles = [
            str(item).strip()
            for item in (surface.get("week1_task_titles") or [])
            if str(item).strip()
        ]
        pending_titles = [
            str(item).strip()
            for item in (surface.get("pending_task_titles") or [])
            if str(item).strip()
        ]
        procurement_prereq_pending = bool(surface.get("week1_procurement_prerequisite_pending"))
        if not titles:
            return {}
        state = self._reconcile_week1_progress_state_from_tasks()
        stages = (state.get("stages") or {}) if isinstance(state, dict) else {}
        next_stage = self._week1_next_pending_stage(state)
        if not next_stage:
            return {}
        by_domain: Dict[str, str] = {}
        for title in titles:
            by_domain.setdefault(self._classify_week1_surface_title(title), title)
        bullet_block = "\n".join(f"- {title}" for title in titles[:3])

        def _stage_done(stage: str) -> bool:
            row = stages.get(stage)
            return bool(isinstance(row, dict) and row.get("done"))

        def _plan(stage: str, title: str, action_text: str) -> Dict[str, str]:
            return {
                "stage": stage,
                "primary_target": title,
                "action_text": action_text,
                "bullet_block": bullet_block,
            }

        if procurement_prereq_pending and pending_titles:
            for title in pending_titles:
                lowered = title.lower()
                if "inventory" in lowered or "missing-spec" in lowered or "procurement packet" in lowered:
                    return _plan(
                        "procurement_prerequisite",
                        title,
                        (
                            "Advance the Week1 procurement prerequisite before retrying the procurement packet. "
                            "Use existing task/memory context first, then at most one safe read-only lookup if needed. "
                            "Produce a room-by-room fan/light inventory template, fixture-count assumptions, and a missing-spec checklist that will unblock the procurement packet.\n"
                            f"Primary target: {title}\n"
                            "Blocked downstream stage: procurement_packet\n"
                            f"Current Week1 surface:\n{bullet_block}"
                        ),
                    )

        if "fan_lighting" in by_domain and not _stage_done("fan_shortlist"):
            title = by_domain["fan_lighting"]
            return _plan(
                "fan_shortlist",
                title,
                (
                    "Advance the Week1 fan/light shortlist instead of re-inspecting the same surface. "
                    "Use existing task/memory context first, then at most one safe read-only lookup if needed. "
                    "Produce a concrete shortlist of 3 candidate replacements with tradeoffs and a recommended first pick.\n"
                    f"Primary target: {title}\n"
                    f"Current Week1 surface:\n{bullet_block}"
                ),
            )
        if "contractor_scope" in by_domain and not _stage_done("contractor_brief"):
            title = by_domain["contractor_scope"]
            return _plan(
                "contractor_brief",
                title,
                (
                    "Prepare the remodel contractor call brief as the next concrete Week1 step. "
                    "Use existing task/memory context first, then at most one safe read-only lookup if needed. "
                    "Draft scope bullets, 5-7 questions, dependencies, and a recommended next-step checklist.\n"
                    f"Primary target: {title}\n"
                    f"Current Week1 surface:\n{bullet_block}"
                ),
            )
        if "pressure_wash" in by_domain and not _stage_done("pressure_wash_plan"):
            title = by_domain["pressure_wash"]
            return _plan(
                "pressure_wash_plan",
                title,
                (
                    "Turn the Week1 pressure-wash item into a concrete work plan. "
                    "Use existing task/memory context first, then at most one safe read-only lookup if needed. "
                    "Produce an order-of-operations plan, supplies list, and safety/cleanup checklist.\n"
                    f"Primary target: {title}\n"
                    f"Current Week1 surface:\n{bullet_block}"
                ),
            )
        if "contractor_scope" in by_domain and not _stage_done("contractor_outreach"):
            title = by_domain["contractor_scope"]
            return _plan(
                "contractor_outreach",
                title,
                (
                    "Turn the existing Week1 contractor brief into an outreach-ready package. "
                    "Use existing task/memory context first, then at most one safe read-only lookup if needed. "
                    "Draft one concise outreach message, one call agenda, and a send-ready checklist with missing fields clearly marked.\n"
                    f"Primary target: {title}\n"
                    f"Current Week1 surface:\n{bullet_block}"
                ),
            )
        if "fan_lighting" in by_domain and not _stage_done("procurement_packet"):
            title = by_domain["fan_lighting"]
            return _plan(
                "procurement_packet",
                title,
                (
                    "Turn the existing Week1 fan/light shortlist into a procurement-ready packet. "
                    "Use existing task/memory context first, then at most one safe read-only lookup if needed. "
                    "Produce a buy-list table, room/fixture assumptions, and a missing-information checklist needed before purchase.\n"
                    f"Primary target: {title}\n"
                    f"Current Week1 surface:\n{bullet_block}"
                ),
            )
        return {}

    def _build_week1_surface_fallback_action(self, surface: Dict[str, Any]) -> str:
        plan = self._select_week1_surface_fallback(surface)
        return str(plan.get("action_text") or "")

    def _select_week1_ops_backlog_candidate(self, surface: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(surface, dict):
            return {}
        titles = [
            str(item).strip()
            for item in (surface.get("week1_task_titles") or [])
            if str(item).strip()
        ]
        if not titles:
            return {}
        schedule_items = self._load_week1_structured_schedule_items()
        by_title = {
            str(row.get("parent_title") or "").strip(): row
            for row in schedule_items
            if isinstance(row, dict) and str(row.get("parent_title") or "").strip()
        }
        state = self._load_week1_ops_backlog_state()
        item_state = state.get("items") if isinstance(state.get("items"), dict) else {}
        now = _utc_now()
        fallback: Dict[str, Any] = {}
        for title in titles:
            row = by_title.get(title)
            if not isinstance(row, dict):
                row = {"parent_title": title}
            meta = dict(item_state.get(title) or {})
            next_eligible = _parse_iso_utc(str(meta.get("next_eligible_utc") or ""))
            resume_after = _parse_iso_utc(str(meta.get("resume_after_utc") or ""))
            awaiting_followthrough = bool(meta.get("awaiting_human_followthrough"))
            candidate = {
                "title": title,
                "schedule_row": row,
                "state_meta": meta,
            }
            if awaiting_followthrough and resume_after is not None and resume_after > now:
                continue
            if next_eligible is None or next_eligible <= now:
                return candidate
        return fallback

    def _resolve_week1_ops_backlog_context(self, candidate: Dict[str, Any], surface: Dict[str, Any]) -> Dict[str, str]:
        row = dict(candidate.get("schedule_row") or {})
        meta = dict(candidate.get("state_meta") or {})
        titles = [
            str(item).strip()
            for item in (surface.get("week1_task_titles") or [])
            if str(item).strip()
        ]
        lines = [
            "Week1 ops backlog context from the structured Week1 schedule.",
            f"Primary target: {str(candidate.get('title') or '')}",
            f"- scheduled_local: {str(row.get('scheduled_local') or '')}",
            f"- focus_slot: {str(row.get('focus_slot') or '')}",
            f"- priority: {str(row.get('priority') or '')}",
            f"- category: {str(row.get('category') or '')}",
            f"- start_step: {str(row.get('start_step') or '')}",
            f"- notes: {str(row.get('notes') or '')}",
        ]
        if meta:
            lines.extend(
                [
                    f"- last_status: {str(meta.get('last_status') or '')}",
                    f"- last_reason: {str(meta.get('last_reason') or '')}",
                    f"- last_task_id: {str(meta.get('last_task_id') or '')}",
                    f"- next_eligible_utc: {str(meta.get('next_eligible_utc') or '')}",
                    f"- awaiting_human_followthrough: {str(bool(meta.get('awaiting_human_followthrough'))).lower()}",
                    f"- resume_after_utc: {str(meta.get('resume_after_utc') or '')}",
                ]
            )
        if titles:
            lines.append("Current Week1 ops focus:")
            lines.extend(f"- {title}" for title in titles[:3])
        return {
            "context": "\n".join(lines).strip(),
            "title": str(candidate.get("title") or "").strip(),
        }

    def _build_week1_ops_backlog_action(self, candidate: Dict[str, Any], surface: Dict[str, Any]) -> str:
        if not isinstance(candidate, dict):
            return ""
        title = str(candidate.get("title") or "").strip()
        if not title:
            return ""
        titles = [
            str(item).strip()
            for item in (surface.get("week1_task_titles") or [])
            if str(item).strip()
        ]
        bullet_block = "\n".join(f"- {item}" for item in titles[:3])
        return (
            "Advance the current Week1 operating backlog focus without reopening the completed Week1 stage chain. "
            "Use the structured Week1 schedule entry, start step, and existing task surface first. "
            "Produce a bounded artifact or direct next-step plan for the selected Week1 ops item. "
            "If the item requires external contact, provide a concrete prep packet instead of just restating that contact is needed.\n"
            f"Selected Week1 ops target: {title}\n"
            f"Current Week1 ops focus:\n{bullet_block}"
        )

    async def _execute_autonomy_work_jar_fallback_workflow(
        self,
        *,
        run_id: str,
    ) -> Dict[str, Any]:
        item = self._select_autonomy_work_jar_item()
        if not item:
            return {"ok": False, "reason": "autonomy_work_jar_empty"}
        item_id = str(item.get("id") or "").strip()
        action_text = self._build_autonomy_work_jar_action(item)
        if not action_text:
            return {"ok": False, "reason": "autonomy_work_jar_invalid_item"}
        workflow_result = await self._execute_inner_action_workflow(
            action_text=action_text,
            run_id=run_id,
            additional_context=str(item.get("context") or ""),
            tool_choice=self._normalize_autonomy_work_tool_choice(item.get("tool_choice")),
        )
        if not isinstance(workflow_result, dict):
            workflow_result = {"ok": False, "reason": "invalid_workflow_result"}
        contract = self._build_autonomy_work_completion_contract(item)
        evaluation = self._evaluate_autonomy_work_completion_contract(contract, workflow_result)
        workflow_result["fallback_reason"] = "autonomy_work_jar"
        workflow_result["autonomy_work_item_id"] = item_id
        workflow_result["autonomy_work_item_title"] = str(item.get("title") or "")
        workflow_result["completion_contract"] = contract
        workflow_result["completion_evaluation"] = evaluation
        workflow_result["stage_advanced"] = bool(evaluation.get("satisfied"))
        if bool(evaluation.get("satisfied")):
            self._mark_autonomy_work_item_status(
                item_id,
                status="completed",
                metadata_patch={
                    "completed_by_task_id": str(workflow_result.get("task_id") or ""),
                    "completion_reason": str(evaluation.get("reason") or ""),
                },
            )
        else:
            retry_count = int(item.get("retry_count") or 0) + 1
            next_eligible = _utc_iso(_utc_now() + timedelta(minutes=30))
            metadata_patch = {
                "last_reason": str(evaluation.get("reason") or workflow_result.get("reason") or ""),
                "last_task_id": str(workflow_result.get("task_id") or ""),
            }
            if str(workflow_result.get("status") or "").strip().lower() == "blocked":
                metadata_patch["blocked"] = True
            self._mark_autonomy_work_item_status(
                item_id,
                status="pending",
                retry_count=retry_count,
                next_eligible_utc=next_eligible,
                metadata_patch=metadata_patch,
            )
        if str(workflow_result.get("status") or "").strip().lower() == "completed":
            workflow_result["state_sync_verifier"] = self._run_post_completion_state_sync_verifier(
                task_id=str(workflow_result.get("task_id") or ""),
                trigger="post_completion",
                autonomy_work_item_id=item_id,
                completion_evaluation=evaluation,
            )
        return workflow_result

    async def _execute_task_state_sync_monitor_fallback_workflow(
        self,
        actionable_surface: Dict[str, Any],
        *,
        run_id: str,
    ) -> Dict[str, Any]:
        candidate = self._select_task_state_sync_monitor_candidate(
            actionable_surface if isinstance(actionable_surface, dict) else {}
        )
        if not candidate:
            return {"ok": False, "reason": "task_state_sync_monitor_empty"}
        context = self._resolve_task_state_sync_monitor_context(candidate)
        action_text = self._build_task_state_sync_monitor_action(candidate, context)
        if not action_text:
            return {"ok": False, "reason": "task_state_sync_monitor_invalid_candidate"}
        workflow_result = await self._execute_inner_action_workflow(
            action_text=action_text,
            run_id=run_id,
            additional_context=str(context.get("context") or ""),
        )
        if not isinstance(workflow_result, dict):
            workflow_result = {"ok": False, "reason": "invalid_workflow_result"}
        workflow_result["fallback_reason"] = "task_state_sync_monitor"
        workflow_result["task_state_sync_monitor_task_id"] = str(candidate.get("task_id") or "")
        workflow_result["task_state_sync_monitor_reason"] = str(candidate.get("last_reason") or "")
        workflow_result["task_state_sync_monitor_cycle_scans"] = int(
            candidate.get("consecutive_cycle_scans") or 0
        )
        if str(workflow_result.get("status") or "").strip().lower() == "completed":
            workflow_result["state_sync_verifier"] = self._run_post_completion_state_sync_verifier(
                task_id=str(workflow_result.get("task_id") or ""),
                trigger="post_completion",
            )
        return workflow_result

    async def _execute_week1_validation_monitor_fallback_workflow(
        self,
        actionable_surface: Dict[str, Any],
        *,
        run_id: str,
    ) -> Dict[str, Any]:
        candidate = self._select_week1_validation_monitor_candidate(
            actionable_surface if isinstance(actionable_surface, dict) else {}
        )
        if not candidate:
            return {"ok": False, "reason": "week1_validation_monitor_empty"}
        context = self._resolve_week1_validation_monitor_context(candidate)
        action_text = self._build_week1_validation_monitor_action(candidate, context)
        if not action_text:
            return {"ok": False, "reason": "week1_validation_monitor_invalid_candidate"}
        workflow_result = await self._execute_inner_action_workflow(
            action_text=action_text,
            run_id=run_id,
            additional_context=str(context.get("context") or ""),
            tool_choice="none",
        )
        if not isinstance(workflow_result, dict):
            workflow_result = {"ok": False, "reason": "invalid_workflow_result"}
        workflow_result["fallback_reason"] = "week1_validation_monitor"
        workflow_result["week1_validation_monitor_reason"] = str(candidate.get("reason") or "")
        workflow_result["week1_validation_monitor_cycle_scans"] = int(
            candidate.get("consecutive_cycle_scans") or 0
        )
        if str(workflow_result.get("status") or "").strip().lower() == "completed":
            state = self._load_week1_validation_monitor_state()
            state["last_snapshot_task_id"] = str(workflow_result.get("task_id") or "")
            state["last_snapshot_utc"] = _utc_iso()
            state["last_snapshot_reason"] = str(candidate.get("reason") or "")
            state["candidate"] = {}
            self._save_week1_validation_monitor_state(state)
        return workflow_result

    def _resolve_week1_surface_task_context(self, surface: Dict[str, Any], stage: str) -> Dict[str, str]:
        if not isinstance(surface, dict):
            return {}
        master_list = getattr(self, "master_list", None)
        if master_list is None or not hasattr(master_list, "parse"):
            return {}
        pending_titles = {
            str(item).strip()
            for item in (surface.get("pending_task_titles") or [])
            if str(item).strip()
        }
        try:
            tasks = list(master_list.parse() or [])
        except Exception:
            return {}
        candidates: List[Any] = []
        for task in tasks:
            status_value = str(getattr(task, "status", "") or "").split(".")[-1].lower()
            if status_value not in {
                TaskStatus.PENDING.value,
                TaskStatus.IN_PROGRESS.value,
                TaskStatus.BLOCKED.value,
            }:
                continue
            title = str(getattr(task, "title", "") or "").strip()
            if pending_titles and title not in pending_titles:
                continue
            candidates.append(task)
        if not candidates:
            return {}

        stage_name = str(stage or "").strip()
        stage_markers = {
            "procurement_packet": ("procurement-ready packet", "buy-list table"),
            "procurement_prerequisite": ("inventory template", "missing-spec checklist"),
            "contractor_outreach": ("outreach-ready", "call agenda"),
            "contractor_brief": ("contractor call brief", "scope bullets"),
            "pressure_wash_plan": ("pressure wash plan", "order-of-operations"),
            "fan_shortlist": ("shortlist", "candidate replacements"),
        }
        preferred_markers = stage_markers.get(stage_name, ())

        def _score(task: Any) -> tuple[int, int]:
            title = str(getattr(task, "title", "") or "").strip().lower()
            text = "\n".join(
                str(value or "")
                for value in (
                    getattr(task, "title", ""),
                    getattr(task, "description", ""),
                    getattr(task, "notes", ""),
                )
            ).lower()
            marker_hits = sum(1 for marker in preferred_markers if marker in text)
            exact_title = 1 if title in {item.lower() for item in pending_titles} else 0
            return (marker_hits, exact_title)

        candidates.sort(key=_score, reverse=True)
        task = candidates[0]
        title = str(getattr(task, "title", "") or "").strip()
        description = str(getattr(task, "description", "") or "").strip()
        notes = str(getattr(task, "notes", "") or "").strip()
        context_lines = [
            f"Task ID: {getattr(task, 'id', '')}",
            f"Title: {title}",
        ]
        if description:
            context_lines.append("Description:")
            context_lines.append(description[:5000])
        if notes:
            context_lines.append("Notes:")
            context_lines.append(notes[:4000])
        return {
            "task_id": str(getattr(task, "id", "") or ""),
            "title": title,
            "context": "\n".join(context_lines).strip(),
        }

    def _build_week1_completion_contract(
        self,
        stage: str,
        primary_target: str,
        actionable_surface: Dict[str, Any],
    ) -> Dict[str, Any]:
        stage_name = str(stage or "").strip()
        markers = list(self._week1_stage_markers(stage_name))
        contract: Dict[str, Any] = {
            "kind": "task_artifact_markers",
            "stage": stage_name,
            "primary_target": str(primary_target or ""),
            "required_markers": markers,
            "match_mode": "any",
            "surface_snapshot": {
                "week1_task_titles": list((actionable_surface or {}).get("week1_task_titles") or []),
                "pending_task_titles": list((actionable_surface or {}).get("pending_task_titles") or []),
            },
        }
        if stage_name == "procurement_prerequisite":
            contract["required_markers"] = [
                "room-by-room fan/light inventory",
                "missing-spec checklist",
            ]
            contract["match_mode"] = "all"
        elif stage_name == "procurement_packet":
            contract["required_markers"] = [
                "buy-list table",
                "missing-information checklist",
            ]
            contract["match_mode"] = "all"
        elif not markers:
            contract["kind"] = "task_completed"
        return contract

    def _evaluate_week1_completion_contract(
        self,
        contract: Dict[str, Any],
        workflow_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        evaluation: Dict[str, Any] = {
            "stage": str(contract.get("stage") or ""),
            "kind": str(contract.get("kind") or "task_completed"),
            "satisfied": False,
            "task_id": str(workflow_result.get("task_id") or ""),
            "decision": "hold_stage",
        }
        if not bool(workflow_result.get("ok")):
            evaluation["reason"] = str(workflow_result.get("reason") or workflow_result.get("status") or "workflow_not_ok")
            return evaluation
        if str(workflow_result.get("status") or "").strip().lower() == "blocked":
            evaluation["reason"] = "workflow_blocked"
            return evaluation

        task_id = str(workflow_result.get("task_id") or "").strip()
        if not task_id:
            evaluation["reason"] = "missing_task_id"
            return evaluation

        master_list = getattr(self, "master_list", None)
        if master_list is None or not hasattr(master_list, "get_by_id"):
            evaluation["reason"] = "master_list_unavailable"
            return evaluation
        try:
            task = master_list.get_by_id(task_id)
        except Exception:
            task = None
        if task is None:
            evaluation["reason"] = "task_not_found"
            return evaluation

        status_value = str(getattr(task, "status", "") or "").split(".")[-1].lower()
        evaluation["task_status"] = status_value
        if status_value != TaskStatus.COMPLETED.value:
            evaluation["reason"] = f"task_status:{status_value or 'unknown'}"
            return evaluation

        contract_kind = str(contract.get("kind") or "task_completed")
        if contract_kind == "task_completed":
            evaluation["satisfied"] = True
            evaluation["decision"] = "advance_stage"
            evaluation["reason"] = "task_completed"
            return evaluation

        required_markers = [
            str(item).strip().lower()
            for item in (contract.get("required_markers") or [])
            if str(item).strip()
        ]
        task_text = "\n".join(
            str(value or "")
            for value in (
                getattr(task, "title", ""),
                getattr(task, "description", ""),
                getattr(task, "notes", ""),
            )
        ).lower()
        present = [marker for marker in required_markers if marker in task_text]
        missing = [marker for marker in required_markers if marker not in task_text]
        match_mode = str(contract.get("match_mode") or "any").strip().lower()
        if match_mode == "all":
            satisfied = not missing
        else:
            satisfied = bool(present) if required_markers else True
        evaluation["required_markers"] = required_markers
        evaluation["present_markers"] = present
        evaluation["missing_markers"] = missing
        evaluation["match_mode"] = match_mode
        evaluation["satisfied"] = satisfied
        evaluation["decision"] = "advance_stage" if satisfied else "hold_stage"
        evaluation["reason"] = "markers_satisfied" if satisfied else "missing_required_markers"
        return evaluation

    async def _execute_week1_surface_fallback_workflow(
        self,
        actionable_surface: Dict[str, Any],
        *,
        run_id: str,
        fallback_reason_override: str = "week1_surface_default_action",
    ) -> Dict[str, Any]:
        autonomy_work_result = await self._execute_autonomy_work_jar_fallback_workflow(
            run_id=f"{run_id}:autonomy_work"
        )
        if str(autonomy_work_result.get("reason") or "") not in {"autonomy_work_jar_empty", "autonomy_work_jar_invalid_item"}:
            return autonomy_work_result
        fallback_plan = self._select_week1_surface_fallback(actionable_surface)
        fallback_action_text = str(fallback_plan.get("action_text") or "")
        if not fallback_action_text:
            return {"ok": False, "reason": "week1_surface_no_fallback_action"}
        stage_name = str(fallback_plan.get("stage") or "")
        surface_task_context = self._resolve_week1_surface_task_context(
            actionable_surface if isinstance(actionable_surface, dict) else {},
            stage_name,
        )
        workflow_result = await self._execute_inner_action_workflow(
            action_text=fallback_action_text,
            run_id=run_id,
            additional_context=str(surface_task_context.get("context") or ""),
            preferred_task_id=str(surface_task_context.get("task_id") or ""),
        )
        if isinstance(workflow_result, dict):
            primary_target = str(fallback_plan.get("primary_target") or "")
            completion_contract = self._build_week1_completion_contract(
                stage_name,
                primary_target,
                actionable_surface if isinstance(actionable_surface, dict) else {},
            )
            contract_evaluation = self._evaluate_week1_completion_contract(
                completion_contract,
                workflow_result,
            )
            workflow_result["fallback_reason"] = str(fallback_reason_override or "week1_surface_default_action")
            workflow_result["week1_stage"] = stage_name
            workflow_result["week1_primary_target"] = primary_target
            workflow_result["week1_surface_task_context"] = surface_task_context
            workflow_result["completion_contract"] = completion_contract
            workflow_result["completion_evaluation"] = contract_evaluation
            workflow_result["stage_advanced"] = bool(contract_evaluation.get("satisfied"))
            workflow_status = str(workflow_result.get("status") or "").strip().lower()
            if workflow_result.get("ok") and workflow_status != "blocked" and bool(contract_evaluation.get("satisfied")):
                self._mark_week1_stage_completed(
                    stage_name,
                    task_id=str(workflow_result.get("task_id") or ""),
                    source="autonomy_fallback",
                )
            elif workflow_result.get("ok") and workflow_status != "blocked" and not bool(contract_evaluation.get("satisfied")):
                workflow_result["reason"] = str(contract_evaluation.get("reason") or "completion_contract_unsatisfied")
            if workflow_status == "completed":
                workflow_result["state_sync_verifier"] = self._run_post_completion_state_sync_verifier(
                    task_id=str(workflow_result.get("task_id") or ""),
                    trigger="post_completion",
                    week1_stage=stage_name,
                    completion_evaluation=contract_evaluation,
                )
        return workflow_result

    async def _execute_week1_ops_backlog_fallback_workflow(
        self,
        actionable_surface: Dict[str, Any],
        *,
        run_id: str,
    ) -> Dict[str, Any]:
        surface = actionable_surface if isinstance(actionable_surface, dict) else {}
        candidate = self._select_week1_ops_backlog_candidate(surface)
        if not candidate:
            return {"ok": False, "reason": "week1_ops_backlog_empty"}
        context = self._resolve_week1_ops_backlog_context(candidate, surface)
        action_text = self._build_week1_ops_backlog_action(candidate, surface)
        if not action_text:
            return {"ok": False, "reason": "week1_ops_backlog_empty"}
        workflow_result = await self._execute_inner_action_workflow(
            action_text=action_text,
            run_id=run_id,
            additional_context=str(context.get("context") or ""),
        )
        if not isinstance(workflow_result, dict):
            workflow_result = {"ok": False, "reason": "invalid_workflow_result"}
        status = str(workflow_result.get("status") or "").strip().lower()
        resume_after_utc, awaiting_followthrough = self._week1_ops_backlog_resume_after_utc(candidate, status)
        state = self._load_week1_ops_backlog_state()
        items = state.get("items") if isinstance(state.get("items"), dict) else {}
        title = str(candidate.get("title") or "").strip()
        if title:
            items[title] = {
                "next_eligible_utc": resume_after_utc,
                "last_status": status,
                "last_task_id": str(workflow_result.get("task_id") or ""),
                "last_reason": str(workflow_result.get("reason") or workflow_result.get("response_preview") or "")[:240],
                "awaiting_human_followthrough": awaiting_followthrough,
                "resume_after_utc": resume_after_utc,
                "updated_at_utc": _utc_iso(),
            }
            state["items"] = items
            self._save_week1_ops_backlog_state(state)
        workflow_result["fallback_reason"] = "week1_ops_backlog"
        workflow_result["week1_stage"] = "ops_backlog"
        workflow_result["week1_primary_target"] = title
        workflow_result["week1_ops_backlog_context"] = context
        return workflow_result
