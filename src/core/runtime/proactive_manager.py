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
            "version": 1,
            "initiative_score": initial_score,
            "last_update_utc": _utc_iso(),
            "last_signal": {},
            "positive_feedback_count": 0,
            "negative_feedback_count": 0,
            "action_success_count": 0,
            "action_failure_count": 0,
            "suppressed_count": 0,
            "recent_actions": [],
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

    def _should_execute_recommendation(self, recommendation: RecommendedAction) -> Tuple[bool, str]:
        state = self._ensure_initiative_runtime()
        if not bool(self._initiative_config.get("enabled", True)):
            return True, "initiative_tuning_disabled"
        if recommendation.priority in {ActionPriority.HIGH, ActionPriority.URGENT}:
            return True, "priority_override"

        score = self._clamp_initiative_score(state.get("initiative_score"))
        required = self._required_score_for_priority(recommendation.priority)
        mood = self._current_mood()
        mood_delta = self._initiative_threshold_delta_for_mood(mood)
        adjusted_required = min(1.0, max(0.0, required + mood_delta))
        if score >= adjusted_required:
            return True, (
                f"initiative_score_ok:{score:.3f}>={adjusted_required:.3f}"
                f";mood={mood};delta={mood_delta:+.3f}"
            )
        return False, (
            f"initiative_score_below_threshold:{score:.3f}<{adjusted_required:.3f}"
            f";mood={mood};delta={mood_delta:+.3f}"
        )

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

            followthrough_result: Dict[str, Any] = {"ok": False, "reason": "followthrough_disabled"}
            if bool(self._autonomy_config.get("followthrough_enabled", True)):
                last_follow = _parse_iso_utc(str(state.get("last_followthrough_utc") or ""))
                cooldown_seconds = int(self._autonomy_config.get("followthrough_cooldown_seconds", 900))
                now_utc = _utc_now()
                cooldown_ok = (last_follow is None) or ((now_utc - last_follow).total_seconds() >= cooldown_seconds)
                if cooldown_ok:
                    followthrough_result = await self._run_followthrough_executor_once()
                    if followthrough_result.get("ok"):
                        state["last_followthrough_utc"] = _utc_iso()
                else:
                    followthrough_result = {"ok": False, "reason": "followthrough_cooldown_active"}

            result.update(
                {
                    "reflection_reason": reflection_reason,
                    "reflection_outcome": getattr(reflection_result, "outcome", None) if reflection_result else None,
                    "workflow_result": workflow_result,
                    "followthrough_result": followthrough_result,
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
        self.dnd.queue_interrupt(
            message=recommendation.description,
            urgency=urgency,
            callback=lambda msg: self.execute_proactive_action(recommendation),
        )
        if self.config.debug:
            logger.debug("[DEBUG] Proactive action queued (DND active): %s", recommendation.description)

    def execute_proactive_action(self, recommendation: RecommendedAction):
        """Execute a proactive action recommendation."""
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
