from __future__ import annotations

import json
from pathlib import Path

from observability.rollout_service import RolloutPaths, RolloutService
from core.services.flight_recorder import verify_flight_ledger


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def test_run_work_item_rollout_scores_archived_artifact_and_writes_ledger(tmp_path: Path) -> None:
    artifact = tmp_path / "audit.json"
    _write_json(artifact, {"ok": True, "payload": {"selected_servers": ["brave-search"]}})

    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [],
            "archived_items": [
                {
                    "id": "awj_test_rollout_01",
                    "title": "Replay archived artifact",
                    "objective": "Verify artifact capture",
                    "context": "bounded replay",
                    "tool_choice": "none",
                    "status": "completed",
                    "completion_contract": {
                        "kind": "task_completed",
                        "match_mode": "any",
                        "required_markers": ["brave-search"],
                    },
                    "metadata": {"artifact": str(artifact)},
                }
            ],
        },
    )

    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=tmp_path / "rollouts",
            flight_recorder_dir=tmp_path / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_test_rollout_01", include_archived=True, mode="artifact")

    assert result["ok"] is True
    assert result["score"]["artifact_exists"] is True
    assert result["score"]["missing_markers"] == []
    rollout_path = Path(result["rollout_path"])
    assert rollout_path.exists()

    verify = verify_flight_ledger(tmp_path / "flight_recorder" / "ledger.jsonl", cross_check_source=True)
    assert verify["ok"] is True


def test_run_work_item_rollout_fails_when_required_marker_missing(tmp_path: Path) -> None:
    artifact = tmp_path / "audit.json"
    _write_json(artifact, {"ok": True, "payload": {"selected_servers": ["time"]}})

    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_test_rollout_02",
                    "title": "Replay pending artifact",
                    "objective": "Verify failed scoring",
                    "context": "bounded replay",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "task_completed",
                        "match_mode": "any",
                        "required_markers": ["brave-search"],
                    },
                    "metadata": {"artifact": str(artifact)},
                }
            ],
            "archived_items": [],
        },
    )

    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=tmp_path / "rollouts",
            flight_recorder_dir=tmp_path / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_test_rollout_02", mode="artifact")

    assert result["ok"] is False
    assert result["score"]["failed_checks"] == ["required_markers_present"]
    assert result["score"]["missing_markers"] == ["brave-search"]


def test_build_work_item_envelope_carries_archive_query_metadata(tmp_path: Path) -> None:
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(work_jar, {"version": 1, "items": [], "archived_items": []})
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=tmp_path / "rollouts",
            flight_recorder_dir=tmp_path / "flight_recorder",
        )
    )
    item = {
        "id": "awj_test_rollout_03",
        "title": "Envelope metadata",
        "objective": "Carry signatures",
        "context": "archive seeded",
        "status": "pending",
        "tool_choice": "none",
        "completion_contract": {"required_markers": []},
        "metadata": {
            "artifact": str(tmp_path / "artifact.json"),
            "archive_query": {
                "problem_signature": "preview:web_research:browser_noise",
                "failure_class": "tool_routing_noise",
            },
        },
    }
    envelope = service.build_work_item_envelope(item=item, artifact_path=tmp_path / "artifact.json", rollout_id="rollout_test")
    assert envelope["rollout_id"] == "rollout_test"
    assert envelope["problem_signature"] == "preview:web_research:browser_noise"
    assert envelope["failure_class"] == "tool_routing_noise"
    assert envelope["context_refs"] == [str(tmp_path / "artifact.json")]


def test_run_work_item_rollout_prefers_best_scoring_candidate_artifact(tmp_path: Path) -> None:
    weak_artifact = tmp_path / "weak.json"
    _write_json(weak_artifact, {"ok": True, "payload": {"selected_servers": ["time"]}})
    strong_artifact = tmp_path / "strong.md"
    strong_artifact.write_text("lazy genesis\nverifier script\nfocused tests\n", encoding="utf-8")

    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [],
            "archived_items": [
                {
                    "id": "awj_test_rollout_04",
                    "title": "Prefer best artifact",
                    "objective": "Choose the best candidate",
                    "context": f"secondary source: {strong_artifact}",
                    "source": str(strong_artifact),
                    "tool_choice": "none",
                    "status": "completed",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["lazy genesis", "verifier script", "focused tests"],
                    },
                    "metadata": {"artifact": str(weak_artifact)},
                }
            ],
        },
    )

    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=tmp_path / "rollouts",
            flight_recorder_dir=tmp_path / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_test_rollout_04", include_archived=True, mode="artifact")

    assert result["ok"] is True
    assert result["score"]["artifact_path"] == str(strong_artifact)
    assert result["score"]["missing_markers"] == []



def test_run_work_item_rollout_executes_isolated_toolless_task_in_auto_mode(tmp_path: Path) -> None:
    artifact = tmp_path / "source.md"
    artifact.write_text("lazy genesis\nverifier script\nfocused tests\n", encoding="utf-8")

    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_test_rollout_05",
                    "title": "Execute isolated task",
                    "objective": "Run bounded executor path",
                    "context": f"primary evidence: {artifact}",
                    "source": str(artifact),
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["lazy genesis", "verifier script", "focused tests"],
                    },
                    "metadata": {"artifact": str(artifact)},
                }
            ],
            "archived_items": [],
        },
    )

    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=tmp_path / "rollouts",
            flight_recorder_dir=tmp_path / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_test_rollout_05", mode="auto")

    assert result["ok"] is True
    assert result["trajectory"]["kind"] == "work_jar_executor_replay"
    assert result["score"]["executor_kind"] == "isolated_toolless_task"
    assert result["score"]["task_status"] == "completed"
    exec_result = result["executor_result"]
    assert Path(exec_result["task_path"]).exists()
    assert Path(exec_result["deliverable_path"]).exists()
    assert Path(exec_result["execution_artifact_path"]).exists()
    deliverable_text = Path(exec_result["deliverable_path"]).read_text(encoding="utf-8")
    task_text = Path(exec_result["task_path"]).read_text(encoding="utf-8")
    assert "lazy genesis" in deliverable_text
    assert "verifier script" in deliverable_text
    assert "focused tests" in deliverable_text
    assert "deliverable.md" in task_text


