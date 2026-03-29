from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from planning.sentinel_engine import (
    ActionPriority,
    ActionRecommender,
    Event,
    EventPattern,
    EventSource,
    EventType,
    SentinelEngine,
    Trigger,
    TriggerCondition,
)


def _event(event_id: str, conversation_id: str = "", path: str = "config.json") -> Event:
    payload = {"path": path}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return Event(
        event_id=event_id,
        source=EventSource.FILE_SYSTEM,
        event_type=EventType.FILE_MODIFIED,
        timestamp=datetime.now().isoformat(),
        payload=payload,
    )


def _trigger() -> Trigger:
    return Trigger(
        trigger_id="config_trigger",
        name="Config File Changed",
        description="Reload config when JSON changes",
        pattern=EventPattern(
            pattern_id="config_pattern",
            name="Config Pattern",
            sources=[EventSource.FILE_SYSTEM],
            event_types=[EventType.FILE_MODIFIED],
            payload_patterns={"path": "glob:*.json"},
        ),
        condition=TriggerCondition.IMMEDIATE,
        priority=ActionPriority.LOW,
        action_template={"type": "reload_config", "urgency": "low"},
    )


def test_recommendation_dedup_merges_same_pending_intent() -> None:
    recommender = ActionRecommender()
    trigger = _trigger()

    first, created_first = recommender.create_or_merge_recommendation(trigger, [_event("e1")])
    second, created_second = recommender.create_or_merge_recommendation(trigger, [_event("e2")])

    assert created_first is True
    assert created_second is False
    assert second.action_id == first.action_id

    pending = recommender.get_pending_recommendations()
    assert len(pending) == 1
    assert pending[0].action_id == first.action_id
    assert pending[0].payload["event_count"] == 2
    assert pending[0].triggering_events == ["e1", "e2"]


def test_recommendation_dedup_keeps_distinct_conversations_separate() -> None:
    recommender = ActionRecommender()
    trigger = _trigger()

    _, created_first = recommender.create_or_merge_recommendation(trigger, [_event("e1", conversation_id="conv-a")])
    _, created_second = recommender.create_or_merge_recommendation(trigger, [_event("e2", conversation_id="conv-b")])

    assert created_first is True
    assert created_second is True
    assert len(recommender.get_pending_recommendations()) == 2


def test_sentinel_on_recommendation_only_fires_for_new_recommendations(tmp_path: Path) -> None:
    sentinel = SentinelEngine(str(tmp_path / "sentinel"))
    sentinel.on_recommendation = MagicMock()
    trigger = _trigger()
    sentinel.trigger_engine.add_trigger(trigger)

    sentinel.emit_event(_event("e1", path="config-a.json"))
    sentinel.emit_event(_event("e2", path="config-b.json"))

    pending = sentinel.get_recommendations()
    assert len(pending) == 1
    assert pending[0].payload["event_count"] == 2
    sentinel.on_recommendation.assert_called_once()


def test_config_watch_regex_matches_runtime_config_not_state_files() -> None:
    pattern = EventPattern(
        pattern_id="config_changes",
        name="Config Changes",
        sources=[EventSource.FILE_SYSTEM],
        event_types=[EventType.FILE_MODIFIED],
        payload_patterns={"path": r"regex:(^|/)vera_memory/(preferences|dnd_config)\.json$"},
    )

    assert _event("p1", path="vera_memory/preferences.json").matches_pattern(pattern) is True
    assert _event("d1", path="vera_memory/dnd_config.json").matches_pattern(pattern) is True
    assert _event("s1", path="vera_memory/autonomy_cadence_state.json").matches_pattern(pattern) is False
    assert _event("s2", path="vera_memory/initiative_tuning_state.json").matches_pattern(pattern) is False
