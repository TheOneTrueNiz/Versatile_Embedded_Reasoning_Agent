"""Guards for followthrough evidence classification."""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path


def _load_followthrough_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "vera_followthrough_executor.py"
    spec = importlib.util.spec_from_file_location("vera_followthrough_executor", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blocked_attempts_do_not_count_as_execution_evidence():
    mod = _load_followthrough_module()
    now = dt.datetime.now().replace(microsecond=0)
    commitment = {
        "conversation_id": "c1",
        "at_local": now - dt.timedelta(minutes=10),
        "schedule_start_local": "",
        "schedule_end_local": "",
    }
    tool_calls = {"c1": []}
    decisions = {
        "c1": [{"at": now - dt.timedelta(minutes=3), "tool_name": "send_gmail_message"}],
    }

    evidence = mod._count_window_evidence(
        commitment=commitment,
        tool_calls_by_conversation=tool_calls,
        decisions_by_conversation=decisions,
        default_window_hours=1.0,
    )

    assert evidence["tool_call_count"] == 0
    assert evidence["blocked_attempt_count"] == 1
    assert evidence["has_blocked_evidence"] is True
    assert evidence["has_execution_evidence"] is False


def test_real_tool_call_counts_as_execution_evidence():
    mod = _load_followthrough_module()
    now = dt.datetime.now().replace(microsecond=0)
    commitment = {
        "conversation_id": "c2",
        "at_local": now - dt.timedelta(minutes=10),
        "schedule_start_local": "",
        "schedule_end_local": "",
    }
    tool_calls = {
        "c2": [{"at": now - dt.timedelta(minutes=2), "tool_name": "send_mobile_push"}],
    }
    decisions = {"c2": []}

    evidence = mod._count_window_evidence(
        commitment=commitment,
        tool_calls_by_conversation=tool_calls,
        decisions_by_conversation=decisions,
        default_window_hours=1.0,
    )

    assert evidence["tool_call_count"] == 1
    assert evidence["has_execution_evidence"] is True
    assert evidence["has_blocked_evidence"] is False


def test_execution_evidence_step_marks_blocked_attempts_as_running():
    mod = _load_followthrough_module()
    now = dt.datetime.now().replace(microsecond=0)
    action = {"status": "planned", "status_reason": "awaiting_execution_evidence"}
    evidence = {"has_execution_evidence": False, "blocked_attempt_count": 2}

    status, reason = mod._step_status_for_trigger(
        "execution_evidence",
        action=action,
        evidence=evidence,
        now_local=now,
    )

    assert status == "running"
    assert reason == "blocked_attempt_recorded"
