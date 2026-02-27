from __future__ import annotations

import inspect
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_calendar_tools_module():
    project_root = Path(__file__).resolve().parents[2]
    gw_mcp_root = project_root / "mcp_server_and_tools" / "google_workspace_mcp"
    gw_mcp_root_str = str(gw_mcp_root)
    if gw_mcp_root_str not in sys.path:
        sys.path.append(gw_mcp_root_str)
    import gcalendar.calendar_tools as calendar_tools  # pylint: disable=import-outside-toplevel

    return calendar_tools


def test_custom_reminders_alias_used_when_reminders_absent():
    calendar_tools = _load_calendar_tools_module()
    custom = [{"method": "popup", "minutes": 30}]
    resolved = calendar_tools._coalesce_reminders_input(  # noqa: SLF001
        reminders=None,
        custom_reminders=custom,
        function_name="test_create_event",
    )
    assert resolved == custom


def test_reminders_wins_over_custom_reminders_alias():
    calendar_tools = _load_calendar_tools_module()
    reminders = [{"method": "email", "minutes": 1440}]
    custom = [{"method": "popup", "minutes": 30}]
    resolved = calendar_tools._coalesce_reminders_input(  # noqa: SLF001
        reminders=reminders,
        custom_reminders=custom,
        function_name="test_modify_event",
    )
    assert resolved == reminders


def test_calendar_tool_signatures_include_legacy_custom_reminders_param():
    calendar_tools = _load_calendar_tools_module()
    create_sig = inspect.signature(calendar_tools.create_event.fn)
    modify_sig = inspect.signature(calendar_tools.modify_event.fn)
    create_schema = calendar_tools.create_event.parameters
    modify_schema = calendar_tools.modify_event.parameters

    assert "custom_reminders" in create_sig.parameters
    assert "custom_reminders" in modify_sig.parameters
    assert "custom_reminders" in create_schema.get("properties", {})
    assert "custom_reminders" in modify_schema.get("properties", {})


def test_create_event_guard_rejects_distant_past_by_default():
    calendar_tools = _load_calendar_tools_module()
    start = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    end = (datetime.now(timezone.utc) - timedelta(days=399, hours=23)).isoformat()

    try:
        calendar_tools._guard_event_time_window(  # noqa: SLF001
            start_time=start,
            end_time=end,
            function_name="create_event",
            allow_past_dates=False,
        )
    except ValueError as exc:
        assert "distant past" in str(exc).lower()
    else:
        raise AssertionError("Expected distant-past guard to raise ValueError")


def test_create_event_guard_allows_distant_past_with_explicit_override():
    calendar_tools = _load_calendar_tools_module()
    start = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    end = (datetime.now(timezone.utc) - timedelta(days=399, hours=23)).isoformat()

    calendar_tools._guard_event_time_window(  # noqa: SLF001
        start_time=start,
        end_time=end,
        function_name="create_event",
        allow_past_dates=True,
    )
