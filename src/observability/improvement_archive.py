from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.atomic_io import atomic_json_write, safe_json_read


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


ARCHIVE_VERSION = 1


SEED_RULES: Dict[str, Dict[str, Any]] = {
    "awj_web_research_shortlist_cleanup_01": {
        "failure_class": "tool_routing_noise",
        "problem_signature": "preview:web_research:browser_noise",
        "intervention_type": "routing_rule",
        "files_changed": [
            "src/orchestration/llm_bridge.py",
            "src/tests/test_llm_bridge_workflow_guards.py",
        ],
        "reuse_rule": "Suggest when a preview/web-research turn leaks browser automation or dev-helper tools into the shortlist.",
        "rollout_guard": "suggest_only_same_failure_class",
        "evidence_fields": [
            "payload.selected_servers",
            "payload.selected_categories",
            "payload.mcp_shortlist_context_intents",
        ],
        "required_fields": [
            "payload.selected_servers",
            "payload.selected_categories",
        ],
        "required_absent_values": {
            "payload.tool_names": [
                "clone_element_to_file",
                "get_active_tab",
                "get_request_details",
                "get_file_info",
            ]
        },
    },
    "awj_preview_payload_budget_01": {
        "failure_class": "tool_routing_observability_latency",
        "problem_signature": "preview:payload:unbounded_debug_rows",
        "intervention_type": "payload_budget",
        "files_changed": [
            "src/orchestration/llm_bridge.py",
            "src/tests/test_llm_bridge_workflow_guards.py",
        ],
        "reuse_rule": "Suggest when preview or last_payload debugging becomes large, slow, or dominated by row/detail blobs rather than summary fields.",
        "rollout_guard": "suggest_only_debug_surfaces",
        "evidence_fields": [
            "payload.selected_servers",
            "payload.mcp_shortlist_rows_total",
            "payload.mcp_shortlist_rows_truncated",
        ],
        "required_truthy_fields": ["ok"],
        "required_fields": [
            "payload.mcp_shortlist_rows_total",
            "payload.mcp_shortlist_rows_truncated",
        ],
    },
    "awj_web_research_ranking_cleanup_01": {
        "failure_class": "tool_routing_noise",
        "problem_signature": "preview:web_research:ranking_local_video_noise",
        "intervention_type": "ranking_rule",
        "files_changed": [
            "src/orchestration/llm_bridge.py",
            "src/tests/test_llm_bridge_workflow_guards.py",
        ],
        "reuse_rule": "Suggest when pure web-research turns still rank local/video search tools despite a clean web-only server clamp.",
        "rollout_guard": "suggest_only_same_problem_signature",
        "evidence_fields": [
            "payload.tool_names",
            "payload.mcp_shortlist_names",
            "payload.mcp_shortlist_context_intents",
        ],
        "required_truthy_fields": ["ok"],
        "required_absent_values": {
            "payload.mcp_shortlist_names": [
                "brave_local_search",
                "brave_video_search",
            ]
        },
    },
    "awj_flight_ledger_impl_phase1_01": {
        "failure_class": "flight_recorder_integrity",
        "problem_signature": "flight_recorder:no_hash_chain_verification",
        "intervention_type": "ledger_integrity",
        "files_changed": [
            "src/core/services/flight_recorder.py",
            "scripts/vera_flight_ledger_verify.py",
            "src/tests/test_flight_ledger.py",
        ],
        "reuse_rule": "Suggest when a recorder or audit trail needs tamper-evident continuity and verifier coverage without replacing the current source-of-truth log.",
        "rollout_guard": "suggest_only_append_only_logs",
        "evidence_fields": [
            "verify.ok",
            "verify.records",
            "verify.errors",
            "verify.warnings",
        ],
        "required_truthy_fields": ["verify.ok"],
    },
}


def _load_json(path: Path, default: Any) -> Any:
    loaded = safe_json_read(path, default)
    return loaded if loaded is not None else default


def _dotted_get(payload: Dict[str, Any], dotted: str) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _extract_success_evidence(artifact_path: Path, dotted_fields: List[str]) -> Dict[str, Any]:
    if not artifact_path.exists():
        return {"artifact_exists": False}
    payload = _load_json(artifact_path, {})
    evidence: Dict[str, Any] = {"artifact_exists": True}
    for dotted in dotted_fields:
        evidence[dotted] = _dotted_get(payload, dotted)
    return evidence