def test_run_work_item_rollout_executes_improvement_archive_materializer(tmp_path: Path) -> None:
    seed_artifact = tmp_path / "flight_ledger_verify.json"
    _write_json(seed_artifact, {"verify": {"ok": True, "records": 12, "errors": [], "warnings": []}})

    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_improvement_archive_impl_phase1_01",
                    "title": "Implement phase-1 improvement archive materializer",
                    "objective": "Materialize the archive in isolation",
                    "context": "archive schema\nmaterializer\nseed entries",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["archive schema", "materializer", "seed entries"],
                    },
                    "metadata": {"artifact": str(tmp_path / "improvement_archive.json")},
                }
            ],
            "archived_items": [
                {
                    "id": "awj_flight_ledger_impl_phase1_01",
                    "title": "Implement phase-1 flight ledger mirror and verifier",
                    "objective": "Seed archive candidate",
                    "context": "flight recorder integrity",
                    "tool_choice": "none",
                    "status": "completed",
                    "completion_contract": {"kind": "task_completed"},
                    "metadata": {
                        "artifact": str(seed_artifact),
                        "archived_at_utc": "2026-03-28T00:00:00Z",
                        "completed_by_task_id": "TASK-TEST",
                    },
                }
            ],
        },
    )

    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=tmp_path / "rollouts",
            flight_recorder_dir=tmp_path / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_improvement_archive_impl_phase1_01", mode="auto")

    assert result["ok"] is True
    assert result["trajectory"]["kind"] == "work_jar_executor_replay"
    assert result["score"]["executor_kind"] == "improvement_archive_materialize"
    assert result["score"]["task_status"] == "completed"
    exec_result = result["executor_result"]
    archive_path = Path(exec_result["deliverable_path"])
    summary_path = Path(exec_result["execution_artifact_path"])
    task_path = Path(exec_result["task_path"])
    assert archive_path.exists()
    assert summary_path.exists()
    assert task_path.exists()
    archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert len(list(archive_payload.get("entries") or [])) == 1
    assert archive_payload["entries"][0]["archive_id"] == "ia_awj_flight_ledger_impl_phase1_01"
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "archive schema" in summary_text
    assert "materializer" in summary_text
    assert "seed entries" in summary_text


def test_run_work_item_rollout_executes_improvement_archive_suggestion_query(tmp_path: Path) -> None:
    archive = tmp_path / "improvement_archive.json"
    _write_json(
        archive,
        {
            "version": 1,
            "updated_at_utc": "2026-03-28T00:00:00Z",
            "entries": [
                {
                    "archive_id": "ia_awj_web_research_shortlist_cleanup_01",
                    "created_at_utc": "2026-03-26T20:47:24Z",
                    "title": "Tighten web-research shortlist to suppress browserbase/dev helper noise",
                    "failure_class": "tool_routing_noise",
                    "problem_signature": "preview:web_research:browser_noise",
                    "intervention_type": "routing_rule",
                    "source_work_item_id": "awj_web_research_shortlist_cleanup_01",
                    "source_task_id": "TASK-TEST",
                    "proof_artifact": "tmp/audits/web_research_shortlist_cleanup_live_20260326T204724Z.json",
                    "files_changed": ["src/orchestration/llm_bridge.py"],
                    "success_evidence": {"artifact_exists": True},
                    "proof_check": {"artifact_exists": True, "reason": "ok"},
                    "reuse_rule": "Suggest when browser noise leaks into a web-research shortlist.",
                    "rollout_guard": "suggest_only_same_failure_class",
                    "status": "active",
                }
            ],
        },
    )

    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    archive_copy = memory_dir / "improvement_archive.json"
    archive_copy.write_text(archive.read_text(encoding="utf-8"), encoding="utf-8")

    work_jar = memory_dir / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_archive_phase2_probe_01",
                    "title": "Archive phase-2 queue seed probe",
                    "objective": "Verify archive suggestions attach to queued work creation.",
                    "context": "archive suggestions\nsuggest_only",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["archive suggestions", "suggest_only"],
                    },
                    "metadata": {
                        "archive_query": {
                            "problem_signature": "preview:web_research:browser_noise",
                            "failure_class": "tool_routing_noise",
                            "limit": 2,
                        }
                    },
                }
            ],
            "archived_items": [],
        },
    )

    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_archive_phase2_probe_01", mode="auto")

    assert result["ok"] is True
    assert result["trajectory"]["kind"] == "work_jar_executor_replay"
    assert result["score"]["executor_kind"] == "improvement_archive_suggest"
    exec_result = result["executor_result"]
    suggestions_path = Path(exec_result["deliverable_path"])
    summary_path = Path(exec_result["execution_artifact_path"])
    assert suggestions_path.exists()
    assert summary_path.exists()
    suggestions = json.loads(suggestions_path.read_text(encoding="utf-8"))
    assert suggestions["match_count"] == 1
    assert suggestions["matches"][0]["archive_id"] == "ia_awj_web_research_shortlist_cleanup_01"
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "archive suggestions" in summary_text
    assert "suggest_only" in summary_text


def test_compare_work_item_rollout_returns_mode_summary(tmp_path: Path) -> None:
    artifact = tmp_path / "source.md"
    artifact.write_text("lazy genesis\nverifier script\nfocused tests\n", encoding="utf-8")

    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_test_rollout_compare_01",
                    "title": "Compare rollout modes",
                    "objective": "Run artifact and executor replays",
                    "context": f"primary evidence: {artifact}",
                    "source": str(artifact),
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["lazy genesis", "verifier script", "focused tests"],
                    },
                    "metadata": {"artifact": str(artifact)},
                }
            ],
            "archived_items": [],
        },
    )

    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=tmp_path / "rollouts",
            flight_recorder_dir=tmp_path / "flight_recorder",
        )
    )
    result = service.compare_work_item_rollout(
        item_id="awj_test_rollout_compare_01",
        modes=["artifact", "auto"],
    )

    assert result["ok"] is True
    assert result["preferred_mode"] in {"artifact", "auto"}
    assert result["modes"] == ["artifact", "auto"]
    assert len(result["comparisons"]) == 2
    by_mode = {row["mode"]: row for row in result["comparisons"]}
    assert by_mode["artifact"]["ok"] is True
    assert by_mode["auto"]["ok"] is True
    assert by_mode["auto"]["executor_kind"] == "isolated_toolless_task"


