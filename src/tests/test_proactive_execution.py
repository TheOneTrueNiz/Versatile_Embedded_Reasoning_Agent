"""Unit tests for sentinel recommendation proactive execution."""

import asyncio
import json
import os
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.foundation.master_list import MasterTaskList, TaskPriority, TaskStatus
from core.runtime.proactive_manager import ProactiveManager, _utc_iso, _utc_now
from planning.sentinel_engine import ActionPriority, RecommendedAction
from planning.sentinel_engine import Event, EventPattern, EventSource, EventType, SentinelEngine, Trigger, TriggerCondition


# ---------------------------------------------------------------------------
# Helpers / Stubs
# ---------------------------------------------------------------------------

def _make_rec(
    action_id: str = "a1",
    priority: ActionPriority = ActionPriority.HIGH,
    description: str = "Search Wikipedia for recent AI developments",
    action_type: str = "proactive_check",
) -> RecommendedAction:
    return RecommendedAction(
        action_id=action_id,
        trigger_id="test_trigger",
        description=description,
        priority=priority,
        action_type=action_type,
        payload={},
        triggering_events=[],
    )


def _make_manager(tmp_path: Path, pending_recs: Optional[List[RecommendedAction]] = None) -> ProactiveManager:
    """Create a minimal ProactiveManager stub for proactive execution tests."""
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._memory_dir.mkdir(parents=True, exist_ok=True)
    manager._owner = MagicMock()
    manager._owner.process_messages = AsyncMock(return_value="COMPLETED: Done")
    manager._owner._proactive_tool_whitelist = None
    manager.dnd = MagicMock()
    manager.dnd.can_interrupt = MagicMock(return_value=True)
    manager.sentinel = MagicMock()
    manager.sentinel.recommender = MagicMock()
    recommendations = list(pending_recs or [])

    def _pending(priority: Optional[ActionPriority] = None):
        rows = [
            rec for rec in recommendations
            if not getattr(rec, "acknowledged", False) and not getattr(rec, "executed", False)
        ]
        if priority is not None:
            rows = [rec for rec in rows if rec.priority == priority]
        return rows

    manager.sentinel.recommender.get_pending_recommendations = MagicMock(side_effect=_pending)
    def _mark_executed(action_id: str) -> bool:
        for rec in recommendations:
            if rec.action_id == action_id:
                rec.executed = True
                return True
        return False

    def _acknowledge(action_id: str) -> bool:
        for rec in recommendations:
            if rec.action_id == action_id:
                rec.acknowledged = True
                return True
        return False

    def _execute_recommendation(action_id: str):
        _mark_executed(action_id)
        return True, {"ok": True}

    manager.sentinel.recommender.mark_executed = MagicMock(side_effect=_mark_executed)
    manager.sentinel.recommender.acknowledge = MagicMock(side_effect=_acknowledge)
    manager.sentinel.execute_recommendation = MagicMock(side_effect=_execute_recommendation)
    manager.decision_ledger = None
    manager.config = SimpleNamespace(debug=False, observability=False)
    manager.observability = MagicMock()
    manager._pending_proactive_actions = []
    manager._proactive_lane_lock = threading.RLock()
    manager._active_proactive_lanes = {}
    manager._proactive_lane_queues = {}
    manager._proactive_lane_queue_max = 8
    manager._should_execute_recommendation = MagicMock(return_value=(True, "allowed"))
    manager._record_recent_proactive_action = MagicMock()
    manager._evaluate_action_reward_signal = MagicMock(return_value=(0.0, "action_success"))
    manager._apply_initiative_signal = MagicMock()
    manager._update_action_type_stats = MagicMock()
    manager._append_failure_learning_event = MagicMock()
    manager._append_initiative_event = MagicMock()

    # Stub _execute_inner_action_workflow
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={"ok": True, "task_id": "t1", "status": "completed", "response_preview": "Done"}
    )
    return manager


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_proactive_execution_skips_when_env_off(tmp_path: Path) -> None:
    """With VERA_PROACTIVE_EXECUTION=0, no processing should occur."""
    recs = [_make_rec()]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "0"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )
    assert result is None
    manager._execute_inner_action_workflow.assert_not_called()


def test_proactive_execution_respects_dnd(tmp_path: Path) -> None:
    """When DND blocks HIGH urgency, should skip."""
    recs = [_make_rec()]
    manager = _make_manager(tmp_path, pending_recs=recs)
    manager.dnd.can_interrupt = MagicMock(return_value=False)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )
    assert result is not None
    assert result.get("skipped") is True
    assert result.get("reason") == "dnd_active"


def test_proactive_execution_executes_high_priority(tmp_path: Path) -> None:
    """HIGH priority recommendation should be auto-executed."""
    recs = [_make_rec(priority=ActionPriority.HIGH)]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert len(result.get("executed", [])) == 1
    manager._execute_inner_action_workflow.assert_called_once()
    manager.sentinel.recommender.mark_executed.assert_called_once_with("a1")


def test_high_priority_handler_backed_action_uses_registered_handler_path(tmp_path: Path) -> None:
    recs = [_make_rec(action_id="w1", priority=ActionPriority.HIGH, action_type="week1_due_check")]
    manager = _make_manager(tmp_path, pending_recs=recs)
    manager.sentinel.recommender.recommendation_handlers = {"week1_due_check": object()}
    manager.handle_proactive_recommendation = MagicMock(
        return_value={
            "outcome": "executed_noop",
            "result": {"scheduled": False, "attempted": False, "reason": "no_due_work"},
        }
    )

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(manager._process_sentinel_recommendations())

    assert result is not None
    assert result["executed"] == [
        {
            "action_id": "w1",
            "result": {"scheduled": False, "attempted": False, "reason": "no_due_work"},
        }
    ]
    manager.handle_proactive_recommendation.assert_called_once_with(recs[0])
    manager._execute_inner_action_workflow.assert_not_called()


def test_proactive_execution_executes_urgent_priority(tmp_path: Path) -> None:
    """URGENT priority recommendation should also be auto-executed."""
    recs = [_make_rec(action_id="u1", priority=ActionPriority.URGENT)]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert len(result.get("executed", [])) == 1
    manager.sentinel.recommender.mark_executed.assert_called_once_with("u1")


def test_proactive_execution_routes_normal_priority_through_proactive_handler(tmp_path: Path) -> None:
    """NORMAL priority should use the proactive handler path, not forced push-only notify."""
    recs = [_make_rec(action_id="n1", priority=ActionPriority.NORMAL)]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert len(result.get("executed", [])) == 1
    assert result["executed"][0]["action_id"] == "n1"
    manager.sentinel.execute_recommendation.assert_called_once_with("n1")
    manager.sentinel.recommender.acknowledge.assert_not_called()


def test_proactive_execution_routes_low_priority_through_initiative_gate(tmp_path: Path) -> None:
    """LOW priority should no longer be force-logged when the handler path allows execution."""
    recs = [_make_rec(action_id="l1", priority=ActionPriority.LOW)]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert len(result.get("executed", [])) == 1
    assert result["executed"][0]["action_id"] == "l1"
    manager.sentinel.execute_recommendation.assert_called_once_with("l1")
    manager.sentinel.recommender.acknowledge.assert_not_called()


def test_proactive_execution_routes_background_priority_through_initiative_gate(tmp_path: Path) -> None:
    """BACKGROUND priority should no longer be force-logged when the handler path allows execution."""
    recs = [_make_rec(action_id="b1", priority=ActionPriority.BACKGROUND)]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert len(result.get("executed", [])) == 1
    assert result["executed"][0]["action_id"] == "b1"


def test_proactive_execution_rate_limits(tmp_path: Path) -> None:
    """Max 3 executions per cycle (default)."""
    recs = [_make_rec(action_id=f"h{i}", priority=ActionPriority.HIGH) for i in range(6)]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {
        "VERA_PROACTIVE_EXECUTION": "1",
        "VERA_PROACTIVE_MAX_PER_CYCLE": "3",
    }, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert len(result.get("executed", [])) == 3
    assert result.get("pending_remaining", 0) > 0


def test_proactive_execution_reports_queued_outcome(tmp_path: Path) -> None:
    recs = [_make_rec(action_id="q1", priority=ActionPriority.NORMAL)]
    manager = _make_manager(tmp_path, pending_recs=recs)
    manager._active_proactive_lanes[manager._build_proactive_lane_key(recs[0])] = "other-action"

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(manager._process_sentinel_recommendations())

    assert result is not None
    assert len(result.get("queued", [])) == 1
    assert result["queued"][0]["action_id"] == "q1"
    assert result.get("pending_remaining", 0) >= 1


def test_proactive_execution_reports_suppressed_outcome(tmp_path: Path) -> None:
    recs = [_make_rec(action_id="s1", priority=ActionPriority.LOW)]
    manager = _make_manager(tmp_path, pending_recs=recs)
    manager._should_execute_recommendation = MagicMock(return_value=(False, "duplicate_action"))
    manager._ensure_initiative_runtime = MagicMock(return_value={"suppressed_count": 0})
    manager._save_initiative_state = MagicMock()

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(manager._process_sentinel_recommendations())

    assert result is not None
    assert len(result.get("suppressed", [])) == 1
    assert result["suppressed"][0]["action_id"] == "s1"
    assert result.get("pending_remaining", 0) >= 1


def test_proactive_execution_auto_acks_repeated_transient_suppression(tmp_path: Path) -> None:
    rec = _make_rec(action_id="s2", priority=ActionPriority.LOW)
    rec.suppression_count = 2
    manager = _make_manager(tmp_path, pending_recs=[rec])
    manager._should_execute_recommendation = MagicMock(
        return_value=(False, "duplicate_action_success_cooldown:reload_config;age=30s<240s")
    )
    manager._ensure_initiative_runtime = MagicMock(return_value={"suppressed_count": 0})
    manager._save_initiative_state = MagicMock()

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(manager._process_sentinel_recommendations())

    assert result is not None
    assert len(result.get("suppressed", [])) == 1
    assert result["suppressed"][0]["action_id"] == "s2"
    assert result["suppressed"][0]["auto_acked"] is True
    assert result["pending_remaining"] == 0


def test_proactive_execution_defers_retry_when_suppressed_recommendation_has_backoff(tmp_path: Path) -> None:
    rec = _make_rec(action_id="s3", priority=ActionPriority.LOW)
    rec.retry_not_before = (_utc_now() + timedelta(seconds=45)).isoformat().replace("+00:00", "Z")
    manager = _make_manager(tmp_path, pending_recs=[rec])

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(manager._process_sentinel_recommendations())

    assert result is not None
    assert len(result["deferred"]) == 1
    assert result["deferred"][0]["action_id"] == "s3"
    assert result["deferred"][0]["reason"].startswith("retry_deferred:")
    assert result["processed"] == 0
    assert result["pending_remaining"] == 1
    manager._should_execute_recommendation.assert_not_called()


def test_record_suppressed_recommendation_sets_retry_not_before(tmp_path: Path) -> None:
    rec = _make_rec(action_id="s4", priority=ActionPriority.LOW)
    manager = _make_manager(tmp_path, pending_recs=[rec])
    manager._parse_int_env = MagicMock(side_effect=lambda name, default, minimum=0: default)

    row = manager._record_suppressed_recommendation(
        rec,
        "duplicate_action_success_cooldown:reload_config;age=210s<240s",
    )

    assert row["action_id"] == "s4"
    assert "retry_not_before" in row
    retry_not_before = rec.retry_not_before
    assert retry_not_before is not None
    retry_dt = datetime.fromisoformat(str(retry_not_before).replace("Z", "+00:00"))
    remaining = (retry_dt - _utc_now()).total_seconds()
    assert 0 < remaining <= 35


