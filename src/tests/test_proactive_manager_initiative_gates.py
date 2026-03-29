"""Regression tests for proactive manager initiative anti-repeat and recency gates."""

import json
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


def _utc_future(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


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
        "type_base_cooldown_seconds": 300,
        "type_max_cooldown_seconds": 14400,
        "type_backoff_factor": 2.0,
        "type_feedback_penalty_floor": 3,
        "type_noop_streak_threshold": 5,
    }
    manager._initiative_state = {
        "version": 2,
        "initiative_score": 0.80,
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
    manager.inner_life = None
    manager.session_store = _SessionStoreStub(minutes_since_activity=minutes_since_activity)
    return manager


def _recommendation(
    action_type: str = "check_tasks",
    priority: ActionPriority = ActionPriority.LOW,
) -> RecommendedAction:
    return RecommendedAction(
        action_id="a1",
        trigger_id=action_type,
        description="Test recommendation",
        priority=priority,
        action_type=action_type,
        payload={"conversation_id": "default"},
        triggering_events=[],
    )


# --- Existing tests (updated) ---


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
            "trigger_id": "check_tasks",
            "action_type": "check_tasks",
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
            "trigger_id": "check_tasks",
            "action_type": "check_tasks",
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
            "trigger_id": "check_tasks",
            "action_type": "check_tasks",
            "priority": "LOW",
            "conversation_id": "default",
            "success": True,
            "result_preview": "ok",
        }
    ]

    allowed, reason = manager._should_execute_recommendation(_recommendation())

    assert allowed is True
    assert reason.startswith("allowed;")


# --- New tests: per-type adaptive cooldowns ---


def test_action_type_on_cooldown_is_suppressed(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)
    manager._initiative_state["action_type_stats"] = {
        "check_tasks": {
            "consecutive_failures": 2,
            "consecutive_noops": 0,
            "cooldown_until_utc": _utc_future(600),
            "total_successes": 0,
            "total_failures": 2,
            "total_noops": 0,
            "last_attempt_utc": _utc_ago(60),
            "last_outcome": "action_failure",
        }
    }

    allowed, reason = manager._should_execute_recommendation(_recommendation())

    assert allowed is False
    assert reason.startswith("action_type_cooldown:check_tasks;")


def test_expired_action_type_cooldown_is_allowed(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)
    manager._initiative_state["action_type_stats"] = {
        "check_tasks": {
            "consecutive_failures": 2,
            "consecutive_noops": 0,
            "cooldown_until_utc": _utc_ago(60),
            "total_successes": 0,
            "total_failures": 2,
            "total_noops": 0,
            "last_attempt_utc": _utc_ago(600),
            "last_outcome": "action_failure",
        }
    }

    allowed, reason = manager._should_execute_recommendation(_recommendation())

    assert allowed is True
    assert reason.startswith("allowed;")


def test_unknown_action_type_has_no_cooldown(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)
    # action_type_stats is empty — no stats for check_tasks

    allowed, reason = manager._should_execute_recommendation(_recommendation())

    assert allowed is True


def test_low_global_score_no_longer_blocks(tmp_path: Path) -> None:
    """The key behavioral change: score at floor should NOT block actions."""
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)
    manager._initiative_state["initiative_score"] = 0.20  # at floor

    allowed, reason = manager._should_execute_recommendation(_recommendation())

    assert allowed is True
    assert "initiative_score_observed" in reason


def test_high_priority_bypasses_type_cooldown(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)
    manager._initiative_state["action_type_stats"] = {
        "check_tasks": {
            "consecutive_failures": 5,
            "consecutive_noops": 0,
            "cooldown_until_utc": _utc_future(3600),
            "total_successes": 0,
            "total_failures": 5,
            "total_noops": 0,
            "last_attempt_utc": _utc_ago(60),
            "last_outcome": "action_failure",
        }
    }

    rec = _recommendation(action_type="check_tasks", priority=ActionPriority.HIGH)
    allowed, reason = manager._should_execute_recommendation(rec)

    assert allowed is True
    assert reason == "priority_override"


