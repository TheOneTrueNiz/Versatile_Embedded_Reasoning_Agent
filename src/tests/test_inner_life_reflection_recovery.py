from __future__ import annotations

import time

import pytest

from planning.inner_life_engine import (
    INTENT_INTERNAL,
    InnerLifeConfig,
    InnerLifeEngine,
    MonologueEntry,
)


def _make_entry() -> MonologueEntry:
    return MonologueEntry(
        timestamp="2026-02-24T00:00:00",
        run_id="run-test",
        trigger="manual",
        intent=INTENT_INTERNAL,
        thought="steady",
        chain_depth=0,
    )


@pytest.mark.asyncio
async def test_execute_reflection_cycle_recovers_from_stale_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = InnerLifeEngine(InnerLifeConfig(), tmp_path / "innerlife")
    monkeypatch.setenv("VERA_REFLECTION_STALE_SECONDS", "30")

    async def _process_messages(*args, **kwargs):
        return "[INTERNAL] steady"

    async def _single_turn(*args, **kwargs):
        return _make_entry()

    engine._process_messages_fn = _process_messages
    engine._execute_single_turn = _single_turn  # type: ignore[assignment]
    engine._reflection_running = True
    engine._reflection_started_monotonic = time.monotonic() - 120.0

    result = await engine.execute_reflection_cycle(trigger="manual", force=True)

    assert result.outcome == "internal"
    assert engine._reflection_running is False
    assert engine._reflection_started_monotonic is None


def test_get_statistics_reports_reflection_running_seconds(tmp_path) -> None:
    engine = InnerLifeEngine(InnerLifeConfig(), tmp_path / "innerlife")
    engine._reflection_running = True
    engine._reflection_started_monotonic = time.monotonic() - 3.0

    stats = engine.get_statistics()

    assert stats["reflection_running"] is True
    assert isinstance(stats["reflection_running_seconds"], float)
    assert stats["reflection_running_seconds"] >= 0.0