def test_record_suppressed_recommendation_aligns_action_type_cooldown_retry_to_cooldown_end(tmp_path: Path) -> None:
    rec = _make_rec(action_id="s4b", priority=ActionPriority.LOW, action_type="red_team_check")
    rec.suppression_count = 99
    rec.created_at = (_utc_now() - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    manager = _make_manager(tmp_path, pending_recs=[rec])
    manager._parse_int_env = MagicMock(side_effect=lambda name, default, minimum=0: default)

    cooldown_until = (_utc_now() + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    row = manager._record_suppressed_recommendation(
        rec,
        f"action_type_cooldown:red_team_check;remaining=900s;until={cooldown_until}",
    )

    assert row["action_id"] == "s4b"
    assert row.get("auto_acked") is not True
    assert row.get("retry_not_before") == cooldown_until
    assert rec.retry_not_before == cooldown_until
    manager.sentinel.recommender.acknowledge.assert_not_called()


def test_proactive_execution_marks_executed(tmp_path: Path) -> None:
    """Executed recommendations should be marked via mark_executed."""
    recs = [
        _make_rec(action_id="ex1", priority=ActionPriority.HIGH),
        _make_rec(action_id="ex2", priority=ActionPriority.HIGH),
    ]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert manager.sentinel.recommender.mark_executed.call_count == 2
    calls = [c.args[0] for c in manager.sentinel.recommender.mark_executed.call_args_list]
    assert "ex1" in calls
    assert "ex2" in calls


def test_proactive_execution_no_pending(tmp_path: Path) -> None:
    """No pending recommendations should return cleanly."""
    manager = _make_manager(tmp_path, pending_recs=[])

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert result.get("processed") == 0
    assert result.get("pending") == 0


def test_handle_recommendation_autonomy_cycle_bypasses_dnd(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager.execute_proactive_action = MagicMock()
    manager._should_execute_recommendation = MagicMock(return_value=(True, "allowed"))
    manager.dnd.can_interrupt = MagicMock(return_value=False)

    rec = _make_rec(action_id="aut1", priority=ActionPriority.BACKGROUND, action_type="autonomy_cycle")
    manager.handle_proactive_recommendation(rec)

    manager.execute_proactive_action.assert_called_once_with(rec)
    manager.dnd.queue_interrupt.assert_not_called()
    assert manager._pending_proactive_actions == []


def test_handle_recommendation_defers_when_retry_window_active(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager._append_initiative_event = MagicMock()
    manager._should_execute_recommendation = MagicMock(return_value=(True, "allowed"))

    rec = _make_rec(action_id="def1", priority=ActionPriority.LOW, action_type="reload_config")
    rec.retry_not_before = (_utc_now() + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")

    result = manager.handle_proactive_recommendation(rec)

    assert result["outcome"] == "deferred"
    assert result["reason"].startswith("retry_deferred:")
    manager._should_execute_recommendation.assert_not_called()
    manager._append_initiative_event.assert_called_once()


def test_handle_recommendation_transient_suppression_sets_retry_not_before(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager._append_initiative_event = MagicMock()
    manager._ensure_initiative_runtime = MagicMock(return_value={"suppressed_count": 0})
    manager._save_initiative_state = MagicMock()
    manager._should_execute_recommendation = MagicMock(
        return_value=(False, "duplicate_action_success_cooldown:proactive_check;age=20s<240s")
    )

    rec = _make_rec(action_id="def2", priority=ActionPriority.LOW, action_type="proactive_check")
    result = manager.handle_proactive_recommendation(rec)

    assert result["outcome"] == "suppressed"
    assert rec.retry_not_before is not None
    manager._append_initiative_event.assert_called_once()


def test_handle_recommendation_skips_reload_config_for_recent_local_write(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager._append_initiative_event = MagicMock()
    manager._update_action_type_stats = MagicMock()
    manager._probe_reload_config_needed = MagicMock(
        return_value={"needed": False, "reason": "recent_local_write:preferences", "paths": ["preferences"]}
    )

    rec = _make_rec(action_id="rc1", priority=ActionPriority.LOW, action_type="reload_config")
    result = manager.handle_proactive_recommendation(rec)

    assert result["outcome"] == "executed_noop"
    assert result["result"]["reason"] == "recent_local_write:preferences"
    manager.sentinel.recommender.acknowledge.assert_called_once_with("rc1")
    manager._update_action_type_stats.assert_called_once_with(
        action_type="reload_config",
        outcome="action_success_skipped",
    )


def test_handle_recommendation_allows_reload_config_external_change_despite_duplicate_cooldown(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager._probe_reload_config_needed = MagicMock(
        return_value={"needed": True, "reason": "external_change_or_unknown", "paths": []}
    )
    manager._should_execute_recommendation = MagicMock(
        return_value=(False, "duplicate_action_success_cooldown:reload_config;age=10s<240s")
    )
    manager.execute_proactive_action = MagicMock(return_value={"outcome": "executed", "result": {"reloaded": True}})

    rec = _make_rec(action_id="rc2", priority=ActionPriority.LOW, action_type="reload_config")
    result = manager.handle_proactive_recommendation(rec)

    assert result["outcome"] == "executed"
    manager.execute_proactive_action.assert_called_once_with(rec)


def test_handle_recommendation_skips_red_team_when_not_due(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager._append_initiative_event = MagicMock()
    manager._update_action_type_stats = MagicMock()
    manager._probe_red_team_due_work = MagicMock(return_value={"due": False, "reason": "not_due", "delta": 12, "current": 42})

    rec = _make_rec(action_id="rt1", priority=ActionPriority.LOW, action_type="red_team_check")
    result = manager.handle_proactive_recommendation(rec)

    assert result["outcome"] == "executed_noop"
    assert result["result"]["reason"] == "not_due"
    manager.sentinel.recommender.acknowledge.assert_called_once_with("rt1")
    manager._update_action_type_stats.assert_called_once_with(
        action_type="red_team_check",
        outcome="action_success_not_due",
    )


def test_handle_recommendation_suppresses_repeated_red_team_skip_event(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager._append_initiative_event = MagicMock()
    manager._update_action_type_stats = MagicMock()
    manager._probe_red_team_due_work = MagicMock(return_value={"due": False, "reason": "not_due"})
    manager._should_suppress_maintenance_skip_event = MagicMock(return_value=True)

    rec = _make_rec(action_id="rt2", priority=ActionPriority.LOW, action_type="red_team_check")
    result = manager.handle_proactive_recommendation(rec)

    assert result["outcome"] == "executed_noop"
    manager._append_initiative_event.assert_not_called()


def test_handle_recommendation_skips_check_tasks_when_no_overdue(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager._append_initiative_event = MagicMock()
    manager._update_action_type_stats = MagicMock()
    manager._probe_check_tasks_due_work = MagicMock(
        return_value={"due": False, "reason": "no_overdue_tasks", "overdue_count": 0, "tasks": []}
    )

    rec = _make_rec(action_id="ct1", priority=ActionPriority.LOW, action_type="check_tasks")
    result = manager.handle_proactive_recommendation(rec)

    assert result["outcome"] == "executed_noop"
    assert result["result"]["reason"] == "no_overdue_tasks"
    manager.sentinel.recommender.acknowledge.assert_called_once_with("ct1")
    manager._update_action_type_stats.assert_called_once_with(
        action_type="check_tasks",
        outcome="action_success_noop",
    )


def test_handle_recommendation_suppresses_repeated_check_tasks_skip_event(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager._append_initiative_event = MagicMock()
    manager._update_action_type_stats = MagicMock()
    manager._probe_check_tasks_due_work = MagicMock(
        return_value={"due": False, "reason": "no_overdue_tasks", "overdue_count": 0, "tasks": []}
    )
    manager._should_suppress_maintenance_skip_event = MagicMock(return_value=True)

    rec = _make_rec(action_id="ct2", priority=ActionPriority.LOW, action_type="check_tasks")
    result = manager.handle_proactive_recommendation(rec)

    assert result["outcome"] == "executed_noop"
    manager._append_initiative_event.assert_not_called()


def test_action_check_tasks_uses_probe_and_returns_overdue_tasks(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._probe_check_tasks_due_work = MagicMock(
        return_value={
            "due": True,
            "reason": "overdue_tasks",
            "overdue_count": 2,
            "tasks": [{"id": "t1", "title": "A"}, {"id": "t2", "title": "B"}],
        }
    )
    manager._owner = SimpleNamespace()
    manager._stopping = False
    manager._send_overdue_tasks_push = AsyncMock(return_value=None)
    manager._schedule_coroutine = MagicMock()

    result = manager.action_check_tasks({})

    assert result == {
        "overdue_count": 2,
        "tasks": [{"id": "t1", "title": "A"}, {"id": "t2", "title": "B"}],
    }


def test_probe_check_tasks_due_work_uses_master_list_overdue_api(tmp_path: Path) -> None:
    memory_dir = tmp_path / "vera_memory"
    tasks = MasterTaskList(memory_dir=memory_dir)
    tasks.add_task(
        title="Overdue probe task",
        priority=TaskPriority.HIGH,
        description="Created by proactive execution regression test.",
        due=datetime.now() - timedelta(minutes=15),
        tags=["test"],
    )

    manager = object.__new__(ProactiveManager)
    manager.master_list = tasks

    result = manager._probe_check_tasks_due_work()

    assert result["due"] is True
    assert result["reason"] == "overdue_tasks"
    assert result["overdue_count"] == 1
    assert result["tasks"][0]["title"] == "Overdue probe task"


def test_action_week1_due_check_schedules_coroutine(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_config = {"week1_executor_enabled": True}
    manager._week1_due_check_future = None
    manager._probe_week1_executor_due_work_sync = MagicMock(return_value={"ok": True, "due_count": 1})
    def _capture(coro):
        coro.close()
        return object()
    manager._schedule_coroutine = MagicMock(side_effect=_capture)

    result = manager.action_week1_due_check({"trigger": "sentinel"})

    assert result == {"scheduled": True, "trigger": "sentinel"}
    manager._schedule_coroutine.assert_called_once()


def test_action_week1_due_check_short_circuits_when_no_due_work(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_config = {"week1_executor_enabled": True}
    manager._week1_due_check_future = None
    manager._probe_week1_executor_due_work_sync = MagicMock(
        return_value={"ok": True, "due_count": 0, "reason": "no_due_work"}
    )
    manager._schedule_coroutine = MagicMock()

    result = manager.action_week1_due_check({"trigger": "sentinel"})

    assert result["scheduled"] is False
    assert result["attempted"] is False
    assert result["reason"] == "no_due_work"


def test_action_autonomy_cycle_uses_payload_action_as_default_trigger(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_config = {"enabled": True}
    manager._autonomy_cycle_future = None

    def _capture(coro):
        coro.close()
        return object()

    manager._schedule_coroutine = MagicMock(side_effect=_capture)

    result = manager.action_autonomy_cycle({"action": "autonomy_cycle"})

    assert result == {"scheduled": True, "trigger": "autonomy_cycle", "force": False}
    manager._schedule_coroutine.assert_called_once()


def test_action_reflect_skips_heartbeat_echo_streak(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(enabled=True),
        _recent_monologue=[
            SimpleNamespace(timestamp=_utc_iso(), trigger="heartbeat", intent="INTERNAL"),
            SimpleNamespace(timestamp=_utc_iso(), trigger="heartbeat", intent="INTERNAL"),
            SimpleNamespace(timestamp=_utc_iso(), trigger="heartbeat", intent="INTERNAL"),
        ],
    )
    manager._schedule_coroutine = MagicMock()

    result = manager.action_reflect({"trigger": "heartbeat"})

    assert result["skipped"] is True
    assert result["reason"] == "heartbeat_internal_echo_streak"
    manager._schedule_coroutine.assert_not_called()


def test_action_reflect_skips_heartbeat_echo_streak_even_with_non_heartbeat_entry_afterward(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(enabled=True),
        _recent_monologue=[
            SimpleNamespace(timestamp=_utc_iso(), trigger="heartbeat", intent="INTERNAL"),
            SimpleNamespace(timestamp=_utc_iso(), trigger="heartbeat", intent="INTERNAL"),
            SimpleNamespace(timestamp=_utc_iso(), trigger="heartbeat", intent="INTERNAL"),
            SimpleNamespace(timestamp=_utc_iso(), trigger="autonomy_cycle", intent="INTERNAL"),
        ],
    )
    manager._schedule_coroutine = MagicMock()

    result = manager.action_reflect({"trigger": "heartbeat"})

    assert result["skipped"] is True
    assert result["reason"] == "heartbeat_internal_echo_streak"
    manager._schedule_coroutine.assert_not_called()


def test_action_reflect_schedules_for_manual_trigger_even_with_heartbeat_echo_streak(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(enabled=True),
        _recent_monologue=[
            SimpleNamespace(timestamp=_utc_iso(), trigger="heartbeat", intent="INTERNAL"),
            SimpleNamespace(timestamp=_utc_iso(), trigger="heartbeat", intent="INTERNAL"),
            SimpleNamespace(timestamp=_utc_iso(), trigger="heartbeat", intent="INTERNAL"),
        ],
    )
    manager._schedule_coroutine = MagicMock(return_value=object())
    manager.run_reflection_cycle = MagicMock(return_value="scheduled")

    result = manager.action_reflect({"trigger": "manual", "force": True})

    assert result["scheduled"] is True
    assert result["trigger"] == "manual"
    assert result["force"] is True
    manager._schedule_coroutine.assert_called_once()


def test_active_autonomy_cycle_skips_reflection_when_no_actionable_work(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 21, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 21, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "autonomy_no_actionable_work"
    assert result["reflection_outcome"] is None
    assert result["actionable_surface"] == {
        "pending_tasks": 0,
        "pending_task_titles": [],
        "in_progress_tasks": 0,
        "overdue_tasks": 0,
        "active_goals": 0,
        "dnd_pending": 0,
        "dead_letter_backlog": 0,
        "week1_top_tasks": 0,
        "week1_task_titles": [],
        "week1_completed_stages": [],
        "week1_next_stage": "fan_shortlist",
        "week1_procurement_prerequisite_pending": 0,
        "autonomy_work_jar_items": 0,
        "autonomy_work_jar_titles": [],
        "task_state_sync_monitor_items": 0,
        "task_state_sync_monitor_titles": [],
        "task_state_sync_monitor_task_ids": [],
    }
    manager.run_reflection_cycle.assert_not_awaited()
    assert saved_state["active_window_reflections"] == 0


def test_active_autonomy_cycle_runs_reflection_when_actionable_work_exists(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 1, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 22, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 22, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "reflection_internal_on_actionable_surface"
    assert result["reflection_outcome"] == "internal"
    assert result["actionable_surface"]["pending_tasks"] == 1
    manager.run_reflection_cycle.assert_awaited_once()
    assert saved_state["active_window_reflections"] == 0


def test_active_autonomy_cycle_consumes_reflection_slot_for_action_outcome(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 1, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 22, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 22, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="action", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "action_executed"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "reflection_executed"
    assert result["reflection_outcome"] == "action"
    assert result["actionable_surface"]["pending_tasks"] == 1
    manager.run_reflection_cycle.assert_awaited_once()
    assert saved_state["active_window_reflections"] == 1


def test_startup_active_cycle_skips_reflection_when_no_actionable_work(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
        is_within_active_hours=lambda: True,
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 23, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 23, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="startup", force=False))

    assert result["reflection_reason"] == "autonomy_no_actionable_work"
    assert result["reflection_outcome"] is None
    assert result["actionable_surface"]["dead_letter_backlog"] == 0
    manager.run_reflection_cycle.assert_not_awaited()
    assert saved_state["active_window_reflections"] == 0


def test_startup_active_cycle_does_not_consume_regular_active_window_budgets(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
        is_within_active_hours=lambda: True,
    )
    manager.mcp = MagicMock()
    manager.mcp.get_status = MagicMock(
        return_value={
            "servers": {
                "google-workspace": {"running": True, "health": "healthy", "missing_env": []},
                "time": {"running": True, "health": "healthy", "missing_env": []},
            }
        }
    )
    manager.mcp.get_available_tools = MagicMock(return_value={"google-workspace": ["get_events"], "time": ["get_time"]})
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 1, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 41,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "startup_window_reflection_index": -1,
        "startup_window_workflow_index": -1,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 41, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    entry = SimpleNamespace(thought="Inspect the overdue task surface and act on the top item")
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="action", entries=[entry], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "action_executed"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="startup", force=False))

    assert result["reflection_reason"] == "reflection_executed"
    assert result["reflection_outcome"] == "action"
    assert result["workflow_result"]["ok"] is True
    assert saved_state["active_window_reflections"] == 0
    assert saved_state["active_window_workflows"] == 0
    assert saved_state["startup_window_reflection_index"] == 41
    assert saved_state["startup_window_workflow_index"] == 41


def test_startup_active_cycle_is_once_per_window_across_restarts(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
        is_within_active_hours=lambda: True,
    )
    manager.mcp = MagicMock()
    manager.mcp.get_status = MagicMock(
        return_value={
            "servers": {
                "google-workspace": {"running": True, "health": "healthy", "missing_env": []},
                "time": {"running": True, "health": "healthy", "missing_env": []},
            }
        }
    )
    manager.mcp.get_available_tools = MagicMock(return_value={"google-workspace": ["get_events"], "time": ["get_time"]})
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 1, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 42,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "startup_window_reflection_index": 42,
        "startup_window_workflow_index": 42,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 42, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="action", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "action_executed"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="startup", force=False))

    assert result["reflection_reason"] == "startup_window_reflection_already_used"
    assert result["workflow_result"]["reason"] == "workflow_not_attempted"
    manager.run_reflection_cycle.assert_not_awaited()


def test_startup_active_cycle_skips_until_critical_tools_ready(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
        is_within_active_hours=lambda: True,
    )
    manager.mcp = MagicMock()
    manager.mcp.get_status = MagicMock(
        return_value={
            "servers": {
                "google-workspace": {"running": True, "health": "starting", "missing_env": []},
                "time": {"running": True, "health": "healthy", "missing_env": []},
            }
        }
    )
    manager.mcp.get_available_tools = MagicMock(return_value={"google-workspace": [], "time": ["get_time"]})
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 1, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 43,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "startup_window_reflection_index": -1,
        "startup_window_workflow_index": -1,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 43, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="action", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "action_executed"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="startup", force=False))

    assert result["reflection_reason"] == "startup_dependencies_pending"
    assert result["reflection_outcome"] is None
    assert result["workflow_result"]["reason"] == "workflow_not_attempted"
    assert result["calendar_result"]["reason"] == "startup_dependencies_pending"
    assert saved_state["active_window_reflections"] == 0
    assert saved_state["startup_window_reflection_index"] == -1
    manager.run_reflection_cycle.assert_not_awaited()


def test_probe_week1_delivery_dependencies_ready_accepts_effective_runtime_health(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager.mcp = MagicMock()
    manager.mcp.get_status = MagicMock(
        return_value={
            "servers": {
                "call-me": {
                    "running": True,
                    "health": "unknown",
                    "effective_health": "healthy",
                    "starting": True,
                    "runtime_status": {"phase": "ready"},
                    "missing_env": [],
                }
            }
        }
    )
    manager.mcp.get_available_tools = MagicMock(return_value={"call-me": []})

    result = manager._probe_week1_delivery_dependencies_ready()

    assert result["ready"] is True
    assert result["reason"] == "ready"
    assert result["pending_servers"] == []
    assert result["missing_tools"] == {}


def test_probe_week1_delivery_dependencies_ready_blocks_when_call_me_not_running(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager.mcp = MagicMock()
    manager.mcp.get_status = MagicMock(
        return_value={
            "servers": {
                "call-me": {
                    "running": False,
                    "health": "unknown",
                    "effective_health": "unknown",
                    "runtime_status": {"phase": "starting"},
                    "missing_env": [],
                }
            }
        }
    )
    manager.mcp.get_available_tools = MagicMock(return_value={"call-me": ["send_native_push", "send_mobile_push", "initiate_call"]})

    result = manager._probe_week1_delivery_dependencies_ready()

    assert result["ready"] is False
    assert result["reason"] == "delivery_dependencies_pending"
    assert result["pending_servers"] == ["call-me"]


def test_active_autonomy_cycle_executes_explicit_autonomy_work_without_reflection(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
        is_within_active_hours=lambda: True,
    )
    manager.mcp = MagicMock()
    manager.mcp.get_status = MagicMock(
        return_value={
            "servers": {
                "google-workspace": {"running": True, "health": "healthy", "missing_env": []},
                "time": {"running": True, "health": "healthy", "missing_env": []},
            }
        }
    )
    manager.mcp.get_available_tools = MagicMock(return_value={"google-workspace": ["get_events"], "time": ["get_time"]})
    completed_task = SimpleNamespace(
        id="TASK-300",
        status=TaskStatus.COMPLETED,
        title="Research repo autonomy surface memo",
        description="Top 3 applicable patterns. Source references. Recommended next experiment.",
        notes="ready",
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.master_list.get_by_id = MagicMock(return_value=completed_task)
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 50,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "startup_window_reflection_index": -1,
        "startup_window_workflow_index": -1,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 50, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={"ok": True, "status": "completed", "task_id": "TASK-300", "reason": "action_executed"}
    )
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False
    manager._save_autonomy_work_jar(
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_1",
                    "title": "Review Research_Repo for one autonomy-surface expansion Vera can adopt next",
                    "objective": "Produce a short memo with top 3 applicable patterns, source references, and one recommended next experiment.",
                    "context": "Primary local source: /media/nizbot-macmini/F040-0608/Research_Repo",
                    "source": "test",
                    "priority": "high",
                    "tool_choice": "none",
                    "status": "pending",
                    "next_eligible_utc": "",
                    "retry_count": 0,
                    "created_at_utc": "2026-03-22T00:00:00Z",
                    "updated_at_utc": "2026-03-22T00:00:00Z",
                    "last_attempt_utc": "",
                    "completion_contract": {
                        "kind": "task_artifact_markers",
                        "match_mode": "all",
                        "required_markers": ["top 3 applicable patterns", "source references", "recommended next experiment"],
                    },
                    "metadata": {},
                }
            ],
            "updated_at_utc": "2026-03-22T00:00:00Z",
        }
    )

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "autonomy_work_jar_direct_workflow"
    assert result["reflection_outcome"] is None
    assert result["workflow_result"]["ok"] is True
    assert result["workflow_result"]["fallback_reason"] == "autonomy_work_jar"
    assert result["workflow_result"]["state_sync_verifier"]["ok"] is True
    assert result["workflow_result"]["state_sync_verifier"]["autonomy_work_item_status"] == "completed"
    assert manager._execute_inner_action_workflow.await_args.kwargs["tool_choice"] == "none"
    manager.run_reflection_cycle.assert_not_awaited()
    assert saved_state["active_window_reflections"] == 0
    assert saved_state["active_window_workflows"] == 1
    saved_jar = manager._load_autonomy_work_jar()
    assert saved_jar["items"] == []
    assert saved_jar["archived_items"][0]["id"] == "awj_1"


def test_startup_reflection_error_does_not_consume_startup_budget(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager.session_start = datetime.now()
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
        is_within_active_hours=lambda: True,
    )
    manager.mcp = MagicMock()
    manager.mcp.get_status = MagicMock(
        return_value={
            "servers": {
                "google-workspace": {"running": True, "health": "healthy", "missing_env": []},
                "time": {"running": True, "health": "healthy", "missing_env": []},
            }
        }
    )
    manager.mcp.get_available_tools = MagicMock(return_value={"google-workspace": ["get_events"], "time": ["get_time"]})
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 1, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 44,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "startup_window_reflection_index": -1,
        "startup_window_workflow_index": -1,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 44, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(
        return_value=SimpleNamespace(
            outcome="error",
            error="reflection_turn_timeout:75s",
            entries=[],
            run_id="run-test",
        )
    )
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "action_executed"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="startup", force=False))

    assert result["reflection_reason"] == "reflection_error_runtime_warmup"
    assert result["reflection_outcome"] == "error"
    assert result["reflection_error"] == "reflection_turn_timeout:75s"
    assert result["reflection_error_classification"] == "runtime_warmup"
    assert result["workflow_result"]["reason"] == "workflow_not_attempted"
    assert saved_state["startup_window_reflection_index"] == -1
    assert saved_state["active_window_reflections"] == 0
    manager._execute_inner_action_workflow.assert_not_awaited()
    assert saved_state["active_window_reflections"] == 0
    assert saved_state["active_window_workflows"] == 0


def test_startup_reflection_timeout_after_warmup_stays_plain_error(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager.session_start = datetime.now() - timedelta(minutes=10)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
        is_within_active_hours=lambda: True,
    )
    manager.mcp = MagicMock()
    manager.mcp.get_status = MagicMock(
        return_value={
            "servers": {
                "google-workspace": {"running": True, "health": "healthy", "missing_env": [], "starting": False},
                "time": {"running": True, "health": "healthy", "missing_env": [], "starting": False},
            }
        }
    )
    manager.mcp.get_available_tools = MagicMock(return_value={"google-workspace": ["get_events"], "time": ["get_time"]})
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 1, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 45,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "startup_window_reflection_index": -1,
        "startup_window_workflow_index": -1,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 45, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(
        return_value=SimpleNamespace(
            outcome="error",
            error="reflection_turn_timeout:75s",
            entries=[],
            run_id="run-test",
        )
    )
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "action_executed"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="startup", force=False))

    assert result["reflection_reason"] == "reflection_error"
    assert result["reflection_error_classification"] == "steady_state"
    assert result["reflection_error"] == "reflection_turn_timeout:75s"


def test_active_autonomy_cycle_treats_recent_week1_top_tasks_as_actionable(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(
        return_value=[
            {
                "job_id": "executor.week1",
                "result": {
                    "top_tasks": [
                        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                        "[P2] Call contractor for remodel (scope + next steps)",
                    ]
                },
            }
        ]
    )
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 31, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 31, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "reflection_internal_on_actionable_surface"
    assert result["actionable_surface"]["week1_top_tasks"] == 2
    assert result["actionable_surface"]["week1_task_titles"] == [
        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
        "[P2] Call contractor for remodel (scope + next steps)",
    ]
    assert result["actionable_surface"]["week1_completed_stages"] == []
    assert result["actionable_surface"]["week1_next_stage"] == "fan_shortlist"
    stage_state = json.loads(manager._week1_progress_state_path.read_text(encoding="utf-8"))
    assert stage_state["stages"]["fan_shortlist"]["done"] is False
    manager.run_reflection_cycle.assert_awaited_once()


def test_active_autonomy_cycle_uses_structured_week1_schedule_when_recent_run_summary_is_empty(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    (Path(tmp_path) / "week1_task_schedule.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "parent_title": "[P2] Call contractor for remodel (scope + next steps)",
                        "scheduled_local": "2099-03-27T18:30:00-05:00",
                        "priority": "P2",
                    },
                    {
                        "parent_title": "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                        "scheduled_local": "2099-03-27T19:30:00-05:00",
                        "priority": "P2",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 31, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 31, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["actionable_surface"]["week1_top_tasks"] == 2
    assert result["actionable_surface"]["week1_task_titles"] == [
        "[P2] Call contractor for remodel (scope + next steps)",
        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
    ]
    assert result["actionable_surface"]["week1_next_stage"] == "fan_shortlist"


def test_active_autonomy_cycle_executes_week1_ops_backlog_when_stage_chain_is_complete(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager._save_week1_progress_state(
        {
            "stages": {
                "fan_shortlist": {"done": True},
                "contractor_brief": {"done": True},
                "pressure_wash_plan": {"done": True},
                "contractor_outreach": {"done": True},
                "procurement_packet": {"done": True},
            }
        }
    )
    (Path(tmp_path) / "week1_task_schedule.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "parent_title": "[P2] Contact a landscaper about fixing the yard and preventing further damage",
                        "scheduled_local": "2026-03-27T18:30:00-05:00",
                        "priority": "P2",
                    },
                    {
                        "parent_title": "[P2] Cut grass front/back; clean up leaves; make yard presentable",
                        "scheduled_local": "2026-03-27T19:30:00-05:00",
                        "priority": "P2",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 31, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 31, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={"ok": True, "status": "completed", "task_id": "TASK-OPS"}
    )
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "week1_ops_backlog_direct_workflow"
    assert result["actionable_surface"]["week1_ops_backlog_items"] == 2
    manager._execute_inner_action_workflow.assert_awaited_once()


def test_week1_ops_backlog_candidate_skips_item_on_cooldown(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    (Path(tmp_path) / "week1_task_schedule.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "parent_title": "[P2] Contact a landscaper about fixing the yard and preventing further damage",
                        "scheduled_local": "2026-03-27T18:30:00-05:00",
                        "priority": "P2",
                        "start_step": "Gather photos and identify 3 local landscapers",
                    },
                    {
                        "parent_title": "[P2] Cut grass front/back; clean up leaves; make yard presentable",
                        "scheduled_local": "2026-03-27T19:30:00-05:00",
                        "priority": "P2",
                        "start_step": "Pick mower setup and the first cleanup zone",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manager._save_week1_ops_backlog_state(
        {
            "items": {
                "[P2] Contact a landscaper about fixing the yard and preventing further damage": {
                    "next_eligible_utc": (_utc_now() + timedelta(minutes=45)).isoformat().replace("+00:00", "Z"),
                    "last_status": "blocked",
                    "last_task_id": "TASK-OLD",
                    "last_reason": "missing contact info",
                }
            }
        }
    )

    candidate = manager._select_week1_ops_backlog_candidate(
        {
            "week1_task_titles": [
                "[P2] Contact a landscaper about fixing the yard and preventing further damage",
                "[P2] Cut grass front/back; clean up leaves; make yard presentable",
            ]
        }
    )

    assert candidate["title"] == "[P2] Cut grass front/back; clean up leaves; make yard presentable"


def test_week1_ops_backlog_candidate_skips_item_awaiting_human_followthrough(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    (Path(tmp_path) / "week1_task_schedule.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "parent_title": "[P2] Contact a landscaper about fixing the yard and preventing further damage",
                        "scheduled_local": "2099-03-27T18:30:00-05:00",
                        "priority": "P2",
                        "start_step": "Gather photos and identify 3 local landscapers",
                    },
                    {
                        "parent_title": "[P2] Cut grass front/back; clean up leaves; make yard presentable",
                        "scheduled_local": "2026-03-27T19:30:00-05:00",
                        "priority": "P2",
                        "start_step": "Pick mower setup and the first cleanup zone",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manager._save_week1_ops_backlog_state(
        {
            "items": {
                "[P2] Contact a landscaper about fixing the yard and preventing further damage": {
                    "next_eligible_utc": "2099-03-27T23:30:00Z",
                    "resume_after_utc": "2099-03-27T23:30:00Z",
                    "awaiting_human_followthrough": True,
                    "last_status": "completed",
                    "last_task_id": "TASK-OLD",
                    "last_reason": "prep packet complete",
                }
            }
        }
    )

    candidate = manager._select_week1_ops_backlog_candidate(
        {
            "week1_task_titles": [
                "[P2] Contact a landscaper about fixing the yard and preventing further damage",
                "[P2] Cut grass front/back; clean up leaves; make yard presentable",
            ]
        }
    )

    assert candidate["title"] == "[P2] Cut grass front/back; clean up leaves; make yard presentable"


def test_execute_week1_ops_backlog_workflow_persists_cooldown_and_context(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    (Path(tmp_path) / "week1_task_schedule.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "parent_title": "[P2] Contact a landscaper about fixing the yard and preventing further damage",
                        "scheduled_local": "2026-03-27T18:30:00-05:00",
                        "priority": "P2",
                        "category": "Exterior / yard",
                        "focus_slot": "13:30",
                        "start_step": "Gather photos and identify 3 local landscapers",
                        "notes": "yard damage prevention",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={"ok": False, "status": "blocked", "task_id": "TASK-BLOCK", "reason": "missing_vendor_contacts"}
    )

    result = asyncio.run(
        manager._execute_week1_ops_backlog_fallback_workflow(
            {"week1_task_titles": ["[P2] Contact a landscaper about fixing the yard and preventing further damage"]},
            run_id="test:week1_ops_backlog",
        )
    )

    assert result["fallback_reason"] == "week1_ops_backlog"
    assert result["week1_primary_target"] == "[P2] Contact a landscaper about fixing the yard and preventing further damage"
    assert "Gather photos and identify 3 local landscapers" in result["week1_ops_backlog_context"]["context"]
    state = manager._load_week1_ops_backlog_state()
    item_state = state["items"]["[P2] Contact a landscaper about fixing the yard and preventing further damage"]
    assert item_state["last_status"] == "blocked"
    assert item_state["last_task_id"] == "TASK-BLOCK"


def test_execute_week1_ops_backlog_workflow_marks_completed_future_item_awaiting_followthrough(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    (Path(tmp_path) / "week1_task_schedule.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "parent_title": "[P2] Pressure wash exterior surfaces (plan scope and sequence)",
                        "scheduled_local": "2099-04-05T13:30:00-05:00",
                        "priority": "P2",
                        "category": "Exterior / yard",
                        "focus_slot": "13:30",
                        "start_step": "Walk the target area and list the first visible quick win",
                        "notes": "pressure wash planning",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={"ok": True, "status": "completed", "task_id": "TASK-DONE", "response_preview": "prep artifact complete"}
    )

    result = asyncio.run(
        manager._execute_week1_ops_backlog_fallback_workflow(
            {"week1_task_titles": ["[P2] Pressure wash exterior surfaces (plan scope and sequence)"]},
            run_id="test:week1_ops_backlog",
        )
    )

    assert result["fallback_reason"] == "week1_ops_backlog"
    state = manager._load_week1_ops_backlog_state()
    item_state = state["items"]["[P2] Pressure wash exterior surfaces (plan scope and sequence)"]
    assert item_state["last_status"] == "completed"
    assert item_state["last_task_id"] == "TASK-DONE"
    assert item_state["awaiting_human_followthrough"] is True
    assert item_state["resume_after_utc"] == "2099-04-05T18:30:00Z"


def test_active_autonomy_cycle_reports_workflow_cap_before_week1_ops_backlog_direct_branch(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    (Path(tmp_path) / "week1_task_schedule.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "parent_title": "[P2] Contact a landscaper about fixing the yard and preventing further damage",
                        "scheduled_local": "2026-03-27T18:30:00-05:00",
                        "priority": "P2",
                    },
                    {
                        "parent_title": "[P2] Cut grass front/back; clean up leaves; make yard presentable",
                        "scheduled_local": "2026-03-27T19:30:00-05:00",
                        "priority": "P2",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 31, "active_window_reflections": 0, "active_window_workflows": 1}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 31, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "should_not_run"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False
    manager._save_week1_progress_state(
        {
            "version": 1,
            "stages": {
                "fan_shortlist": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-013", "source": "test"},
                "contractor_brief": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-014", "source": "test"},
                "pressure_wash_plan": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-015", "source": "test"},
                "contractor_outreach": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-016", "source": "test"},
                "procurement_packet": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-017", "source": "test"},
            },
            "updated_at_utc": "2026-03-20T00:00:00Z",
        }
    )

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "workflow_window_cap_reached_on_actionable_surface"
    assert result["workflow_result"]["reason"] == "workflow_window_cap_reached_on_actionable_surface"
    manager.run_reflection_cycle.assert_not_awaited()
    manager._execute_inner_action_workflow.assert_not_awaited()
    assert saved_state["active_window_workflows"] == 1


def test_active_autonomy_cycle_ignores_week1_ops_backlog_when_all_visible_items_are_awaiting_followthrough(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    (Path(tmp_path) / "week1_task_schedule.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "parent_title": "[P2] Contact a landscaper about fixing the yard and preventing further damage",
                        "scheduled_local": "2099-04-03T13:30:00-05:00",
                        "priority": "P2",
                    },
                    {
                        "parent_title": "[P2] Cut grass front/back; clean up leaves; make yard presentable",
                        "scheduled_local": "2099-04-04T13:30:00-05:00",
                        "priority": "P2",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manager._save_week1_ops_backlog_state(
        {
            "items": {
                "[P2] Contact a landscaper about fixing the yard and preventing further damage": {
                    "next_eligible_utc": "2099-04-03T18:30:00Z",
                    "resume_after_utc": "2099-04-03T18:30:00Z",
                    "awaiting_human_followthrough": True,
                    "last_status": "completed",
                    "last_task_id": "TASK-045",
                    "last_reason": "prep artifact complete",
                },
                "[P2] Cut grass front/back; clean up leaves; make yard presentable": {
                    "next_eligible_utc": "2099-04-04T18:30:00Z",
                    "resume_after_utc": "2099-04-04T18:30:00Z",
                    "awaiting_human_followthrough": True,
                    "last_status": "completed",
                    "last_task_id": "TASK-046",
                    "last_reason": "prep artifact complete",
                },
            }
        }
    )
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 31, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 31, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "should_not_run"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False
    manager._save_week1_progress_state(
        {
            "version": 1,
            "stages": {
                "fan_shortlist": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-013", "source": "test"},
                "contractor_brief": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-014", "source": "test"},
                "pressure_wash_plan": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-015", "source": "test"},
                "contractor_outreach": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-016", "source": "test"},
                "procurement_packet": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-017", "source": "test"},
            },
            "updated_at_utc": "2026-03-20T00:00:00Z",
        }
    )

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["actionable_surface"]["week1_ops_backlog_items"] == 0
    assert result["actionable_surface"]["week1_ops_backlog_titles"] == []
    assert result["reflection_reason"] != "week1_ops_backlog_direct_workflow"
    manager._execute_inner_action_workflow.assert_not_awaited()


def test_load_week1_ops_backlog_state_migrates_legacy_completed_rows_to_followthrough_hold(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._save_week1_ops_backlog_state(
        {
            "items": {
                "[P2] Pressure wash exterior surfaces (plan scope and sequence)": {
                    "next_eligible_utc": "2099-04-05T18:30:00Z",
                    "last_status": "completed",
                    "last_task_id": "TASK-047",
                    "last_reason": "prep artifact complete",
                }
            }
        }
    )

    state = manager._load_week1_ops_backlog_state()
    row = state["items"]["[P2] Pressure wash exterior surfaces (plan scope and sequence)"]

    assert row["awaiting_human_followthrough"] is True
    assert row["resume_after_utc"] == "2099-04-05T18:30:00Z"



def test_active_autonomy_cycle_falls_back_to_week1_surface_action_when_reflection_stays_internal(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Reviewed task surface via multiple memory tools",
                notes="Used brave_web_search to compile current ENERGY STAR/DC-motor options for energy-efficient ceiling fans with LED lights.",
                description="Compiled fan and light shortlist inputs.",
            )
        ]
    )
    manager.master_list.get_by_id = MagicMock(
        return_value=SimpleNamespace(
            id="TASK-777",
            status=TaskStatus.COMPLETED,
            title="Prepared remodel contractor call brief",
            notes="Contractor call brief with scope bullets, questions for contractor, and dependencies: permits, sequencing, materials.",
            description="Remodel call prep complete.",
        )
    )
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(
        return_value=[
            {
                "job_id": "executor.week1",
                "result": {
                    "top_tasks": [
                        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                        "[P2] Call contractor for remodel (scope + next steps)",
                    ]
                },
            }
        ]
    )
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 32, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 32, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "action_executed", "task_id": "TASK-777", "status": "completed"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "reflection_internal_on_actionable_surface"
    assert result["workflow_result"]["ok"] is True
    assert result["workflow_result"]["fallback_reason"] == "week1_surface_default_action"
    assert result["workflow_result"]["week1_stage"] == "contractor_brief"
    manager._execute_inner_action_workflow.assert_awaited_once()
    action_text = manager._execute_inner_action_workflow.await_args.kwargs["action_text"]
    assert "contractor call brief" in action_text.lower()
    assert "Call contractor for remodel" in action_text
    assert saved_state["active_window_workflows"] == 1
    stage_state = json.loads(manager._week1_progress_state_path.read_text(encoding="utf-8"))
    assert stage_state["stages"]["contractor_brief"]["done"] is True


def test_active_autonomy_cycle_falls_back_to_week1_surface_action_when_reflection_reaches_out(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(
        return_value=[
            {
                "job_id": "executor.week1",
                "result": {
                    "top_tasks": [
                        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                        "[P2] Call contractor for remodel (scope + next steps)",
                    ]
                },
            }
        ]
    )
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 33, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 33, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="reached_out", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "action_executed"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "reflection_reached_out_on_actionable_surface"
    assert result["workflow_result"]["ok"] is True
    assert result["workflow_result"]["fallback_reason"] == "week1_surface_default_action"
    assert result["workflow_result"]["week1_stage"] == "fan_shortlist"
    manager._execute_inner_action_workflow.assert_awaited_once()
    assert saved_state["active_window_reflections"] == 0
    assert saved_state["active_window_workflows"] == 1


def test_active_autonomy_cycle_uses_workflow_reserve_for_week1_fallback(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager._budget_guard = SimpleNamespace(
        _refresh_config=lambda: None,
        config=SimpleNamespace(daily_call_budget=64),
        _load_state=lambda: {"calls": 60},
    )
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Prepared remodel contractor call brief",
                notes="Contractor call brief with scope bullets, dependencies, and questions for contractor.",
                description="Brief complete.",
            ),
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Built fan shortlist",
                notes="Concrete shortlist for ceiling fan replacements with candidate replacements and recommended first pick.",
                description="Shortlist complete.",
            ),
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Built pressure wash plan",
                notes="Pressure wash plan with order of operations, supplies list, safety checklist, and cleanup checklist.",
                description="Plan complete.",
            ),
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Turned contractor brief into outreach-ready package",
                notes="Contractor outreach draft, call agenda, and send-ready checklist complete.",
                description="Outreach package complete.",
            ),
        ]
    )
    manager.master_list.get_by_id = MagicMock(
        return_value=SimpleNamespace(
            id="TASK-900",
            status=TaskStatus.COMPLETED,
            title="Turn the existing Week1 fan/light shortlist into a procurement-ready packet",
            notes="Completed procurement packet with buy-list table and missing-information checklist.",
            description="Buy-list table for fixtures plus missing-information checklist for remaining unknowns.",
        )
    )
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(
        return_value=[
            {
                "job_id": "executor.week1",
                "result": {
                    "top_tasks": [
                        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                        "[P2] Call contractor for remodel (scope + next steps)",
                        "[P2] Pressure wash exterior surfaces (plan scope and sequence)",
                    ]
                },
            }
        ]
    )
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 35, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 35, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "action_executed", "task_id": "TASK-900"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    with patch.dict(os.environ, {"VERA_AUTONOMY_WORKFLOW_CALL_RESERVE": "8"}):
        result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "workflow_call_reserve_active"
    assert result["workflow_result"]["ok"] is True
    assert result["workflow_result"]["week1_stage"] == "procurement_packet"
    assert result["workflow_result"]["fallback_reason"] == "week1_surface_default_action"
    manager.run_reflection_cycle.assert_not_awaited()
    manager._execute_inner_action_workflow.assert_awaited_once()
    action_text = manager._execute_inner_action_workflow.await_args.kwargs["action_text"]
    assert "procurement-ready packet" in action_text
    assert saved_state["active_window_workflows"] == 1
    stage_state = json.loads(manager._week1_progress_state_path.read_text(encoding="utf-8"))
    assert stage_state["stages"]["procurement_packet"]["done"] is True
    assert result["workflow_result"]["completion_evaluation"]["satisfied"] is True
    assert result["workflow_result"]["stage_advanced"] is True


def test_active_autonomy_cycle_does_not_advance_week1_stage_when_fallback_blocks(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager._budget_guard = SimpleNamespace(
        _refresh_config=lambda: None,
        config=SimpleNamespace(daily_call_budget=64),
        _load_state=lambda: {"calls": 60},
    )
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(updated=datetime.now(), status=TaskStatus.COMPLETED, title="Built fan shortlist", notes="Concrete shortlist for ceiling fan replacements with candidate replacements and recommended first pick.", description="Shortlist complete."),
            SimpleNamespace(updated=datetime.now(), status=TaskStatus.COMPLETED, title="Prepared remodel contractor call brief", notes="Contractor call brief with scope bullets, dependencies, and questions for contractor.", description="Brief complete."),
            SimpleNamespace(updated=datetime.now(), status=TaskStatus.COMPLETED, title="Built pressure wash plan", notes="Pressure wash plan with order of operations, supplies list, safety checklist, and cleanup checklist.", description="Plan complete."),
            SimpleNamespace(updated=datetime.now(), status=TaskStatus.COMPLETED, title="Turned contractor brief into outreach-ready package", notes="Contractor outreach draft, call agenda, and send-ready checklist complete.", description="Outreach package complete."),
        ]
    )
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(
        return_value=[
            {
                "job_id": "executor.week1",
                "result": {
                    "top_tasks": [
                        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                        "[P2] Call contractor for remodel (scope + next steps)",
                        "[P2] Pressure wash exterior surfaces (plan scope and sequence)",
                    ]
                },
            }
        ]
    )
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 36, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 36, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={
            "ok": False,
            "reason": "blocked",
            "status": "blocked",
            "task_id": "TASK-901",
            "response_preview": "**BLOCKED:** Missing inventory.",
        }
    )
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    with patch.dict(os.environ, {"VERA_AUTONOMY_WORKFLOW_CALL_RESERVE": "8"}):
        result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "workflow_call_reserve_active"
    assert result["workflow_result"]["ok"] is False
    assert result["workflow_result"]["status"] == "blocked"
    stage_state = json.loads(manager._week1_progress_state_path.read_text(encoding="utf-8"))
    assert stage_state["stages"]["procurement_packet"]["done"] is False


def test_active_autonomy_cycle_does_not_advance_week1_stage_when_completion_contract_unsatisfied(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager._budget_guard = SimpleNamespace(
        _refresh_config=lambda: None,
        config=SimpleNamespace(daily_call_budget=64),
        _load_state=lambda: {"calls": 60},
    )
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(updated=datetime.now(), status=TaskStatus.COMPLETED, title="Built fan shortlist", notes="Concrete shortlist for ceiling fan replacements with candidate replacements and recommended first pick.", description="Shortlist complete."),
            SimpleNamespace(updated=datetime.now(), status=TaskStatus.COMPLETED, title="Prepared remodel contractor call brief", notes="Contractor call brief with scope bullets, dependencies, and questions for contractor.", description="Brief complete."),
            SimpleNamespace(updated=datetime.now(), status=TaskStatus.COMPLETED, title="Built pressure wash plan", notes="Pressure wash plan with order of operations, supplies list, safety checklist, and cleanup checklist.", description="Plan complete."),
            SimpleNamespace(updated=datetime.now(), status=TaskStatus.COMPLETED, title="Turned contractor brief into outreach-ready package", notes="Contractor outreach draft, call agenda, and send-ready checklist complete.", description="Outreach package complete."),
        ]
    )
    manager.master_list.get_by_id = MagicMock(
        return_value=SimpleNamespace(
            id="TASK-902",
            status=TaskStatus.COMPLETED,
            title="Turn the existing Week1 fan/light shortlist into a procurement-ready packet",
            notes="Completed a partial procurement draft without the required packet structure.",
            description="Fixture summary only.",
        )
    )
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(
        return_value=[
            {
                "job_id": "executor.week1",
                "result": {
                    "top_tasks": [
                        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                        "[P2] Call contractor for remodel (scope + next steps)",
                        "[P2] Pressure wash exterior surfaces (plan scope and sequence)",
                    ]
                },
            }
        ]
    )
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 37, "active_window_reflections": 0, "active_window_workflows": 0}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 37, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={
            "ok": True,
            "status": "completed",
            "task_id": "TASK-902",
            "response_preview": "COMPLETED: Partial procurement draft.",
        }
    )
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    with patch.dict(os.environ, {"VERA_AUTONOMY_WORKFLOW_CALL_RESERVE": "8"}):
        result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["workflow_result"]["ok"] is True
    assert result["workflow_result"]["status"] == "completed"
    assert result["workflow_result"]["completion_evaluation"]["satisfied"] is False
    assert result["workflow_result"]["completion_evaluation"]["reason"] == "missing_required_markers"
    assert result["workflow_result"]["stage_advanced"] is False
    assert result["workflow_result"]["reason"] == "missing_required_markers"
    stage_state = json.loads(manager._week1_progress_state_path.read_text(encoding="utf-8"))
    assert stage_state["stages"]["procurement_packet"]["done"] is False


def test_active_autonomy_cycle_skips_reflection_when_workflow_cap_already_spent_on_actionable_surface(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(
        return_value=[
            {
                "job_id": "executor.week1",
                "result": {
                    "top_tasks": [
                        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                        "[P2] Call contractor for remodel (scope + next steps)",
                    ]
                },
            }
        ]
    )
    saved_state: Dict[str, Any] = {}
    state = {"window_index": 34, "active_window_reflections": 0, "active_window_workflows": 1}
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 34, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "should_not_run"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False
    manager._save_week1_progress_state(
        {
            "version": 1,
            "stages": {
                "fan_shortlist": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-013", "source": "test"},
                "contractor_brief": {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""},
                "pressure_wash_plan": {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""},
                "contractor_outreach": {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""},
                "procurement_packet": {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""},
            },
            "updated_at_utc": "2026-03-20T00:00:00Z",
        }
    )

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "workflow_window_cap_reached_on_actionable_surface"
    assert result["reflection_outcome"] is None
    assert result["workflow_result"]["reason"] == "workflow_window_cap_reached_on_actionable_surface"
    manager.run_reflection_cycle.assert_not_awaited()
    manager._execute_inner_action_workflow.assert_not_awaited()
    assert saved_state["active_window_reflections"] == 0
    assert saved_state["active_window_workflows"] == 1


def test_week1_surface_fallback_prefers_unfinished_pressure_wash_plan(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Prepared remodel contractor call brief",
                notes="Scope bullets, contractor call brief, dependencies, and questions for contractor are complete.",
                description="Contractor scope ready.",
            ),
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Built fan shortlist",
                notes="Concrete shortlist for ceiling fan replacements with candidate replacements and recommended first pick.",
                description="Fan shortlist ready.",
            ),
        ]
    )

    action_text = manager._build_week1_surface_fallback_action(
        {
            "week1_task_titles": [
                "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                "[P2] Call contractor for remodel (scope + next steps)",
                "[P2] Pressure wash exterior surfaces (plan scope and sequence)",
            ]
        }
    )

    assert "pressure-wash item into a concrete work plan" in action_text
    assert "Primary target: [P2] Pressure wash exterior surfaces (plan scope and sequence)" in action_text


def test_week1_surface_fallback_advances_to_outreach_package_after_core_artifacts(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Prepared remodel contractor call brief",
                notes="Contractor call brief with scope bullets, dependencies, and questions for contractor.",
                description="Brief complete.",
            ),
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Built fan shortlist",
                notes="Concrete shortlist for ceiling fan replacements with candidate replacements and recommended first pick.",
                description="Shortlist complete.",
            ),
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Built pressure wash plan",
                notes="Pressure wash plan with order of operations, supplies list, safety checklist, and cleanup checklist.",
                description="Plan complete.",
            ),
        ]
    )

    action_text = manager._build_week1_surface_fallback_action(
        {
            "week1_task_titles": [
                "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                "[P2] Call contractor for remodel (scope + next steps)",
                "[P2] Pressure wash exterior surfaces (plan scope and sequence)",
            ]
        }
    )

    assert "outreach-ready package" in action_text
    assert "Draft one concise outreach message" in action_text
    assert "Primary target: [P2] Call contractor for remodel (scope + next steps)" in action_text


def test_week1_surface_fallback_uses_persisted_stage_state_to_skip_completed_steps(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.parse = MagicMock(return_value=[])
    manager._save_week1_progress_state(
        {
            "version": 1,
            "stages": {
                "fan_shortlist": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-013", "source": "test"},
                "contractor_brief": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-006", "source": "test"},
                "pressure_wash_plan": {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""},
                "contractor_outreach": {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""},
                "procurement_packet": {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""},
            },
            "updated_at_utc": "2026-03-20T00:00:00Z",
        }
    )

    plan = manager._select_week1_surface_fallback(
        {
            "week1_task_titles": [
                "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                "[P2] Call contractor for remodel (scope + next steps)",
                "[P2] Pressure wash exterior surfaces (plan scope and sequence)",
            ]
        }
    )

    assert plan["stage"] == "pressure_wash_plan"
    assert "pressure-wash item into a concrete work plan" in plan["action_text"]


def test_week1_surface_fallback_prefers_procurement_prerequisite_when_pending(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.parse = MagicMock(return_value=[])
    manager._save_week1_progress_state(
        {
            "version": 1,
            "stages": {
                "fan_shortlist": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-013", "source": "test"},
                "contractor_brief": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-006", "source": "test"},
                "pressure_wash_plan": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-008", "source": "test"},
                "contractor_outreach": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-015", "source": "test"},
                "procurement_packet": {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""},
            },
            "updated_at_utc": "2026-03-20T00:00:00Z",
        }
    )

    plan = manager._select_week1_surface_fallback(
        {
            "week1_task_titles": [
                "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                "[P2] Call contractor for remodel (scope + next steps)",
            ],
            "pending_task_titles": [
                "Build the room-by-room fan/light inventory and missing-spec checklist needed before the Week1 procurement packet",
            ],
            "week1_procurement_prerequisite_pending": 1,
        }
    )

    assert plan["stage"] == "procurement_prerequisite"
    assert "Advance the Week1 procurement prerequisite before retrying the procurement packet" in plan["action_text"]
    assert "room-by-room fan/light inventory template" in plan["action_text"]


def test_week1_surface_fallback_injects_pending_task_context_into_workflow(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(
                id="TASK-016",
                status=TaskStatus.PENDING,
                title="Turn the existing Week1 fan/light shortlist into a procurement-ready packet",
                description="Source artifact: TASK-019\n\n### Room-by-Room Fan/Light Inventory Template\n- Kitchen fan\n- Living room fan",
                notes="UNBLOCKED by Codex loop after prerequisite completion.\n\nUse the materialized inventory context below as the working procurement surface.",
            )
        ]
    )
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={"ok": False, "status": "blocked", "task_id": "TASK-023", "reason": "blocked"}
    )
    manager._save_week1_progress_state(
        {
            "version": 1,
            "stages": {
                "fan_shortlist": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-013", "source": "test"},
                "contractor_brief": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-006", "source": "test"},
                "pressure_wash_plan": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-008", "source": "test"},
                "contractor_outreach": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-015", "source": "test"},
                "procurement_packet": {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""},
            },
            "updated_at_utc": "2026-03-20T00:00:00Z",
        }
    )

    surface = {
        "week1_task_titles": [
            "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
            "[P2] Call contractor for remodel (scope + next steps)",
        ],
        "pending_task_titles": [
            "Turn the existing Week1 fan/light shortlist into a procurement-ready packet",
        ],
        "week1_procurement_prerequisite_pending": 0,
    }

    result = asyncio.run(
        manager._execute_week1_surface_fallback_workflow(surface, run_id="test-run")
    )

    assert result["week1_stage"] == "procurement_packet"
    assert result["week1_surface_task_context"]["task_id"] == "TASK-016"
    manager._execute_inner_action_workflow.assert_awaited_once()
    kwargs = manager._execute_inner_action_workflow.await_args.kwargs
    assert "Room-by-Room Fan/Light Inventory Template" in kwargs["additional_context"]
    assert "TASK-016" in kwargs["additional_context"]


def test_week1_surface_fallback_prefers_existing_pending_task_id_for_workflow(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(
                id="TASK-016",
                status=TaskStatus.PENDING,
                title="Turn the existing Week1 fan/light shortlist into a procurement-ready packet",
                tags=["inner-life", "autonomy", "workflow"],
                description="Source artifact: TASK-019\n\n### Room-by-Room Fan/Light Inventory Template\n- Kitchen fan\n- Living room fan",
                notes="UNBLOCKED by Codex loop after prerequisite completion.",
            )
        ]
    )
    manager.master_list.get_by_id = MagicMock(
        return_value=SimpleNamespace(
            id="TASK-016",
            status=TaskStatus.PENDING,
            title="Turn the existing Week1 fan/light shortlist into a procurement-ready packet",
            tags=["inner-life", "autonomy", "workflow"],
            description="Source artifact: TASK-019\n\n### Room-by-Room Fan/Light Inventory Template\n- Kitchen fan\n- Living room fan",
            notes="UNBLOCKED by Codex loop after prerequisite completion.",
        )
    )
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={"ok": False, "status": "blocked", "task_id": "TASK-016", "reason": "blocked"}
    )
    manager._save_week1_progress_state(
        {
            "version": 1,
            "stages": {
                "fan_shortlist": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-013", "source": "test"},
                "contractor_brief": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-006", "source": "test"},
                "pressure_wash_plan": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-008", "source": "test"},
                "contractor_outreach": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-015", "source": "test"},
                "procurement_packet": {"done": False, "updated_at_utc": "", "source_task_id": "", "source": ""},
            },
            "updated_at_utc": "2026-03-20T00:00:00Z",
        }
    )

    surface = {
        "week1_task_titles": [
            "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
        ],
        "pending_task_titles": [
            "Turn the existing Week1 fan/light shortlist into a procurement-ready packet",
        ],
        "week1_procurement_prerequisite_pending": 0,
    }

    result = asyncio.run(
        manager._execute_week1_surface_fallback_workflow(surface, run_id="test-run")
    )

    assert result["week1_surface_task_context"]["task_id"] == "TASK-016"
    kwargs = manager._execute_inner_action_workflow.await_args.kwargs
    assert kwargs["preferred_task_id"] == "TASK-016"


def test_probe_autonomy_reflection_needed_reconciles_week1_progress_state(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Built fan shortlist",
                notes="Concrete shortlist for ceiling fan replacements with candidate replacements and recommended first pick.",
                description="Shortlist complete.",
            ),
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Prepared remodel contractor call brief",
                notes="Contractor call brief with scope bullets, dependencies, and questions for contractor.",
                description="Brief complete.",
            ),
        ]
    )
    manager.inner_life = SimpleNamespace(_load_goals=lambda: {"goals": []})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(
        return_value=[
            {
                "job_id": "executor.week1",
                "result": {
                    "top_tasks": [
                        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                        "[P2] Call contractor for remodel (scope + next steps)",
                        "[P2] Pressure wash exterior surfaces (plan scope and sequence)",
                    ]
                },
            }
        ]
    )

    result = manager._probe_autonomy_reflection_needed()

    assert result["needed"] is True
    surface = result["surface"]
    assert surface["week1_completed_stages"] == ["fan_shortlist", "contractor_brief"]
    assert surface["week1_next_stage"] == "pressure_wash_plan"


