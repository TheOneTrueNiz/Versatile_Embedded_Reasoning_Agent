from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

from core.runtime.proactive_manager import ProactiveManager
from planning.sentinel_engine import ActionPriority, RecommendedAction


class _SentinelStub:
    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises
        self.calls: List[str] = []

    def execute_recommendation(self, action_id: str) -> Tuple[bool, Dict[str, Any]]:
        self.calls.append(action_id)
        if self.raises:
            raise RuntimeError("sentinel boom")
        return True, {"ok": True}


def _make_recommendation(*, action_id: str, action_type: str = "notify", payload: Dict[str, Any] | None = None) -> RecommendedAction:
    return RecommendedAction(
        action_id=action_id,
        trigger_id=action_type,
        description="test proactive action",
        priority=ActionPriority.NORMAL,
        action_type=action_type,
        payload=payload or {"conversation_id": "thread-1"},
        triggering_events=[],
    )


def _make_manager(sentinel: _SentinelStub) -> ProactiveManager:
    manager = object.__new__(ProactiveManager)
    manager._pending_proactive_actions = []
    manager._proactive_lane_lock = threading.RLock()
    manager._active_proactive_lanes = {}
    manager._proactive_lane_queue_max = 8
    manager._proactive_lane_queues = {}
    manager.sentinel = sentinel
    manager.config = SimpleNamespace(debug=False, observability=False)
    manager.observability = SimpleNamespace(record_event=lambda *args, **kwargs: None)
    manager._recorded_results: List[Tuple[bool, Dict[str, Any]]] = []
    manager._initiative_events: List[Dict[str, Any]] = []
    manager._drain_pending_recommendation = lambda action_id: 0
    manager._record_recent_proactive_action = (
        lambda recommendation, success, result, signal_type=None: manager._recorded_results.append((bool(success), dict(result or {})))
    )
    manager._evaluate_action_reward_signal = (
        lambda recommendation, success, result: (0.0, "action_success" if success else "action_failure")
    )
    manager._apply_initiative_signal = lambda **kwargs: None
    manager._update_action_type_stats = lambda **kwargs: None
    manager._append_initiative_event = lambda event: manager._initiative_events.append(dict(event))
    return manager


def test_proactive_lane_key_prefers_session_link_id() -> None:
    manager = _make_manager(_SentinelStub())
    rec = _make_recommendation(
        action_id="a1",
        payload={
            "session_link_id": "niz@example.com",
            "conversation_id": "thread-1",
        },
    )
    lane_key = manager._build_proactive_lane_key(rec)
    assert lane_key == "notify:niz@example.com"


def test_execute_proactive_action_skips_when_lane_busy() -> None:
    sentinel = _SentinelStub()
    manager = _make_manager(sentinel)
    manager._active_proactive_lanes["notify:thread-1"] = "active_action"
    rec = _make_recommendation(action_id="a2", payload={"conversation_id": "thread-1"})

    manager.execute_proactive_action(rec)

    assert sentinel.calls == []
    assert manager._active_proactive_lanes["notify:thread-1"] == "active_action"
    assert "notify:thread-1" in manager._proactive_lane_queues
    assert len(manager._proactive_lane_queues["notify:thread-1"]) == 1
    assert manager._initiative_events
    assert manager._initiative_events[-1].get("type") == "proactive_lane_busy"


def test_lane_queue_drains_after_lane_release() -> None:
    sentinel = _SentinelStub()
    manager = _make_manager(sentinel)
    lane_key = "notify:thread-1"
    manager._active_proactive_lanes[lane_key] = "active_action"
    rec = _make_recommendation(action_id="a2", payload={"conversation_id": "thread-1"})

    manager.execute_proactive_action(rec)
    assert sentinel.calls == []
    assert len(manager._proactive_lane_queues[lane_key]) == 1

    manager._leave_proactive_lane(lane_key, "active_action")
    manager._drain_queued_proactive_lane(lane_key)

    assert sentinel.calls == ["a2"]
    assert lane_key not in manager._proactive_lane_queues


def test_execute_proactive_action_releases_lane_on_exception() -> None:
    sentinel = _SentinelStub(raises=True)
    manager = _make_manager(sentinel)
    rec = _make_recommendation(action_id="a3", payload={"conversation_id": "thread-2"})

    manager.execute_proactive_action(rec)

    assert sentinel.calls == ["a3"]
    assert manager._active_proactive_lanes == {}
    assert manager._recorded_results
    success, result = manager._recorded_results[-1]
    assert success is False
    assert str(result.get("error", "")).startswith("execute_recommendation_exception:")
