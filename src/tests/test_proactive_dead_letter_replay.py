from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.runtime.proactive_manager import ProactiveManager, _utc_iso


class _RunplaneStub:
    def __init__(self, dead_letters, *, replay_ok: bool = True, delivered_runs=None) -> None:
        self._dead_letters = list(dead_letters)
        self._delivered_runs = list(delivered_runs or [])
        self.replay_ok = replay_ok
        self.replay_calls = []
        self.mark_calls = []

    def list_dead_letters(self, *, limit: int = 200):
        return list(self._dead_letters)[:limit]

    def list_runs(self, *, limit: int = 200, status_filter: str = "", job_id: str = ""):
        rows = list(self._delivered_runs)
        if status_filter:
            rows = [row for row in rows if str(row.get("status") or "").strip().lower() == status_filter]
        if job_id:
            rows = [row for row in rows if str(row.get("job_id") or "").strip() == job_id]
        return rows[:limit]

    def replay_dead_letter(self, *, run_id: str = "", job_id: str = "", trigger: str = "operator_replay"):
        self.replay_calls.append((run_id, job_id, trigger))
        if self.replay_ok:
            return {"ok": True, "job_id": job_id or "job-1", "replayed_run_id": run_id}
        return {"ok": False, "reason": "replay_failed"}

    def mark_run_status(
        self,
        *,
        run_id: str,
        status: str,
        source: str = "operator",
        note: str = "",
    ):
        self.mark_calls.append((run_id, status, source, note))
        return {"ok": True, "run_id": run_id, "run_status": status}


def _make_manager(tmp_path: Path, runplane: _RunplaneStub) -> ProactiveManager:
    manager = object.__new__(ProactiveManager)
    manager._memory_dir = Path(tmp_path)
    manager._failure_learning_event_log = manager._memory_dir / "failure_learning_events.jsonl"
    manager._autonomy_event_log = manager._memory_dir / "autonomy_cadence_events.jsonl"
    manager.runplane = runplane
    return manager


def test_auto_replay_dead_letters_replays_allowed_classes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_AUTO_REPLAY", "1")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_REPLAY_MAX_PER_CYCLE", "2")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_REPLAY_COOLDOWN_SECONDS", "30")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_REPLAY_ALLOW", "delivery_unroutable,transport_error")

    runplane = _RunplaneStub(
        [
            {"job_id": "job-1", "run_id": "run-1", "failure_class": "delivery_unroutable"},
        ]
    )
    manager = _make_manager(tmp_path, runplane)
    state = {}

    result = manager._auto_replay_dead_letters(state)

    assert result.get("enabled") is True
    assert result.get("replayed") == 1
    assert runplane.replay_calls == [("run-1", "", "autonomy_auto_replay")]
    assert "dead_letter_replay" in state
    assert "job-1" in state["dead_letter_replay"]
    assert manager._failure_learning_event_log.exists()


def test_auto_replay_dead_letters_respects_cooldown(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_AUTO_REPLAY", "1")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_REPLAY_COOLDOWN_SECONDS", "1800")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_REPLAY_ALLOW", "delivery_unroutable")

    runplane = _RunplaneStub(
        [
            {"job_id": "job-1", "run_id": "run-1", "failure_class": "delivery_unroutable"},
        ]
    )
    manager = _make_manager(tmp_path, runplane)
    state = {"dead_letter_replay": {"job-1": _utc_iso()}}

    result = manager._auto_replay_dead_letters(state)

    assert result.get("replayed") == 0
    assert result.get("skipped_cooldown") == 1
    assert runplane.replay_calls == []


def test_auto_replay_dead_letters_skips_disallowed_failure_class(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_AUTO_REPLAY", "1")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_REPLAY_ALLOW", "delivery_unroutable")

    runplane = _RunplaneStub(
        [
            {"job_id": "job-2", "run_id": "run-2", "failure_class": "permanent_missing_dependency"},
        ]
    )
    manager = _make_manager(tmp_path, runplane)
    state = {}

    result = manager._auto_replay_dead_letters(state)

    assert result.get("replayed") == 0
    assert result.get("skipped_disallowed") == 1
    assert runplane.replay_calls == []


def test_auto_replay_failure_logs_event_when_replay_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_AUTO_REPLAY", "1")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_REPLAY_ALLOW", "delivery_unroutable")

    runplane = _RunplaneStub(
        [{"job_id": "job-3", "run_id": "run-3", "failure_class": "delivery_unroutable"}],
        replay_ok=False,
    )
    manager = _make_manager(tmp_path, runplane)
    state = {}

    result = manager._auto_replay_dead_letters(state)

    assert result.get("replay_failures") == 1
    assert manager._failure_learning_event_log.exists()
    lines = manager._failure_learning_event_log.read_text(encoding="utf-8").splitlines()
    assert lines
    row = json.loads(lines[-1])
    assert row.get("type") == "dead_letter_auto_replay"
    assert row.get("ok") is False


def test_auto_replay_escalates_when_max_replays_per_job_reached(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_AUTO_REPLAY", "1")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_REPLAY_ALLOW", "delivery_unroutable")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_MAX_REPLAYS_PER_JOB", "2")
    runplane = _RunplaneStub(
        [{"job_id": "job-4", "run_id": "run-4", "failure_class": "delivery_unroutable"}],
        replay_ok=True,
    )
    manager = _make_manager(tmp_path, runplane)
    state = {
        "dead_letter_replay": {
            "job-4": {
                "last_replay_utc": _utc_iso(),
                "replay_count": 2,
                "consecutive_replay_failures": 0,
                "escalated": False,
            }
        }
    }

    result = manager._auto_replay_dead_letters(state)

    assert result.get("replayed") == 0
    assert result.get("escalated_jobs") == 1
    assert runplane.replay_calls == []
    assert runplane.mark_calls
    assert state["dead_letter_replay"]["job-4"]["escalated"] is True