def test_probe_autonomy_reflection_needed_ignores_week1_surface_when_all_stages_complete(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.inner_life = SimpleNamespace(_load_goals=lambda: {"goals": []})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(
        return_value=[
            {
                "job_id": "executor.week1",
                "result": {
                    "top_tasks": [
                        "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                        "[P2] Call contractor for remodel (scope + next steps)",
                    ]
                },
            }
        ]
    )
    manager._save_week1_progress_state(
        {
            "version": 1,
            "stages": {
                "fan_shortlist": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-013", "source": "test"},
                "contractor_brief": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-006", "source": "test"},
                "pressure_wash_plan": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-008", "source": "test"},
                "contractor_outreach": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-015", "source": "test"},
                "procurement_packet": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-016", "source": "test"},
            },
            "updated_at_utc": "2026-03-20T00:00:00Z",
        }
    )

    result = manager._probe_autonomy_reflection_needed()

    assert result["needed"] is False
    assert result["reason"] == "autonomy_no_actionable_work"
    assert result["surface"]["week1_completed_stages"] == [
        "fan_shortlist",
        "contractor_brief",
        "pressure_wash_plan",
        "contractor_outreach",
        "procurement_packet",
    ]
    assert result["surface"]["week1_next_stage"] == ""


def test_select_week1_surface_fallback_returns_empty_when_all_stages_complete(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.parse = MagicMock(return_value=[])
    manager._save_week1_progress_state(
        {
            "version": 1,
            "stages": {
                "fan_shortlist": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-013", "source": "test"},
                "contractor_brief": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-006", "source": "test"},
                "pressure_wash_plan": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-008", "source": "test"},
                "contractor_outreach": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-015", "source": "test"},
                "procurement_packet": {"done": True, "updated_at_utc": "2026-03-20T00:00:00Z", "source_task_id": "TASK-016", "source": "test"},
            },
            "updated_at_utc": "2026-03-20T00:00:00Z",
        }
    )

    surface = {
        "week1_task_titles": [
            "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
            "[P2] Call contractor for remodel (scope + next steps)",
        ],
        "pending_task_titles": [],
        "week1_procurement_prerequisite_pending": 0,
    }

    assert manager._select_week1_surface_fallback(surface) == {}


def test_probe_autonomy_reflection_needed_includes_autonomy_work_jar_items(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.inner_life = SimpleNamespace(_load_goals=lambda: {"goals": []})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    manager._save_autonomy_work_jar(
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_1",
                    "title": "Review Research_Repo for one runtime-hardening pattern worth piloting",
                    "objective": "Produce one concrete next experiment from the local research corpus.",
                    "context": "Research repo path: /media/nizbot-macmini/F040-0608/Research_Repo",
                    "source": "test",
                    "priority": "high",
                    "status": "pending",
                    "next_eligible_utc": "",
                    "retry_count": 0,
                    "created_at_utc": "2026-03-22T00:00:00Z",
                    "updated_at_utc": "2026-03-22T00:00:00Z",
                    "last_attempt_utc": "",
                    "completion_contract": {"kind": "task_completed"},
                    "metadata": {},
                }
            ],
            "updated_at_utc": "2026-03-22T00:00:00Z",
        }
    )

    result = manager._probe_autonomy_reflection_needed()

    assert result["needed"] is True
    assert result["surface"]["autonomy_work_jar_items"] == 1
    assert result["surface"]["autonomy_work_jar_titles"] == [
        "Review Research_Repo for one runtime-hardening pattern worth piloting"
    ]


