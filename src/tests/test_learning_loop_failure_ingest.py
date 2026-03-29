"""Failure-learning ingestion coverage for LearningLoopManager."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from learning.learning_loop_manager import LearningLoopManager
from learning.trajectory_distillation import (
    AdapterRegistry,
    DistillationConfig,
    DistillationPipeline,
    ExampleStore,
    MockLoRATrainer,
    QualityLevel,
    TrajectoryCapture,
)


def _build_failure_ingest_manager(tmp_path: Path) -> LearningLoopManager:
    manager = object.__new__(LearningLoopManager)
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    manager.memory_dir = memory_dir
    manager.failure_learning_path = memory_dir / "failure_learning_events.jsonl"
    manager.failure_batch_max = 200
    manager.failure_ingest_enabled = True
    manager._state = {
        "failure_learning_offset": 0,
        "failure_learning_processed_total": 0,
        "failure_learning_examples_total": 0,
        "failure_learning_malformed_total": 0,
    }
    manager._trace_reward = lambda *args, **kwargs: None
    manager._save_state = lambda: None

    manager.capture = TrajectoryCapture(storage_path=memory_dir / "trajectories" / "trajectories.json")
    manager.example_store = ExampleStore(storage_path=memory_dir / "training_examples" / "examples.json")
    manager.adapter_registry = AdapterRegistry(storage_dir=memory_dir / "adapters")
    manager.pipeline = DistillationPipeline(
        capture=manager.capture,
        example_store=manager.example_store,
        adapter_registry=manager.adapter_registry,
        trainer=MockLoRATrainer(),
        config=DistillationConfig(
            min_trajectory_score=0.55,
            min_quality_level=QualityLevel.MEDIUM,
            min_examples_for_training=5,
            auto_train_threshold=500,
        ),
    )
    return manager


def test_ingest_failure_learning_events_generates_examples_and_updates_state(tmp_path: Path) -> None:
    manager = _build_failure_ingest_manager(tmp_path)
    rows = [
        {
            "ts_utc": "2026-03-05T01:02:03Z",
            "type": "dead_letter_auto_replay",
            "ok": False,
            "job_id": "job-1",
            "run_id": "run-1",
            "failure_class": "transport_error",
            "reason": "upstream timeout",
        },
        "not-json-row",
        {
            "ts_utc": "2026-03-05T01:04:05Z",
            "type": "delivery_ack_timeout_escalated",
            "ok": True,
            "job_id": "job-2",
            "run_id": "run-2",
            "kind": "delivery.reachout",
            "reason": "ack_timeout_sla_exceeded",
        },
    ]
    with manager.failure_learning_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            if isinstance(row, str):
                handle.write(row + "\n")
            else:
                handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    result = manager.ingest_failure_learning_events(max_events=10)

    assert result["events_processed"] == 2
    assert result["trajectories_created"] == 2
    assert result["malformed_lines"] == 1
    assert int(result["examples_created"]) > 0
    assert int(manager._state.get("failure_learning_processed_total", 0)) == 2
    assert int(manager._state.get("failure_learning_examples_total", 0)) == int(result["examples_created"])
    assert int(manager._state.get("failure_learning_malformed_total", 0)) == 1
    assert int(manager._state.get("failure_learning_offset", 0)) > 0
    stats = manager.example_store.get_statistics()
    assert int(stats["by_type"].get("instruction_response", 0)) >= 1


def test_ingest_failure_learning_events_respects_disabled_flag(tmp_path: Path) -> None:
    manager = _build_failure_ingest_manager(tmp_path)
    manager.failure_ingest_enabled = False
    result = manager.ingest_failure_learning_events(max_events=5)
    assert result["events_processed"] == 0
    assert result["examples_created"] == 0
    assert result["reason"] == "disabled"


@pytest.mark.usefixtures("monkeypatch")
def test_run_daily_learning_cycle_includes_failure_ingest_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = object.__new__(LearningLoopManager)
    manager._trace_learning = lambda *args, **kwargs: None
    manager.trace_engine = SimpleNamespace(extract_recent_successes=lambda hours: ["trace-1"])
    manager.pipeline = SimpleNamespace(extract_from_all_successful=lambda: ["example-1"])
    manager.ingest_flight_recorder_transitions = lambda max_items: {
        "transitions_processed": 3,
        "examples_created": 2,
    }
    manager.ingest_failure_learning_events = lambda max_items: {
        "events_processed": 4,
        "examples_created": 5,
        "reason": "processed",
    }
    manager.maybe_train_reward_model = lambda: {"trained": False}
    manager.maybe_train_lora_adapter = lambda: {"trained": False}
    manager.flight_batch_max = 250
    manager.failure_batch_max = 120
    manager.example_store = SimpleNamespace(count=lambda: 42)
    manager._state = {"daily_runs": 0}
    manager._save_state = lambda: None
    manager._emit_event = lambda *args, **kwargs: None

    async def _direct_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _direct_to_thread)

    result = asyncio.run(manager.run_daily_learning_cycle())

    assert result["trajectories_extracted"] == 1
    assert result["examples_from_trajectories"] == 1
    assert int(result["flight_ingest"]["examples_created"]) == 2
    assert int(result["failure_learning_ingest"]["examples_created"]) == 5
    assert int(result["total_examples"]) == 42
    assert int(manager._state.get("daily_runs", 0)) == 1