def test_auto_replay_escalates_after_consecutive_failures(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_AUTO_REPLAY", "1")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_REPLAY_ALLOW", "delivery_unroutable")
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_REPLAY_FAIL_ESCALATION_THRESHOLD", "1")
    runplane = _RunplaneStub(
        [{"job_id": "job-5", "run_id": "run-5", "failure_class": "delivery_unroutable"}],
        replay_ok=False,
    )
    manager = _make_manager(tmp_path, runplane)
    state = {}

    result = manager._auto_replay_dead_letters(state)

    assert result.get("replay_failures") == 1
    assert result.get("escalated_jobs") == 1
    assert runplane.mark_calls
    assert state["dead_letter_replay"]["job-5"]["escalated"] is True


def test_dead_letter_replay_slo_audit_flags_backlog_violation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_AUTONOMY_DEAD_LETTER_SLO_MAX_BACKLOG", "1")
    runplane = _RunplaneStub(
        [
            {"job_id": "job-6", "run_id": "run-6", "failure_class": "delivery_unroutable"},
            {"job_id": "job-7", "run_id": "run-7", "failure_class": "delivery_unroutable"},
        ]
    )
    manager = _make_manager(tmp_path, runplane)
    state = {}
    replay_summary = {
        "attempted": 1,
        "replayed": 1,
        "replay_failures": 0,
        "escalated_jobs": 0,
    }

    audit = manager._audit_dead_letter_replay_slo(replay_summary, state)

    assert audit.get("pass") is False
    assert any("dead_letter_backlog" in row for row in audit.get("violations", []))
    assert "last_dead_letter_replay_slo" in state


def test_auto_escalate_stale_deliveries_marks_old_runs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_AUTONOMY_ACK_SLA_ESCALATION_ENABLED", "1")
    monkeypatch.setenv("VERA_AUTONOMY_ACK_SLA_SECONDS", "60")
    monkeypatch.setenv("VERA_AUTONOMY_ACK_SLA_MAX_ESCALATIONS_PER_CYCLE", "2")
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=180)).isoformat().replace("+00:00", "Z")
    runplane = _RunplaneStub(
        [],
        delivered_runs=[
            {
                "run_id": "run-delivery-1",
                "job_id": "delivery.reachout.1",
                "status": "delivered",
                "kind": "delivery_reachout",
                "finished_at_utc": old_ts,
                "result": {"delivered_to": ["fcm"], "ack_expected": True, "ack_channels": ["fcm"]},
            }
        ],
    )
    manager = _make_manager(tmp_path, runplane)
    state = {}

    result = manager._auto_escalate_stale_deliveries(state)

    assert result.get("enabled") is True
    assert result.get("escalated") == 1
    assert runplane.mark_calls
    assert state.get("last_delivery_escalation_result", {}).get("escalated") == 1


def test_auto_escalate_stale_deliveries_skips_recent_and_non_delivery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_AUTONOMY_ACK_SLA_ESCALATION_ENABLED", "1")
    monkeypatch.setenv("VERA_AUTONOMY_ACK_SLA_SECONDS", "120")
    recent_ts = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat().replace("+00:00", "Z")
    runplane = _RunplaneStub(
        [],
        delivered_runs=[
            {
                "run_id": "run-recent",
                "job_id": "delivery.reachout.recent",
                "status": "delivered",
                "kind": "delivery_reachout",
                "finished_at_utc": recent_ts,
                "result": {"delivered_to": ["fcm"], "ack_expected": True, "ack_channels": ["fcm"]},
            },
            {
                "run_id": "run-nondelivery",
                "job_id": "executor.week1",
                "status": "delivered",
                "kind": "executor",
                "finished_at_utc": old_ts,
            },
        ],
    )
    manager = _make_manager(tmp_path, runplane)
    state = {}

    result = manager._auto_escalate_stale_deliveries(state)

    assert result.get("escalated") == 0
    assert result.get("skipped_not_due", 0) >= 1
    assert result.get("skipped_non_delivery", 0) >= 1
    assert runplane.mark_calls == []


def test_auto_escalate_stale_deliveries_skips_non_ackable_api_only_runs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_AUTONOMY_ACK_SLA_ESCALATION_ENABLED", "1")
    monkeypatch.setenv("VERA_AUTONOMY_ACK_SLA_SECONDS", "60")
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat().replace("+00:00", "Z")
    runplane = _RunplaneStub(
        [],
        delivered_runs=[
            {
                "run_id": "run-api-only",
                "job_id": "delivery.reachout.api_only",
                "status": "delivered",
                "kind": "delivery_reachout",
                "finished_at_utc": old_ts,
                "result": {"delivered_to": ["api"], "ack_expected": False},
            }
        ],
    )
    manager = _make_manager(tmp_path, runplane)
    state = {}

    result = manager._auto_escalate_stale_deliveries(state)

    assert result.get("escalated") == 0
    assert result.get("skipped_ack_not_expected") == 1
    assert runplane.mark_calls == []
