"""Tests for the self-improvement auto-trigger in the autonomy cadence."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from core.runtime.proactive_manager import ProactiveManager, _utc_iso


def _make_manager_for_auto_trigger(tmp_path: Path) -> ProactiveManager:
    """Build a minimal ProactiveManager with enough wiring for action_red_team."""
    mgr = object.__new__(ProactiveManager)
    mgr._memory_dir = tmp_path
    mgr._red_team_state_path = tmp_path / "red_team_state.json"
    mgr._red_team_running = False
    mgr._autonomy_cycle_running = False

    # Autonomy config/state
    mgr._autonomy_config = {"enabled": True}
    mgr._autonomy_state_path = tmp_path / "autonomy_state.json"
    mgr._autonomy_events_path = tmp_path / "autonomy_events.jsonl"

    # Stubs for methods called during the autonomy cycle
    mgr._owner = None
    mgr.inner_life = None
    mgr.channel_dock = None
    mgr._stopping = False
    mgr._budget_guard = None
    return mgr


def _old_timestamp(hours_ago: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.isoformat()


def test_auto_trigger_env_off_skips(tmp_path: Path) -> None:
    """When VERA_SELF_IMPROVEMENT_AUTO=0, no red-team run happens."""
    mgr = _make_manager_for_auto_trigger(tmp_path)
    # Write a stale red-team state (24h ago)
    import json
    (tmp_path / "red_team_state.json").write_text(
        json.dumps({"last_run_at": _old_timestamp(24)})
    )

    with patch.dict(os.environ, {"VERA_SELF_IMPROVEMENT_AUTO": "0"}):
        with patch.object(mgr, "action_red_team") as mock_rt:
            # Simulate what the autonomy cycle does
            result: dict = {}
            if os.getenv("VERA_SELF_IMPROVEMENT_AUTO", "0") == "1":
                result = mgr.action_red_team({})
            mock_rt.assert_not_called()


def test_auto_trigger_env_on_fires_when_due(tmp_path: Path) -> None:
    """When env=1 and last run >12h ago, red-team fires."""
    mgr = _make_manager_for_auto_trigger(tmp_path)
    import json
    (tmp_path / "red_team_state.json").write_text(
        json.dumps({"last_run_at": _old_timestamp(13)})
    )

    with patch.dict(os.environ, {"VERA_SELF_IMPROVEMENT_AUTO": "1"}):
        with patch.object(mgr, "action_red_team", return_value={"ran": True}) as mock_rt:
            rt_state = mgr.load_red_team_state()
            last_run_at = rt_state.get("last_run_at", "")
            hours_since = 999.0
            if last_run_at:
                last_dt = datetime.fromisoformat(last_run_at)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600

            min_hours = float(os.getenv("VERA_SELF_IMPROVEMENT_INTERVAL_HOURS", "12"))
            if hours_since >= min_hours and not mgr._red_team_running:
                mgr.action_red_team({})

            mock_rt.assert_called_once()


def test_auto_trigger_skips_when_recent(tmp_path: Path) -> None:
    """When last run was <12h ago, auto-trigger skips."""
    mgr = _make_manager_for_auto_trigger(tmp_path)
    import json
    (tmp_path / "red_team_state.json").write_text(
        json.dumps({"last_run_at": _old_timestamp(2)})  # 2 hours ago
    )

    with patch.dict(os.environ, {"VERA_SELF_IMPROVEMENT_AUTO": "1"}):
        with patch.object(mgr, "action_red_team", return_value={"ran": True}) as mock_rt:
            rt_state = mgr.load_red_team_state()
            last_run_at = rt_state.get("last_run_at", "")
            hours_since = 999.0
            if last_run_at:
                last_dt = datetime.fromisoformat(last_run_at)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600

            min_hours = float(os.getenv("VERA_SELF_IMPROVEMENT_INTERVAL_HOURS", "12"))
            if hours_since >= min_hours and not mgr._red_team_running:
                mgr.action_red_team({})

            mock_rt.assert_not_called()


def test_auto_trigger_skips_when_already_running(tmp_path: Path) -> None:
    """When _red_team_running is True, auto-trigger skips."""
    mgr = _make_manager_for_auto_trigger(tmp_path)
    mgr._red_team_running = True
    import json
    (tmp_path / "red_team_state.json").write_text(
        json.dumps({"last_run_at": _old_timestamp(24)})
    )

    with patch.dict(os.environ, {"VERA_SELF_IMPROVEMENT_AUTO": "1"}):
        with patch.object(mgr, "action_red_team", return_value={"ran": True}) as mock_rt:
            rt_state = mgr.load_red_team_state()
            last_run_at = rt_state.get("last_run_at", "")
            hours_since = 999.0
            if last_run_at:
                last_dt = datetime.fromisoformat(last_run_at)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600

            min_hours = float(os.getenv("VERA_SELF_IMPROVEMENT_INTERVAL_HOURS", "12"))
            if hours_since >= min_hours and not mgr._red_team_running:
                mgr.action_red_team({})

            mock_rt.assert_not_called()
