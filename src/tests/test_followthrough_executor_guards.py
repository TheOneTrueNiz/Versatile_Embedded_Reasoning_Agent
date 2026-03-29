"""Guards for followthrough evidence classification."""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path
import json
import subprocess
import sys


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


def test_followthrough_due_probe_marks_overdue_default_window_action_due():
    mod = _load_followthrough_module()
    now = dt.datetime.now().replace(microsecond=0)
    commitment = {
        "commitment_id": "c3:1",
        "conversation_id": "c3",
        "at_local": now - dt.timedelta(hours=10),
        "schedule_start_local": "",
        "schedule_end_local": "",
    }
    entry = {"status": "pending", "last_attempt_utc": ""}
    action = {
        "action_id": "c3:1",
        "conversation_id": "c3",
        "workflow_name": "autonomy_followthrough",
        "workflow_required_tools": [],
        "schedule_start_local": "",
        "schedule_end_local": "",
        "completed_via_executor": False,
        "status": "planned",
        "status_reason": "new_commitment",
        "evidence": {},
    }
    workflows = {"autonomy_followthrough": {"default_window_hours": 8.0}}

    mod._update_action_runtime_state(
        commitment=commitment,
        entry=entry,
        action=action,
        now_local=now,
        grace_cutoff=now - dt.timedelta(minutes=30),
        action_events_path=None,
        tool_calls_by_conversation={"c3": []},
        decisions_by_conversation={"c3": []},
        workflow_specs=workflows,
        fallback_window_hours=8.0,
    )
    decision = mod._followthrough_due_decision(
        commitment=commitment,
        entry=entry,
        action=action,
        now_local=now,
        now_utc=dt.datetime.now(dt.timezone.utc),
        grace_cutoff=now - dt.timedelta(minutes=30),
        cooldown=dt.timedelta(minutes=45),
    )

    assert decision["due"] is True
    assert decision["reason"] == "default_window_elapsed"
    assert decision["minutes_overdue"] >= 119


def test_followthrough_due_probe_respects_attempt_cooldown():
    mod = _load_followthrough_module()
    now = dt.datetime.now().replace(microsecond=0)
    last_attempt_utc = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    commitment = {
        "commitment_id": "c4:1",
        "conversation_id": "c4",
        "at_local": now - dt.timedelta(hours=10),
        "schedule_start_local": "",
        "schedule_end_local": "",
    }
    entry = {"status": "pending", "last_attempt_utc": last_attempt_utc}
    action = {
        "action_id": "c4:1",
        "conversation_id": "c4",
        "workflow_name": "autonomy_followthrough",
        "workflow_required_tools": [],
        "schedule_start_local": "",
        "schedule_end_local": "",
        "completed_via_executor": False,
        "status": "planned",
        "status_reason": "new_commitment",
        "evidence": {},
    }
    workflows = {"autonomy_followthrough": {"default_window_hours": 8.0}}

    mod._update_action_runtime_state(
        commitment=commitment,
        entry=entry,
        action=action,
        now_local=now,
        grace_cutoff=now - dt.timedelta(minutes=30),
        action_events_path=None,
        tool_calls_by_conversation={"c4": []},
        decisions_by_conversation={"c4": []},
        workflow_specs=workflows,
        fallback_window_hours=8.0,
    )
    decision = mod._followthrough_due_decision(
        commitment=commitment,
        entry=entry,
        action=action,
        now_local=now,
        now_utc=dt.datetime.now(dt.timezone.utc),
        grace_cutoff=now - dt.timedelta(minutes=30),
        cooldown=dt.timedelta(minutes=45),
    )

    assert decision["due"] is False
    assert decision["reason"] == "attempt_cooldown_active"
    assert int(decision["cooldown_remaining_seconds"]) > 0


def test_followthrough_due_probe_does_not_retry_missed_actions():
    mod = _load_followthrough_module()
    now = dt.datetime.now().replace(microsecond=0)
    commitment = {
        "commitment_id": "c5:1",
        "conversation_id": "c5",
        "at_local": now - dt.timedelta(hours=10),
        "schedule_start_local": "",
        "schedule_end_local": "",
    }
    last_attempt_utc = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    entry = {"status": "pending", "last_attempt_utc": last_attempt_utc, "attempt_count": 1}
    action = {
        "action_id": "c5:1",
        "conversation_id": "c5",
        "workflow_name": "autonomy_followthrough",
        "workflow_required_tools": [],
        "schedule_start_local": "",
        "schedule_end_local": "",
        "completed_via_executor": False,
        "status": "missed",
        "status_reason": "default_window_elapsed_without_evidence",
        "evidence": {"window_end_local": (now - dt.timedelta(hours=2)).isoformat(timespec="seconds")},
    }

    decision = mod._followthrough_due_decision(
        commitment=commitment,
        entry=entry,
        action=action,
        now_local=now,
        now_utc=dt.datetime.now(dt.timezone.utc),
        grace_cutoff=now - dt.timedelta(minutes=30),
        cooldown=dt.timedelta(minutes=45),
    )

    assert decision["due"] is False
    assert decision["reason"] == "action_missed"