def test_run_work_item_rollout_executes_improvement_archive_operator_surface(tmp_path: Path) -> None:
    archive = tmp_path / "improvement_archive.json"
    _write_json(
        archive,
        {
            "version": 1,
            "updated_at_utc": "2026-03-28T00:00:00Z",
            "entries": [
                {
                    "archive_id": "ia_awj_web_research_shortlist_cleanup_01",
                    "created_at_utc": "2026-03-26T20:47:24Z",
                    "title": "Tighten web-research shortlist to suppress browserbase/dev helper noise",
                    "failure_class": "tool_routing_noise",
                    "problem_signature": "preview:web_research:browser_noise",
                    "intervention_type": "routing_rule",
                    "source_work_item_id": "awj_web_research_shortlist_cleanup_01",
                    "source_task_id": "TASK-TEST",
                    "proof_artifact": "tmp/audits/web_research_shortlist_cleanup_live_20260326T204724Z.json",
                    "files_changed": ["src/orchestration/llm_bridge.py"],
                    "success_evidence": {"artifact_exists": True},
                    "proof_check": {"artifact_exists": True, "reason": "ok"},
                    "reuse_rule": "Suggest when browser noise leaks into a web-research shortlist.",
                    "rollout_guard": "suggest_only_same_failure_class",
                    "status": "active",
                }
            ],
        },
    )

    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    archive_copy = memory_dir / "improvement_archive.json"
    archive_copy.write_text(archive.read_text(encoding="utf-8"), encoding="utf-8")

    work_jar = memory_dir / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_improvement_archive_operator_surface_01",
                    "title": "Expose improvement-archive suggestions in operator diagnostics",
                    "objective": "Add a small operator-facing helper or endpoint that shows matching improvement-archive suggestions for a supplied problem signature or failure class.",
                    "context": "operator diagnostics\narchive suggestions\nsuggest_only",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["operator diagnostics", "archive suggestions", "suggest_only"],
                    },
                    "metadata": {"artifact": str(tmp_path / "operator_surface.json")},
                }
            ],
            "archived_items": [],
        },
    )

    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_improvement_archive_operator_surface_01", mode="auto")

    assert result["ok"] is True
    assert result["score"]["executor_kind"] == "improvement_archive_operator_surface"
    exec_result = result["executor_result"]
    diagnostics_path = Path(exec_result["deliverable_path"])
    summary_path = Path(exec_result["execution_artifact_path"])
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics["active_entries"] == 1
    assert diagnostics["suggest_only"] is True
    assert diagnostics["failure_class_counts"]["tool_routing_noise"] == 1
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "operator diagnostics" in summary_text
    assert "archive suggestions" in summary_text
    assert "suggest_only" in summary_text


def test_run_work_item_rollout_executes_flight_ledger_verify(tmp_path: Path) -> None:
    flight_dir = tmp_path / "vera_memory" / "flight_recorder"
    recorder = RolloutService(
        RolloutPaths(
            work_jar_path=tmp_path / "unused.json",
            output_dir=tmp_path / "rollouts",
            flight_recorder_dir=flight_dir,
        )
    )
    from core.services.flight_recorder import AIRResult, FlightRecorder

    live_recorder = FlightRecorder(base_dir=flight_dir, enabled=True)
    live_recorder.log_transition(
        state_snapshot="state",
        action={"type": "test"},
        result={"success": True},
        air=AIRResult(score=0.5, reason="test_ok"),
        meta={"success": True},
        provenance={"source_type": "test"},
    )

    work_jar = tmp_path / "vera_memory" / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_flight_ledger_impl_phase1_01",
                    "title": "Implement phase-1 flight ledger mirror and verifier",
                    "objective": "Verify copied ledger in isolation",
                    "context": "lazy genesis\nverifier script\nfocused tests",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["lazy genesis", "verifier script", "focused tests"],
                    },
                    "metadata": {"artifact": str(tmp_path / "live_verify.json")},
                }
            ],
            "archived_items": [],
        },
    )

    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=tmp_path / "vera_memory" / "rollouts",
            flight_recorder_dir=flight_dir,
        )
    )
    result = service.run_work_item_rollout(item_id="awj_flight_ledger_impl_phase1_01", mode="auto")

    assert result["ok"] is True
    assert result["score"]["executor_kind"] == "flight_ledger_verify"
    exec_result = result["executor_result"]
    verify_path = Path(exec_result["deliverable_path"])
    summary_path = Path(exec_result["execution_artifact_path"])
    verify_payload = json.loads(verify_path.read_text(encoding="utf-8"))
    assert verify_payload["ok"] is True
    assert int(verify_payload["records"]) >= 1
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "lazy genesis" in summary_text
    assert "verifier script" in summary_text
    assert "focused tests" in summary_text