def _value_contains(container: Any, expected: Any) -> bool:
    if isinstance(container, list):
        return expected in container
    if isinstance(container, dict):
        return expected in container
    if isinstance(container, str):
        return str(expected) in container
    return False


def _field_exists(payload: Dict[str, Any], dotted: str) -> bool:
    sentinel = object()
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return False
        current = current.get(part, sentinel)
        if current is sentinel:
            return False
    return True


def _proof_satisfies_rule(artifact_path: Path, rule: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    if not artifact_path.exists():
        return False, {"artifact_exists": False, "reason": "artifact_missing"}

    payload = _load_json(artifact_path, {})
    if not isinstance(payload, dict):
        return False, {"artifact_exists": True, "reason": "artifact_invalid_json"}

    missing_fields: List[str] = []
    for dotted in list(rule.get("required_fields") or []):
        if not _field_exists(payload, dotted):
            missing_fields.append(dotted)

    falsey_fields: List[str] = []
    for dotted in list(rule.get("required_truthy_fields") or []):
        if not _dotted_get(payload, dotted):
            falsey_fields.append(dotted)

    unexpected_values: Dict[str, List[Any]] = {}
    for dotted, values in dict(rule.get("required_absent_values") or {}).items():
        container = _dotted_get(payload, dotted)
        hits = [value for value in list(values or []) if _value_contains(container, value)]
        if hits:
            unexpected_values[dotted] = hits

    ok = not missing_fields and not falsey_fields and not unexpected_values
    return ok, {
        "artifact_exists": True,
        "reason": "ok" if ok else "proof_checks_failed",
        "missing_fields": missing_fields,
        "falsey_fields": falsey_fields,
        "unexpected_values": unexpected_values,
    }


def _make_entry(item: Dict[str, Any], rule: Dict[str, Any], proof_check: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(item.get("metadata") or {})
    artifact = Path(str(metadata.get("artifact") or ""))
    archived_at = str(metadata.get("archived_at_utc") or item.get("updated_at_utc") or utc_iso())
    proof_artifact = str(artifact) if artifact else ""
    return {
        "archive_id": f"ia_{item['id']}",
        "created_at_utc": archived_at,
        "title": str(item.get("title") or ""),
        "failure_class": str(rule["failure_class"]),
        "problem_signature": str(rule["problem_signature"]),
        "intervention_type": str(rule["intervention_type"]),
        "source_work_item_id": str(item.get("id") or ""),
        "source_task_id": str(metadata.get("completed_by_task_id") or ""),
        "proof_artifact": proof_artifact,
        "files_changed": list(rule.get("files_changed") or []),
        "success_evidence": _extract_success_evidence(artifact, list(rule.get("evidence_fields") or [])),
        "proof_check": proof_check,
        "reuse_rule": str(rule.get("reuse_rule") or ""),
        "rollout_guard": str(rule.get("rollout_guard") or "suggest_only"),
        "status": "active",
    }


def materialize_improvement_archive(
    *,
    work_jar_path: Path,
    archive_path: Path,
) -> Dict[str, Any]:
    jar = _load_json(work_jar_path, {})
    archived_items = list(jar.get("archived_items") or [])
    existing = _load_json(archive_path, {})
    entries = list(existing.get("entries") or [])
    by_archive_id = {str(entry.get("archive_id") or ""): entry for entry in entries}

    added = 0
    updated = 0
    skipped = 0
    skipped_details: List[Dict[str, Any]] = []

    for item in archived_items:
        item_id = str(item.get("id") or "")
        rule = SEED_RULES.get(item_id)
        metadata = dict(item.get("metadata") or {})
        if not rule:
            skipped += 1
            skipped_details.append({"id": item_id, "reason": "no_seed_rule"})
            continue
        if str(item.get("status") or "") != "completed":
            skipped += 1
            skipped_details.append({"id": item_id, "reason": "not_completed"})
            continue
        if not metadata.get("artifact"):
            skipped += 1
            skipped_details.append({"id": item_id, "reason": "missing_artifact"})
            continue
        artifact_path = Path(str(metadata.get("artifact") or ""))
        proof_ok, proof_check = _proof_satisfies_rule(artifact_path, rule)
        if not proof_ok:
            skipped += 1
            skipped_details.append({"id": item_id, "reason": "proof_checks_failed", "proof_check": proof_check})
            continue
        entry = _make_entry(item, rule, proof_check)
        archive_id = entry["archive_id"]
        if archive_id in by_archive_id:
            by_archive_id[archive_id] = entry
            updated += 1
        else:
            by_archive_id[archive_id] = entry
            added += 1

    final_entries = sorted(
        by_archive_id.values(),
        key=lambda item: (item.get("created_at_utc") or "", item.get("archive_id") or ""),
    )
    payload = {
        "version": ARCHIVE_VERSION,
        "updated_at_utc": utc_iso(),
        "entries": final_entries,
    }
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(archive_path, payload)
    return {
        "archive_path": str(archive_path),
        "entries": len(final_entries),
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "skipped_details": skipped_details,
    }


def suggest_improvement_entries(
    *,
    archive_path: Path,
    problem_signature: str = "",
    failure_class: str = "",
    limit: int = 3,
) -> Dict[str, Any]:
    archive = _load_json(archive_path, {})
    entries = list(archive.get("entries") or [])
    normalized_signature = str(problem_signature or "").strip().lower()
    normalized_class = str(failure_class or "").strip().lower()

    matches: List[Dict[str, Any]] = []
    for entry in entries:
        if str(entry.get("status") or "") != "active":
            continue
        entry_signature = str(entry.get("problem_signature") or "").strip().lower()
        entry_class = str(entry.get("failure_class") or "").strip().lower()
        if normalized_signature and entry_signature == normalized_signature:
            matches.append(copy.deepcopy(entry))
            continue
        if normalized_class and entry_class == normalized_class:
            matches.append(copy.deepcopy(entry))

    def _priority(entry: Dict[str, Any]) -> Tuple[int, str]:
        entry_signature = str(entry.get("problem_signature") or "").strip().lower()
        exact = int(bool(normalized_signature) and entry_signature == normalized_signature)
        return (-exact, str(entry.get("created_at_utc") or ""))

    matches.sort(key=_priority)
    return {
        "archive_path": str(archive_path),
        "query": {
            "problem_signature": problem_signature,
            "failure_class": failure_class,
            "limit": limit,
        },
        "matches": matches[: max(0, int(limit))],
        "match_count": len(matches),
    }


def build_archive_seed_payload(
    *,
    archive_path: Path,
    problem_signature: str = "",
    failure_class: str = "",
    limit: int = 3,
) -> Dict[str, Any]:
    result = suggest_improvement_entries(
        archive_path=archive_path,
        problem_signature=problem_signature,
        failure_class=failure_class,
        limit=limit,
    )
    compact_matches: List[Dict[str, Any]] = []
    context_lines: List[str] = []
    for entry in list(result.get("matches") or []):
        compact = {
            "archive_id": str(entry.get("archive_id") or ""),
            "title": str(entry.get("title") or ""),
            "failure_class": str(entry.get("failure_class") or ""),
            "problem_signature": str(entry.get("problem_signature") or ""),
            "intervention_type": str(entry.get("intervention_type") or ""),
            "proof_artifact": str(entry.get("proof_artifact") or ""),
            "files_changed": list(entry.get("files_changed") or []),
            "reuse_rule": str(entry.get("reuse_rule") or ""),
            "rollout_guard": str(entry.get("rollout_guard") or ""),
        }
        compact_matches.append(compact)
        files_changed = ", ".join(compact["files_changed"][:3])
        context_lines.append(
            f"- {compact['title']} [{compact['failure_class']}] "
            f"(signature={compact['problem_signature']}, proof={compact['proof_artifact']}, files={files_changed})"
        )

    context_block = ""
    if context_lines:
        context_block = "Archive suggestions:\n" + "\n".join(context_lines)

    return {
        "archive_path": str(archive_path),
        "query": dict(result.get("query") or {}),
        "match_count": len(compact_matches),
        "matches": compact_matches,
        "context_block": context_block,
    }
