from __future__ import annotations

from datetime import datetime, timezone

from api.server import (
    _build_temporal_scheduling_directive,
    _needs_temporal_scheduling_guard,
)


def test_temporal_guard_detects_relative_scheduling_requests():
    text = "Create a calendar event for today in 2 hours with a reminder."
    assert _needs_temporal_scheduling_guard(text) is True


def test_temporal_guard_ignores_non_scheduling_text():
    text = "Summarize the latest MCP docs and explain tradeoffs."
    assert _needs_temporal_scheduling_guard(text) is False


def test_temporal_guard_ignores_absolute_scheduling_without_relative_terms():
    text = "Create a calendar event for 2026-03-04 at 10:00."
    assert _needs_temporal_scheduling_guard(text) is False


def test_temporal_directive_includes_datetime_anchor():
    now_local = datetime(2026, 2, 24, 10, 30, tzinfo=timezone.utc)
    directive = _build_temporal_scheduling_directive(now_local)
    assert "Current local datetime anchor" in directive
    assert "2026-02-24" in directive
    assert ("+00:00" in directive) or ("-06:00" in directive) or ("-05:00" in directive)
