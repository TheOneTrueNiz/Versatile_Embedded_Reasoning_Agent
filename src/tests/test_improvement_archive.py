from __future__ import annotations

import json
from pathlib import Path

from observability.improvement_archive import (
    build_archive_seed_payload,
    materialize_improvement_archive,
    suggest_improvement_entries,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _build_work_jar(artifact_map: dict[str, str]) -> dict:
    archived_items = []
    for item_id, artifact in artifact_map.items():
        archived_items.append(
            {
                "id": item_id,
                "title": f"title:{item_id}",
                "status": "completed",
                "updated_at_utc": "2026-03-26T21:00:00Z",
                "metadata": {
                    "artifact": artifact,
                    "completed_by_task_id": f"TASK_{item_id}",
                    "archived_at_utc": "2026-03-26T21:00:00Z",
                },
            }
        )
    return {"version": 1, "items": [], "archived_items": archived_items}


def test_materialize_improvement_archive_seeds_known_entries(tmp_path: Path) -> None:
    artifacts = {
        "awj_web_research_shortlist_cleanup_01": tmp_path / "web_cleanup.json",
        "awj_preview_payload_budget_01": tmp_path / "preview_budget.json",
        "awj_web_research_ranking_cleanup_01": tmp_path / "ranking_cleanup.json",
        "awj_flight_ledger_impl_phase1_01": tmp_path / "flight_ledger.json",
    }
    _write_json(
        artifacts["awj_web_research_shortlist_cleanup_01"],
        {
            "payload": {
                "selected_servers": ["brave-search", "searxng", "grokipedia"],
                "selected_categories": ["web", "time"],
                "tool_names": ["brave_ai_grounding", "search"],
            }
        },
    )
    _write_json(
        artifacts["awj_preview_payload_budget_01"],
        {
            "ok": True,
            "payload": {
                "selected_servers": ["brave-search", "grokipedia"],
                "mcp_shortlist_rows_total": 8,
                "mcp_shortlist_rows_truncated": False,
            },
        },
    )
    _write_json(
        artifacts["awj_web_research_ranking_cleanup_01"],
        {
            "ok": True,
            "payload": {
                "tool_names": ["brave_ai_grounding", "search"],
                "mcp_shortlist_names": ["brave_ai_grounding", "search", "get_page"],
                "mcp_shortlist_context_intents": ["web"],
            },
        },
    )
    _write_json(
        artifacts["awj_flight_ledger_impl_phase1_01"],
        {
            "verify": {
                "ok": True,
                "records": 6,
                "errors": [],
                "warnings": [],
            }
        },
    )

    work_jar_path = tmp_path / "autonomy_work_jar.json"
    archive_path = tmp_path / "improvement_archive.json"
    _write_json(work_jar_path, _build_work_jar({k: str(v) for k, v in artifacts.items()}))

    result = materialize_improvement_archive(work_jar_path=work_jar_path, archive_path=archive_path)
    assert result["entries"] == 4
    assert result["added"] == 4
    payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert len(payload["entries"]) == 4
    assert {entry["source_work_item_id"] for entry in payload["entries"]} == set(artifacts)


def test_materialize_improvement_archive_skips_failed_proof(tmp_path: Path) -> None:
    bad_artifact = tmp_path / "bad_ranking_cleanup.json"
    _write_json(
        bad_artifact,
        {
            "ok": True,
            "payload": {
                "tool_names": ["brave_ai_grounding", "search"],
                "mcp_shortlist_names": ["brave_ai_grounding", "brave_local_search", "brave_video_search"],
                "mcp_shortlist_context_intents": ["web"],
            },
        },
    )
    work_jar_path = tmp_path / "autonomy_work_jar.json"
    archive_path = tmp_path / "improvement_archive.json"
    _write_json(
        work_jar_path,
        _build_work_jar({"awj_web_research_ranking_cleanup_01": str(bad_artifact)}),
    )

    result = materialize_improvement_archive(work_jar_path=work_jar_path, archive_path=archive_path)
    assert result["entries"] == 0
    assert result["skipped"] == 1
    assert result["skipped_details"][0]["id"] == "awj_web_research_ranking_cleanup_01"


def test_suggest_improvement_entries_prefers_exact_signature(tmp_path: Path) -> None:
    archive_path = tmp_path / "improvement_archive.json"
    _write_json(
        archive_path,
        {
            "version": 1,
            "updated_at_utc": "2026-03-26T21:00:00Z",
            "entries": [
                {
                    "archive_id": "ia_exact",
                    "created_at_utc": "2026-03-26T21:00:00Z",
                    "title": "Exact",
                    "failure_class": "tool_routing_noise",
                    "problem_signature": "preview:web_research:browser_noise",
                    "intervention_type": "routing_rule",
                    "source_work_item_id": "awj_x",
                    "source_task_id": "TASK-X",
                    "proof_artifact": "tmp/audits/x.json",
                    "files_changed": ["src/orchestration/llm_bridge.py"],
                    "success_evidence": {"artifact_exists": True},
                    "proof_check": {"artifact_exists": True, "reason": "ok"},
                    "reuse_rule": "Suggest exact reuse.",
                    "rollout_guard": "suggest_only",
                    "status": "active",
                },
                {
                    "archive_id": "ia_class",
                    "created_at_utc": "2026-03-26T20:00:00Z",
                    "title": "Class",
                    "failure_class": "tool_routing_noise",
                    "problem_signature": "preview:other",
                    "intervention_type": "routing_rule",
                    "source_work_item_id": "awj_y",
                    "source_task_id": "TASK-Y",
                    "proof_artifact": "tmp/audits/y.json",
                    "files_changed": ["src/orchestration/llm_bridge.py"],
                    "success_evidence": {"artifact_exists": True},
                    "proof_check": {"artifact_exists": True, "reason": "ok"},
                    "reuse_rule": "Suggest class reuse.",
                    "rollout_guard": "suggest_only",
                    "status": "active",
                },
            ],
        },
    )

    result = suggest_improvement_entries(
        archive_path=archive_path,
        problem_signature="preview:web_research:browser_noise",
        failure_class="tool_routing_noise",
        limit=2,
    )
    assert result["match_count"] == 2
    assert result["matches"][0]["archive_id"] == "ia_exact"


def test_build_archive_seed_payload_formats_suggestion_context(tmp_path: Path) -> None:
    archive_path = tmp_path / "improvement_archive.json"
    _write_json(
        archive_path,
        {
            "version": 1,
            "updated_at_utc": "2026-03-26T21:00:00Z",
            "entries": [
                {
                    "archive_id": "ia_exact",
                    "created_at_utc": "2026-03-26T21:00:00Z",
                    "title": "Exact",
                    "failure_class": "tool_routing_noise",
                    "problem_signature": "preview:web_research:browser_noise",
                    "intervention_type": "routing_rule",
                    "source_work_item_id": "awj_x",
                    "source_task_id": "TASK-X",
                    "proof_artifact": "tmp/audits/x.json",
                    "files_changed": ["src/orchestration/llm_bridge.py"],
                    "success_evidence": {"artifact_exists": True},
                    "proof_check": {"artifact_exists": True, "reason": "ok"},
                    "reuse_rule": "Suggest exact reuse.",
                    "rollout_guard": "suggest_only",
                    "status": "active",
                }
            ],
        },
    )
    payload = build_archive_seed_payload(
        archive_path=archive_path,
        problem_signature="preview:web_research:browser_noise",
        failure_class="tool_routing_noise",
        limit=3,
    )
    assert payload["match_count"] == 1
    assert payload["matches"][0]["archive_id"] == "ia_exact"
    assert "Archive suggestions:" in payload["context_block"]
    assert "preview:web_research:browser_noise" in payload["context_block"]