def test_probe_autonomy_reflection_needed_ignores_stale_blocked_autonomy_workflow_overdue_noise(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 6})
    stale_blocked = SimpleNamespace(
        id="TASK-032",
        status=TaskStatus.BLOCKED,
        title="Advance the highest-priority queued autonomy work item",
        description="Old blocked autonomy workflow",
        notes="historical blocked row",
        tags=["inner-life", "autonomy", "workflow"],
        is_overdue=lambda: True,
    )
    manager.master_list.parse = MagicMock(return_value=[stale_blocked])
    manager.inner_life = SimpleNamespace(_load_goals=lambda: {"goals": []})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])

    result = manager._probe_autonomy_reflection_needed()

    assert result["needed"] is False
    assert result["surface"]["overdue_tasks"] == 0
    assert result["surface"]["pending_tasks"] == 0
    assert result["surface"]["in_progress_tasks"] == 0


def test_probe_autonomy_reflection_needed_includes_surfaced_state_sync_monitor_items(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.master_list.get_by_id = MagicMock(
        return_value=SimpleNamespace(
            id="TASK-901",
            title="Repair recurring state-sync mismatch for queued memo",
            status=TaskStatus.COMPLETED,
            description="completed task",
            notes="note",
        )
    )
    manager.inner_life = SimpleNamespace(_load_goals=lambda: {"goals": []})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    manager._save_state_sync_verifier_state(
        {
            "version": 1,
            "updated_at_utc": "2026-03-26T00:00:00Z",
            "last_cycle_scan_utc": "",
            "verified_tasks": {},
            "pending_followup_task_ids": ["TASK-901"],
            "monitor_candidates": {
                "TASK-901": {
                    "first_seen_utc": "2026-03-26T00:00:00Z",
                    "last_seen_utc": "2026-03-26T00:10:00Z",
                    "consecutive_cycle_scans": 3,
                    "last_reason": "autonomy_work_item_still_actionable",
                    "autonomy_work_item_id": "awj_sync",
                    "week1_stage": "",
                    "task_title": "Repair recurring state-sync mismatch for queued memo",
                    "surfaced": True,
                }
            },
        }
    )

    result = manager._probe_autonomy_reflection_needed()

    assert result["needed"] is True
    assert result["surface"]["task_state_sync_monitor_items"] == 1
    assert result["surface"]["task_state_sync_monitor_task_ids"] == ["TASK-901"]
    assert result["surface"]["task_state_sync_monitor_titles"] == [
        "Repair recurring state-sync mismatch for queued memo"
    ]


def test_refresh_week1_validation_monitor_state_requires_confirmation_cycles(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._autonomy_config = {}
    manager._week1_validation_monitor_path = Path(tmp_path) / "week1_validation_monitor.json"
    manager._collect_recent_week1_validation_signal = lambda **_kwargs: {
        "lookback_hours": 72,
        "recent_event_count": 3,
        "recent_ok_count": 3,
        "recent_failed_count": 0,
        "recent_deferred_count": 0,
        "latest_event_utc": "2026-03-27T01:45:45Z",
        "recent_ack_count": 0,
        "latest_ack_utc": "",
    }

    first = manager._refresh_week1_validation_monitor_state()
    second = manager._refresh_week1_validation_monitor_state()
    third = manager._refresh_week1_validation_monitor_state()

    assert first["due"] is True
    assert first["surfaced"] is False
    assert second["surfaced"] is False
    assert third["surfaced"] is True
    assert third["candidate"]["consecutive_cycle_scans"] == 3


def test_probe_autonomy_reflection_needed_includes_surfaced_week1_validation_monitor_items(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager._week1_validation_monitor_path = Path(tmp_path) / "week1_validation_monitor.json"
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.inner_life = SimpleNamespace(_load_goals=lambda: {"goals": []})
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    manager._refresh_week1_validation_monitor_state = lambda: {
        "due": True,
        "reason": "week1_validation_snapshot_missing",
        "surfaced": True,
        "title": "Produce a Week1 validation snapshot from recent executor and ACK evidence",
        "signal": {},
        "candidate": {"consecutive_cycle_scans": 3},
        "last_snapshot_utc": "",
        "last_snapshot_task_id": "",
    }

    result = manager._probe_autonomy_reflection_needed()

    assert result["needed"] is True
    assert result["surface"]["week1_validation_monitor_items"] == 1
    assert result["surface"]["week1_validation_monitor_titles"] == [
        "Produce a Week1 validation snapshot from recent executor and ACK evidence"
    ]


def test_execute_week1_surface_fallback_uses_autonomy_work_jar_first(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager.master_list = MagicMock()
    completed_task = SimpleNamespace(
        id="TASK-200",
        status=TaskStatus.COMPLETED,
        title="Research repo runtime-hardening pilot",
        description="Top 3 patterns and recommended next experiment.",
        notes="ready",
    )
    manager.master_list.get_by_id = MagicMock(return_value=completed_task)
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={"ok": True, "status": "completed", "task_id": "TASK-200", "reason": "action_executed"}
    )
    manager._save_autonomy_work_jar(
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_1",
                    "title": "Review Research_Repo for one runtime-hardening pattern worth piloting",
                    "objective": "Produce a short memo with top 3 patterns and a recommended next experiment.",
                    "context": "Research repo path: /media/nizbot-macmini/F040-0608/Research_Repo",
                    "source": "test",
                    "priority": "high",
                    "status": "pending",
                    "next_eligible_utc": "",
                    "retry_count": 0,
                    "created_at_utc": "2026-03-22T00:00:00Z",
                    "updated_at_utc": "2026-03-22T00:00:00Z",
                    "last_attempt_utc": "",
                    "completion_contract": {
                        "kind": "task_artifact_markers",
                        "match_mode": "all",
                        "required_markers": ["top 3 patterns", "recommended next experiment"],
                    },
                    "metadata": {},
                }
            ],
            "updated_at_utc": "2026-03-22T00:00:00Z",
        }
    )

    result = asyncio.run(
        manager._execute_week1_surface_fallback_workflow({"week1_task_titles": []}, run_id="test-run")
    )

    assert result["fallback_reason"] == "autonomy_work_jar"
    assert result["autonomy_work_item_id"] == "awj_1"
    assert result["completion_evaluation"]["satisfied"] is True
    assert result["state_sync_verifier"]["ok"] is True
    saved = manager._load_autonomy_work_jar()
    assert saved["items"] == []
    assert saved["archived_items"][0]["id"] == "awj_1"


