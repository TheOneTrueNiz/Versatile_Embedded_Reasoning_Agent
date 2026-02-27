"""Unit tests for sentinel recommendation proactive execution."""

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.runtime.proactive_manager import ProactiveManager, _utc_iso
from planning.sentinel_engine import ActionPriority, RecommendedAction


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
    manager.sentinel.recommender.get_pending_recommendations = MagicMock(
        return_value=pending_recs or []
    )
    manager.sentinel.recommender.mark_executed = MagicMock(return_value=True)
    manager.sentinel.recommender.acknowledge = MagicMock(return_value=True)
    manager.decision_ledger = None

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


def test_proactive_execution_notifies_normal_priority(tmp_path: Path) -> None:
    """NORMAL priority should notify, not execute."""
    recs = [_make_rec(action_id="n1", priority=ActionPriority.NORMAL)]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert len(result.get("notified", [])) == 1
    assert "n1" in result["notified"]
    manager._execute_inner_action_workflow.assert_not_called()
    manager.sentinel.recommender.acknowledge.assert_called_once_with("n1")


def test_proactive_execution_logs_low_priority(tmp_path: Path) -> None:
    """LOW priority should log only."""
    recs = [_make_rec(action_id="l1", priority=ActionPriority.LOW)]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert len(result.get("logged", [])) == 1
    assert "l1" in result["logged"]
    manager._execute_inner_action_workflow.assert_not_called()
    manager.sentinel.recommender.acknowledge.assert_called_once_with("l1")


def test_proactive_execution_logs_background_priority(tmp_path: Path) -> None:
    """BACKGROUND priority should log only."""
    recs = [_make_rec(action_id="b1", priority=ActionPriority.BACKGROUND)]
    manager = _make_manager(tmp_path, pending_recs=recs)

    with patch.dict(os.environ, {"VERA_PROACTIVE_EXECUTION": "1"}, clear=False):
        result = asyncio.run(
            manager._process_sentinel_recommendations()
        )

    assert result is not None
    assert len(result.get("logged", [])) == 1


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
    """Mix of priorities should route correctly."""
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
    assert len(result.get("executed", [])) == 1
    assert len(result.get("notified", [])) == 1
    assert len(result.get("logged", [])) == 1
    assert result.get("processed") == 3