def test_run_work_item_rollout_executes_week1_validation_snapshot(tmp_path: Path) -> None:
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "ops" / "week1").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ops" / "week1" / "WEEK1_VALIDATION_METRICS.md").write_text(
        "Metric targets for Week1 validation.\n", encoding="utf-8"
    )
    (tmp_path / "ops" / "week1" / "DAY1_OPERATOR_CHECKLIST.txt").write_text(
        "Checklist item A\nChecklist item B\n", encoding="utf-8"
    )
    (memory_dir / "week1_executor_events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts_utc": "2026-03-28T12:00:00Z",
                        "event_id": "midday_check",
                        "status": "ok",
                        "delivery_channel": "native_push",
                    }
                ),
                json.dumps(
                    {
                        "ts_utc": "2026-03-28T12:05:00Z",
                        "event_id": "low_dopamine_start",
                        "status": "ok",
                        "delivery_channel": "native_push",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        memory_dir / "week1_validation_monitor.json",
        {
            "version": 1,
            "last_snapshot_utc": "2026-03-28T11:00:00Z",
            "last_snapshot_reason": "week1_activity_since_last_snapshot",
            "candidate": {"reason": "week1_activity_since_last_snapshot"},
        },
    )
    work_jar = memory_dir / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_week1_validation_snapshot_probe_01",
                    "title": "Produce a concise Week1 validation snapshot from recent runtime evidence",
                    "objective": "Produce one bounded Week1 validation snapshot from copied local evidence.",
                    "context": "signal summary\nlikely weak spots\ntop 3 week2 tuning recommendations",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": [
                            "signal summary",
                            "likely weak spots",
                            "top 3 week2 tuning recommendations",
                        ],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_snapshot.md")},
                }
            ],
            "archived_items": [],
        },
    )

    old_cwd = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        service = RolloutService(
            RolloutPaths(
                work_jar_path=work_jar,
                output_dir=memory_dir / "rollouts",
                flight_recorder_dir=memory_dir / "flight_recorder",
            )
        )
        result = service.run_work_item_rollout(item_id="awj_week1_validation_snapshot_probe_01", mode="auto")
    finally:
        os.chdir(old_cwd)

    assert result["ok"] is True
    assert result["score"]["executor_kind"] == "week1_validation_snapshot"
    exec_result = result["executor_result"]
    snapshot_path = Path(exec_result["deliverable_path"])
    summary_path = Path(exec_result["execution_artifact_path"])
    snapshot_text = snapshot_path.read_text(encoding="utf-8").lower()
    assert "signal summary" in snapshot_text
    assert "likely weak spots" in snapshot_text
    assert "top 3 week2 tuning recommendations" in snapshot_text
    assert "midday_check" in snapshot_text
    assert "low_dopamine_start" in snapshot_text
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "events=2" in summary_text


def test_run_work_item_rollout_executes_operator_runtime_snapshot(tmp_path: Path) -> None:
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_operator_runtime_snapshot_probe_01",
                    "title": "Capture one operator/runtime snapshot",
                    "objective": "Produce one bounded operator/runtime snapshot from the live local HTTP surfaces.",
                    "context": "health\nreadiness\noperator baseline\ntool diagnostics",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["health", "readiness", "operator baseline", "tool diagnostics"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_operator_snapshot.json"), "base_url": "http://127.0.0.1:9999"},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=tmp_path / "rollouts",
            flight_recorder_dir=tmp_path / "flight_recorder",
        )
    )

    def fake_http_json(url: str, *, timeout: float = 10.0) -> dict:
        if url.endswith("/api/health"):
            return {"ok": True, "status_code": 200, "payload": {"ok": True, "status": "ok"}}
        if url.endswith("/api/readiness"):
            return {"ok": True, "status_code": 200, "payload": {"ready": True, "phase": "ready", "warnings": []}}
        if url.endswith("/api/autonomy/slo"):
            return {"ok": True, "status_code": 200, "payload": {"operator_baseline": {"delivered_runs": 3, "failed_runs": 0, "deferred_runs": 0}}}
        if url.endswith("/api/tools/status"):
            return {"ok": True, "status_code": 200, "payload": {"mcp": {"running": 5}, "warnings": []}}
        return {"ok": False, "status_code": 404, "payload": {}}

    service._http_json = fake_http_json  # type: ignore[method-assign]
    result = service.run_work_item_rollout(item_id="awj_operator_runtime_snapshot_probe_01", mode="auto")

    assert result["ok"] is True
    assert result["score"]["executor_kind"] == "operator_runtime_snapshot"
    exec_result = result["executor_result"]
    snapshot_path = Path(exec_result["deliverable_path"])
    summary_path = Path(exec_result["execution_artifact_path"])
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["health"]["payload"]["ok"] is True
    assert snapshot["readiness"]["payload"]["ready"] is True
    assert snapshot["autonomy_slo"]["payload"]["operator_baseline"]["delivered_runs"] == 3
    assert snapshot["tools_status"]["payload"]["mcp"]["running"] == 5
    summary_text = summary_path.read_text(encoding="utf-8").lower()
    assert "health" in summary_text
    assert "readiness" in summary_text
    assert "operator baseline" in summary_text
    assert "tool diagnostics" in summary_text


def test_run_work_item_rollout_executes_state_sync_surface_snapshot(tmp_path: Path) -> None:
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        memory_dir / "autonomy_state_sync_verifier.json",
        {
            "version": 1,
            "verified_tasks": {
                "TASK-030": {
                    "verified_at_utc": "2026-03-22T23:23:52Z",
                    "last_reason": "aligned",
                    "last_ok": True,
                }
            },
        },
    )
    (memory_dir / "autonomy_state_sync_verifier_events.jsonl").write_text(
        json.dumps({"task_id": "TASK-030", "reason": "aligned"}) + "\n",
        encoding="utf-8",
    )
    (memory_dir / "autonomy_cadence_events.jsonl").write_text(
        json.dumps({"ts_utc": "2026-03-28T21:00:00Z", "phase": "idle"}) + "\n",
        encoding="utf-8",
    )
    (memory_dir / "MASTER_TODO.md").write_text(
        "## TASK-030 [completed] Example\n[STATE-SYNC-VERIFIED:TASK-030] outcome=aligned awj=awj_state_sync_surface_note_01\n",
        encoding="utf-8",
    )
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_state_sync_surface_snapshot_probe_01",
                    "title": "Capture one state-sync task/memory surface snapshot",
                    "objective": "Produce one bounded state-sync task/memory surface snapshot from local verifier and task files.",
                    "context": "verification hook\nrepair write\nfollow-up replay",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["verification hook", "repair write", "follow-up replay"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_state_sync.json"), "task_id": "TASK-030"},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_state_sync_surface_snapshot_probe_01", mode="auto")

    assert result["ok"] is True
    assert result["score"]["executor_kind"] == "state_sync_surface_snapshot"
    exec_result = result["executor_result"]
    snapshot_path = Path(exec_result["deliverable_path"])
    summary_path = Path(exec_result["execution_artifact_path"])
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["task_id"] == "TASK-030"
    assert snapshot["task_surface_note_present"] is True
    assert snapshot["verified_tasks_count"] == 1
    summary_text = summary_path.read_text(encoding="utf-8").lower()
    assert "verification hook" in summary_text
    assert "repair write" in summary_text
    assert "follow-up replay" in summary_text