def test_compute_type_cooldown_seconds(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)

    assert manager._compute_type_cooldown_seconds(0) == 0.0
    assert manager._compute_type_cooldown_seconds(1) == 300.0   # base
    assert manager._compute_type_cooldown_seconds(2) == 600.0   # base * 2
    assert manager._compute_type_cooldown_seconds(3) == 1200.0  # base * 4
    assert manager._compute_type_cooldown_seconds(10) <= 14400.0  # capped


def test_compute_noop_cooldown_seconds(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)

    assert manager._compute_noop_cooldown_seconds(0) == 0.0
    assert manager._compute_noop_cooldown_seconds(4) == 0.0
    assert manager._compute_noop_cooldown_seconds(5) == 300.0
    assert manager._compute_noop_cooldown_seconds(6) == 600.0
    assert manager._compute_noop_cooldown_seconds(7) == 1200.0
    assert manager._compute_noop_cooldown_seconds(20) <= 14400.0


def test_cooldown_multiplier_for_mood(tmp_path: Path) -> None:
    assert ProactiveManager._cooldown_multiplier_for_mood("strained") == 1.50
    assert ProactiveManager._cooldown_multiplier_for_mood("energized") == 0.75
    assert ProactiveManager._cooldown_multiplier_for_mood("steady") == 1.0
    assert ProactiveManager._cooldown_multiplier_for_mood("") == 1.0


def test_v1_state_migrates_to_v2(tmp_path: Path) -> None:
    """v1 state without action_type_stats should be bootstrapped from recent_actions."""
    state_path = tmp_path / "initiative_tuning_state.json"
    v1_state = {
        "version": 1,
        "initiative_score": 0.5,
        "last_update_utc": _utc_iso(),
        "last_signal": {},
        "positive_feedback_count": 0,
        "negative_feedback_count": 0,
        "action_success_count": 10,
        "action_failure_count": 1,
        "suppressed_count": 5,
        "recent_actions": [
            {"ts_utc": _utc_ago(200), "action_type": "check_tasks", "success": True},
            {"ts_utc": _utc_ago(100), "action_type": "check_tasks", "success": False},
            {"ts_utc": _utc_ago(50), "action_type": "reflect", "success": True},
        ],
    }
    state_path.write_text(json.dumps(v1_state))

    manager = object.__new__(ProactiveManager)
    manager._memory_dir = tmp_path
    manager._initiative_state_path = state_path
    manager._initiative_event_log = tmp_path / "initiative_tuning_events.jsonl"
    manager._initiative_config = _make_manager(tmp_path)._initiative_config

    state = manager._load_initiative_state()

    assert "action_type_stats" in state
    assert state["version"] == 2
    assert "check_tasks" in state["action_type_stats"]
    assert "reflect" in state["action_type_stats"]
    ct = state["action_type_stats"]["check_tasks"]
    assert ct["total_successes"] == 1
    assert ct["total_failures"] == 1
    # Last check_tasks action was a failure, so consecutive_failures should be 1
    assert ct["consecutive_failures"] == 1
    # reflect had one success
    rt = state["action_type_stats"]["reflect"]
    assert rt["total_successes"] == 1
    assert rt["consecutive_failures"] == 0


def test_cooldown_does_not_affect_other_action_types(tmp_path: Path) -> None:
    """Only the specific action type on cooldown is blocked; others are free."""
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)
    manager._initiative_state["action_type_stats"] = {
        "check_tasks": {
            "consecutive_failures": 3,
            "consecutive_noops": 0,
            "cooldown_until_utc": _utc_future(3600),
            "total_successes": 0,
            "total_failures": 3,
            "total_noops": 0,
            "last_attempt_utc": _utc_ago(60),
            "last_outcome": "action_failure",
        }
    }

    # check_tasks is on cooldown
    rec_blocked = _recommendation(action_type="check_tasks", priority=ActionPriority.NORMAL)
    allowed_blocked, _ = manager._should_execute_recommendation(rec_blocked)
    assert allowed_blocked is False

    # reflect has no cooldown — should be free
    rec_free = _recommendation(action_type="reflect", priority=ActionPriority.NORMAL)
    allowed_free, reason_free = manager._should_execute_recommendation(rec_free)
    assert allowed_free is True
    assert reason_free == "internal_cadence_bypass"


