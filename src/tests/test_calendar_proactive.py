"""Unit tests for calendar proactive checks in ProactiveManager."""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.runtime.proactive_manager import ProactiveManager, _utc_iso, _utc_now
from core.atomic_io import atomic_json_write, safe_json_read


# ---------------------------------------------------------------------------
# Helpers / Stubs
# ---------------------------------------------------------------------------

def _make_manager(tmp_path: Path) -> ProactiveManager:
    """Create a minimal ProactiveManager stub for calendar tests."""
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._memory_dir.mkdir(parents=True, exist_ok=True)
    manager._owner = MagicMock()
    manager._owner.process_messages = AsyncMock(return_value="[]")
    manager._owner._proactive_tool_whitelist = None
    manager.dnd = MagicMock()
    manager.dnd.can_interrupt = MagicMock(return_value=True)
    manager.sentinel = MagicMock()
    manager.sentinel.recommender = MagicMock()
    manager.sentinel.recommender.get_pending_recommendations = MagicMock(return_value=[])
    return manager


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_calendar_check_skips_when_env_off(tmp_path: Path) -> None:
    """With VERA_CALENDAR_PROACTIVE=0, no tool calls should be made."""
    manager = _make_manager(tmp_path)
    with patch.dict(os.environ, {"VERA_CALENDAR_PROACTIVE": "0"}, clear=False):
        result = asyncio.run(
            manager._check_calendar_proactive()
        )
    assert result is None
    manager._owner.process_messages.assert_not_called()


def test_calendar_check_respects_cooldown(tmp_path: Path) -> None:
    """If polled < 30 min ago, should skip."""
    manager = _make_manager(tmp_path)
    # Write a recent poll timestamp
    state_path = tmp_path / "calendar_alerts_state.json"
    state = {"last_poll_utc": _utc_iso(), "alerted_event_ids": []}
    atomic_json_write(state_path, state)

    with patch.dict(os.environ, {"VERA_CALENDAR_PROACTIVE": "1"}, clear=False):
        result = asyncio.run(
            manager._check_calendar_proactive()
        )
    assert result is not None
    assert result.get("skipped") is True
    assert result.get("reason") == "cooldown_active"
    manager._owner.process_messages.assert_not_called()


def test_calendar_check_alerts_upcoming_event(tmp_path: Path) -> None:
    """Mock an event starting in 10 minutes — should send an alert."""
    manager = _make_manager(tmp_path)
    now_utc = _utc_now()
    event_start = (now_utc + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")

    mock_events = json.dumps([{
        "id": "evt_123",
        "summary": "Team standup",
        "start_time": event_start,
        "end_time": (now_utc + timedelta(minutes=40)).isoformat().replace("+00:00", "Z"),
        "location": "Room 42",
    }])

    # First call returns events, second call sends notification
    manager._owner.process_messages = AsyncMock(side_effect=[mock_events, "Notification sent"])

    with patch.dict(os.environ, {
        "VERA_CALENDAR_PROACTIVE": "1",
        "VERA_CALENDAR_ALERT_MINUTES": "15",
    }, clear=False):
        result = asyncio.run(
            manager._check_calendar_proactive()
        )

    assert result is not None
    assert result.get("ok") is True
    assert len(result.get("alerts_sent", [])) == 1
    assert result["alerts_sent"][0]["summary"] == "Team standup"
    # Should have called process_messages twice (once for events, once for notification)
    assert manager._owner.process_messages.call_count == 2


def test_calendar_check_skips_already_alerted(tmp_path: Path) -> None:
    """Same event ID should not be re-alerted."""
    manager = _make_manager(tmp_path)
    now_utc = _utc_now()
    event_start = (now_utc + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")

    # Pre-populate alerted IDs
    state_path = tmp_path / "calendar_alerts_state.json"
    state = {
        "last_poll_utc": "",  # No cooldown
        "alerted_event_ids": ["evt_already"],
        "alerted_event_ids_expiry": (now_utc + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
    }
    atomic_json_write(state_path, state)

    mock_events = json.dumps([{
        "id": "evt_already",
        "summary": "Already alerted meeting",
        "start_time": event_start,
    }])
    manager._owner.process_messages = AsyncMock(return_value=mock_events)

    with patch.dict(os.environ, {
        "VERA_CALENDAR_PROACTIVE": "1",
        "VERA_CALENDAR_ALERT_MINUTES": "15",
    }, clear=False):
        result = asyncio.run(
            manager._check_calendar_proactive()
        )

    assert result is not None
    assert result.get("ok") is True
    assert len(result.get("alerts_sent", [])) == 0
    # Only one call (events fetch), no notification
    assert manager._owner.process_messages.call_count == 1


def test_calendar_check_handles_missing_tool(tmp_path: Path) -> None:
    """If process_messages raises, should return graceful error."""
    manager = _make_manager(tmp_path)
    manager._owner.process_messages = AsyncMock(side_effect=Exception("Tool not found"))

    with patch.dict(os.environ, {"VERA_CALENDAR_PROACTIVE": "1"}, clear=False):
        result = asyncio.run(
            manager._check_calendar_proactive()
        )

    assert result is not None
    assert result.get("ok") is False
    assert result.get("reason") == "calendar_tool_unavailable"