def test_run_work_item_rollout_executes_week1_ops_surface_snapshot(tmp_path: Path) -> None:
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        memory_dir / "week1_task_schedule.json",
        {
            "source_mode": "seed_csv",
            "source_ref": "ops/week1/WEEK1_SEEDED_TASK_BACKLOG.csv",
            "items": [
                {
                    "parent_title": "[P2] Contact a landscaper about fixing the yard and preventing further damage",
                    "scheduled_local": "2026-04-04T13:30:00-05:00",
                    "focus_slot": "13:30",
                    "start_step": "Gather photos and quote checklist",
                    "priority": "P2",
                    "category_key": "home",
                },
                {
                    "parent_title": "[P0] Make appointment for ADHD/autism assessment (no medication requirement; focus on learning/mitigation)",
                    "scheduled_local": "2026-03-29T09:30:00-05:00",
                    "focus_slot": "09:30",
                    "start_step": "Find contact details and choose a 10-minute call window",
                    "priority": "P0",
                    "category_key": "appointments",
                },
            ],
        },
    )
    _write_json(
        memory_dir / "week1_ops_backlog_state.json",
        {
            "version": 1,
            "items": {
                "[P2] Contact a landscaper about fixing the yard and preventing further damage": {
                    "awaiting_human_followthrough": True,
                    "resume_after_utc": "2026-04-04T18:30:00Z",
                    "last_task_id": "TASK-048",
                    "last_status": "completed",
                }
            },
        },
    )
    _write_json(
        memory_dir / "week1_executor_state.json",
        {
            "version": 1,
            "last_run_utc": "2026-03-28T20:00:21.440588Z",
            "completed_events": {
                "2026-03-28:followup_factory": {"status": "ok"},
                "2026-03-28:midday_check": {"status": "ok"},
            },
        },
    )
    (memory_dir / "week1_executor_events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event_id": "midday_check", "delivery_channel": "native_push", "status": "ok"}),
                json.dumps({"event_id": "followup_factory", "delivery_channel": "native_push", "status": "ok"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_week1_ops_surface_snapshot_probe_01",
                    "title": "Capture one Week1 ops surface snapshot",
                    "objective": "Produce one bounded Week1 ops surface snapshot from the local structured schedule and hold state.",
                    "context": "focus lane\nhuman followthrough holds\nnext focus slots",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["focus lane", "human followthrough holds", "next focus slots"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_week1_ops_surface.json")},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_week1_ops_surface_snapshot_probe_01", mode="auto")

    assert result["ok"] is True
    assert result["score"]["executor_kind"] == "week1_ops_surface_snapshot"
    exec_result = result["executor_result"]
    snapshot_path = Path(exec_result["deliverable_path"])
    summary_path = Path(exec_result["execution_artifact_path"])
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["schedule_item_count"] == 2
    assert snapshot["held_item_count"] == 1
    assert snapshot["eligible_item_count"] == 1
    assert snapshot["next_focus_items"][0]["title"].startswith("[P0] Make appointment")
    summary_text = summary_path.read_text(encoding="utf-8").lower()
    assert "focus lane" in summary_text
    assert "human followthrough holds" in summary_text
    assert "next focus slots" in summary_text


def test_run_work_item_rollout_executes_autonomy_queue_surface_snapshot(tmp_path: Path) -> None:
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        memory_dir / "autonomy_work_jar.json",
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_pending_probe_01",
                    "title": "Pending probe",
                    "status": "pending",
                    "tool_choice": "none",
                }
            ],
            "archived_items": [
                {
                    "id": "awj_archived_probe_01",
                    "title": "Archived probe",
                    "status": "completed",
                    "completed_by_task_id": "TASK-900",
                }
            ],
        },
    )
    _write_json(
        memory_dir / "autonomy_state_sync_verifier.json",
        {
            "version": 1,
            "verified_tasks": {
                "TASK-900": {"verified_at_utc": "2026-03-28T21:00:00Z", "last_ok": True}
            },
        },
    )
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_autonomy_queue_surface_snapshot_probe_01",
                    "title": "Capture one autonomy queue surface snapshot",
                    "objective": "Produce one bounded autonomy queue surface snapshot from the local work jar and verification state.",
                    "context": "pending items\narchived items\nqueue health",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["pending items", "archived items", "queue health"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_queue_snapshot.json")},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_autonomy_queue_surface_snapshot_probe_01", mode="auto")

    assert result["ok"] is True
    assert result["score"]["executor_kind"] == "autonomy_queue_surface_snapshot"
    exec_result = result["executor_result"]
    snapshot_path = Path(exec_result["deliverable_path"])
    summary_path = Path(exec_result["execution_artifact_path"])
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["pending_count"] == 1
    assert snapshot["archived_count"] == 1
    assert snapshot["verified_task_count"] == 1
    assert snapshot["pending_summary"][0]["id"] == "awj_pending_probe_01"
    summary_text = summary_path.read_text(encoding="utf-8").lower()
    assert "pending items" in summary_text
    assert "archived items" in summary_text
    assert "queue health" in summary_text