def test_internal_autonomy_cycle_bypasses_initiative_gates(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=0.1)
    manager._initiative_state["recent_actions"] = [
        {
            "ts_utc": _utc_ago(5),
            "action_id": "prev",
            "trigger_id": "autonomy_cycle",
            "action_type": "autonomy_cycle",
            "priority": "LOW",
            "conversation_id": "default",
            "success": True,
            "result_preview": "ok",
        }
    ]
    manager._initiative_state["action_type_stats"] = {
        "autonomy_cycle": {
            "consecutive_failures": 3,
            "consecutive_noops": 0,
            "cooldown_until_utc": _utc_future(600),
            "total_successes": 1,
            "total_failures": 3,
            "total_noops": 0,
            "last_attempt_utc": _utc_ago(5),
            "last_outcome": "action_failure",
        }
    }

    rec = _recommendation(action_type="autonomy_cycle", priority=ActionPriority.LOW)
    allowed, reason = manager._should_execute_recommendation(rec)

    assert allowed is True
    assert reason == "internal_cadence_bypass"


def test_internal_autonomy_cycle_stats_never_set_cooldown(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)

    manager._update_action_type_stats(action_type="autonomy_cycle", outcome="action_failure")
    state_after_failure = manager._ensure_initiative_runtime()
    stats = state_after_failure["action_type_stats"]["autonomy_cycle"]
    assert stats["total_failures"] == 1
    assert stats["cooldown_until_utc"] is None
    assert stats["consecutive_failures"] == 0

    manager._update_action_type_stats(action_type="autonomy_cycle", outcome="action_success_noop")
    state_after_noop = manager._ensure_initiative_runtime()
    stats = state_after_noop["action_type_stats"]["autonomy_cycle"]
    assert stats["total_noops"] == 0
    assert stats["last_outcome"] == "action_success_noop"
    assert stats["cooldown_until_utc"] is None
    assert stats["consecutive_noops"] == 0


def test_internal_reflect_stats_never_set_cooldown_or_noop_totals(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)

    manager._update_action_type_stats(action_type="reflect", outcome="action_success_skipped")
    stats = manager._ensure_initiative_runtime()["action_type_stats"]["reflect"]

    assert stats["total_noops"] == 0
    assert stats["last_outcome"] == "action_success_skipped"
    assert stats["cooldown_until_utc"] is None
    assert stats["consecutive_noops"] == 0


def test_noop_streak_applies_exponential_cooldown_without_reset(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)

    for _ in range(5):
        manager._update_action_type_stats(action_type="check_tasks", outcome="action_success_noop")

    stats = manager._ensure_initiative_runtime()["action_type_stats"]["check_tasks"]
    first_cooldown = datetime.fromisoformat(stats["cooldown_until_utc"].replace("Z", "+00:00"))
    first_remaining = (first_cooldown - datetime.now(timezone.utc)).total_seconds()
    assert 250 <= first_remaining <= 330
    assert stats["consecutive_noops"] == 5

    manager._update_action_type_stats(action_type="check_tasks", outcome="action_success_noop")
    stats = manager._ensure_initiative_runtime()["action_type_stats"]["check_tasks"]
    second_cooldown = datetime.fromisoformat(stats["cooldown_until_utc"].replace("Z", "+00:00"))
    second_remaining = (second_cooldown - datetime.now(timezone.utc)).total_seconds()
    assert 550 <= second_remaining <= 630
    assert stats["consecutive_noops"] == 6


def test_feedback_linking_ignores_internal_cadence_not_due_rows(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, minutes_since_activity=10.0)
    manager._initiative_state["recent_actions"] = [
        {
            "ts_utc": _utc_ago(30),
            "action_id": "week1",
            "trigger_id": "week1_due_check",
            "action_type": "week1_due_check",
            "priority": "HIGH",
            "conversation_id": "",
            "success": True,
            "signal_type": "action_success_not_due",
            "result_preview": "{'scheduled': False, 'attempted': False, 'reason': 'no_due_work'}",
        },
        {
            "ts_utc": _utc_ago(20),
            "action_id": "tasks",
            "trigger_id": "check_tasks",
            "action_type": "check_tasks",
            "priority": "LOW",
            "conversation_id": "default",
            "success": True,
            "signal_type": "action_success",
            "result_preview": "{'scheduled': True}",
        },
    ]

    linked, row = manager._is_feedback_linked_to_recent_action("default")

    assert linked is True
    assert row.get("action_id") == "tasks"