def test_post_completion_state_sync_verifier_repairs_autonomy_work_item_status(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager.master_list = MagicMock()
    manager.master_list.get_by_id = MagicMock(
        return_value=SimpleNamespace(
            id="TASK-400",
            status=TaskStatus.COMPLETED,
            title="Queued autonomy memo",
            description="Top 3 applicable patterns and recommended next experiment.",
            notes="ready",
        )
    )
    manager._save_autonomy_work_jar(
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_sync",
                    "title": "Queued autonomy memo",
                    "objective": "Memo",
                    "context": "",
                    "source": "test",
                    "priority": "high",
                    "status": "pending",
                    "next_eligible_utc": "",
                    "retry_count": 0,
                    "created_at_utc": "2026-03-22T00:00:00Z",
                    "updated_at_utc": "2026-03-22T00:00:00Z",
                    "last_attempt_utc": "",
                    "completion_contract": {"kind": "task_artifact_markers", "required_markers": ["memo"]},
                    "metadata": {},
                }
            ],
            "updated_at_utc": "2026-03-22T00:00:00Z",
        }
    )

    report = manager._run_post_completion_state_sync_verifier(
        task_id="TASK-400",
        trigger="post_completion",
        autonomy_work_item_id="awj_sync",
        completion_evaluation={"satisfied": True},
    )

    assert report["ok"] is True
    assert report["repaired"] is True
    assert report["autonomy_work_item_status"] == "completed"
    assert report["autonomy_work_item_archived"] is True
    saved = manager._load_autonomy_work_jar()
    assert saved["items"] == []
    assert saved["archived_items"][0]["id"] == "awj_sync"
    assert saved["archived_items"][0]["metadata"]["archive_reason"] == "verified_complete"
    verifier_state = manager._load_state_sync_verifier_state()
    assert verifier_state["pending_followup_task_ids"] == []
    assert verifier_state["verified_tasks"]["TASK-400"]["last_repaired"] is True


def test_post_completion_state_sync_verifier_writes_task_surface_note(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager.master_list = MagicMock()
    task = SimpleNamespace(
        id="TASK-499",
        status=TaskStatus.COMPLETED,
        title="Queued autonomy memo",
        description="verification hook repair write follow-up replay",
        notes="Existing note",
    )
    manager.master_list.get_by_id = MagicMock(return_value=task)
    manager.master_list.update_task = MagicMock(return_value=task)
    manager._save_autonomy_work_jar(
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_note",
                    "title": "Queued autonomy memo",
                    "objective": "Verifier note",
                    "context": "",
                    "source": "test",
                    "priority": "high",
                    "tool_choice": "none",
                    "status": "completed",
                    "next_eligible_utc": "",
                    "retry_count": 0,
                    "created_at_utc": "2026-03-22T00:00:00Z",
                    "updated_at_utc": "2026-03-22T00:00:00Z",
                    "last_attempt_utc": "2026-03-22T00:00:00Z",
                    "completion_contract": {"kind": "task_artifact_markers"},
                    "metadata": {"completed_by_task_id": "TASK-499"},
                }
            ],
            "updated_at_utc": "2026-03-22T00:00:00Z",
        }
    )

    report = manager._run_post_completion_state_sync_verifier(
        task_id="TASK-499",
        trigger="post_completion",
        autonomy_work_item_id="awj_note",
        completion_evaluation={"satisfied": True},
    )

    assert report["ok"] is True
    assert report["task_surface_note_written"] is True
    assert report["autonomy_work_item_archived"] is True
    written_notes = manager.master_list.update_task.call_args.kwargs["notes"]
    assert "[STATE-SYNC-VERIFIED:TASK-499]" in written_notes
    assert "awj=awj_note" in written_notes
    saved = manager._load_autonomy_work_jar()
    assert saved["items"] == []
    assert saved["archived_items"][0]["id"] == "awj_note"


def test_post_completion_state_sync_verifier_repairs_week1_stage(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.get_by_id = MagicMock(
        return_value=SimpleNamespace(
            id="TASK-401",
            status=TaskStatus.COMPLETED,
            title="Built fan shortlist",
            description="Concrete shortlist for ceiling fan replacements.",
            notes="shortlist complete",
        )
    )
    manager._save_week1_progress_state(manager._default_week1_progress_state())

    report = manager._run_post_completion_state_sync_verifier(
        task_id="TASK-401",
        trigger="post_completion",
        week1_stage="fan_shortlist",
        completion_evaluation={"satisfied": True},
    )

    assert report["ok"] is True
    assert report["repaired"] is True
    assert report["week1_stage_done"] is True
    state = manager._load_week1_progress_state()
    assert state["stages"]["fan_shortlist"]["done"] is True


def test_periodic_state_sync_verifier_retries_pending_followup(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager.master_list = MagicMock()
    manager.master_list.get_by_id = MagicMock(
        return_value=SimpleNamespace(
            id="TASK-402",
            status=TaskStatus.COMPLETED,
            title="Queued verifier",
            description="verification pass and repair actions",
            notes="ready",
        )
    )
    manager._save_autonomy_work_jar(
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_retry",
                    "title": "Queued verifier",
                    "objective": "Verifier",
                    "context": "",
                    "source": "test",
                    "priority": "high",
                    "status": "pending",
                    "next_eligible_utc": "",
                    "retry_count": 0,
                    "created_at_utc": "2026-03-22T00:00:00Z",
                    "updated_at_utc": "2026-03-22T00:00:00Z",
                    "last_attempt_utc": "",
                    "completion_contract": {"kind": "task_completed"},
                    "metadata": {},
                }
            ],
            "updated_at_utc": "2026-03-22T00:00:00Z",
        }
    )
    manager._save_state_sync_verifier_state(
        {
            "version": 1,
            "updated_at_utc": "2026-03-22T00:00:00Z",
            "last_cycle_scan_utc": "",
            "verified_tasks": {
                "TASK-402": {
                    "verified_at_utc": "2026-03-22T00:00:00Z",
                    "last_trigger": "post_completion",
                    "autonomy_work_item_id": "awj_retry",
                    "week1_stage": "",
                    "completion_contract_satisfied": True,
                    "last_reason": "autonomy_work_item_still_actionable",
                    "last_ok": False,
                    "last_repaired": False,
                }
            },
            "pending_followup_task_ids": ["TASK-402"],
        }
    )

    summary = manager._run_periodic_state_sync_verifier(limit=3)

    assert summary["attempted"] == 1
    assert summary["verified"] == 1
    assert summary["archived_items"] == 0
    assert summary["remaining_followups"] == 0
    saved = manager._load_autonomy_work_jar()
    assert saved["items"] == []
    assert saved["archived_items"][0]["id"] == "awj_retry"


def test_state_sync_monitor_surfaces_after_three_cycle_scans(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager.master_list = MagicMock()
    task = SimpleNamespace(
        id="TASK-450",
        status=TaskStatus.COMPLETED,
        title="Queued verifier artifact",
        description="verification pass repair actions",
        notes="ready",
    )
    manager.master_list.get_by_id = MagicMock(return_value=task)
    manager.master_list.update_task = MagicMock(return_value=task)
    manager._autonomy_config = {"task_state_sync_monitor_confirmation_cycles": 3}
    post_report = manager._run_post_completion_state_sync_verifier(
        task_id="TASK-450",
        trigger="post_completion",
        autonomy_work_item_id="awj_missing",
        completion_evaluation={"satisfied": True},
    )

    assert post_report["needs_followup"] is True
    assert post_report["monitor_candidate_cycle_scans"] == 0
    assert post_report["monitor_candidate_surfaced"] is False

    summary_one = manager._run_periodic_state_sync_verifier(limit=3)
    summary_two = manager._run_periodic_state_sync_verifier(limit=3)
    summary_three = manager._run_periodic_state_sync_verifier(limit=3)

    assert summary_one["surfaced_monitor_candidates"] == 0
    assert summary_two["surfaced_monitor_candidates"] == 0
    assert summary_three["surfaced_monitor_candidates"] == 1
    state = manager._load_state_sync_verifier_state()
    assert state["monitor_candidates"]["TASK-450"]["consecutive_cycle_scans"] == 3
    assert state["monitor_candidates"]["TASK-450"]["surfaced"] is True


def test_periodic_state_sync_verifier_archives_previously_verified_completed_items(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager.master_list = MagicMock()
    manager._save_autonomy_work_jar(
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_done",
                    "title": "Completed verifier artifact",
                    "objective": "Memo",
                    "context": "",
                    "source": "test",
                    "priority": "high",
                    "status": "completed",
                    "next_eligible_utc": "",
                    "retry_count": 0,
                    "created_at_utc": "2026-03-22T00:00:00Z",
                    "updated_at_utc": "2026-03-22T00:00:00Z",
                    "last_attempt_utc": "2026-03-22T00:00:00Z",
                    "completion_contract": {"kind": "task_completed"},
                    "metadata": {"completed_by_task_id": "TASK-403"},
                }
            ],
            "updated_at_utc": "2026-03-22T00:00:00Z",
        }
    )
    manager._save_state_sync_verifier_state(
        {
            "version": 1,
            "updated_at_utc": "2026-03-22T00:00:00Z",
            "last_cycle_scan_utc": "",
            "verified_tasks": {
                "TASK-403": {
                    "verified_at_utc": "2026-03-22T00:05:00Z",
                    "last_trigger": "post_completion",
                    "autonomy_work_item_id": "awj_done",
                    "week1_stage": "",
                    "completion_contract_satisfied": True,
                    "last_reason": "aligned",
                    "last_ok": True,
                    "last_repaired": False,
                }
            },
            "pending_followup_task_ids": [],
        }
    )

    summary = manager._run_periodic_state_sync_verifier(limit=3)

    assert summary["attempted"] == 0
    assert summary["verified"] == 0
    assert summary["archived_items"] == 1
    saved = manager._load_autonomy_work_jar()
    assert saved["items"] == []
    assert saved["archived_items"][0]["id"] == "awj_done"