def test_run_work_item_rollout_executes_autonomy_queue_repair(tmp_path: Path) -> None:
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        memory_dir / "autonomy_work_jar.json",
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_done_probe_01",
                    "title": "Done probe",
                    "status": "completed",
                    "tool_choice": "none",
                    "metadata": {"completed_by_task_id": "TASK-900"},
                },
                {
                    "id": "awj_pending_probe_02",
                    "title": "Pending probe",
                    "status": "pending",
                    "tool_choice": "none",
                },
            ],
            "archived_items": [],
        },
    )
    _write_json(
        memory_dir / "autonomy_state_sync_verifier.json",
        {
            "version": 1,
            "verified_tasks": {
                "TASK-900": {"verified_at_utc": "2026-03-28T21:00:00Z", "last_ok": True}
            },
        },
    )
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_autonomy_queue_repair_probe_01",
                    "title": "Repair one copied autonomy queue",
                    "objective": "Run one bounded copied queue repair that archives verified complete items from the isolated work jar.",
                    "context": "verified complete\narchived items\nqueue repair",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["verified complete", "archived items", "queue repair"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_queue_repair.json")},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.run_work_item_rollout(item_id="awj_autonomy_queue_repair_probe_01", mode="auto")

    assert result["ok"] is True
    assert result["score"]["executor_kind"] == "autonomy_queue_repair"
    exec_result = result["executor_result"]
    repaired_path = Path(exec_result["deliverable_path"])
    summary_path = Path(exec_result["execution_artifact_path"])
    repaired = json.loads(repaired_path.read_text(encoding="utf-8"))
    assert len(repaired["items"]) == 1
    assert repaired["items"][0]["id"] == "awj_pending_probe_02"
    assert len(repaired["archived_items"]) == 1
    assert repaired["archived_items"][0]["id"] == "awj_done_probe_01"
    assert repaired["archived_items"][0]["metadata"]["archive_reason"] == "verified_complete"
    summary_text = summary_path.read_text(encoding="utf-8").lower()
    assert "verified complete" in summary_text
    assert "archived items" in summary_text
    assert "queue repair" in summary_text


def test_compare_work_item_rollout_includes_policy_variants(tmp_path: Path) -> None:
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        memory_dir / "autonomy_work_jar.json",
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_done_verified",
                    "title": "Done verified",
                    "status": "completed",
                    "metadata": {"completed_by_task_id": "TASK-900"},
                },
                {
                    "id": "awj_done_unverified",
                    "title": "Done unverified",
                    "status": "completed",
                    "metadata": {"completed_by_task_id": "TASK-901"},
                },
            ],
            "archived_items": [],
        },
    )
    _write_json(
        memory_dir / "autonomy_state_sync_verifier.json",
        {
            "version": 1,
            "verified_tasks": {
                "TASK-900": {"verified_at_utc": "2026-03-28T21:00:00Z", "last_ok": True},
                "TASK-901": {"verified_at_utc": "2026-03-28T21:10:00Z", "last_ok": False},
            },
        },
    )
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_autonomy_queue_repair_compare_probe_01",
                    "title": "Repair one copied autonomy queue",
                    "objective": "Run one bounded copied queue repair that archives verified complete items from the isolated work jar.",
                    "context": "verified complete\narchived items\nqueue repair",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["verified complete", "archived items", "queue repair"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_queue_repair_compare.json")},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.compare_work_item_rollout(
        item_id="awj_autonomy_queue_repair_compare_probe_01",
        modes=["auto"],
        policies=["verified_only", "verified_or_completed"],
    )

    assert result["ok"] is True
    assert result["preferred_mode"] == "auto"
    assert result["preferred_policy"] == "verified_only"
    assert result["policies"] == ["verified_only", "verified_or_completed"]
    assert len(result["comparisons"]) == 2
    policies = {row["policy"] for row in result["comparisons"]}
    assert policies == {"verified_only", "verified_or_completed"}


def test_compare_work_item_rollout_prefers_strict_week1_ops_policy(tmp_path: Path) -> None:
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        memory_dir / "week1_task_schedule.json",
        {
            "source_mode": "seed_csv",
            "source_ref": "ops/week1/WEEK1_SEEDED_TASK_BACKLOG.csv",
            "items": [
                {
                    "parent_title": "[P2] Held exterior task",
                    "scheduled_local": "2026-03-29T08:00:00-05:00",
                    "focus_slot": "08:00",
                    "start_step": "Held start step",
                    "priority": "P2",
                    "category_key": "home",
                },
                {
                    "parent_title": "[P0] Eligible appointment task",
                    "scheduled_local": "2026-03-29T09:00:00-05:00",
                    "focus_slot": "09:00",
                    "start_step": "Eligible start step",
                    "priority": "P0",
                    "category_key": "appointments",
                },
            ],
        },
    )
    _write_json(
        memory_dir / "week1_ops_backlog_state.json",
        {
            "version": 1,
            "items": {
                "[P2] Held exterior task": {
                    "awaiting_human_followthrough": True,
                    "resume_after_utc": "2026-04-04T18:30:00Z",
                    "last_task_id": "TASK-500",
                    "last_status": "completed",
                }
            },
        },
    )
    _write_json(
        memory_dir / "week1_executor_state.json",
        {
            "version": 1,
            "last_run_utc": "2026-03-28T20:00:21.440588Z",
            "completed_events": {},
        },
    )
    (memory_dir / "week1_executor_events.jsonl").write_text("", encoding="utf-8")
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_week1_ops_policy_compare_probe_01",
                    "title": "Capture one Week1 ops surface snapshot",
                    "objective": "Produce one bounded Week1 ops surface snapshot from the local structured schedule and hold state.",
                    "context": "focus lane\nhuman followthrough holds\nnext focus slots",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["focus lane", "human followthrough holds", "next focus slots"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_week1_policy_compare.json")},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.compare_work_item_rollout(
        item_id="awj_week1_ops_policy_compare_probe_01",
        modes=["auto"],
        policies=["strict_hold_aware", "raw_schedule"],
    )

    assert result["ok"] is True
    assert result["preferred_mode"] == "auto"
    assert result["preferred_policy"] == "strict_hold_aware"
    assert result["policies"] == ["strict_hold_aware", "raw_schedule"]
    assert len(result["comparisons"]) == 2


