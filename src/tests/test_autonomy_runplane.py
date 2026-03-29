from __future__ import annotations

import json

from core.runtime.autonomy_runplane import AutonomyRunplane


def test_runplane_serializes_lane_and_marks_success(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")
    started = runplane.begin_run(
        job_id="executor.followthrough",
        lane_key="executor:followthrough",
        trigger="test",
        kind="executor",
        max_attempts=3,
    )
    assert started.get("ok") is True
    run_id = str(started.get("run_id"))

    busy = runplane.begin_run(
        job_id="executor.followthrough",
        lane_key="executor:followthrough",
        trigger="test",
        kind="executor",
        max_attempts=3,
    )
    assert busy.get("ok") is False
    assert busy.get("reason") == "lane_busy"

    completed = runplane.complete_run(
        job_id="executor.followthrough",
        run_id=run_id,
        ok=True,
        status="delivered",
        result={"status": "ok"},
    )
    assert completed.get("ok") is True
    assert completed.get("job_state") == "delivered"
    assert completed.get("run_status") == "delivered"

    snapshot = runplane.status_snapshot()
    assert snapshot.get("active_lanes") == {}
    jobs = runplane.list_jobs(limit=10)
    assert jobs
    assert jobs[0].get("state") == "delivered"


def test_runplane_dead_letters_after_non_retryable_limit(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")
    started = runplane.begin_run(
        job_id="executor.week1",
        lane_key="executor:week1",
        trigger="test",
        kind="executor",
        max_attempts=1,
    )
    assert started.get("ok") is True

    completed = runplane.complete_run(
        job_id="executor.week1",
        run_id=str(started.get("run_id")),
        ok=False,
        retryable=False,
        failure_class="permanent_missing_dependency",
        result={"stderr": "missing command"},
    )
    assert completed.get("ok") is True
    assert completed.get("run_status") == "dead_letter"
    assert completed.get("job_state") == "dead_letter"

    dead_letters = runplane.list_dead_letters(limit=10)
    assert len(dead_letters) == 1
    assert dead_letters[0].get("job_id") == "executor.week1"
    assert dead_letters[0].get("failure_class") == "permanent_missing_dependency"


def test_runplane_ack_marks_job_and_run(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")
    started = runplane.begin_run(
        job_id="reachout.push",
        lane_key="delivery:push",
        trigger="test",
        kind="delivery",
        max_attempts=2,
    )
    assert started.get("ok") is True
    run_id = str(started.get("run_id"))

    delivered = runplane.complete_run(
        job_id="reachout.push",
        run_id=run_id,
        ok=True,
        status="delivered",
        result={"delivered_to": ["push"]},
    )
    assert delivered.get("ok") is True

    acked = runplane.ack_run(run_id, ack_type="opened", source="native_ack")
    assert acked.get("ok") is True
    assert acked.get("job_state") == "acked"

    runs = runplane.list_runs(limit=10, job_id="reachout.push")
    assert runs
    assert runs[0].get("status") == "acked"
    assert runs[0].get("ack_type") == "opened"


def test_runplane_replay_dead_letter_requeues_job(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")
    started = runplane.begin_run(
        job_id="executor.retryable",
        lane_key="executor:retryable",
        trigger="test",
        kind="executor",
        max_attempts=1,
    )
    assert started.get("ok") is True
    dead = runplane.complete_run(
        job_id="executor.retryable",
        run_id=str(started.get("run_id")),
        ok=False,
        retryable=False,
        failure_class="transport_error",
        result={"stderr": "network down"},
    )
    assert dead.get("run_status") == "dead_letter"

    replayed = runplane.replay_dead_letter(job_id="executor.retryable", trigger="test_replay")
    assert replayed.get("ok") is True
    assert replayed.get("job_state") == "due"

    jobs = runplane.list_jobs(limit=10, state_filter="due")
    assert any(row.get("job_id") == "executor.retryable" for row in jobs)


def test_runplane_ack_accepts_external_alias_run_id(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")
    started = runplane.begin_run(
        job_id="delivery.reachout.test",
        lane_key="delivery:reachout:test",
        trigger="innerlife.reached_out",
        kind="delivery_reachout",
        metadata={"external_run_id": "inner_run_123", "innerlife_run_id": "inner_run_123"},
    )
    assert started.get("ok") is True

    delivered = runplane.complete_run(
        job_id="delivery.reachout.test",
        run_id=str(started.get("run_id")),
        ok=True,
        status="delivered",
        result={"innerlife_run_id": "inner_run_123", "delivered_to": ["push"]},
    )
    assert delivered.get("ok") is True

    acked = runplane.ack_run("inner_run_123", ack_type="opened", source="native_ack")
    assert acked.get("ok") is True
    assert acked.get("job_state") == "acked"


def test_runplane_mark_run_status_updates_job_and_run(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")
    started = runplane.begin_run(
        job_id="delivery.reachout.mark",
        lane_key="delivery:reachout:mark",
        trigger="innerlife.reached_out",
        kind="delivery_reachout",
    )
    assert started.get("ok") is True
    run_id = str(started.get("run_id"))
    delivered = runplane.complete_run(
        job_id="delivery.reachout.mark",
        run_id=run_id,
        ok=True,
        status="delivered",
    )
    assert delivered.get("ok") is True

    escalated = runplane.mark_run_status(
        run_id=run_id,
        status="escalated",
        source="operator",
        note="waiting for user response",
    )
    assert escalated.get("ok") is True
    assert escalated.get("run_status") == "escalated"
    assert escalated.get("job_state") == "escalated"

    closed = runplane.mark_run_status(
        run_id=run_id,
        status="closed",
        source="operator",
    )
    assert closed.get("ok") is True
    assert closed.get("run_status") == "closed"
    assert closed.get("job_state") == "closed"


def test_runplane_slo_ack_rate_uses_only_ack_eligible_deliveries(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")

    api_only = runplane.begin_run(
        job_id="delivery.reachout.api_only",
        lane_key="delivery:reachout:api_only",
        trigger="innerlife.reached_out",
        kind="delivery_reachout",
        metadata={"ack_expected": False},
    )
    assert api_only.get("ok") is True
    runplane.complete_run(
        job_id="delivery.reachout.api_only",
        run_id=str(api_only.get("run_id")),
        ok=True,
        status="delivered",
        result={"delivered_to": ["api"], "ack_expected": False},
    )

    ackable = runplane.begin_run(
        job_id="delivery.reachout.push",
        lane_key="delivery:reachout:push",
        trigger="innerlife.reached_out",
        kind="delivery_reachout",
        metadata={"ack_expected": True, "ack_channels": ["fcm"]},
    )
    assert ackable.get("ok") is True
    ackable_run_id = str(ackable.get("run_id"))
    runplane.complete_run(
        job_id="delivery.reachout.push",
        run_id=ackable_run_id,
        ok=True,
        status="delivered",
        result={"delivered_to": ["fcm"], "ack_expected": True, "ack_channels": ["fcm"]},
    )
    runplane.ack_run(ackable_run_id, ack_type="opened", source="native_ack")

    snapshot = runplane.slo_snapshot()
    assert snapshot.get("delivered_runs") == 2
    assert snapshot.get("ack_eligible_runs") == 1
    assert snapshot.get("acked_runs") == 1
    assert snapshot.get("ack_rate_pct") == 100.0


def test_runplane_slo_windows_snapshot_filters_historical_failures(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")

    old_failed = runplane.begin_run(
        job_id="executor.week1.old_failed",
        lane_key="executor:week1",
        trigger="week1_due_check",
        kind="week1_executor",
    )
    runplane.complete_run(
        job_id="executor.week1.old_failed",
        run_id=str(old_failed.get("run_id")),
        ok=False,
        status="failed",
        result={"delivery_status": "failed"},
        failure_class="delivery_failed",
        retryable=True,
    )

    recent_delivered = runplane.begin_run(
        job_id="executor.week1.recent_ok",
        lane_key="executor:week1",
        trigger="week1_due_check",
        kind="week1_executor",
    )
    runplane.complete_run(
        job_id="executor.week1.recent_ok",
        run_id=str(recent_delivered.get("run_id")),
        ok=True,
        status="delivered",
        result={"delivery_status": "ok"},
    )

    state_path = tmp_path / "runplane" / "runplane_state.json"
    state = json.loads(state_path.read_text())
    runs = state["runs"]
    old_run = next(row for row in runs if row["run_id"] == str(old_failed.get("run_id")))
    old_run["started_at_utc"] = "2026-03-01T00:00:00Z"
    old_run["finished_at_utc"] = "2026-03-01T00:00:10Z"
    state_path.write_text(json.dumps(state))

    windows = runplane.slo_windows_snapshot()
    assert "last_1h" in windows
    assert "last_6h" in windows
    assert "last_24h" in windows
    assert windows["last_24h"]["total_runs"] == 1
    assert windows["last_24h"]["failed_runs"] == 0
    assert windows["last_24h"]["delivery_success_rate_pct"] == 100.0


def test_runplane_slo_snapshot_counts_deferred_runs_separately(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")

    started = runplane.begin_run(
        job_id="executor.week1.not_ready",
        lane_key="executor:week1",
        trigger="week1_due_check",
        kind="week1_executor",
    )
    assert started.get("ok") is True

    completed = runplane.complete_run(
        job_id="executor.week1.not_ready",
        run_id=str(started.get("run_id")),
        ok=False,
        status="deferred",
        result={"delivery_status": "deferred_not_ready"},
        failure_class="delivery_not_ready",
        retryable=True,
    )
    assert completed.get("ok") is True
    assert completed.get("run_status") == "deferred"
    assert completed.get("job_state") == "due"

    snapshot = runplane.slo_snapshot()
    assert snapshot.get("total_runs") == 1
    assert snapshot.get("deferred_runs") == 1
    assert snapshot.get("failed_runs") == 0
    assert snapshot.get("attempted_runs") == 0
    assert snapshot.get("terminal_runs") == 1
    assert snapshot.get("delivery_success_rate_pct") == 0.0
    assert snapshot.get("attempted_delivery_success_rate_pct") == 0.0
    assert snapshot.get("deferred_rate_pct") == 100.0
    assert snapshot.get("failure_rate_pct") == 0.0
    assert snapshot.get("deferred_by_failure_class") == {"delivery_not_ready": 1}
    assert snapshot.get("deferred_by_job") == {"executor.week1.not_ready": 1}
    assert snapshot.get("failed_by_failure_class") == {}
    assert snapshot.get("failed_by_job") == {}


def test_runplane_slo_snapshot_exposes_attempted_success_rate(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")

    delivered = runplane.begin_run(
        job_id="executor.week1.ok",
        lane_key="executor:week1",
        trigger="week1_due_check",
        kind="week1_executor",
    )
    runplane.complete_run(
        job_id="executor.week1.ok",
        run_id=str(delivered.get("run_id")),
        ok=True,
        status="delivered",
        result={"delivery_status": "ok"},
    )

    deferred = runplane.begin_run(
        job_id="executor.week1.deferred",
        lane_key="executor:week1",
        trigger="week1_due_check",
        kind="week1_executor",
    )
    runplane.complete_run(
        job_id="executor.week1.deferred",
        run_id=str(deferred.get("run_id")),
        ok=False,
        status="deferred",
        result={"delivery_status": "deferred_not_ready"},
        failure_class="delivery_not_ready",
        retryable=True,
    )

    snapshot = runplane.slo_snapshot()
    assert snapshot.get("total_runs") == 2
    assert snapshot.get("delivered_runs") == 1
    assert snapshot.get("deferred_runs") == 1
    assert snapshot.get("attempted_runs") == 1
    assert snapshot.get("terminal_runs") == 2
    assert snapshot.get("delivery_success_rate_pct") == 50.0
    assert snapshot.get("attempted_delivery_success_rate_pct") == 100.0
    assert snapshot.get("deferred_rate_pct") == 50.0
    assert snapshot.get("deferred_by_failure_class") == {"delivery_not_ready": 1}
    assert snapshot.get("deferred_by_job") == {"executor.week1.deferred": 1}


def test_runplane_slo_snapshot_exposes_failure_breakdowns(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")

    failed = runplane.begin_run(
        job_id="executor.week1.failed",
        lane_key="executor:week1",
        trigger="week1_due_check",
        kind="week1_executor",
    )
    runplane.complete_run(
        job_id="executor.week1.failed",
        run_id=str(failed.get("run_id")),
        ok=False,
        status="failed",
        result={"delivery_status": "failed"},
        failure_class="delivery_failed",
        retryable=False,
    )

    snapshot = runplane.slo_snapshot()
    assert snapshot.get("failed_runs") == 1
    assert snapshot.get("failed_by_failure_class") == {"delivery_failed": 1}
    assert snapshot.get("failed_by_job") == {"executor.week1.failed": 1}


def test_runplane_operator_baseline_snapshot_excludes_history_before_last_problem_run(tmp_path) -> None:
    runplane = AutonomyRunplane(tmp_path / "runplane")

    deferred = runplane.begin_run(
        job_id="executor.week1.deferred",
        lane_key="executor:week1",
        trigger="week1_due_check",
        kind="week1_executor",
    )
    runplane.complete_run(
        job_id="executor.week1.deferred",
        run_id=str(deferred.get("run_id")),
        ok=False,
        status="deferred",
        result={"delivery_status": "deferred_not_ready"},
        failure_class="delivery_not_ready",
        retryable=True,
    )

    delivered = runplane.begin_run(
        job_id="executor.week1.ok",
        lane_key="executor:week1",
        trigger="week1_due_check",
        kind="week1_executor",
    )
    runplane.complete_run(
        job_id="executor.week1.ok",
        run_id=str(delivered.get("run_id")),
        ok=True,
        status="delivered",
        result={"delivery_status": "ok"},
    )

    snapshot = runplane.operator_baseline_snapshot()
    assert snapshot.get("scope") == "operator_baseline"
    assert snapshot.get("baseline_reason") == "since_last_problem_run"
    assert snapshot.get("baseline_after_utc")
    assert snapshot.get("latest_problem_run", {}).get("status") == "deferred"
    assert snapshot.get("latest_problem_run", {}).get("failure_class") == "delivery_not_ready"
    assert snapshot.get("total_runs") == 1
    assert snapshot.get("delivered_runs") == 1
    assert snapshot.get("deferred_runs") == 0
    assert snapshot.get("failed_runs") == 0
