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
    manager._owner._internal_tool_call_handler = AsyncMock(
        return_value={
            "content": [{"type": "text", "text": "No events found in calendar 'primary' for jeffnyzio@gmail.com for the specified time range."}],
            "structuredContent": {"result": "No events found in calendar 'primary' for jeffnyzio@gmail.com for the specified time range."},
            "isError": False,
        }
    )
    manager._owner._proactive_tool_whitelist = None
    manager.dnd = MagicMock()
    manager.dnd.can_interrupt = MagicMock(return_value=True)
    manager.sentinel = MagicMock()
    manager.sentinel.recommender = MagicMock()
    manager.sentinel.recommender.get_pending_recommendations = MagicMock(return_value=[])
    manager._autonomy_config = {"pulse_interval_seconds": 300}
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
    manager._owner._internal_tool_call_handler.assert_not_called()


def test_calendar_check_respects_cooldown(tmp_path: Path) -> None:
    """If polled within the computed cooldown window, should skip."""
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
    assert result.get("cooldown_seconds") == 300
    manager._owner._internal_tool_call_handler.assert_not_called()


def test_calendar_check_default_cooldown_tracks_alert_window(tmp_path: Path) -> None:
    """Default cooldown should not exceed the alert window or pulse cadence."""
    manager = _make_manager(tmp_path)
    manager._autonomy_config = {"pulse_interval_seconds": 600}

    state_path = tmp_path / "calendar_alerts_state.json"
    recent_poll = (_utc_now() - timedelta(minutes=9)).isoformat().replace("+00:00", "Z")
    atomic_json_write(state_path, {"last_poll_utc": recent_poll, "alerted_event_ids": []})

    with patch.dict(os.environ, {
        "VERA_CALENDAR_PROACTIVE": "1",
        "VERA_CALENDAR_ALERT_MINUTES": "10",
    }, clear=False):
        result = asyncio.run(manager._check_calendar_proactive())

    assert result is not None
    assert result.get("skipped") is True
    assert result.get("cooldown_seconds") == 600
    manager._owner._internal_tool_call_handler.assert_not_called()


def test_calendar_check_alerts_upcoming_event(tmp_path: Path) -> None:
    """Mock an event starting in 10 minutes — should send an alert."""
    manager = _make_manager(tmp_path)
    now_utc = _utc_now()
    event_start = (now_utc + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")

    mock_events = (
        "Successfully retrieved 1 events from calendar 'primary' for jeffnyzio@gmail.com:\n"
        f'- "Team standup" (Starts: {event_start}, Ends: {(now_utc + timedelta(minutes=40)).isoformat().replace("+00:00", "Z")})\n'
        "  Description: No Description\n"
        "  Location: Room 42\n"
        "  Attendees: None\n"
        "  Attendee Details: None\n"
        "  ID: evt_123 | Link: https://example.test/event"
    )

    manager._owner._internal_tool_call_handler = AsyncMock(
        side_effect=[
            {"structuredContent": {"result": mock_events}, "content": [{"type": "text", "text": mock_events}]},
            {"structuredContent": {"result": "Native push sent."}, "content": [{"type": "text", "text": "Native push sent."}]},
        ]
    )

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
    assert manager._owner._internal_tool_call_handler.call_count == 2


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

    mock_events = (
        "Successfully retrieved 1 events from calendar 'primary' for jeffnyzio@gmail.com:\n"
        f'- "Already alerted meeting" (Starts: {event_start}, Ends: {(now_utc + timedelta(minutes=30)).isoformat().replace("+00:00", "Z")})\n'
        "  Description: No Description\n"
        "  Location: No Location\n"
        "  Attendees: None\n"
        "  Attendee Details: None\n"
        "  ID: evt_already | Link: https://example.test/event"
    )
    manager._owner._internal_tool_call_handler = AsyncMock(
        return_value={"structuredContent": {"result": mock_events}, "content": [{"type": "text", "text": mock_events}]}
    )

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
    assert manager._owner._internal_tool_call_handler.call_count == 1


def test_calendar_check_handles_missing_tool(tmp_path: Path) -> None:
    """If the direct tool call raises, should return graceful error."""
    manager = _make_manager(tmp_path)
    manager._owner._internal_tool_call_handler = AsyncMock(side_effect=Exception("Tool not found"))

    with patch.dict(os.environ, {"VERA_CALENDAR_PROACTIVE": "1"}, clear=False):
        result = asyncio.run(
            manager._check_calendar_proactive()
        )

    assert result is not None
    assert result.get("ok") is False
    assert result.get("reason") == "calendar_tool_unavailable"


def test_parse_calendar_event_listing_extracts_structured_rows(tmp_path: Path) -> None:
    text = (
        "Successfully retrieved 2 events from calendar 'primary' for jeffnyzio@gmail.com:\n"
        '- "Team standup" (Starts: 2026-03-07T18:00:00Z, Ends: 2026-03-07T18:30:00Z)\n'
        "  Description: No Description\n"
        "  Location: Room 42\n"
        "  Attendees: None\n"
        "  Attendee Details: None\n"
        "  ID: evt_123 | Link: https://example.test/1\n"
        '- "Planning block" (Starts: 2026-03-07T19:00:00Z, Ends: 2026-03-07T19:30:00Z)\n'
        "  Description: No Description\n"
        "  Location: No Location\n"
        "  Attendees: None\n"
        "  Attendee Details: None\n"
        "  ID: evt_456 | Link: https://example.test/2"
    )

    rows = ProactiveManager._parse_calendar_event_listing(text)

    assert rows == [
        {
            "summary": "Team standup",
            "start_time": "2026-03-07T18:00:00Z",
            "end_time": "2026-03-07T18:30:00Z",
            "location": "Room 42",
            "id": "evt_123",
            "link": "https://example.test/1",
        },
        {
            "summary": "Planning block",
            "start_time": "2026-03-07T19:00:00Z",
            "end_time": "2026-03-07T19:30:00Z",
            "location": "No Location",
            "id": "evt_456",
            "link": "https://example.test/2",
        },
    ]