def test_compare_work_item_rollout_prefers_strict_archive_policy(tmp_path: Path) -> None:
    archive = tmp_path / "improvement_archive.json"
    _write_json(
        archive,
        {
            "version": 1,
            "updated_at_utc": "2026-03-28T00:00:00Z",
            "entries": [
                {
                    "archive_id": "ia_exact_signature",
                    "created_at_utc": "2026-03-26T20:47:24Z",
                    "title": "Exact signature match",
                    "failure_class": "tool_routing_noise",
                    "problem_signature": "preview:web_research:browser_noise",
                    "intervention_type": "routing_rule",
                    "source_work_item_id": "awj_web_research_shortlist_cleanup_01",
                    "source_task_id": "TASK-TEST-1",
                    "proof_artifact": "tmp/audits/exact.json",
                    "files_changed": ["src/orchestration/llm_bridge.py"],
                    "success_evidence": {"artifact_exists": True},
                    "proof_check": {"artifact_exists": True, "reason": "ok"},
                    "reuse_rule": "Exact signature candidate",
                    "rollout_guard": "suggest_only_same_failure_class",
                    "status": "active",
                },
                {
                    "archive_id": "ia_failure_class_only",
                    "created_at_utc": "2026-03-26T20:50:24Z",
                    "title": "Failure class only match",
                    "failure_class": "tool_routing_noise",
                    "problem_signature": "preview:web_research:ranking_local_video_noise",
                    "intervention_type": "ranking_rule",
                    "source_work_item_id": "awj_web_research_ranking_cleanup_01",
                    "source_task_id": "TASK-TEST-2",
                    "proof_artifact": "tmp/audits/class_only.json",
                    "files_changed": ["src/orchestration/llm_bridge.py"],
                    "success_evidence": {"artifact_exists": True},
                    "proof_check": {"artifact_exists": True, "reason": "ok"},
                    "reuse_rule": "Failure class only candidate",
                    "rollout_guard": "suggest_only_same_problem_signature",
                    "status": "active",
                },
            ],
        },
    )
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_json(memory_dir / "improvement_archive.json", json.loads(archive.read_text(encoding="utf-8")))
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_archive_policy_compare_probe_01",
                    "title": "Archive phase-2 queue seed probe",
                    "objective": "Verify archive suggestions attach to queued work creation.",
                    "context": "archive suggestions\nsuggest_only",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["archive suggestions", "suggest_only"],
                    },
                    "metadata": {
                        "archive_query": {
                            "problem_signature": "preview:web_research:browser_noise",
                            "failure_class": "tool_routing_noise",
                            "limit": 5,
                        }
                    },
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.compare_work_item_rollout(
        item_id="awj_archive_policy_compare_probe_01",
        modes=["auto"],
        policies=["strict_signature", "relaxed_failure_class"],
    )

    assert result["ok"] is True
    assert result["preferred_mode"] == "auto"
    assert result["preferred_policy"] == "strict_signature"
    assert result["policies"] == ["strict_signature", "relaxed_failure_class"]
    assert len(result["comparisons"]) == 2


def test_compare_work_item_rollout_prefers_strict_operator_policy(tmp_path: Path) -> None:
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_operator_runtime_policy_compare_probe_01",
                    "title": "Capture one operator/runtime snapshot",
                    "objective": "Produce one bounded operator/runtime snapshot from the live local HTTP surfaces.",
                    "context": "health\nreadiness\noperator baseline\ntool diagnostics",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["health", "readiness", "operator baseline", "tool diagnostics"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_operator_policy.json"), "base_url": "http://127.0.0.1:9999"},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=tmp_path / "rollouts",
            flight_recorder_dir=tmp_path / "flight_recorder",
        )
    )

    def fake_http_json(url: str, *, timeout: float = 10.0) -> dict:
        if url.endswith("/api/health"):
            return {"ok": True, "status_code": 200, "payload": {"ok": True, "status": "ok"}}
        if url.endswith("/api/readiness"):
            return {"ok": True, "status_code": 200, "payload": {"ready": True, "phase": "ready", "warnings": ["tool warmup"]}}
        if url.endswith("/api/autonomy/slo"):
            return {"ok": True, "status_code": 200, "payload": {"operator_baseline": {"delivered_runs": 5, "failed_runs": 0, "deferred_runs": 0}}}
        if url.endswith("/api/tools/status"):
            return {"ok": True, "status_code": 200, "payload": {"warnings": ["degraded transport"], "mcp": {"running": 5}}}
        return {"ok": False, "status_code": 404, "payload": {}}

    service._http_json = fake_http_json  # type: ignore[method-assign]
    result = service.compare_work_item_rollout(
        item_id="awj_operator_runtime_policy_compare_probe_01",
        modes=["auto"],
        policies=["strict_operator_health", "baseline_favoring_health"],
    )

    assert result["ok"] is True
    assert result["preferred_mode"] == "auto"
    assert result["preferred_policy"] == "strict_operator_health"
    assert result["policies"] == ["strict_operator_health", "baseline_favoring_health"]
    assert len(result["comparisons"]) == 2


def test_compare_work_item_rollout_prefers_strict_state_sync_policy(tmp_path: Path) -> None:
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        memory_dir / "autonomy_state_sync_verifier.json",
        {
            "version": 1,
            "verified_tasks": {
                "TASK-031": {
                    "verified_at_utc": "2026-03-28T22:00:00Z",
                    "last_reason": "aligned",
                    "last_ok": True,
                }
            },
        },
    )
    (memory_dir / "autonomy_state_sync_verifier_events.jsonl").write_text(
        json.dumps({"task_id": "TASK-031", "reason": "aligned"}) + "\n",
        encoding="utf-8",
    )
    (memory_dir / "autonomy_cadence_events.jsonl").write_text(
        json.dumps({"ts_utc": "2026-03-28T22:10:00Z", "phase": "active"}) + "\n",
        encoding="utf-8",
    )
    (memory_dir / "MASTER_TODO.md").write_text(
        "## TASK-031 [completed] Example without verifier note\n",
        encoding="utf-8",
    )
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_state_sync_policy_compare_probe_01",
                    "title": "Capture one state-sync task/memory surface snapshot",
                    "objective": "Produce one bounded state-sync task/memory surface snapshot from local verifier and task files.",
                    "context": "verification hook\nrepair write\nfollow-up replay",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["verification hook", "repair write", "follow-up replay"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_state_sync_policy.json"), "task_id": "TASK-031"},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.compare_work_item_rollout(
        item_id="awj_state_sync_policy_compare_probe_01",
        modes=["auto"],
        policies=["strict_note_required", "verifier_state_only"],
    )

    assert result["ok"] is True
    assert result["preferred_mode"] == "auto"
    assert result["preferred_policy"] == "strict_note_required"
    assert result["policies"] == ["strict_note_required", "verifier_state_only"]
    assert len(result["comparisons"]) == 2


