"""Regression tests for proactive manager initiative anti-repeat and recency gates."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from core.runtime.proactive_manager import ProactiveManager, _utc_iso
from planning.sentinel_engine import ActionPriority, RecommendedAction


class _SessionStoreStub:
    def __init__(self, minutes_since_activity: float) -> None:
        now_epoch = datetime.now(timezone.utc).timestamp()
        self._sessions = [{"last_active": now_epoch - (minutes_since_activity * 60.0)}]

    def list_sessions(self) -> List[Dict[str, Any]]:
        return list(self._sessions)


def _utc_ago(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _make_manager(tmp_path: Path, *, minutes_since_activity: float = 10.0) -> ProactiveManager:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._initiative_state_path = manager._memory_dir / "initiative_tuning_state.json"
    manager._initiative_event_log = manager._memory_dir / "initiative_tuning_events.jsonl"
    manager._initiative_config = {
        "enabled": True,
        "min_score": 0.20,
        "max_score": 0.90,
        "initial_score": 0.55,
        "normal_min_score": 0.30,
        "low_min_score": 0.45,
        "background_min_score": 0.55,
        "feedback_window_seconds": 1800,
        "max_action_memory": 40,
        "repeat_action_success_cooldown_seconds": 240,
        "repeat_action_failure_cooldown_seconds": 120,
        "partner_recent_activity_gate_minutes": 2,
    }
    manager._initiative_state = {
        "version": 1,
        "initiative_score": 0.80,
        "last_update_utc": _utc_iso(),
        "last_signal": {},
        "positive_feedback_count": 0,
        "negative_feedback_count": 0,
        "action_success_count": 0,
        "action_failure_count": 0,
        "suppressed_count": 0,
        "recent_actions": [],
    }
    manager.inner_life = None
    manager.session_store = _SessionStoreStub(minutes_since_activity=minutes_since_activity)
    return manager


def _recommendation() -> RecommendedAction:
    return RecommendedAction(
        action_id="a1",
        trigger_id="autonomy_cycle",
        description="Autonomy pulse",
        priority=ActionPriority.LOW,
        action_type="autonomy_cycle",
        payload={"conversation_id": "default"},
        triggering_events=[],
    )


def test_recent_partner_activity_blocks_low_priority_recommendation(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=0.4)

    allowed, reason = manager._should_execute_recommendation(_recommendation())

    assert allowed is False
    assert reason.startswith("partner_recently_active:")


def test_duplicate_success_within_cooldown_is_suppressed(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)
    manager._initiative_state["recent_actions"] = [
        {
            "ts_utc": _utc_ago(10),
            "action_id": "prev",
            "trigger_id": "autonomy_cycle",
            "action_type": "autonomy_cycle",
            "priority": "LOW",
            "conversation_id": "default",
            "success": True,
            "result_preview": "ok",
        }
    ]

    allowed, reason = manager._should_execute_recommendation(_recommendation())

    assert allowed is False
    assert reason.startswith("duplicate_action_success_cooldown:")


def test_duplicate_failure_within_cooldown_is_suppressed(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)
    manager._initiative_state["recent_actions"] = [
        {
            "ts_utc": _utc_ago(20),
            "action_id": "prev",
            "trigger_id": "autonomy_cycle",
            "action_type": "autonomy_cycle",
            "priority": "LOW",
            "conversation_id": "default",
            "success": False,
            "result_preview": "error",
        }
    ]

    allowed, reason = manager._should_execute_recommendation(_recommendation())

    assert allowed is False
    assert reason.startswith("duplicate_action_failure_cooldown:")


def test_duplicate_action_outside_cooldown_is_allowed(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)
    manager._initiative_state["recent_actions"] = [
        {
            "ts_utc": _utc_ago(900),
            "action_id": "prev",
            "trigger_id": "autonomy_cycle",
            "action_type": "autonomy_cycle",
            "priority": "LOW",
            "conversation_id": "default",
            "success": True,
            "result_preview": "ok",
        }
    ]

    allowed, reason = manager._should_execute_recommendation(_recommendation())

    assert allowed is True
    assert reason.startswith("initiative_score_ok:")
