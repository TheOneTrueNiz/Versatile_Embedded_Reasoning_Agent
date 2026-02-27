"""Regression tests for proactive default env gates."""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.runtime.proactive_manager import ProactiveManager
from context.dnd_mode import InterruptUrgency


class _OwnerStub:
    async def process_messages(self, messages, conversation_id=None):  # noqa: D401
        # Return no events so _check_calendar_proactive completes without push attempts.
        return "[]"


class _DNDStub:
    def can_interrupt(self, urgency: InterruptUrgency) -> bool:
        return True


class _RecommenderStub:
    def get_pending_recommendations(self):
        return []


class _SentinelStub:
    def __init__(self) -> None:
        self.recommender = _RecommenderStub()


def _make_manager(tmp_path: Path) -> ProactiveManager:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._owner = _OwnerStub()
    manager.sentinel = _SentinelStub()
    manager.dnd = _DNDStub()
    return manager


def test_calendar_proactive_default_is_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VERA_CALENDAR_PROACTIVE", raising=False)
    manager = _make_manager(tmp_path)

    result = asyncio.run(manager._check_calendar_proactive())

    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert result.get("events_checked") is True


def test_calendar_proactive_respects_explicit_disable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_CALENDAR_PROACTIVE", "0")
    manager = _make_manager(tmp_path)

    result = asyncio.run(manager._check_calendar_proactive())

    assert result is None


def test_proactive_execution_default_is_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VERA_PROACTIVE_EXECUTION", raising=False)
    manager = _make_manager(tmp_path)

    result = asyncio.run(manager._process_sentinel_recommendations())

    assert isinstance(result, dict)
    assert result.get("processed") == 0
    assert result.get("pending") == 0


def test_proactive_execution_respects_explicit_disable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_PROACTIVE_EXECUTION", "0")
    manager = object.__new__(ProactiveManager)

    result = asyncio.run(manager._process_sentinel_recommendations())

    assert result is None