def test_compare_work_item_rollout_prefers_strict_week1_validation_policy(tmp_path: Path) -> None:
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "week1_executor_events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"event_id": "midday_check", "delivery_channel": "native_push", "status": "ok", "ts_utc": "2026-03-28T21:00:00Z"}),
                json.dumps({"event_id": "followup_factory", "delivery_channel": "call", "status": "ok", "ts_utc": "2026-03-28T21:10:00Z"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        memory_dir / "week1_validation_monitor.json",
        {
            "version": 1,
            "last_snapshot_utc": "2026-03-28T20:00:00Z",
            "candidate": {"reason": "week1_validation_snapshot_missing"},
        },
    )
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_week1_validation_policy_compare_probe_01",
                    "title": "Capture one Week1 validation snapshot",
                    "objective": "Produce one bounded Week1 validation snapshot from local Week1 evidence.",
                    "context": "signal summary\nlikely weak spots\ntop 3 week2 tuning recommendations",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["signal summary", "likely weak spots", "top 3 week2 tuning recommendations"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_week1_validation_policy.json")},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.compare_work_item_rollout(
        item_id="awj_week1_validation_policy_compare_probe_01",
        modes=["auto"],
        policies=["strict_ack_required", "delivery_signal_only"],
    )

    assert result["ok"] is True
    assert result["preferred_mode"] == "auto"
    assert result["preferred_policy"] == "strict_ack_required"
    assert result["policies"] == ["strict_ack_required", "delivery_signal_only"]
    assert len(result["comparisons"]) == 2


def test_compare_work_item_rollout_prefers_strict_archive_operator_policy(tmp_path: Path) -> None:
    archive = tmp_path / "improvement_archive.json"
    _write_json(
        archive,
        {
            "version": 1,
            "updated_at_utc": "2026-03-28T00:00:00Z",
            "entries": [
                {
                    "archive_id": "ia_active",
                    "created_at_utc": "2026-03-26T20:47:24Z",
                    "title": "Active routing improvement",
                    "failure_class": "tool_routing_noise",
                    "problem_signature": "preview:web_research:browser_noise",
                    "intervention_type": "routing_rule",
                    "source_work_item_id": "awj_web_research_shortlist_cleanup_01",
                    "source_task_id": "TASK-TEST-1",
                    "proof_artifact": "tmp/audits/active.json",
                    "files_changed": ["src/orchestration/llm_bridge.py"],
                    "success_evidence": {"artifact_exists": True},
                    "proof_check": {"artifact_exists": True, "reason": "ok"},
                    "reuse_rule": "Active candidate",
                    "rollout_guard": "suggest_only",
                    "status": "active",
                },
                {
                    "archive_id": "ia_retired",
                    "created_at_utc": "2026-03-26T21:47:24Z",
                    "title": "Retired routing improvement",
                    "failure_class": "tool_routing_noise",
                    "problem_signature": "preview:web_research:old_noise",
                    "intervention_type": "routing_rule",
                    "source_work_item_id": "awj_old_cleanup_01",
                    "source_task_id": "TASK-TEST-2",
                    "proof_artifact": "tmp/audits/retired.json",
                    "files_changed": ["src/orchestration/llm_bridge.py"],
                    "success_evidence": {"artifact_exists": True},
                    "proof_check": {"artifact_exists": True, "reason": "ok"},
                    "reuse_rule": "Retired candidate",
                    "rollout_guard": "suggest_only",
                    "status": "retired",
                },
            ],
        },
    )
    memory_dir = tmp_path / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_json(memory_dir / "improvement_archive.json", json.loads(archive.read_text(encoding="utf-8")))
    work_jar = memory_dir / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_archive_operator_policy_compare_probe_01",
                    "title": "Expose improvement-archive suggestions in operator diagnostics",
                    "objective": "Add a small operator-facing helper or endpoint that shows matching improvement-archive suggestions for a supplied problem signature or failure class.",
                    "context": "operator diagnostics\narchive suggestions\nsuggest_only",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["operator diagnostics", "archive suggestions", "suggest_only"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_archive_operator_policy.json")},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=memory_dir / "flight_recorder",
        )
    )
    result = service.compare_work_item_rollout(
        item_id="awj_archive_operator_policy_compare_probe_01",
        modes=["auto"],
        policies=["strict_active_only", "include_inactive"],
    )

    assert result["ok"] is True
    assert result["preferred_mode"] == "auto"
    assert result["preferred_policy"] == "strict_active_only"
    assert result["policies"] == ["strict_active_only", "include_inactive"]
    assert len(result["comparisons"]) == 2


def test_compare_work_item_rollout_prefers_strict_flight_ledger_policy(tmp_path: Path) -> None:
    from core.services.flight_recorder import AIRResult, FlightRecorder

    memory_dir = tmp_path / "vera_memory"
    flight_dir = memory_dir / "flight_recorder"
    flight_dir.mkdir(parents=True, exist_ok=True)
    recorder = FlightRecorder(base_dir=flight_dir, enabled=True)
    recorder.log_transition(
        state_snapshot="state",
        action={"type": "test"},
        result={"success": True},
        air=AIRResult(score=0.5, reason="ok"),
        meta={"success": True},
        provenance={"source_type": "test"},
    )
    work_jar = tmp_path / "autonomy_work_jar.json"
    _write_json(
        work_jar,
        {
            "version": 1,
            "items": [
                {
                    "id": "awj_flight_ledger_policy_compare_probe_01",
                    "title": "Verify one copied flight ledger",
                    "objective": "Run one bounded copied flight ledger verification from local recorder state.",
                    "context": "lazy genesis\nverifier script\nfocused tests",
                    "tool_choice": "none",
                    "status": "pending",
                    "completion_contract": {
                        "kind": "markers",
                        "match_mode": "all",
                        "required_markers": ["lazy genesis", "verifier script", "focused tests"],
                    },
                    "metadata": {"artifact": str(tmp_path / "old_flight_policy.json")},
                }
            ],
            "archived_items": [],
        },
    )
    service = RolloutService(
        RolloutPaths(
            work_jar_path=work_jar,
            output_dir=memory_dir / "rollouts",
            flight_recorder_dir=flight_dir,
        )
    )
    result = service.compare_work_item_rollout(
        item_id="awj_flight_ledger_policy_compare_probe_01",
        modes=["auto"],
        policies=["rebuild_only_if_invalid", "always_rebuild_copy"],
    )

    assert result["ok"] is True
    assert result["preferred_mode"] == "auto"
    assert result["preferred_policy"] == "rebuild_only_if_invalid"
    assert result["policies"] == ["rebuild_only_if_invalid", "always_rebuild_copy"]
    assert len(result["comparisons"]) == 2