def test_scan_commitments_uses_fixed_now_override_window(tmp_path: Path):
    mod = _load_followthrough_module()
    now = dt.datetime(2026, 3, 7, 12, 0, 0)
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir(exist_ok=True)
    ts = dt.datetime(2026, 3, 7, 11, 30, 0).timestamp()
    (transcripts_dir / "conv_a.jsonl").write_text(
        json.dumps(
            {
                "role": "assistant",
                "timestamp": ts,
                "content": "Plan set: summary post-run queued for 11:45 local.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rows = mod._scan_commitments(transcripts_dir, lookback_hours=2.0, now_local=now)
    assert len(rows) == 1
    assert rows[0]["commitment_id"] == f"conv_a:{int(ts)}"


def test_scan_commitments_matches_natural_future_commitment_language(tmp_path: Path):
    mod = _load_followthrough_module()
    now = dt.datetime(2026, 3, 7, 12, 0, 0)
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir(exist_ok=True)
    ts = dt.datetime(2026, 3, 7, 11, 45, 0).timestamp()
    (transcripts_dir / "conv_b.jsonl").write_text(
        json.dumps(
            {
                "role": "assistant",
                "timestamp": ts,
                "content": "I'll send a summary when completed and check back later today.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rows = mod._scan_commitments(transcripts_dir, lookback_hours=2.0, now_local=now)
    assert len(rows) == 1
    assert rows[0]["commitment_id"] == f"conv_b:{int(ts)}"


def test_augment_commitments_with_open_actions_carries_forward_old_unresolved_action():
    mod = _load_followthrough_module()
    now = dt.datetime(2026, 3, 12, 0, 0, 0)
    commitments = []
    carried = mod._augment_commitments_with_open_actions(
        commitments,
        ledger={
            "conv_old:1": {
                "status": "pending",
                "commitment_ts_epoch": (now - dt.timedelta(days=3)).timestamp(),
                "commitment_at_local": (now - dt.timedelta(days=3)).isoformat(timespec="seconds"),
                "conversation_id": "conv_old",
                "source": "transcript:1",
                "content_excerpt": "I'll follow up tomorrow.",
            }
        },
        actions={
            "conv_old:1": {
                "status": "planned",
                "workflow_name": "autonomy_followthrough",
                "commitment_at_local": (now - dt.timedelta(days=3)).isoformat(timespec="seconds"),
                "conversation_id": "conv_old",
                "source": "transcript:1",
                "content_excerpt": "I'll follow up tomorrow.",
            }
        },
    )
    assert len(carried) == 1
    assert carried[0]["commitment_id"] == "conv_old:1"


def test_reconcile_action_terminal_statuses_aligns_action_with_completed_ledger():
    mod = _load_followthrough_module()
    actions = {
        "conv_old:1": {
            "status": "planned",
            "status_reason": "legacy_completed_without_verification",
        }
    }
    ledger = {
        "conv_old:1": {
            "status": "completed",
            "last_attempt_result": {},
        }
    }

    mod._reconcile_action_terminal_statuses(actions=actions, ledger=ledger, action_events_path=None)

    assert actions["conv_old:1"]["status"] == "completed"
    assert actions["conv_old:1"]["status_reason"] == "legacy_completed_without_verification"


def test_update_action_runtime_state_marks_legacy_completed_entries_terminal():
    mod = _load_followthrough_module()
    now = dt.datetime.now().replace(microsecond=0)
    commitment = {
        "commitment_id": "legacy:1",
        "conversation_id": "legacy",
        "at_local": now - dt.timedelta(days=5),
        "schedule_start_local": "",
        "schedule_end_local": "",
    }
    entry = {"status": "completed", "last_attempt_result": {}}
    action = {
        "action_id": "legacy:1",
        "conversation_id": "legacy",
        "workflow_name": "autonomy_followthrough",
        "workflow_required_tools": [],
        "schedule_start_local": "",
        "schedule_end_local": "",
        "completed_via_executor": False,
        "status": "planned",
        "status_reason": "legacy_completed_without_verification",
        "evidence": {},
    }

    mod._update_action_runtime_state(
        commitment=commitment,
        entry=entry,
        action=action,
        now_local=now,
        grace_cutoff=now - dt.timedelta(minutes=30),
        action_events_path=None,
        tool_calls_by_conversation={"legacy": []},
        decisions_by_conversation={"legacy": []},
        workflow_specs={"autonomy_followthrough": {"default_window_hours": 8.0}},
        fallback_window_hours=8.0,
    )

    assert action["status"] == "completed"
    assert action["status_reason"] == "legacy_completed_without_verification"


def test_followthrough_probe_due_supports_transcript_override_and_fixed_clock(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    ts = dt.datetime(2026, 3, 7, 2, 0, 0).timestamp()
    commitment_id = f"conv_probe:{int(ts)}"
    (transcripts_dir / "conv_probe.jsonl").write_text(
        json.dumps(
            {
                "role": "assistant",
                "timestamp": ts,
                "content": "Plan set: summary post-run for autonomy engaged.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        str(root / "scripts" / "vera_followthrough_executor.py"),
        "--vera-root",
        str(root),
        "--transcripts-dir",
        str(transcripts_dir),
        "--state-file",
        str(tmp_path / "state.json"),
        "--events-log",
        str(tmp_path / "events.jsonl"),
        "--actions-file",
        str(tmp_path / "actions.json"),
        "--action-events-log",
        str(tmp_path / "action_events.jsonl"),
        "--workflow-catalog-file",
        str(tmp_path / "workflows.json"),
        "--learned-workflows-file",
        str(tmp_path / "learned.json"),
        "--workflow-stats-file",
        str(tmp_path / "stats.json"),
        "--lock-file",
        str(tmp_path / "executor.lock"),
        "--probe-due",
        "--now-override",
        "2026-03-07T12:00:00",
        "--only-commitment-id",
        commitment_id,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=str(root))

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["probe_due"] is True
    assert payload["due_count"] == 1
    assert payload["due_actions"][0]["commitment_id"] == commitment_id