def test_active_autonomy_cycle_executes_task_state_sync_monitor_without_reflection(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
        "task_state_sync_monitor_confirmation_cycles": 3,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        _load_goals=lambda: {"goals": []},
        is_within_active_hours=lambda: True,
    )
    manager.mcp = MagicMock()
    manager.mcp.get_status = MagicMock(
        return_value={
            "servers": {
                "google-workspace": {"running": True, "health": "healthy", "missing_env": []},
                "time": {"running": True, "health": "healthy", "missing_env": []},
            }
        }
    )
    manager.mcp.get_available_tools = MagicMock(return_value={"google-workspace": ["get_events"], "time": ["get_time"]})
    original_task = SimpleNamespace(
        id="TASK-901",
        status=TaskStatus.COMPLETED,
        title="Repair recurring state-sync mismatch for queued memo",
        description="completed task",
        notes="done",
    )
    followup_task = SimpleNamespace(
        id="TASK-902",
        status=TaskStatus.COMPLETED,
        title="Resolve recurring post-completion state-sync mismatch",
        description="repair memo",
        notes="done",
    )
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.master_list.get_by_id = MagicMock(side_effect=lambda task_id: original_task if task_id == "TASK-901" else followup_task)
    manager.master_list.update_task = MagicMock(return_value=followup_task)
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 50,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "startup_window_reflection_index": -1,
        "startup_window_workflow_index": -1,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 50, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(
        return_value={"ok": True, "status": "completed", "task_id": "TASK-902", "reason": "action_executed"}
    )
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False
    manager._save_state_sync_verifier_state(
        {
            "version": 1,
            "updated_at_utc": "2026-03-22T00:00:00Z",
            "last_cycle_scan_utc": "",
            "verified_tasks": {
                "TASK-901": {
                    "verified_at_utc": "2026-03-22T00:00:00Z",
                    "last_trigger": "cycle_scan",
                    "autonomy_work_item_id": "awj_sync",
                    "week1_stage": "",
                    "completion_contract_satisfied": True,
                    "last_reason": "autonomy_work_item_still_actionable",
                    "last_ok": False,
                    "last_repaired": False,
                }
            },
            "pending_followup_task_ids": ["TASK-901"],
            "monitor_candidates": {
                "TASK-901": {
                    "first_seen_utc": "2026-03-22T00:00:00Z",
                    "last_seen_utc": "2026-03-22T00:15:00Z",
                    "consecutive_cycle_scans": 3,
                    "last_reason": "autonomy_work_item_still_actionable",
                    "autonomy_work_item_id": "awj_sync",
                    "week1_stage": "",
                    "task_title": "Repair recurring state-sync mismatch for queued memo",
                    "surfaced": True,
                }
            },
        }
    )

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "task_state_sync_monitor_direct_workflow"
    assert result["reflection_outcome"] is None
    assert result["workflow_result"]["ok"] is True
    assert result["workflow_result"]["fallback_reason"] == "task_state_sync_monitor"
    assert result["workflow_result"]["task_state_sync_monitor_task_id"] == "TASK-901"
    assert result["workflow_result"]["task_state_sync_monitor_cycle_scans"] >= 3
    manager.run_reflection_cycle.assert_not_awaited()
    assert saved_state["active_window_reflections"] == 0
    assert saved_state["active_window_workflows"] == 1


def test_run_autonomy_cycle_executes_week1_validation_monitor_without_reflection(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager.session_start = datetime.now()
    manager._autonomy_cycle_running = False
    manager._memory_dir = Path(tmp_path)
    manager._week1_validation_monitor_path = Path(tmp_path) / "week1_validation_monitor.json"
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager._autonomy_work_jar_path = Path(tmp_path) / "autonomy_work_jar.json"
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager._initiative_config = {}
    manager.config = SimpleNamespace(debug=False)
    manager._owner = MagicMock()
    manager._owner.process_messages = AsyncMock(return_value="COMPLETED: Validation snapshot completed.")
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=4096),
        _load_goals=lambda: {"goals": []},
        is_within_active_hours=lambda: True,
    )
    manager.mcp = MagicMock()
    manager.mcp.get_status = MagicMock(
        return_value={
            "servers": {
                "google-workspace": {"running": True, "health": "healthy", "missing_env": []},
                "time": {"running": True, "health": "healthy", "missing_env": []},
            }
        }
    )
    manager.mcp.get_available_tools = MagicMock(return_value={"google-workspace": ["get_events"], "time": ["get_time"]})
    manager.master_list = MagicMock()
    manager.master_list.get_stats = MagicMock(return_value={"pending": 0, "in_progress": 0, "overdue": 0})
    manager.master_list.parse = MagicMock(return_value=[])
    manager.master_list.get_by_id = MagicMock(return_value=None)
    manager.master_list.update_task = MagicMock(return_value=None)
    manager.master_list.add_task = MagicMock(return_value=SimpleNamespace(id="TASK-951", title="Produce a Week1 validation snapshot"))
    manager.master_list.update_status = MagicMock()
    manager.dnd = MagicMock()
    manager.dnd.get_pending = MagicMock(return_value=[])
    manager.runplane = MagicMock()
    manager.runplane.list_dead_letters = MagicMock(return_value=[])
    manager.runplane.list_runs = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 51,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "startup_window_reflection_index": -1,
        "startup_window_workflow_index": -1,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 51, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False
    manager._save_week1_validation_monitor_state(
        {
            "version": 1,
            "updated_at_utc": "2026-03-27T00:00:00Z",
            "last_snapshot_task_id": "",
            "last_snapshot_utc": "",
            "last_snapshot_reason": "",
            "candidate": {
                "first_seen_utc": "2026-03-27T00:00:00Z",
                "last_seen_utc": "2026-03-27T00:15:00Z",
                "consecutive_cycle_scans": 3,
                "surfaced": True,
                "reason": "week1_validation_snapshot_missing",
                "title": "Produce a Week1 validation snapshot from recent executor and ACK evidence",
                "latest_event_utc": "2026-03-27T01:45:45Z",
                "recent_event_count": 3,
                "recent_ack_count": 0,
                "latest_ack_utc": "",
            },
        }
    )
    manager._collect_recent_week1_validation_signal = lambda **_kwargs: {
        "lookback_hours": 72,
        "recent_event_count": 3,
        "recent_ok_count": 3,
        "recent_failed_count": 0,
        "recent_deferred_count": 0,
        "latest_event_utc": "2026-03-27T01:45:45Z",
        "recent_ack_count": 0,
        "latest_ack_utc": "",
    }

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="autonomy_cycle", force=False))

    assert result["reflection_reason"] == "week1_validation_monitor_direct_workflow"
    assert result["reflection_outcome"] is None
    assert result["workflow_result"]["ok"] is True
    assert result["workflow_result"]["fallback_reason"] == "week1_validation_monitor"
    assert result["workflow_result"]["week1_validation_monitor_cycle_scans"] >= 3
    manager.run_reflection_cycle.assert_not_awaited()
    assert saved_state["active_window_reflections"] == 0
    assert saved_state["active_window_workflows"] == 1


def test_resolve_preferred_autonomy_task_recovers_stale_in_progress(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    stale_task = SimpleNamespace(
        id="TASK-777",
        status=TaskStatus.IN_PROGRESS,
        tags=["inner-life", "autonomy", "workflow"],
        updated=datetime.now() - timedelta(minutes=10),
        title="Advance queued work",
        description="Verifier rollout note",
        notes="Autonomy workflow execution started",
    )
    pending_task = SimpleNamespace(
        id="TASK-777",
        status=TaskStatus.PENDING,
        tags=["inner-life", "autonomy", "workflow"],
        updated=datetime.now(),
        title="Advance queued work",
        description="Verifier rollout note",
        notes="Recovered stale autonomy workflow before reuse (preferred_task_reuse)",
    )
    manager.master_list = MagicMock()
    manager.master_list.get_by_id = MagicMock(side_effect=[stale_task, pending_task])
    manager.master_list.update_status = MagicMock(return_value=pending_task)

    task = manager._resolve_preferred_autonomy_task("TASK-777")

    assert task is pending_task
    manager.master_list.update_status.assert_called_once()
    assert manager.master_list.update_status.call_args.args[1] == TaskStatus.PENDING


def test_reconcile_week1_progress_does_not_credit_procurement_from_prerequisite_artifact(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                id="TASK-019",
                title="Advance the Week1 procurement prerequisite before retrying the procurement packet",
                tags=["inner-life", "autonomy", "workflow"],
                notes="**COMPLETED:** Produced room-by-room fan/light inventory template, standard fixture-count assumptions, and missing-spec checklist. These directly unblock TASK-017 / procurement packet by giving a structured audit format.",
                description="Inventory template and missing-spec checklist.",
            ),
        ]
    )
    manager._save_week1_progress_state(manager._default_week1_progress_state())

    state = manager._reconcile_week1_progress_state_from_tasks()

    assert state["stages"]["procurement_packet"]["done"] is False
    assert manager._week1_next_pending_stage(state) == "fan_shortlist"


def test_execute_inner_action_workflow_reuses_matching_in_progress_autonomy_task(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager.master_list = MasterTaskList(filepath=Path(tmp_path) / "MASTER_TODO.md")
    existing = manager.master_list.add_task(
        title="Inspect the current Week1 external task surface",
        priority=TaskPriority.HIGH,
        description=(
            "Inspect the current Week1 external task surface and determine one concrete next step "
            "you can take now. Replace/upgrade fans and light fixtures. Call contractor for remodel."
        ),
        tags=["inner-life", "autonomy", "workflow"],
    )
    manager.master_list.update_status(existing.id, TaskStatus.IN_PROGRESS, notes="Autonomy workflow execution started")
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager._record_estimated_usage = MagicMock()
    manager._owner = MagicMock()
    manager._owner.process_messages = AsyncMock(return_value="COMPLETED: Prepared the contractor call brief.")
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    manager.decision_ledger = None

    result = asyncio.run(
        manager._execute_inner_action_workflow(
            action_text=(
                "Prepare the remodel contractor call brief as the next concrete Week1 step. "
                "Draft scope bullets, 5-7 questions, dependencies, and a recommended next-step checklist."
            ),
            run_id="run-reuse",
        )
    )

    tasks = manager.master_list.parse()
    assert len(tasks) == 1
    assert result["task_id"] == existing.id
    updated = manager.master_list.get_by_id(existing.id)
    assert updated is not None
    assert updated.status == TaskStatus.COMPLETED


def test_execute_inner_action_workflow_creates_new_task_when_no_matching_in_progress_task(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager.master_list = MasterTaskList(filepath=Path(tmp_path) / "MASTER_TODO.md")
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager._record_estimated_usage = MagicMock()
    manager._owner = MagicMock()
    manager._owner.process_messages = AsyncMock(return_value="COMPLETED: Built a pressure-wash plan.")
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    manager.decision_ledger = None

    result = asyncio.run(
        manager._execute_inner_action_workflow(
            action_text=(
                "Turn the Week1 pressure-wash item into a concrete work plan. "
                "Produce an order-of-operations plan, supplies list, and safety checklist."
            ),
            run_id="run-new",
        )
    )

    tasks = manager.master_list.parse()
    assert len(tasks) == 1
    assert result["task_id"] == "TASK-001"
    assert tasks[0].status == TaskStatus.COMPLETED


def test_execute_inner_action_workflow_marks_markdown_blocked_response_as_blocked(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager.master_list = MasterTaskList(filepath=Path(tmp_path) / "MASTER_TODO.md")
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager._record_estimated_usage = MagicMock()
    manager._owner = MagicMock()
    manager._owner.process_messages = AsyncMock(
        return_value="**BLOCKED:** Missing fan inventory and room-by-room counts."
    )
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    manager.decision_ledger = None

    result = asyncio.run(
        manager._execute_inner_action_workflow(
            action_text=(
                "Turn the existing Week1 fan/light shortlist into a procurement-ready packet. "
                "Produce a buy-list table and missing-information checklist."
            ),
            run_id="run-blocked",
        )
    )

    task = manager.master_list.get_by_id(result["task_id"])
    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["reason"] == "blocked"
    assert task is not None
    assert task.status == TaskStatus.BLOCKED


def test_build_week1_surface_fallback_action_prioritizes_unadvanced_domain(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._week1_progress_state_path = Path(tmp_path) / "week1_autonomy_progress.json"
    manager.master_list = MagicMock()
    manager.master_list.parse = MagicMock(
        return_value=[
            SimpleNamespace(
                updated=datetime.now(),
                status=TaskStatus.COMPLETED,
                title="Fan shortlist research",
                notes="Used brave_web_search to compile ENERGY STAR, WhisperWind, and DC motor fan options.",
                description="Fan shortlist inputs already exist.",
            )
        ]
    )

    action_text = manager._build_week1_surface_fallback_action(
        {
            "week1_task_titles": [
                "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                "[P2] Call contractor for remodel (scope + next steps)",
                "[P2] Pressure wash exterior surfaces (plan scope and sequence)",
            ]
        }
    )

    assert "contractor call brief" in action_text.lower()
    assert "Call contractor for remodel" in action_text


def test_probe_week1_executor_due_work_sync_returns_parsed_probe_payload(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_config = {"base_url": "http://127.0.0.1:8788"}

    with patch(
        "core.runtime.proactive_manager.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["vera_week1_executor.py", "--probe-due"],
            returncode=0,
            stdout='{"ok": true, "due_count": 0, "reason": "no_due_work"}',
            stderr="",
        ),
    ) as mock_run:
        result = manager._probe_week1_executor_due_work_sync()

    assert result["ok"] is True
    assert result["due_count"] == 0
    assert result["reason"] == "no_due_work"
    mock_run.assert_called_once()


def test_run_week1_executor_once_preserves_structured_executor_summary(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_config = {"base_url": "http://127.0.0.1:8788"}
    manager.runplane = MagicMock()
    manager.runplane.begin_run = MagicMock(return_value={"ok": True, "run_id": "run-week1"})
    manager.runplane.complete_run = MagicMock(return_value={"status": "delivered"})

    payload = {
        "ok": True,
        "actions_attempted": 1,
        "events_report": [
            {
                "event_id": "wake_call",
                "status": "partial_ok_fallback_push",
                "detail": "Native push sent.",
                "delivery_channel": "native_push",
                "primary_channel": "call",
                "fallback_channel": "native_push",
                "primary_error": 'HTTP 500: {"error":"call backend failed"}',
            }
        ],
    }

    class _Proc:
        returncode = 0

        async def communicate(self):
            return json.dumps(payload).encode("utf-8"), b""

    async def _fake_create_subprocess_exec(*args, **kwargs):
        return _Proc()

    with patch("core.runtime.proactive_manager.asyncio.create_subprocess_exec", side_effect=_fake_create_subprocess_exec):
        result = asyncio.run(manager._run_week1_executor_once())

    assert result["ok"] is True
    assert result["actions_attempted"] == 1
    assert result["events_report"][0]["status"] == "partial_ok_fallback_push"
    assert result["delivery_summary"]["partial_ok_count"] == 1
    assert result["delivery_summary"]["failed_count"] == 0
    assert result["delivery_status"] == "partial_ok"
    manager.runplane.complete_run.assert_called_once()


def test_run_week1_executor_once_marks_failed_delivery_summary(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_config = {"base_url": "http://127.0.0.1:8788"}
    manager.runplane = MagicMock()
    manager.runplane.begin_run = MagicMock(return_value={"ok": True, "run_id": "run-week1"})
    manager.runplane.complete_run = MagicMock(return_value={"status": "failed"})

    payload = {
        "ok": True,
        "actions_attempted": 1,
        "events_report": [
            {
                "event_id": "wake_call",
                "status": "failed",
                "detail": "call_failed",
            }
        ],
    }

    class _Proc:
        returncode = 0

        async def communicate(self):
            return json.dumps(payload).encode("utf-8"), b""

    async def _fake_create_subprocess_exec(*args, **kwargs):
        return _Proc()

    with patch("core.runtime.proactive_manager.asyncio.create_subprocess_exec", side_effect=_fake_create_subprocess_exec):
        result = asyncio.run(manager._run_week1_executor_once())

    assert result["ok"] is True
    assert result["delivery_summary"]["failed_count"] == 1
    assert result["delivery_status"] == "failed"
    _, kwargs = manager.runplane.complete_run.call_args
    assert kwargs["ok"] is False
    assert kwargs["failure_class"] == "delivery_failed"
    assert kwargs["status"] == "failed"


def test_run_week1_executor_once_marks_not_ready_delivery_summary_deferred(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_config = {"base_url": "http://127.0.0.1:8788"}
    manager.runplane = MagicMock()
    manager.runplane.begin_run = MagicMock(return_value={"ok": True, "run_id": "run-week1"})
    manager.runplane.complete_run = MagicMock(return_value={"status": "deferred"})

    payload = {
        "ok": True,
        "actions_attempted": 1,
        "events_report": [
            {
                "event_id": "followup_factory",
                "status": "deferred_not_ready",
                "detail": "call-me still warming up",
            }
        ],
    }

    class _Proc:
        returncode = 0

        async def communicate(self):
            return json.dumps(payload).encode("utf-8"), b""

    async def _fake_create_subprocess_exec(*args, **kwargs):
        return _Proc()

    with patch("core.runtime.proactive_manager.asyncio.create_subprocess_exec", side_effect=_fake_create_subprocess_exec):
        result = asyncio.run(manager._run_week1_executor_once())

    assert result["ok"] is True
    assert result["delivery_summary"]["deferred_count"] == 1
    assert result["delivery_status"] == "deferred_not_ready"
    _, kwargs = manager.runplane.complete_run.call_args
    assert kwargs["ok"] is False
    assert kwargs["failure_class"] == "delivery_not_ready"
    assert kwargs["status"] == "deferred"


def test_action_week1_due_check_skips_when_delivery_dependencies_pending(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_config = {"week1_executor_enabled": True}
    manager._week1_due_check_future = None
    manager._probe_week1_executor_due_work_sync = MagicMock(return_value={"ok": True, "due_count": 1})
    manager._probe_week1_delivery_dependencies_ready = MagicMock(
        return_value={"ready": False, "reason": "delivery_dependencies_pending", "pending_servers": ["call-me"]}
    )
    manager._schedule_coroutine = MagicMock()

    result = manager.action_week1_due_check({})

    assert result["scheduled"] is False
    assert result["attempted"] is False
    assert result["reason"] == "delivery_dependencies_pending"
    assert result["delivery_dependencies"]["pending_servers"] == ["call-me"]
    manager._schedule_coroutine.assert_not_called()


def test_run_week1_due_check_async_skips_when_delivery_dependencies_pending(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_config = {}
    manager._probe_week1_executor_due_work = AsyncMock(
        return_value={"ok": True, "due_count": 1, "due_events": [{"event_id": "wake_call"}]}
    )
    manager._probe_week1_delivery_dependencies_ready = MagicMock(
        return_value={"ready": False, "reason": "delivery_dependencies_pending", "pending_servers": ["call-me"]}
    )
    manager._load_autonomy_state = MagicMock(return_value={"last_week1_executor_utc": ""})
    manager._save_autonomy_state = MagicMock()
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": True})

    result = asyncio.run(manager._run_week1_due_check_async())

    assert result["attempted"] is False
    assert result["reason"] == "delivery_dependencies_pending"
    assert result["delivery_dependencies"]["pending_servers"] == ["call-me"]
    manager._run_week1_executor_once.assert_not_awaited()
    manager._save_autonomy_state.assert_not_called()


def test_classify_executor_failure_treats_sigterm_as_cancelled(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)

    result = manager._classify_executor_failure({"ok": False, "returncode": -15, "stdout": "", "stderr": ""})

    assert result == {"failure_class": "executor_cancelled", "retryable": True}


def test_run_week1_executor_once_marks_sigterm_as_deferred(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_config = {"base_url": "http://127.0.0.1:8788"}
    manager.runplane = MagicMock()
    manager.runplane.begin_run = MagicMock(return_value={"ok": True, "run_id": "run-week1"})
    manager.runplane.complete_run = MagicMock(return_value={"status": "deferred"})

    class _Proc:
        returncode = -15

        async def communicate(self):
            return b"", b""

    async def _fake_create_subprocess_exec(*args, **kwargs):
        return _Proc()

    with patch("core.runtime.proactive_manager.asyncio.create_subprocess_exec", side_effect=_fake_create_subprocess_exec):
        result = asyncio.run(manager._run_week1_executor_once())

    assert result["ok"] is False
    _, kwargs = manager.runplane.complete_run.call_args
    assert kwargs["failure_class"] == "executor_cancelled"
    assert kwargs["status"] == "deferred"


def test_action_check_tasks_schedules_overdue_push(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._owner = SimpleNamespace()
    manager._owner._internal_tool_call_handler = AsyncMock()
    probe_response = {
        "due": True,
        "overdue_count": 1,
        "tasks": [{"id": "t1", "title": "Urgent review"}],
    }
    manager._probe_check_tasks_due_work = MagicMock(return_value=probe_response)
    mock_coro = object()
    manager._send_overdue_tasks_push = AsyncMock(return_value=None)
    manager._schedule_coroutine = MagicMock(return_value=mock_coro)
    manager._stopping = False

    result = manager.action_check_tasks({})

    assert result["overdue_count"] == 1
    assert result["tasks"] == probe_response["tasks"]
    manager._send_overdue_tasks_push.assert_called_once_with(probe_response["tasks"])
    manager._schedule_coroutine.assert_called_once()


def test_send_overdue_tasks_push_fallback(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._owner = SimpleNamespace()
    manager._owner._internal_tool_call_handler = AsyncMock(side_effect=[
        Exception("boom"),
        {"status": "sent"},
    ])
    tasks = [{"id": "t1", "title": "Review budget"}, {"id": "t2", "title": "Prep summary"}]

    asyncio.run(manager._send_overdue_tasks_push(tasks))

    calls = manager._owner._internal_tool_call_handler.call_args_list
    assert calls[0][0][0] == "send_native_push"
    assert calls[1][0][0] == "send_mobile_push"
    assert "Overdue Tasks" in calls[0][0][1].get("title", "")


def test_probe_reload_config_needed_detects_recent_local_write(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    pref_path = tmp_path / "preferences.json"
    pref_path.write_text("{}", encoding="utf-8")
    epoch = float(pref_path.stat().st_mtime)
    manager.preferences = SimpleNamespace(storage_path=pref_path, _last_saved_epoch=epoch)
    manager.dnd = SimpleNamespace(config_path=tmp_path / "dnd_config.json", _last_saved_epoch=0.0)
    rec = _make_rec(action_id="rc3", priority=ActionPriority.LOW, action_type="reload_config")
    rec.payload = {"events": [{"payload": {"path": str(pref_path)}}]}

    result = manager._probe_reload_config_needed(rec)

    assert result["needed"] is False
    assert result["paths"] == ["preferences"]
    assert result["targets"] == [str(pref_path)]


def test_probe_reload_config_needed_allows_external_change(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    pref_path = tmp_path / "preferences.json"
    dnd_path = tmp_path / "dnd_config.json"
    pref_path.write_text("{}", encoding="utf-8")
    dnd_path.write_text("{}", encoding="utf-8")
    epoch = float(pref_path.stat().st_mtime)
    pref_path.write_text('{"changed": true}', encoding="utf-8")
    future_epoch = epoch + 5.0
    os.utime(pref_path, (future_epoch, future_epoch))
    manager.preferences = SimpleNamespace(storage_path=pref_path, _last_saved_epoch=epoch)
    manager.dnd = SimpleNamespace(config_path=dnd_path, _last_saved_epoch=float(dnd_path.stat().st_mtime))
    rec = _make_rec(action_id="rc4", priority=ActionPriority.LOW, action_type="reload_config")
    rec.payload = {"events": [{"payload": {"path": str(pref_path)}}]}

    result = manager._probe_reload_config_needed(rec)

    assert result["needed"] is True
    assert result["reason"] == "external_change_or_unknown"
    assert result["targets"] == [str(pref_path)]


def test_probe_reload_config_needed_skips_only_when_all_targets_are_local(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    pref_path = tmp_path / "preferences.json"
    dnd_path = tmp_path / "dnd_config.json"
    pref_path.write_text("{}", encoding="utf-8")
    dnd_path.write_text("{}", encoding="utf-8")
    pref_epoch = float(pref_path.stat().st_mtime)
    dnd_epoch = float(dnd_path.stat().st_mtime)
    manager.preferences = SimpleNamespace(storage_path=pref_path, _last_saved_epoch=pref_epoch)
    manager.dnd = SimpleNamespace(config_path=dnd_path, _last_saved_epoch=dnd_epoch)
    rec = _make_rec(action_id="rc5", priority=ActionPriority.LOW, action_type="reload_config")
    rec.payload = {
        "events": [
            {"payload": {"path": str(pref_path)}},
            {"payload": {"path": str(dnd_path)}},
        ]
    }

    result = manager._probe_reload_config_needed(rec)

    assert result["needed"] is False
    assert set(result["paths"]) == {"preferences", "dnd_config"}


def test_action_red_team_uses_probe_and_runs_when_due(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._red_team_running = False
    manager.load_red_team_state = MagicMock(return_value={})
    manager.save_red_team_state = MagicMock()
    manager._probe_red_team_due_work = MagicMock(
        return_value={
            "due": True,
            "reason": "threshold",
            "delta": 250,
            "current": 400,
            "daily_due": False,
            "threshold_due": True,
            "state": {},
        }
    )

    with patch("core.runtime.proactive_manager.run_red_team", return_value={"hard_cases": 1, "regression_cases": 2}):
        result = manager.action_red_team({})

    assert result["ran"] is True
    assert result["reason"] == "threshold"
    assert result["delta"] == 250
    assert result["current"] == 400
    manager.save_red_team_state.assert_called()


def test_run_week1_due_check_async_executes_due_work_and_updates_state(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._probe_week1_executor_due_work = AsyncMock(
        return_value={
            "ok": True,
            "due_count": 1,
            "due_events": [{"event_id": "low_dopamine_start", "minutes_late": 1}],
        }
    )
    manager._parse_int_env = MagicMock(return_value=45)
    manager._load_autonomy_state = MagicMock(return_value={"last_week1_executor_utc": ""})
    saved_state = {}
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": True, "returncode": 0})

    result = asyncio.run(manager._run_week1_due_check_async(trigger="week1_due_check"))

    manager._run_week1_executor_once.assert_awaited_once_with(trigger="week1_due_check")
    assert result["attempted"] is True
    assert result["due_probe"]["due_count"] == 1
    assert saved_state["last_week1_executor_utc"]


def test_setup_sentinel_triggers_updates_stale_persisted_trigger_pattern(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._owner = MagicMock()
    manager._autonomy_config = {"enabled": True, "pulse_interval_seconds": 300}
    manager.inner_life = None
    manager.preferences = MagicMock()
    manager.dnd = MagicMock()
    manager.master_list = MagicMock()
    manager.config = SimpleNamespace(debug=False, observability=False)
    manager.sentinel = SentinelEngine(storage_dir=str(tmp_path / "sentinel"))
    manager.action_check_tasks = MagicMock()
    manager.action_reload_config = MagicMock()
    manager.action_notify = MagicMock()
    manager.action_red_team = MagicMock()
    manager.action_reflect = MagicMock()
    manager.action_autonomy_cycle = MagicMock()

    manager.sentinel.add_trigger(
        name="Config File Changed",
        description="old",
        pattern=EventPattern(
            pattern_id="config_changes",
            name="Config Changes",
            sources=[EventSource.FILE_SYSTEM],
            event_types=[EventType.FILE_MODIFIED],
            payload_patterns={"path": "glob:*.json"},
        ),
        condition=TriggerCondition.IMMEDIATE,
        priority=ActionPriority.LOW,
        cooldown_seconds=10,
        action_template={"type": "reload_config", "urgency": "low"},
    )

    manager.setup_sentinel_triggers()

    trigger = next(t for t in manager.sentinel.trigger_engine.list_triggers() if t.name == "Config File Changed")
    assert trigger.pattern.payload_patterns["path"] == r"regex:(^|/)vera_memory/(preferences|dnd_config)\.json$"


def test_setup_sentinel_triggers_disables_stale_config_watch_when_env_off(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._owner = MagicMock()
    manager._autonomy_config = {"enabled": True, "pulse_interval_seconds": 300}
    manager.inner_life = None
    manager.preferences = MagicMock()
    manager.dnd = MagicMock()
    manager.master_list = MagicMock()
    manager.config = SimpleNamespace(debug=False, observability=False)
    manager.sentinel = SentinelEngine(storage_dir=str(tmp_path / "sentinel"))
    manager.action_check_tasks = MagicMock()
    manager.action_reload_config = MagicMock()
    manager.action_notify = MagicMock()
    manager.action_red_team = MagicMock()
    manager.action_reflect = MagicMock()
    manager.action_autonomy_cycle = MagicMock()

    manager.sentinel.add_trigger(
        name="Config File Changed",
        description="old",
        pattern=EventPattern(
            pattern_id="config_changes",
            name="Config Changes",
            sources=[EventSource.FILE_SYSTEM],
            event_types=[EventType.FILE_MODIFIED],
            payload_patterns={"path": "glob:*.json"},
        ),
        condition=TriggerCondition.IMMEDIATE,
        priority=ActionPriority.LOW,
        cooldown_seconds=10,
        action_template={"type": "reload_config", "urgency": "low"},
    )

    with patch.dict(os.environ, {"VERA_CONFIG_WATCH_ENABLED": "0"}, clear=False):
        manager.setup_sentinel_triggers()

    trigger = next(t for t in manager.sentinel.trigger_engine.list_triggers() if t.name == "Config File Changed")
    assert trigger.enabled is False


def test_sentinel_engine_on_trigger_can_skip_recommendation_creation(tmp_path: Path) -> None:
    sentinel = SentinelEngine(storage_dir=str(tmp_path / "sentinel"))
    sentinel.on_trigger = MagicMock(return_value={"skip_recommendation": True, "reason": "preflight_skip"})
    sentinel.on_recommendation = MagicMock()

    sentinel.add_trigger(
        name="Test Timer",
        description="test",
        pattern=EventPattern(
            pattern_id="timer_test",
            name="Timer Test",
            sources=[EventSource.TIMER],
            event_types=[EventType.INTERVAL_TRIGGER],
            payload_patterns={"action": "check_tasks"},
        ),
        condition=TriggerCondition.IMMEDIATE,
        priority=ActionPriority.LOW,
        cooldown_seconds=0,
        action_template={"type": "check_tasks", "urgency": "low"},
    )

    sentinel.emit_event(
        Event(
            event_id="evt1",
            source=EventSource.TIMER,
            event_type=EventType.INTERVAL_TRIGGER,
            timestamp=datetime.now().isoformat(),
            payload={"action": "check_tasks"},
        )
    )

    assert sentinel.on_recommendation.call_count == 0
    assert sentinel.get_recommendations() == []


def test_handle_sentinel_trigger_skips_maintenance_recommendation_when_preflight_says_no_work(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._probe_check_tasks_due_work = MagicMock(return_value={"due": False, "reason": "no_overdue_tasks"})

    trigger = Trigger(
        trigger_id="t1",
        name="Check Tasks",
        description="test",
        pattern=EventPattern(pattern_id="p1", name="P1"),
        action_template={"type": "check_tasks"},
    )

    result = manager._handle_sentinel_trigger(trigger, [])

    assert result["skip_recommendation"] is True
    assert result["reason"] == "no_overdue_tasks"


def test_forced_autonomy_cycle_bypasses_reflection_window_cap(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 7,
        "active_window_reflections": 1,
        "active_window_workflows": 0,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("idle", 7, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(
        return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test")
    )
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="manual_verification", force=True))

    assert result["phase_override"] == "forced_active_override"
    assert result["budget_mode"] == "non_consumptive_manual"
    assert result["reflection_reason"] == "reflection_executed_forced_cap_override"
    assert result["reflection_outcome"] == "internal"
    assert result["followthrough_result"]["reason"] == "manual_verification_skip"
    assert result["week1_result"]["reason"] == "manual_verification_skip"
    assert result["calendar_result"]["reason"] == "manual_verification_skip"
    assert result["sentinel_result"]["reason"] == "manual_verification_skip"
    assert result["dead_letter_replay_result"]["reason"] == "manual_verification_skip"
    assert result["delivery_escalation_result"]["reason"] == "manual_verification_skip"
    manager.run_reflection_cycle.assert_awaited_once_with(trigger="autonomy_cycle", force=True)
    manager._run_followthrough_executor_once.assert_not_awaited()
    manager._run_week1_executor_once.assert_not_awaited()
    manager._check_calendar_proactive.assert_not_awaited()
    manager._process_sentinel_recommendations.assert_not_awaited()
    manager._auto_replay_dead_letters.assert_not_called()
    manager._auto_escalate_stale_deliveries.assert_not_called()
    assert saved_state["active_window_reflections"] == 1


def test_active_window_outside_hours_does_not_consume_reflection_slot(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(
        config=SimpleNamespace(max_tokens_per_turn=128),
        is_within_active_hours=lambda: False,
    )
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 9,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 9, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(
        return_value=SimpleNamespace(outcome="outside_hours", entries=[], run_id="run-test")
    )
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="startup", force=False))

    assert result["phase"] == "idle"
    assert result["phase_policy"] == "outside_active_hours"
    assert result["idle_window"] is True
    assert result["reflection_reason"] == "idle_window"
    assert result["reflection_outcome"] is None
    manager.run_reflection_cycle.assert_not_awaited()
    assert saved_state["active_window_reflections"] == 0
    manager._record_estimated_usage.assert_not_called()


def test_manual_force_action_workflow_does_not_consume_window_budgets(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 11,
        "active_window_reflections": 1,
        "active_window_workflows": 1,
    }
    entry = SimpleNamespace(thought="Check reminders and send a follow-up")
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("idle", 11, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(
        return_value=SimpleNamespace(outcome="action", entries=[entry], run_id="run-test")
    )
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": True, "reason": "executed"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="manual_check", force=True))

    assert result["phase_override"] == "forced_active_override"
    assert result["budget_mode"] == "non_consumptive_manual"
    assert result["reflection_reason"] == "reflection_executed_forced_cap_override"
    assert result["reflection_outcome"] == "action"
    manager._execute_inner_action_workflow.assert_awaited_once()
    manager._run_followthrough_executor_once.assert_not_awaited()
    manager._run_week1_executor_once.assert_not_awaited()
    manager._check_calendar_proactive.assert_not_awaited()
    manager._process_sentinel_recommendations.assert_not_awaited()
    assert saved_state["active_window_reflections"] == 1
    assert saved_state["active_window_workflows"] == 1


def test_week1_due_probe_overrides_cooldown_when_due_work_pending(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": True,
        "week1_executor_cooldown_seconds": 900,
    }
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    saved_state: Dict[str, Any] = {}
    recent_week1 = (_utc_now() - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    state = {
        "window_index": 12,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "last_week1_executor_utc": recent_week1,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("idle", 12, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._probe_week1_executor_due_work = AsyncMock(
        return_value={
            "ok": True,
            "due_count": 1,
            "due_events": [{"event_id": "morning_merge", "minutes_late": 2}],
        }
    )
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": True, "returncode": 0})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="sentinel", force=False))

    manager._probe_week1_executor_due_work.assert_awaited_once()
    manager._run_week1_executor_once.assert_awaited_once()
    assert result["week1_result"]["attempted"] is True
    assert result["week1_result"]["cooldown_override"] == "due_work_pending"
    assert result["week1_result"]["due_probe"]["due_count"] == 1
    assert saved_state["last_week1_executor_utc"]


def test_week1_cooldown_remains_when_probe_finds_no_due_work(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": True,
        "week1_executor_cooldown_seconds": 900,
    }
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    saved_state: Dict[str, Any] = {}
    recent_week1 = (_utc_now() - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    state = {
        "window_index": 13,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "last_week1_executor_utc": recent_week1,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("idle", 13, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._probe_week1_executor_due_work = AsyncMock(return_value={"ok": True, "due_count": 0, "due_events": []})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": True, "returncode": 0})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="sentinel", force=False))

    manager._probe_week1_executor_due_work.assert_awaited_once()
    manager._run_week1_executor_once.assert_not_awaited()
    assert result["week1_result"]["reason"] == "week1_executor_cooldown_active"
    assert result["week1_result"]["due_work_pending"] is False


def test_followthrough_due_probe_overrides_cooldown_when_due_work_pending(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": True,
        "followthrough_cooldown_seconds": 900,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    saved_state: Dict[str, Any] = {}
    recent_follow = (_utc_now() - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    state = {
        "window_index": 14,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "last_followthrough_utc": recent_follow,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("idle", 14, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._probe_followthrough_due_work = AsyncMock(
        return_value={
            "ok": True,
            "due_count": 1,
            "due_actions": [{"commitment_id": "c1:1", "reason": "default_window_elapsed"}],
        }
    )
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": True, "returncode": 0})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="sentinel", force=False))

    manager._probe_followthrough_due_work.assert_awaited_once()
    manager._run_followthrough_executor_once.assert_awaited_once()
    assert result["followthrough_result"]["attempted"] is True
    assert result["followthrough_result"]["cooldown_override"] == "due_work_pending"
    assert result["followthrough_result"]["due_probe"]["due_count"] == 1
    assert saved_state["last_followthrough_utc"]


def test_followthrough_cooldown_remains_when_probe_finds_no_due_work(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": True,
        "followthrough_cooldown_seconds": 900,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    saved_state: Dict[str, Any] = {}
    recent_follow = (_utc_now() - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    state = {
        "window_index": 15,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "last_followthrough_utc": recent_follow,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("idle", 15, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._probe_followthrough_due_work = AsyncMock(return_value={"ok": True, "due_count": 0, "due_actions": []})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": True, "returncode": 0})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="sentinel", force=False))

    manager._probe_followthrough_due_work.assert_awaited_once()
    manager._run_followthrough_executor_once.assert_not_awaited()
    assert result["followthrough_result"]["reason"] == "followthrough_cooldown_active"
    assert result["followthrough_result"]["due_work_pending"] is False


def test_sentinel_trigger_skips_reflection_when_no_pending_recommendations(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    manager.sentinel = MagicMock()
    manager.sentinel.recommender = MagicMock()
    manager.sentinel.recommender.get_pending_recommendations = MagicMock(return_value=[])
    saved_state: Dict[str, Any] = {}
    state = {
        "window_index": 18,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("active", 18, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value={"processed": 0, "pending_remaining": 0})
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="sentinel", force=False))

    assert result["reflection_reason"] == "sentinel_no_actionable_work"
    assert result["reflection_outcome"] is None
    manager.run_reflection_cycle.assert_not_awaited()
    assert saved_state["active_window_reflections"] == 0


def test_week1_skips_executor_when_cooldown_expired_but_no_due_work(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": False,
        "week1_executor_enabled": True,
        "week1_executor_cooldown_seconds": 900,
    }
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    saved_state: Dict[str, Any] = {}
    stale_week1 = (_utc_now() - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
    state = {
        "window_index": 16,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "last_week1_executor_utc": stale_week1,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("idle", 16, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": False})
    manager._probe_week1_executor_due_work = AsyncMock(return_value={"ok": True, "due_count": 0, "due_events": []})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": True, "returncode": 0})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="sentinel", force=False))

    manager._probe_week1_executor_due_work.assert_awaited_once()
    manager._run_week1_executor_once.assert_not_awaited()
    assert result["week1_result"]["reason"] == "no_due_work"
    assert result["week1_result"]["attempted"] is False
    assert saved_state["last_week1_executor_utc"] == stale_week1


def test_followthrough_skips_executor_when_cooldown_expired_but_no_due_work(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._autonomy_cycle_running = False
    manager._autonomy_config = {
        "enabled": True,
        "max_reflections_per_active_window": 1,
        "max_workflows_per_active_window": 1,
        "followthrough_enabled": True,
        "followthrough_cooldown_seconds": 900,
        "week1_executor_enabled": False,
    }
    manager.inner_life = SimpleNamespace(config=SimpleNamespace(max_tokens_per_turn=128))
    saved_state: Dict[str, Any] = {}
    stale_follow = (_utc_now() - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
    state = {
        "window_index": 17,
        "active_window_reflections": 0,
        "active_window_workflows": 0,
        "last_followthrough_utc": stale_follow,
    }
    manager._load_autonomy_state = MagicMock(return_value=dict(state))
    manager._compute_cadence_phase = MagicMock(return_value=("idle", 17, 42))
    manager._can_spend = MagicMock(return_value=(True, "ok"))
    manager.run_reflection_cycle = AsyncMock(return_value=SimpleNamespace(outcome="internal", entries=[], run_id="run-test"))
    manager._record_estimated_usage = MagicMock()
    manager._execute_inner_action_workflow = AsyncMock(return_value={"ok": False, "reason": "not_used"})
    manager._probe_followthrough_due_work = AsyncMock(return_value={"ok": True, "due_count": 0, "due_actions": []})
    manager._run_followthrough_executor_once = AsyncMock(return_value={"ok": True, "returncode": 0})
    manager._run_week1_executor_once = AsyncMock(return_value={"ok": False})
    manager._check_calendar_proactive = AsyncMock(return_value=None)
    manager._process_sentinel_recommendations = AsyncMock(return_value=None)
    manager._auto_replay_dead_letters = MagicMock(return_value={})
    manager._audit_dead_letter_replay_slo = MagicMock(return_value={})
    manager._auto_escalate_stale_deliveries = MagicMock(return_value={})
    manager._save_autonomy_state = lambda data: saved_state.update(data)
    manager._append_autonomy_event = MagicMock()
    manager._red_team_running = False

    result = asyncio.run(manager._run_autonomy_cycle_async(trigger="sentinel", force=False))

    manager._probe_followthrough_due_work.assert_awaited_once()
    manager._run_followthrough_executor_once.assert_not_awaited()
    assert result["followthrough_result"]["reason"] == "no_due_work"
    assert result["followthrough_result"]["attempted"] is False


def test_handle_recommendation_non_internal_still_respects_dnd(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager.execute_proactive_action = MagicMock()
    manager._should_execute_recommendation = MagicMock(return_value=(True, "allowed"))
    manager.dnd.can_interrupt = MagicMock(return_value=False)

    rec = _make_rec(action_id="norm1", priority=ActionPriority.NORMAL, action_type="proactive_check")
    manager.handle_proactive_recommendation(rec)

    manager.execute_proactive_action.assert_not_called()
    manager.dnd.queue_interrupt.assert_called_once()
    assert len(manager._pending_proactive_actions) == 1


def test_queued_callback_drains_pending_recommendation(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager.config = MagicMock(debug=False)
    manager._pending_proactive_actions = []
    manager.execute_proactive_action = MagicMock()
    manager._should_execute_recommendation = MagicMock(return_value=(True, "allowed"))
    manager.dnd.can_interrupt = MagicMock(return_value=False)

    rec = _make_rec(action_id="queued1", priority=ActionPriority.NORMAL, action_type="proactive_check")
    manager.handle_proactive_recommendation(rec)

    assert len(manager._pending_proactive_actions) == 1
    callback = manager.dnd.queue_interrupt.call_args.kwargs["callback"]
    callback("deliver")

    assert len(manager._pending_proactive_actions) == 0
    manager.execute_proactive_action.assert_called_once_with(rec)


def test_drain_pending_recommendation_removes_matching_action_id(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    manager._pending_proactive_actions = [
        _make_rec(action_id="a1", priority=ActionPriority.LOW, action_type="proactive_check"),
        _make_rec(action_id="a2", priority=ActionPriority.LOW, action_type="proactive_check"),
        _make_rec(action_id="a1", priority=ActionPriority.LOW, action_type="proactive_check"),
    ]

    removed = manager._drain_pending_recommendation("a1")

    assert removed == 2
    assert [rec.action_id for rec in manager._pending_proactive_actions] == ["a2"]


def test_proactive_execution_sets_tool_whitelist(tmp_path: Path) -> None:
    """During HIGH execution, the proactive tool whitelist should be set on owner."""
    recs = [_make_rec(priority=ActionPriority.HIGH)]
    manager = _make_manager(tmp_path, pending_recs=recs)
    whitelist_during_exec = []

    async def capture_whitelist(**kwargs):
        whitelist_during_exec.append(
            getattr(manager._owner, "_proactive_tool_whitelist", None)
        )
        return {"ok": True, "task_id": "t1", "status": "completed", "response_preview": "Done"}

    manager._execute_inner_action_workflow = AsyncMock(side_effect=capture_whitelist)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert len(whitelist_during_exec) == 1
    assert whitelist_during_exec[0] is not None
    assert "get_events" in whitelist_during_exec[0]
    # After execution, whitelist should be cleared
    assert manager._owner._proactive_tool_whitelist is None


def test_proactive_execution_mixed_priorities(tmp_path: Path) -> None:
    """Mix of priorities should report actual routing outcomes, not hardcoded buckets."""
    recs = [
        _make_rec(action_id="high1", priority=ActionPriority.HIGH),
        _make_rec(action_id="norm1", priority=ActionPriority.NORMAL),
        _make_rec(action_id="low1", priority=ActionPriority.LOW),
    ]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert len(result.get("executed", [])) == 3
    assert len(result.get("notified", [])) == 0
    assert len(result.get("logged", [])) == 0
    assert result.get("processed") == 3


def test_evaluate_action_reward_signal_marks_attempted_false_no_due_as_not_due(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    rec = _make_rec(action_id="w1", priority=ActionPriority.HIGH, action_type="week1_due_check")

    delta, signal = ProactiveManager._evaluate_action_reward_signal(
        manager,
        recommendation=rec,
        success=True,
        result={"ok": True, "attempted": False, "reason": "no_due_work"},
    )

    assert delta == 0.0
    assert signal == "action_success_not_due"


def test_evaluate_action_reward_signal_treats_scheduled_autonomy_cycle_as_skipped(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path, pending_recs=[])
    rec = _make_rec(action_id="ac1", priority=ActionPriority.HIGH, action_type="autonomy_cycle")

    delta, signal = ProactiveManager._evaluate_action_reward_signal(
        manager,
        recommendation=rec,
        success=True,
        result={"scheduled": True, "trigger": "autonomy_cycle", "force": False},
    )

    assert delta == 0.0
    assert signal == "action_success_skipped"


def test_internal_cadence_noop_event_suppression_detects_recent_repeat(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._initiative_config = {}
    manager._initiative_state = {
        "action_type_stats": {
            "week1_due_check": {
                "last_outcome": "action_success_not_due",
                "last_attempt_utc": _utc_iso(),
            }
        }
    }

    suppressed = manager._should_suppress_internal_cadence_noop_event(
        "week1_due_check",
        "action_success_not_due",
        state=manager._initiative_state,
    )

    assert suppressed is True


def test_record_recent_proactive_action_suppresses_internal_cadence_noop_event(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._initiative_config = {}
    manager._initiative_state = manager._default_initiative_state()
    manager._initiative_state["action_type_stats"] = {
        "week1_due_check": {
            **manager._default_action_type_stat(),
            "last_outcome": "action_success_not_due",
            "last_attempt_utc": _utc_iso(),
        }
    }
    manager._save_initiative_state = MagicMock()
    manager._append_initiative_event = MagicMock()
    rec = _make_rec(action_id="w1", priority=ActionPriority.HIGH, action_type="week1_due_check")

    manager._record_recent_proactive_action(
        rec,
        success=True,
        result={"ok": True, "attempted": False, "reason": "no_due_work"},
        signal_type="action_success_not_due",
    )

    assert manager._initiative_state["recent_actions"] == []
    manager._append_initiative_event.assert_not_called()


def test_update_action_type_stats_suppresses_repeated_internal_cadence_noop_event(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._initiative_config = {}
    manager._initiative_state = manager._default_initiative_state()
    manager._initiative_state["action_type_stats"] = {
        "week1_due_check": {
            **manager._default_action_type_stat(),
            "last_outcome": "action_success_not_due",
            "last_attempt_utc": _utc_iso(),
            "total_noops": 4,
        }
    }
    manager._save_initiative_state = MagicMock()
    manager._append_initiative_event = MagicMock()

    manager._update_action_type_stats("week1_due_check", "action_success_not_due")

    assert manager._initiative_state["action_type_stats"]["week1_due_check"]["total_noops"] == 4
    assert manager._initiative_state["action_type_stats"]["week1_due_check"]["last_outcome"] == "action_success_not_due"
    manager._append_initiative_event.assert_not_called()


def test_check_tasks_noop_rollup_stops_growing_total_after_threshold(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._initiative_config = {"type_noop_streak_threshold": 5}
    manager._initiative_state = manager._default_initiative_state()
    manager._initiative_state["action_type_stats"] = {
        "check_tasks": {
            **manager._default_action_type_stat(),
            "last_outcome": "action_success_noop",
            "last_attempt_utc": _utc_iso(),
            "total_noops": 12,
            "consecutive_noops": 5,
        }
    }
    manager._save_initiative_state = MagicMock()
    manager._append_initiative_event = MagicMock()
    manager._current_mood = MagicMock(return_value="steady")

    manager._update_action_type_stats("check_tasks", "action_success_noop")

    stats = manager._initiative_state["action_type_stats"]["check_tasks"]
    assert stats["total_noops"] == 12
    assert stats["consecutive_noops"] == 6
    assert stats["cooldown_until_utc"] is not None
    manager._append_initiative_event.assert_not_called()


def test_red_team_not_due_rollup_stops_growing_total_after_threshold(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._initiative_config = {"type_noop_streak_threshold": 5}
    manager._initiative_state = manager._default_initiative_state()
    manager._initiative_state["action_type_stats"] = {
        "red_team_check": {
            **manager._default_action_type_stat(),
            "last_outcome": "action_success_not_due",
            "last_attempt_utc": _utc_iso(),
            "total_noops": 8,
            "consecutive_noops": 7,
        }
    }
    manager._save_initiative_state = MagicMock()
    manager._append_initiative_event = MagicMock()
    manager._current_mood = MagicMock(return_value="steady")

    manager._update_action_type_stats("red_team_check", "action_success_not_due")

    stats = manager._initiative_state["action_type_stats"]["red_team_check"]
    assert stats["total_noops"] == 8
    assert stats["consecutive_noops"] == 8
    assert stats["cooldown_until_utc"] is not None
    manager._append_initiative_event.assert_not_called()


def test_reconcile_initiative_state_resets_internal_cadence_noops(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._initiative_config = {"type_noop_streak_threshold": 5}
    state = manager._default_initiative_state()
    state["action_type_stats"] = {
        "week1_due_check": {
            **manager._default_action_type_stat(),
            "last_outcome": "action_success_not_due",
            "total_noops": 1247,
            "consecutive_noops": 19,
        },
        "reflect": {
            **manager._default_action_type_stat(),
            "last_outcome": "action_success_skipped",
            "total_noops": 9,
            "consecutive_noops": 2,
        },
    }

    manager._reconcile_initiative_state(state)

    assert state["action_type_stats"]["week1_due_check"]["total_noops"] == 0
    assert state["action_type_stats"]["reflect"]["total_noops"] == 0


def test_reconcile_initiative_state_bounds_maintenance_noops(tmp_path: Path) -> None:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._initiative_config = {"type_noop_streak_threshold": 5}
    state = manager._default_initiative_state()
    state["action_type_stats"] = {
        "check_tasks": {
            **manager._default_action_type_stat(),
            "last_outcome": "action_success_noop",
            "total_noops": 501,
            "consecutive_noops": 54,
        },
        "red_team_check": {
            **manager._default_action_type_stat(),
            "last_outcome": "action_success_not_due",
            "total_noops": 366,
            "consecutive_noops": 67,
        },
    }

    manager._reconcile_initiative_state(state)

    assert state["action_type_stats"]["check_tasks"]["total_noops"] == 5
    assert state["action_type_stats"]["red_team_check"]["total_noops"] == 5
