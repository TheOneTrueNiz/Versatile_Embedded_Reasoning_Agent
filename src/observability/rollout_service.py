from __future__ import annotations

import json
import re
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.atomic_io import atomic_json_write, safe_json_read
from core.foundation.master_list import MasterTaskList, TaskPriority, TaskStatus
from core.services.flight_recorder import (
    AIRResult,
    FlightRecorder,
    _canonical_json,
    _compute_ledger_hash_self,
    _sha256_hex,
    verify_flight_ledger,
)
from observability.improvement_archive import build_archive_seed_payload, materialize_improvement_archive


DEFAULT_MAX_RUNTIME_SECONDS = 90
DEFAULT_MAX_STEPS = 12
DEFAULT_MAX_TOOL_CALLS = 8
DEFAULT_BASE_URL = "http://127.0.0.1:8788"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class RolloutPaths:
    work_jar_path: Path
    output_dir: Path
    flight_recorder_dir: Path
    registry_path: Optional[Path] = None


class RolloutService:
    def __init__(self, paths: RolloutPaths):
        self.paths = paths

    def _policy_registry_path(self) -> Path:
        return self.paths.registry_path or (self.paths.work_jar_path.parent / "rollout_policy_registry.json")

    def _scorecard_path(self) -> Path:
        return self.paths.work_jar_path.parent / "rollout_cross_subsystem_scorecard.json"

    def load_work_jar(self) -> Dict[str, Any]:
        data = safe_json_read(self.paths.work_jar_path, default={}) or {}
        if not isinstance(data, dict):
            data = {}
        if not isinstance(data.get("items"), list):
            data["items"] = []
        if not isinstance(data.get("archived_items"), list):
            data["archived_items"] = []
        return data

    def load_policy_registry(self) -> Dict[str, Any]:
        data = safe_json_read(self._policy_registry_path(), default={}) or {}
        if not isinstance(data, dict):
            data = {}
        if not isinstance(data.get("entries"), dict):
            data["entries"] = {}
        data["version"] = 1
        return data

    def _write_policy_registry(self, payload: Dict[str, Any]) -> Path:
        registry = dict(payload or {})
        registry["version"] = 1
        registry["updated_at_utc"] = utc_iso()
        if not isinstance(registry.get("entries"), dict):
            registry["entries"] = {}
        path = self._policy_registry_path()
        atomic_json_write(path, registry, indent=2)
        return path

    def _get_promoted_policy_entry(self, *, executor_kind: str) -> Dict[str, Any]:
        normalized_kind = str(executor_kind or "").strip()
        if not normalized_kind:
            return {}
        registry = self.load_policy_registry()
        entries = dict(registry.get("entries") or {})
        row = entries.get(f"executor_kind:{normalized_kind}")
        return dict(row or {}) if isinstance(row, dict) else {}

    def _prune_promoted_policy_entry(self, *, executor_kind: str) -> Dict[str, Any]:
        normalized_kind = str(executor_kind or "").strip()
        if not normalized_kind:
            return {"ok": False, "reason": "missing_executor_kind"}
        registry = self.load_policy_registry()
        entries = dict(registry.get("entries") or {})
        entry_key = f"executor_kind:{normalized_kind}"
        existing = dict(entries.get(entry_key) or {}) if isinstance(entries.get(entry_key), dict) else {}
        if entry_key in entries:
            entries.pop(entry_key, None)
            registry["entries"] = entries
            registry_path = self._write_policy_registry(registry)
            return {
                "ok": True,
                "reason": "registry_entry_pruned",
                "entry_key": entry_key,
                "registry_path": str(registry_path),
                "removed_entry": existing,
            }
        return {
            "ok": True,
            "reason": "registry_entry_absent",
            "entry_key": entry_key,
        }

    def promote_comparison_result(self, comparison_result: Dict[str, Any]) -> Dict[str, Any]:
        work_item_id = str(comparison_result.get("work_item_id") or "").strip()
        comparisons = list(comparison_result.get("comparisons") or [])
        preferred_rollout_id = str(comparison_result.get("preferred_rollout_id") or "").strip()
        preferred: Dict[str, Any] = {}
        for row in comparisons:
            if str(row.get("rollout_id") or "").strip() == preferred_rollout_id:
                preferred = dict(row)
                break
        if not preferred and comparisons:
            preferred = dict(comparisons[0] or {})
        executor_kind = str(preferred.get("executor_kind") or "").strip()
        if not executor_kind and work_item_id:
            try:
                item = self.find_work_item(work_item_id, include_archived=True)
            except Exception:
                item = {}
            executor_kind = self._select_local_executor_kind(item) if item else ""
        if not executor_kind:
            return {
                "ok": False,
                "reason": "missing_executor_kind",
                "work_item_id": work_item_id,
            }
        registry = self.load_policy_registry()
        entries = dict(registry.get("entries") or {})
        entry_key = f"executor_kind:{executor_kind}"
        promoted_entry = {
            "scope": "executor_kind",
            "executor_kind": executor_kind,
            "preferred_mode": str(comparison_result.get("preferred_mode") or "auto"),
            "preferred_policy": str(comparison_result.get("preferred_policy") or ""),
            "source_work_item_id": work_item_id,
            "comparison_rollout_id": preferred_rollout_id,
            "comparison_finished_at_utc": str(comparison_result.get("finished_at_utc") or ""),
            "comparisons_count": len(comparisons),
            "promoted_at_utc": utc_iso(),
        }
        entries[entry_key] = promoted_entry
        registry["entries"] = entries
        registry_path = self._write_policy_registry(registry)
        return {
            "ok": True,
            "entry_key": entry_key,
            "registry_path": str(registry_path),
            "entry": promoted_entry,
        }

    def _normalize_comparison_artifact(self, payload: Any) -> Dict[str, Any]:
        if isinstance(payload, dict):
            compare = payload.get("compare")
            if isinstance(compare, dict):
                normalized = dict(compare)
                if isinstance(payload.get("ledger_verify"), dict):
                    normalized["ledger_verify"] = dict(payload.get("ledger_verify") or {})
                normalized["_artifact_shape"] = "wrapped"
                return normalized
            normalized = dict(payload)
            normalized["_artifact_shape"] = "direct"
            return normalized
        return {}

    def summarize_comparison_artifact(self, comparison_path: Path) -> Dict[str, Any]:
        payload = safe_json_read(comparison_path, default={}) or {}
        normalized = self._normalize_comparison_artifact(payload)
        comparisons = list(normalized.get("comparisons") or [])
        preferred_rollout_id = str(normalized.get("preferred_rollout_id") or "").strip()
        preferred_row: Dict[str, Any] = {}
        for row in comparisons:
            if str((row or {}).get("rollout_id") or "").strip() == preferred_rollout_id:
                preferred_row = dict(row or {})
                break
        if not preferred_row and comparisons:
            preferred_row = dict(comparisons[0] or {})
        executor_kind = str(preferred_row.get("executor_kind") or "").strip()
        if not executor_kind:
            for row in comparisons:
                executor_kind = str((row or {}).get("executor_kind") or "").strip()
                if executor_kind:
                    break
        work_item_id = str(normalized.get("work_item_id") or "").strip()
        preferred_mode = str(normalized.get("preferred_mode") or "").strip()
        preferred_policy = str(normalized.get("preferred_policy") or "").strip()
        valid = bool(comparisons) and bool(work_item_id) and bool(preferred_mode)
        passing_count = sum(1 for row in comparisons if bool((row or {}).get("ok")))
        failing_count = max(0, len(comparisons) - passing_count)
        summary = {
            "ok": valid and bool(normalized.get("ok")),
            "valid": valid,
            "artifact_path": str(comparison_path),
            "artifact_shape": str(normalized.get("_artifact_shape") or "direct"),
            "work_item_id": work_item_id,
            "executor_kind": executor_kind,
            "preferred_mode": preferred_mode,
            "preferred_policy": preferred_policy,
            "comparisons_count": len(comparisons),
            "passing_count": passing_count,
            "failing_count": failing_count,
            "has_policy_variants": len({str((row or {}).get('policy') or '').strip() for row in comparisons if str((row or {}).get('policy') or '').strip()}) > 1,
            "has_registry_promotion": isinstance(normalized.get("registry_promotion"), dict),
            "finished_at_utc": str(normalized.get("finished_at_utc") or ""),
            "ledger_verify_ok": bool((normalized.get("ledger_verify") or {}).get("ok")),
            "reason": "ok" if valid else "invalid_or_empty_comparison_artifact",
        }
        if not valid:
            if not comparisons:
                summary["reason"] = "missing_comparisons"
            elif not work_item_id:
                summary["reason"] = "missing_work_item_id"
            elif not preferred_mode:
                summary["reason"] = "missing_preferred_mode"
        return {
            "summary": summary,
            "comparison": normalized,
        }

    def build_cross_subsystem_scorecard(
        self,
        *,
        comparison_paths: List[Path],
        promote: bool = False,
    ) -> Dict[str, Any]:
        started_at = utc_iso()
        scanned: List[Dict[str, Any]] = []
        valid_entries: List[Dict[str, Any]] = []
        invalid_entries: List[Dict[str, Any]] = []
        for raw_path in comparison_paths:
            path = Path(raw_path)
            result = self.summarize_comparison_artifact(path)
            summary = dict(result.get("summary") or {})
            scanned.append(summary)
            if summary.get("valid"):
                valid_entries.append({
                    "summary": summary,
                    "comparison": dict(result.get("comparison") or {}),
                })
            else:
                invalid_entries.append(summary)

        latest_by_subsystem: Dict[str, Dict[str, Any]] = {}
        for row in valid_entries:
            summary = dict(row.get("summary") or {})
            subsystem_key = str(summary.get("executor_kind") or "").strip() or f"work_item:{str(summary.get('work_item_id') or '').strip()}"
            incumbent = latest_by_subsystem.get(subsystem_key)
            candidate_finished = str(summary.get("finished_at_utc") or "")
            incumbent_finished = str(((incumbent or {}).get("summary") or {}).get("finished_at_utc") or "")
            if incumbent is None or candidate_finished >= incumbent_finished:
                latest_by_subsystem[subsystem_key] = row

        subsystem_rows: List[Dict[str, Any]] = []
        promotions: List[Dict[str, Any]] = []
        policy_coverage_count = 0
        for subsystem_key, row in sorted(latest_by_subsystem.items()):
            summary = dict(row.get("summary") or {})
            comparison = dict(row.get("comparison") or {})
            promotion_eligible = bool(summary.get("ok")) and int(summary.get("comparisons_count") or 0) > 0 and int(summary.get("failing_count") or 0) == 0
            if str(summary.get("preferred_policy") or "").strip():
                policy_coverage_count += 1
            subsystem_row = {
                "subsystem_key": subsystem_key,
                "executor_kind": str(summary.get("executor_kind") or ""),
                "work_item_id": str(summary.get("work_item_id") or ""),
                "artifact_path": str(summary.get("artifact_path") or ""),
                "preferred_mode": str(summary.get("preferred_mode") or ""),
                "preferred_policy": str(summary.get("preferred_policy") or ""),
                "comparisons_count": int(summary.get("comparisons_count") or 0),
                "passing_count": int(summary.get("passing_count") or 0),
                "failing_count": int(summary.get("failing_count") or 0),
                "has_policy_variants": bool(summary.get("has_policy_variants")),
                "ledger_verify_ok": bool(summary.get("ledger_verify_ok")),
                "finished_at_utc": str(summary.get("finished_at_utc") or ""),
                "promotion_eligible": promotion_eligible,
                "status": "preferred_policy_selected" if str(summary.get("preferred_policy") or "").strip() else "preferred_mode_selected",
            }
            if promote:
                if promotion_eligible:
                    promotion = self.promote_comparison_result(comparison)
                else:
                    promotion = self._prune_promoted_policy_entry(executor_kind=subsystem_row["executor_kind"])
                    promotion["promotion_eligible"] = False
                    promotion["work_item_id"] = subsystem_row["work_item_id"]
                subsystem_row["registry_promotion"] = promotion
                promotions.append(promotion)
            subsystem_rows.append(subsystem_row)

        subsystem_count = len(subsystem_rows)
        successful_subsystems = sum(
            1
            for row in subsystem_rows
            if int(row.get("comparisons_count") or 0) > 0 and int(row.get("failing_count") or 0) == 0
        )
        score_pct = round((successful_subsystems / subsystem_count) * 100.0, 1) if subsystem_count else 0.0
        result = {
            "ok": bool(subsystem_count),
            "started_at_utc": started_at,
            "finished_at_utc": utc_iso(),
            "comparison_path_count": len(comparison_paths),
            "valid_artifact_count": len(valid_entries),
            "invalid_artifact_count": len(invalid_entries),
            "subsystem_count": subsystem_count,
            "successful_subsystem_count": successful_subsystems,
            "policy_coverage_count": policy_coverage_count,
            "score_pct": score_pct,
            "scanned_artifacts": scanned,
            "invalid_artifacts": invalid_entries,
            "subsystems": subsystem_rows,
            "promotions": promotions,
        }
        scorecard_path = self._scorecard_path()
        atomic_json_write(scorecard_path, result, indent=2)
        result["scorecard_path"] = str(scorecard_path)
        return result

    def find_work_item(self, item_id: str, *, include_archived: bool = False) -> Dict[str, Any]:
        jar = self.load_work_jar()
        pools: List[List[Dict[str, Any]]] = [list(jar.get("items") or [])]
        if include_archived:
            pools.append(list(jar.get("archived_items") or []))
        for pool in pools:
            for item in pool:
                if str(item.get("id") or "") == item_id:
                    return dict(item)
        raise KeyError(f"work_item_not_found:{item_id}")

    def _extract_context_paths(self, text: str) -> List[Path]:
        candidates: List[Path] = []
        for token in re.findall(r"[A-Za-z0-9_./\-]+\.(?:md|json|jsonl|txt|py)", text or ""):
            path = Path(token)
            if path.exists() and path not in candidates:
                candidates.append(path)
        return candidates

    def _candidate_artifact_paths(self, item: Dict[str, Any], artifact_override: Optional[Path]) -> List[Path]:
        metadata = dict(item.get("metadata") or {})
        seen: set[str] = set()
        ordered: List[Path] = []
        raw_candidates: List[Any] = [artifact_override, metadata.get("artifact"), item.get("source")]
        raw_candidates.extend(self._extract_context_paths(str(item.get("context") or "")))
        for candidate in raw_candidates:
            if not candidate:
                continue
            path = Path(str(candidate))
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(path)
        return ordered

    def build_work_item_envelope(
        self,
        *,
        item: Dict[str, Any],
        artifact_path: Optional[Path] = None,
        rollout_id: Optional[str] = None,
        policy_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        metadata = dict(item.get("metadata") or {})
        if str(policy_override or "").strip():
            metadata["rollout_policy"] = str(policy_override).strip().lower()
        completion_contract = dict(item.get("completion_contract") or {})
        context = str(item.get("context") or "").strip()
        context_refs: List[str] = []
        for candidate in self._candidate_artifact_paths(item, artifact_path):
            value = str(candidate)
            if value and value not in context_refs:
                context_refs.append(value)
        archive_query = dict(metadata.get("archive_query") or {})
        problem_signature = str(
            archive_query.get("problem_signature")
            or metadata.get("problem_signature")
            or ""
        ).strip()
        failure_class = str(
            archive_query.get("failure_class")
            or metadata.get("failure_class")
            or ""
        ).strip()
        return {
            "rollout_id": rollout_id or f"rollout_{uuid.uuid4().hex[:16]}",
            "created_at_utc": utc_iso(),
            "source": "work_jar",
            "work_item_id": str(item.get("id") or ""),
            "title": str(item.get("title") or "").strip(),
            "objective": str(item.get("objective") or "").strip(),
            "status": str(item.get("status") or ""),
            "priority": str(item.get("priority") or "normal"),
            "problem_signature": problem_signature,
            "failure_class": failure_class,
            "context": context,
            "context_refs": context_refs,
            "tool_policy": {
                "tool_choice": str(item.get("tool_choice") or "auto"),
                "allowed_servers": [],
                "max_tool_calls": DEFAULT_MAX_TOOL_CALLS,
            },
            "budget": {
                "max_runtime_seconds": DEFAULT_MAX_RUNTIME_SECONDS,
                "max_steps": DEFAULT_MAX_STEPS,
            },
            "success_checks": [
                "artifact_exists",
                "required_markers_present",
            ],
            "completion_contract": completion_contract,
            "metadata": metadata,
        }

    def score_artifact(self, envelope: Dict[str, Any], artifact_path: Optional[Path]) -> Dict[str, Any]:
        required_markers = list(
            ((envelope.get("completion_contract") or {}).get("required_markers") or [])
        )
        artifact_exists = bool(artifact_path and artifact_path.exists())
        content = ""
        artifact_kind = "missing"
        if artifact_exists and artifact_path is not None:
            try:
                content = artifact_path.read_text(encoding="utf-8", errors="ignore")
                artifact_kind = "text"
            except Exception:
                try:
                    payload = safe_json_read(artifact_path, default={})
                    content = json.dumps(payload, ensure_ascii=True, default=str)
                    artifact_kind = "json"
                except Exception:
                    content = ""
                    artifact_kind = "unreadable"
        marker_hits = [marker for marker in required_markers if str(marker) and str(marker) in content]
        missing_markers = [marker for marker in required_markers if marker not in marker_hits]
        passed_checks: List[str] = []
        failed_checks: List[str] = []
        if artifact_exists:
            passed_checks.append("artifact_exists")
        else:
            failed_checks.append("artifact_exists")
        if not required_markers or not missing_markers:
            passed_checks.append("required_markers_present")
        else:
            failed_checks.append("required_markers_present")
        success = not failed_checks
        return {
            "ok": success,
            "artifact_exists": artifact_exists,
            "artifact_path": str(artifact_path) if artifact_path else "",
            "artifact_kind": artifact_kind,
            "required_markers": required_markers,
            "marker_hits": marker_hits,
            "missing_markers": missing_markers,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
        }

    def resolve_best_artifact(self, item: Dict[str, Any], artifact_override: Optional[Path]) -> Dict[str, Any]:
        best_path: Optional[Path] = None
        best_score: Optional[Dict[str, Any]] = None
        envelope = self.build_work_item_envelope(item=item, artifact_path=artifact_override)
        for candidate in self._candidate_artifact_paths(item, artifact_override):
            score = self.score_artifact(envelope, candidate)
            hits = len(score.get("marker_hits") or [])
            best_hits = len((best_score or {}).get("marker_hits") or [])
            if best_score is None:
                best_path, best_score = candidate, score
                continue
            if bool(score.get("ok")) and not bool(best_score.get("ok")):
                best_path, best_score = candidate, score
                continue
            if bool(score.get("ok")) == bool(best_score.get("ok")) and hits > best_hits:
                best_path, best_score = candidate, score
                continue
            if hits == best_hits and bool(score.get("artifact_exists")) and not bool(best_score.get("artifact_exists")):
                best_path, best_score = candidate, score
        if best_score is None:
            best_score = self.score_artifact(envelope, None)
        return {"artifact_path": best_path, "score": best_score}

    def _rollout_dir(self, rollout_id: str) -> Path:
        return self.paths.output_dir / rollout_id

    def _build_executor_artifact_text(self, envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> str:
        lines = [
            f"# Rollout Deliverable: {str(envelope.get('title') or '').strip()}",
            "",
            f"Rollout ID: {str(envelope.get('rollout_id') or '').strip()}",
            f"Work Item ID: {str(envelope.get('work_item_id') or '').strip()}",
            f"Objective: {str(envelope.get('objective') or '').strip()}",
            "",
            "## Deliverable Summary",
            "This file is a bounded local-action deliverable generated by the rollout executor from local evidence only.",
            "",
            "## Mechanical Score Inputs",
            f"Artifact Path: {str(artifact_path) if artifact_path else ''}",
            f"Artifact Exists: {str(bool(artifact_score.get('artifact_exists'))).lower()}",
            f"Passed Checks: {', '.join(list(artifact_score.get('passed_checks') or []))}",
            f"Failed Checks: {', '.join(list(artifact_score.get('failed_checks') or []))}",
            "",
            "## Required Markers",
        ]
        required_markers = list(artifact_score.get("required_markers") or [])
        if required_markers:
            lines.extend(f"- {marker}" for marker in required_markers)
        else:
            lines.append("- none")
        marker_hits = list(artifact_score.get("marker_hits") or [])
        if marker_hits:
            lines.extend(["", "## Marker Hits"])
            lines.extend(f"- {marker}" for marker in marker_hits)
        context = str(envelope.get("context") or "").strip()
        if context:
            lines.extend(["", "## Context", context[:4000]])
        if artifact_path and artifact_path.exists():
            try:
                excerpt = artifact_path.read_text(encoding="utf-8", errors="ignore")[:4000].strip()
            except Exception:
                excerpt = ""
            if excerpt:
                lines.extend(["", "## Evidence Excerpt", excerpt])
        return "\n".join(lines).strip() + "\n"

    def _score_task_contract(self, envelope: Dict[str, Any], task_text: str, task_status: str, task_id: str) -> Dict[str, Any]:
        contract = dict(envelope.get("completion_contract") or {})
        contract_kind = str(contract.get("kind") or "task_completed").strip().lower()
        evaluation: Dict[str, Any] = {
            "kind": contract_kind,
            "task_id": task_id,
            "task_status": task_status,
            "satisfied": False,
            "decision": "hold_item",
        }
        if task_status != TaskStatus.COMPLETED.value:
            evaluation["reason"] = f"task_status:{task_status or 'unknown'}"
            return evaluation
        if contract_kind == "task_completed":
            evaluation["satisfied"] = True
            evaluation["decision"] = "complete_item"
            evaluation["reason"] = "task_completed"
            return evaluation
        required_markers = [str(item).strip().lower() for item in (contract.get("required_markers") or []) if str(item).strip()]
        lowered = str(task_text or "").lower()
        present = [marker for marker in required_markers if marker in lowered]
        missing = [marker for marker in required_markers if marker not in lowered]
        match_mode = str(contract.get("match_mode") or "any").strip().lower()
        satisfied = (not missing) if match_mode == "all" else (bool(present) if required_markers else True)
        evaluation.update(
            {
                "required_markers": required_markers,
                "present_markers": present,
                "missing_markers": missing,
                "match_mode": match_mode,
                "satisfied": satisfied,
                "decision": "complete_item" if satisfied else "hold_item",
                "reason": "markers_satisfied" if satisfied else "missing_required_markers",
            }
        )
        return evaluation

    def _policy_preference_rank(self, policy: str) -> int:
        normalized = str(policy or "").strip().lower()
        ranking = {
            "": 0,
            "verified_only": 0,
            "strict_hold_aware": 0,
            "strict_signature": 0,
            "strict_operator_health": 0,
            "strict_note_required": 0,
            "strict_ack_required": 0,
            "strict_active_only": 0,
            "rebuild_only_if_invalid": 0,
            "verified_or_completed": 1,
            "raw_schedule": 1,
            "relaxed_failure_class": 1,
            "baseline_favoring_health": 1,
            "verifier_state_only": 1,
            "delivery_signal_only": 1,
            "include_inactive": 1,
            "always_rebuild_copy": 1,
        }
        return int(ranking.get(normalized, 2))

    def _select_local_executor_kind(self, item: Dict[str, Any]) -> str:
        item_id = str(item.get("id") or "").strip()
        objective = str(item.get("objective") or "").lower()
        title = str(item.get("title") or "").lower()
        if "state-sync" in objective or "state-sync" in title or "state sync" in objective or "state sync" in title:
            return "state_sync_surface_snapshot"
        if item_id == "awj_improvement_archive_operator_surface_01" or "operator diagnostics" in objective or "operator diagnostics" in title:
            return "improvement_archive_operator_surface"
        if "archive suggestion" in objective or "archive suggestion" in title or "archive suggestions" in objective or "archive suggestions" in title:
            return "improvement_archive_suggest"
        if "queue repair" in objective or "queue repair" in title or "queue maintenance" in objective or "queue maintenance" in title:
            return "autonomy_queue_repair"
        if "autonomy queue surface" in objective or "autonomy queue surface" in title or "queue health" in objective or "queue health" in title:
            return "autonomy_queue_surface_snapshot"
        if "week1 ops surface" in objective or "week1 ops surface" in title or "ops backlog surface" in objective or "ops backlog surface" in title:
            return "week1_ops_surface_snapshot"
        if "operator/runtime snapshot" in objective or "operator/runtime snapshot" in title or "operator snapshot" in objective or "operator snapshot" in title:
            return "operator_runtime_snapshot"
        if "week1 validation" in objective or "week1 validation" in title or "validation snapshot" in objective or "validation snapshot" in title:
            return "week1_validation_snapshot"
        if item_id == "awj_flight_ledger_impl_phase1_01" or "flight ledger" in objective or "flight ledger" in title:
            return "flight_ledger_verify"
        if item_id == "awj_improvement_archive_impl_phase1_01" or "improvement archive" in objective or "improvement archive" in title:
            return "improvement_archive_materialize"
        metadata = dict(item.get("metadata") or {})
        if metadata.get("archive_query") or "archive suggestions" in objective or "archive suggestions" in title:
            return "improvement_archive_suggest"
        return "isolated_toolless_task"

    def _default_improvement_archive_path(self) -> Path:
        return self.paths.work_jar_path.parent / "improvement_archive.json"

    def _copy_improvement_archive_for_rollout(self, rollout_dir: Path) -> Path:
        archive_copy = rollout_dir / "improvement_archive.json"
        source_archive = self._default_improvement_archive_path()
        if source_archive.exists():
            payload = safe_json_read(source_archive, default={}) or {}
            atomic_json_write(archive_copy, payload, indent=2)
            return archive_copy
        work_jar_copy = rollout_dir / "autonomy_work_jar.json"
        source_jar = self.load_work_jar()
        atomic_json_write(work_jar_copy, source_jar, indent=2)
        materialize_improvement_archive(work_jar_path=work_jar_copy, archive_path=archive_copy)
        return archive_copy

    def _copy_flight_recorder_for_rollout(self, rollout_dir: Path) -> Path:
        source_dir = self.paths.flight_recorder_dir
        target_dir = rollout_dir / "flight_recorder"
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in ("transitions.ndjson", "ledger.jsonl"):
            source = source_dir / name
            target = target_dir / name
            if source.exists():
                target.write_bytes(source.read_bytes())
        return target_dir

    def _copy_week1_validation_inputs(self, rollout_dir: Path) -> Dict[str, Path]:
        targets: Dict[str, Path] = {}
        inputs_dir = rollout_dir / "week1_inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        memory_dir = self.paths.work_jar_path.parent
        canonical_memory_dir = self.paths.output_dir.parent

        def _pick_existing(*candidates: Path) -> Path:
            for candidate in candidates:
                if candidate.exists():
                    return candidate
            return candidates[0]

        source_map = {
            "events": _pick_existing(memory_dir / "week1_executor_events.jsonl", canonical_memory_dir / "week1_executor_events.jsonl"),
            "monitor": _pick_existing(memory_dir / "week1_validation_monitor.json", canonical_memory_dir / "week1_validation_monitor.json"),
            "acks": _pick_existing(memory_dir / "push_user_ack.jsonl", canonical_memory_dir / "push_user_ack.jsonl"),
            "metrics": Path("ops/week1/WEEK1_VALIDATION_METRICS.md"),
            "checklist": Path("ops/week1/DAY1_OPERATOR_CHECKLIST.txt"),
        }
        for key, source in source_map.items():
            target = inputs_dir / source.name
            if source.exists():
                target.write_bytes(source.read_bytes())
                targets[key] = target
        return targets

    def _copy_week1_ops_inputs(self, rollout_dir: Path) -> Dict[str, Path]:
        targets: Dict[str, Path] = {}
        inputs_dir = rollout_dir / "week1_ops_inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        memory_dir = self.paths.work_jar_path.parent
        canonical_memory_dir = self.paths.output_dir.parent

        def _pick_existing(*candidates: Path) -> Path:
            for candidate in candidates:
                if candidate.exists():
                    return candidate
            return candidates[0]

        source_map = {
            "schedule": _pick_existing(memory_dir / "week1_task_schedule.json", canonical_memory_dir / "week1_task_schedule.json"),
            "ops_state": _pick_existing(memory_dir / "week1_ops_backlog_state.json", canonical_memory_dir / "week1_ops_backlog_state.json"),
            "executor_state": _pick_existing(memory_dir / "week1_executor_state.json", canonical_memory_dir / "week1_executor_state.json"),
            "events": _pick_existing(memory_dir / "week1_executor_events.jsonl", canonical_memory_dir / "week1_executor_events.jsonl"),
        }
        for key, source in source_map.items():
            target = inputs_dir / source.name
            if source.exists():
                target.write_bytes(source.read_bytes())
                targets[key] = target
        return targets

    def _copy_autonomy_queue_inputs(self, rollout_dir: Path) -> Dict[str, Path]:
        targets: Dict[str, Path] = {}
        inputs_dir = rollout_dir / "autonomy_queue_inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        memory_dir = self.paths.work_jar_path.parent
        canonical_memory_dir = self.paths.output_dir.parent

        def _pick_existing(*candidates: Path) -> Path:
            for candidate in candidates:
                if candidate.exists():
                    return candidate
            return candidates[0]

        source_map = {
            "work_jar": _pick_existing(canonical_memory_dir / "autonomy_work_jar.json", memory_dir / "autonomy_work_jar.json"),
            "state_sync": _pick_existing(canonical_memory_dir / "autonomy_state_sync_verifier.json", memory_dir / "autonomy_state_sync_verifier.json"),
        }
        for key, source in source_map.items():
            target = inputs_dir / source.name
            if source.exists():
                target.write_bytes(source.read_bytes())
                targets[key] = target
        return targets

    def _copy_autonomy_queue_repair_inputs(self, rollout_dir: Path) -> Dict[str, Path]:
        targets: Dict[str, Path] = {}
        inputs_dir = rollout_dir / "autonomy_queue_repair_inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        memory_dir = self.paths.work_jar_path.parent
        canonical_memory_dir = self.paths.output_dir.parent

        def _pick_existing(*candidates: Path) -> Path:
            for candidate in candidates:
                if candidate.exists():
                    return candidate
            return candidates[0]

        source_map = {
            "work_jar": _pick_existing(canonical_memory_dir / "autonomy_work_jar.json", memory_dir / "autonomy_work_jar.json"),
            "state_sync": _pick_existing(canonical_memory_dir / "autonomy_state_sync_verifier.json", memory_dir / "autonomy_state_sync_verifier.json"),
        }
        for key, source in source_map.items():
            target = inputs_dir / source.name
            if source.exists():
                target.write_bytes(source.read_bytes())
                targets[key] = target
        return targets

    def _archive_verified_complete_items_in_payload(self, queue_payload: Dict[str, Any], verifier_state: Dict[str, Any], *, limit: int = 50, policy: str = "verified_only") -> Dict[str, Any]:
        if not isinstance(queue_payload, dict):
            queue_payload = {}
        items = list(queue_payload.get("items") or [])
        archived_items = list(queue_payload.get("archived_items") or [])
        verified_tasks = dict(verifier_state.get("verified_tasks") or {}) if isinstance(verifier_state, dict) else {}
        kept: List[Dict[str, Any]] = []
        archived_ids: List[str] = []

        for row in items:
            if not isinstance(row, dict):
                continue
            if len(archived_ids) >= max(1, int(limit or 1)):
                kept.append(row)
                continue
            status = str(row.get("status") or "").strip().lower()
            task_id = str(((row.get("metadata") or {}).get("completed_by_task_id")) or row.get("completed_by_task_id") or "").strip()
            item_id = str(row.get("id") or "").strip()
            verified_row = dict(verified_tasks.get(task_id) or {})
            policy_value = str(policy or "verified_only").strip().lower()
            verifier_ok = bool(verified_row.get("last_ok"))
            should_archive = False
            if policy_value == "verified_or_completed":
                should_archive = status == "completed" and bool(item_id) and bool(task_id)
            else:
                should_archive = status == "completed" and bool(item_id) and bool(task_id) and verifier_ok
            if should_archive:
                archived_row = dict(row)
                metadata = dict(archived_row.get("metadata") or {})
                metadata["archived_at_utc"] = utc_iso()
                metadata["archive_reason"] = "verified_complete" if policy_value == "verified_only" else policy_value
                archived_row["metadata"] = metadata
                archived_row["updated_at_utc"] = utc_iso()
                archived_items.append(archived_row)
                archived_ids.append(item_id)
                continue
            kept.append(row)

        queue_payload["items"] = kept
        queue_payload["archived_items"] = archived_items
        queue_payload["updated_at_utc"] = utc_iso()
        return {
            "policy": str(policy or "verified_only").strip().lower(),
            "pending_before": len(items),
            "pending_after": len(kept),
            "archived_before": len(list(queue_payload.get("archived_items") or [])) - len(archived_ids),
            "archived_after": len(archived_items),
            "archived_item_ids": archived_ids,
        }

    def _load_jsonl_rows(self, path: Path, *, limit: int = 20) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not path.exists():
            return rows
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max(1, int(limit)):]:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
        except Exception:
            return []
        return rows

    def _tail_text_lines(self, path: Path, *, limit: int = 12) -> List[str]:
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            return lines[-max(1, int(limit)) :]
        except Exception:
            return []

    def _http_json(self, url: str, *, timeout: float = 10.0) -> Dict[str, Any]:
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status_code = int(getattr(response, "status", 200) or 200)
                raw = response.read().decode("utf-8", errors="ignore")
                payload = json.loads(raw) if raw else {}
                return {
                    "ok": status_code == 200,
                    "status_code": status_code,
                    "payload": payload if isinstance(payload, dict) else {"value": payload},
                }
        except Exception as exc:
            return {"ok": False, "status_code": 0, "error": str(exc), "payload": {}}

    def _iter_jsonl_payloads(self, path: Path) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not path.exists():
            return rows
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
        except Exception:
            return []
        return rows

    def _rebuild_flight_ledger_copy(self, recorder_dir: Path) -> Dict[str, Any]:
        transitions_path = recorder_dir / "transitions.ndjson"
        ledger_path = recorder_dir / "ledger.jsonl"
        if not transitions_path.exists():
            return {
                "ok": False,
                "reason": f"missing_transitions:{transitions_path}",
                "ledger_path": str(ledger_path),
                "records": 0,
            }
        rows: List[Dict[str, Any]] = []
        genesis = {
            "ledger_version": 1,
            "timestamp_utc": utc_iso(),
            "record_type": "GENESIS",
            "event_uuid": "",
            "source_file": "",
            "source_kind": "flight_recorder",
            "hash_prev": "0" * 64,
            "hash_self": "",
            "payload_sha256": "",
            "summary": "flight ledger genesis",
            "meta": {},
        }
        genesis["hash_self"] = _compute_ledger_hash_self(genesis)
        rows.append(genesis)
        last_hash = genesis["hash_self"]

        for payload in self._iter_jsonl_payloads(transitions_path):
            action = payload.get("action") or {}
            meta = payload.get("meta") or {}
            result = payload.get("result") or {}
            record_type = str(payload.get("type") or "transition")
            summary = record_type
            if isinstance(action, dict):
                action_type = str(action.get("type") or "")
                tool_name = str(action.get("tool_name") or "")
                model = str(action.get("model") or "")
                if tool_name:
                    summary = f"{record_type}:{action_type}:{tool_name}"
                elif model:
                    summary = f"{record_type}:{action_type}:{model}"
                elif action_type:
                    summary = f"{record_type}:{action_type}"
            if isinstance(result, dict) and "success" in result and summary == record_type:
                summary = f"{record_type}:success={bool(result.get('success'))}"
            compact_meta = {
                "action_type": str(action.get("type") or "") if isinstance(action, dict) else "",
                "tool_name": str(action.get("tool_name") or "") if isinstance(action, dict) else "",
                "model": str(action.get("model") or "") if isinstance(action, dict) else "",
                "success": bool(meta.get("success")) if "success" in meta else None,
                "air_score": payload.get("air_score"),
                "air_reason": str(payload.get("air_reason") or ""),
                "latency_ms": meta.get("latency_ms") if isinstance(meta, dict) else None,
            }
            compact_meta = {k: v for k, v in compact_meta.items() if v not in ("", None)}
            record = {
                "ledger_version": 1,
                "timestamp_utc": utc_iso(),
                "record_type": record_type,
                "event_uuid": str(payload.get("uuid") or ""),
                "source_file": str(transitions_path),
                "source_kind": "flight_recorder",
                "hash_prev": last_hash,
                "hash_self": "",
                "payload_sha256": _sha256_hex(_canonical_json(payload)),
                "summary": summary[:160],
                "meta": compact_meta,
            }
            record["hash_self"] = _compute_ledger_hash_self(record)
            rows.append(record)
            last_hash = record["hash_self"]

        with ledger_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(_canonical_json(row) + "\n")
        return {
            "ok": True,
            "reason": "rebuilt_from_transitions",
            "ledger_path": str(ledger_path),
            "records": len(rows),
            "rebuilt_at_utc": utc_iso(),
        }

    def _execute_improvement_archive_materialize(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        work_jar_copy = rollout_dir / "autonomy_work_jar.json"
        archive_path = rollout_dir / "improvement_archive.json"
        summary_path = rollout_dir / "execution_summary.md"
        source_jar = self.load_work_jar()
        atomic_json_write(work_jar_copy, source_jar, indent=2)
        materialize_result = materialize_improvement_archive(work_jar_path=work_jar_copy, archive_path=archive_path)
        archive_payload = safe_json_read(archive_path, default={}) or {}
        entry_count = len(list((archive_payload.get("entries") or []))) if isinstance(archive_payload, dict) else 0
        summary_text = "\n".join([
            f"# Rollout Deliverable: {str(envelope.get('title') or '').strip()}",
            "",
            "archive schema",
            "materializer",
            "seed entries",
            "",
            f"Rollout ID: {rollout_id}",
            f"Archive Path: {archive_path}",
            f"Entries: {entry_count}",
            f"Added: {int(materialize_result.get('added') or 0)}",
            f"Updated: {int(materialize_result.get('updated') or 0)}",
            f"Skipped: {int(materialize_result.get('skipped') or 0)}",
            "",
            "## Context",
            str(envelope.get("context") or "")[:3000],
        ]).strip() + "\n"
        summary_path.write_text(summary_text, encoding="utf-8")
        master = MasterTaskList(filepath=task_path)
        description = "\n".join([
            f"Generated archive: {archive_path.name}",
            f"Execution summary: {summary_path.name}",
            "Use the generated archive as the primary replay output.",
        ])
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "local_runtime_action"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; archive={archive_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; archive={archive_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join([
            str(getattr(completed, "title", "") or ""),
            str(getattr(completed, "description", "") or ""),
            str(getattr(completed, "notes", "") or ""),
            summary_text,
        ])
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "improvement_archive_materialize",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(archive_path),
            "execution_artifact_path": str(summary_path),
            "materialize_result": materialize_result,
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def _execute_improvement_archive_suggest(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        archive_path = self._copy_improvement_archive_for_rollout(rollout_dir)
        suggestions_path = rollout_dir / "archive_suggestions.json"
        summary_path = rollout_dir / "execution_summary.md"
        metadata = dict(item.get("metadata") or {})
        archive_query = dict(metadata.get("archive_query") or {})
        policy = str(metadata.get("rollout_policy") or "").strip().lower()
        problem_signature = str(archive_query.get("problem_signature") or "")
        failure_class = str(archive_query.get("failure_class") or "")
        if policy == "strict_signature":
            failure_class = ""
        elif policy == "relaxed_failure_class":
            problem_signature = ""
        result = build_archive_seed_payload(
            archive_path=archive_path,
            problem_signature=problem_signature,
            failure_class=failure_class,
            limit=int(archive_query.get("limit") or 3),
        )
        atomic_json_write(suggestions_path, result, indent=2)
        required_markers = list(((envelope.get("completion_contract") or {}).get("required_markers") or []))
        summary_lines = [
            f"# Rollout Deliverable: {str(envelope.get('title') or '').strip()}",
            "",
            f"Rollout ID: {rollout_id}",
            f"Archive Path: {archive_path}",
            f"Suggestions Path: {suggestions_path}",
            f"Policy: {policy or 'default'}",
            f"Match Count: {int(result.get('match_count') or 0)}",
            "",
            "## Required Markers",
        ]
        summary_lines.extend(required_markers or ["none"])
        context_block = str(result.get("context_block") or "").strip()
        if context_block:
            summary_lines.extend(["", "## Suggestion Context", context_block])
        summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
        master = MasterTaskList(filepath=task_path)
        description = "\n".join(
            [
                f"Suggestion output: {suggestions_path.name}",
                f"Execution summary: {summary_path.name}",
                "Use the generated suggestion payload as the primary replay output.",
            ]
        )
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "archive_suggestions"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; suggestions={suggestions_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; suggestions={suggestions_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join([
            str(getattr(completed, "title", "") or ""),
            str(getattr(completed, "description", "") or ""),
            str(getattr(completed, "notes", "") or ""),
            summary_path.read_text(encoding="utf-8"),
        ])
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "improvement_archive_suggest",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(suggestions_path),
            "execution_artifact_path": str(summary_path),
            "suggest_result": result,
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def _execute_improvement_archive_operator_surface(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        archive_path = self._copy_improvement_archive_for_rollout(rollout_dir)
        diagnostics_path = rollout_dir / "operator_diagnostics.json"
        summary_path = rollout_dir / "execution_summary.md"
        metadata = dict(item.get("metadata") or {})
        policy = str(metadata.get("rollout_policy") or "strict_active_only").strip().lower() or "strict_active_only"
        archive_payload = safe_json_read(archive_path, default={}) or {}
        entries = list((archive_payload.get("entries") or [])) if isinstance(archive_payload, dict) else []
        active_entries = [entry for entry in entries if str(entry.get("status") or "") == "active"]
        visible_entries = list(entries) if policy == "include_inactive" else active_entries
        by_failure_class: Dict[str, int] = {}
        for entry in visible_entries:
            key = str(entry.get("failure_class") or "unknown").strip() or "unknown"
            by_failure_class[key] = int(by_failure_class.get(key) or 0) + 1
        sample_suggestions = [
            {
                "archive_id": str(entry.get("archive_id") or ""),
                "title": str(entry.get("title") or ""),
                "failure_class": str(entry.get("failure_class") or ""),
                "problem_signature": str(entry.get("problem_signature") or ""),
                "rollout_guard": str(entry.get("rollout_guard") or ""),
            }
            for entry in visible_entries[:3]
        ]
        diagnostics = {
            "archive_path": str(archive_path),
            "policy": policy,
            "total_entries": len(entries),
            "active_entries": len(active_entries),
            "visible_entries": len(visible_entries),
            "failure_class_counts": by_failure_class,
            "sample_suggestions": sample_suggestions,
            "suggest_only": True,
        }
        atomic_json_write(diagnostics_path, diagnostics, indent=2)
        required_markers = list(((envelope.get("completion_contract") or {}).get("required_markers") or []))
        summary_lines = [
            f"# Rollout Deliverable: {str(envelope.get('title') or '').strip()}",
            "",
            f"Rollout ID: {rollout_id}",
            f"Archive Path: {archive_path}",
            f"Diagnostics Path: {diagnostics_path}",
            f"Policy: {policy}",
            f"Total Entries: {len(entries)}",
            f"Active Entries: {len(active_entries)}",
            f"Visible Entries: {len(visible_entries)}",
            "",
            "operator diagnostics",
            "archive suggestions",
            "suggest_only",
            "",
            "## Policy Notes",
            "- strict_active_only limits the surface to active reusable entries only." if policy == "strict_active_only" else "- include_inactive broadens the surface to every archived entry, including inactive rows.",
            "",
            "## Failure Classes",
        ]
        if by_failure_class:
            summary_lines.extend(f"- {key}: {value}" for key, value in sorted(by_failure_class.items()))
        else:
            summary_lines.append("- none")
        if sample_suggestions:
            summary_lines.extend(["", "## Sample Suggestions"])
            summary_lines.extend(
                f"- {row['title']} [{row['failure_class']}] ({row['problem_signature']})"
                for row in sample_suggestions
            )
        summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
        master = MasterTaskList(filepath=task_path)
        description = "\n".join(
            [
                f"Diagnostics output: {diagnostics_path.name}",
                f"Execution summary: {summary_path.name}",
                "Use the generated diagnostics payload as the primary replay output.",
            ]
        )
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "operator_diagnostics"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; diagnostics={diagnostics_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; diagnostics={diagnostics_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join([
            str(getattr(completed, "title", "") or ""),
            str(getattr(completed, "description", "") or ""),
            str(getattr(completed, "notes", "") or ""),
            summary_path.read_text(encoding="utf-8"),
        ])
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "improvement_archive_operator_surface",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(diagnostics_path),
            "execution_artifact_path": str(summary_path),
            "diagnostics": diagnostics,
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def _execute_flight_ledger_verify(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        copied_recorder_dir = self._copy_flight_recorder_for_rollout(rollout_dir)
        verify_path = rollout_dir / "ledger_verify.json"
        rebuild_path = rollout_dir / "ledger_rebuild.json"
        summary_path = rollout_dir / "execution_summary.md"
        metadata = dict(item.get("metadata") or {})
        policy = str(metadata.get("rollout_policy") or "rebuild_only_if_invalid").strip().lower() or "rebuild_only_if_invalid"
        initial_verify = verify_flight_ledger(copied_recorder_dir / "ledger.jsonl", cross_check_source=True)
        rebuild_result: Dict[str, Any] = {}
        should_rebuild = policy == "always_rebuild_copy" or not bool(initial_verify.get("ok"))
        if should_rebuild:
            rebuild_result = self._rebuild_flight_ledger_copy(copied_recorder_dir)
            atomic_json_write(rebuild_path, rebuild_result, indent=2)
        verify_result = verify_flight_ledger(copied_recorder_dir / "ledger.jsonl", cross_check_source=True)
        atomic_json_write(verify_path, verify_result, indent=2)
        summary_lines = [
            f"# Rollout Deliverable: {str(envelope.get('title') or '').strip()}",
            "",
            "lazy genesis",
            "verifier script",
            "focused tests",
            "",
            f"Rollout ID: {rollout_id}",
            f"Policy: {policy}",
            f"Initial Ledger OK: {str(bool(initial_verify.get('ok'))).lower()}",
            f"Rebuilt Copy: {str(bool(should_rebuild)).lower()}",
            f"Ledger Verify Path: {verify_path}",
            f"Ledger OK: {str(bool(verify_result.get('ok'))).lower()}",
            f"Records: {int(verify_result.get('records') or 0)}",
        ]
        if rebuild_result:
            summary_lines.append(f"Rebuild Path: {rebuild_path}")
        errors = list(verify_result.get("errors") or [])
        warnings = list(verify_result.get("warnings") or [])
        if errors:
            summary_lines.extend(["", "## Errors"])
            summary_lines.extend(f"- {value}" for value in errors[:10])
        if warnings:
            summary_lines.extend(["", "## Warnings"])
            summary_lines.extend(f"- {value}" for value in warnings[:10])
        summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
        master = MasterTaskList(filepath=task_path)
        description = "\n".join(
            [
                f"Verification output: {verify_path.name}",
                f"Execution summary: {summary_path.name}",
                "Use the generated ledger verification payload as the primary replay output.",
            ]
        )
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "flight_ledger"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; verify={verify_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; verify={verify_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join([
            str(getattr(completed, "title", "") or ""),
            str(getattr(completed, "description", "") or ""),
            str(getattr(completed, "notes", "") or ""),
            summary_path.read_text(encoding="utf-8"),
        ])
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "flight_ledger_verify",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(verify_path),
            "execution_artifact_path": str(summary_path),
            "initial_verify_result": initial_verify,
            "rebuild_result": rebuild_result,
            "verify_result": verify_result,
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def _execute_week1_validation_snapshot(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        snapshot_path = rollout_dir / "week1_validation_snapshot.md"
        summary_path = rollout_dir / "execution_summary.md"
        copied = self._copy_week1_validation_inputs(rollout_dir)
        metadata = dict(item.get("metadata") or {})
        policy = str(metadata.get("rollout_policy") or "strict_ack_required").strip().lower() or "strict_ack_required"
        event_rows = self._load_jsonl_rows(copied.get("events", Path("_missing_")), limit=20) if copied.get("events") else []
        ack_rows = self._load_jsonl_rows(copied.get("acks", Path("_missing_")), limit=20) if copied.get("acks") else []
        monitor = safe_json_read(copied.get("monitor", Path("_missing_")), default={}) or {}
        status_counts: Dict[str, int] = {}
        channel_counts: Dict[str, int] = {}
        event_ids: List[str] = []
        for row in event_rows:
            status = str(row.get("status") or "unknown").strip() or "unknown"
            channel = str(row.get("delivery_channel") or "unknown").strip() or "unknown"
            event_id = str(row.get("event_id") or "").strip()
            status_counts[status] = int(status_counts.get(status) or 0) + 1
            channel_counts[channel] = int(channel_counts.get(channel) or 0) + 1
            if event_id and event_id not in event_ids:
                event_ids.append(event_id)
        latest_event = str(event_rows[-1].get("ts_utc") or "") if event_rows else ""
        latest_ack = str(ack_rows[-1].get("ts_utc") or ack_rows[-1].get("created_at_utc") or "") if ack_rows else ""
        metrics_excerpt = ""
        checklist_excerpt = ""
        if copied.get("metrics"):
            metrics_excerpt = copied["metrics"].read_text(encoding="utf-8", errors="ignore")[:1800].strip()
        if copied.get("checklist"):
            checklist_excerpt = copied["checklist"].read_text(encoding="utf-8", errors="ignore")[:1800].strip()
        ok_count = int(status_counts.get("ok") or 0)
        deferred_count = int(status_counts.get("deferred") or 0)
        failed_count = int(status_counts.get("failed") or 0)
        weak_spots: List[str] = []
        if policy == "strict_ack_required" and not ack_rows:
            weak_spots.append("No ACK rows are available, so acknowledgement/followthrough metrics remain unmeasurable.")
        if not checklist_excerpt:
            weak_spots.append("Operator checklist excerpt is unavailable, so no checklist completion evidence can be confirmed.")
        if not metrics_excerpt:
            weak_spots.append("Validation metrics reference is unavailable, so metric targets cannot be cross-checked.")
        if failed_count == 0 and deferred_count == 0 and policy == "strict_ack_required":
            weak_spots.append("Delivery reliability looks good, but user-response quality is still under-observed relative to delivery volume.")
        noise_risks: List[str] = []
        if ok_count and not ack_rows and policy == "strict_ack_required":
            noise_risks.append("High delivery success with zero ACK evidence risks overestimating Week1 effectiveness.")
        if "call" in channel_counts and "send_gmail_message" in channel_counts and not ack_rows and policy == "strict_ack_required":
            noise_risks.append("Multi-channel delivery is working, but there is still no confirmation that the human-facing interventions changed behavior.")
        if policy == "delivery_signal_only":
            weak_spots.append("This replay policy treats delivery evidence as primary and does not require acknowledgement capture to score signal quality.")
            recommendations = [
                "Keep validating channel mix and executor status counts so delivery signal remains mechanically trustworthy.",
                "Record checklist completion beside the shipped Day 1 checklist so operational gaps are distinguishable from missing telemetry.",
                "Use ACK capture as a secondary metric, not a hard prerequisite, when delivery signal is already stable.",
            ]
        else:
            recommendations = [
                "Add a lightweight ACK capture path so Week1 validation can measure acknowledgement and followthrough instead of only delivery success.",
                "Record checklist completion or operator checkmarks beside the shipped Day 1 checklist so validation snapshots can distinguish missing telemetry from incomplete operations.",
                "Keep the validation monitor active, but rate-limit resurfacing until either new executor activity or new ACK evidence appears.",
            ]
        snapshot_lines = [
            f"# Week1 Validation Snapshot ({utc_iso()})",
            "",
            "## Signal Summary",
            f"- Recent executor events: {len(event_rows)}",
            f"- Status counts: {json.dumps(status_counts, ensure_ascii=True, sort_keys=True)}",
            f"- Latest event UTC: {latest_event}",
            f"- Delivery channels: {json.dumps(channel_counts, ensure_ascii=True, sort_keys=True)}",
            f"- Event IDs observed: {', '.join(event_ids[:10])}",
            f"- Recent ACK rows: {len(ack_rows)}",
            f"- Latest ACK UTC: {latest_ack}",
            f"- Policy: {policy}",
            f"- Last snapshot UTC: {str(monitor.get('last_snapshot_utc') or '')}",
            f"- Validation reason: {str(((monitor.get('candidate') or {}).get('reason')) or monitor.get('last_snapshot_reason') or '')}",
            "",
            "## Likely Weak Spots",
        ]
        snapshot_lines.extend(f"- {line}" for line in weak_spots or ["No immediate weak spots identified from the bounded local evidence."])
        snapshot_lines.extend(["", "## Noise/Risk Notes"])
        snapshot_lines.extend(f"- {line}" for line in noise_risks or ["No additional noise spikes were visible in the bounded local evidence."])
        snapshot_lines.extend(["", "## Top 3 Week2 Tuning Recommendations"])
        snapshot_lines.extend(f"- {line}" for line in recommendations)
        if metrics_excerpt:
            snapshot_lines.extend(["", "## Validation Metrics Excerpt", metrics_excerpt])
        if checklist_excerpt:
            snapshot_lines.extend(["", "## Day 1 Checklist Excerpt", checklist_excerpt])
        snapshot_text = "\n".join(snapshot_lines).strip() + "\n"
        snapshot_path.write_text(snapshot_text, encoding="utf-8")
        summary_path.write_text(
            "\n".join(
                [
                    f"rollout_id={rollout_id}",
                    f"snapshot={snapshot_path.name}",
                    f"events={len(event_rows)}",
                    f"acks={len(ack_rows)}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        master = MasterTaskList(filepath=task_path)
        description = "\n".join(
            [
                f"Validation snapshot: {snapshot_path.name}",
                f"Execution summary: {summary_path.name}",
                "Use the generated Week1 validation snapshot as the primary replay output.",
            ]
        )
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "week1_validation"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; snapshot={snapshot_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; snapshot={snapshot_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join(
            [
                str(getattr(completed, "title", "") or ""),
                str(getattr(completed, "description", "") or ""),
                str(getattr(completed, "notes", "") or ""),
                snapshot_text,
            ]
        )
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "week1_validation_snapshot",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(snapshot_path),
            "execution_artifact_path": str(summary_path),
            "validation_counts": {
                "policy": policy,
                "events": len(event_rows),
                "acks": len(ack_rows),
                "status_counts": status_counts,
                "channel_counts": channel_counts,
            },
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def _execute_operator_runtime_snapshot(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        snapshot_path = rollout_dir / "operator_runtime_snapshot.json"
        summary_path = rollout_dir / "execution_summary.md"
        metadata = dict(item.get("metadata") or {})
        policy = str(metadata.get("rollout_policy") or "strict_operator_health").strip().lower() or "strict_operator_health"
        base_url = str(metadata.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        health = self._http_json(f"{base_url}/api/health")
        readiness = self._http_json(f"{base_url}/api/readiness")
        slo = self._http_json(f"{base_url}/api/autonomy/slo")
        tools_status = self._http_json(f"{base_url}/api/tools/status")
        snapshot = {
            "captured_at_utc": utc_iso(),
            "base_url": base_url,
            "health": health,
            "readiness": readiness,
            "autonomy_slo": slo,
            "tools_status": tools_status,
        }
        atomic_json_write(snapshot_path, snapshot, indent=2)
        readiness_payload = dict(readiness.get("payload") or {})
        slo_payload = dict(slo.get("payload") or {})
        operator_baseline = dict(slo_payload.get("operator_baseline") or {})
        tools_payload = dict(tools_status.get("payload") or {})
        summary_lines = [
            f"# Rollout Deliverable: {str(envelope.get('title') or '').strip()}",
            "",
            "health",
            "readiness",
            "operator baseline",
            "tool diagnostics",
            "",
            f"Rollout ID: {rollout_id}",
            f"Policy: {policy}",
            f"Base URL: {base_url}",
            f"Health OK: {str(bool((health.get('payload') or {}).get('ok'))).lower()}",
            f"Readiness Ready: {str(bool(readiness_payload.get('ready'))).lower()}",
            f"Readiness Phase: {str(readiness_payload.get('phase') or '')}",
            f"Operator Baseline Delivered Runs: {str(operator_baseline.get('delivered_runs') or '')}",
            f"Operator Baseline Failed Runs: {str(operator_baseline.get('failed_runs') or '')}",
            f"Operator Baseline Deferred Runs: {str(operator_baseline.get('deferred_runs') or '')}",
            f"Tool Diagnostics Keys: {', '.join(sorted(list(tools_payload.keys()))[:8])}",
        ]
        warnings = list(readiness_payload.get("warnings") or [])
        degraded_tools = list((tools_payload.get("warnings") or [])) if isinstance(tools_payload, dict) else []
        if policy == "strict_operator_health":
            summary_lines.extend([
                "",
                "## Policy Notes",
                "- favor green health/readiness and minimal warnings",
                f"- readiness warning count: {len(warnings)}",
                f"- tool warning count: {len(degraded_tools)}",
            ])
        elif policy == "baseline_favoring_health":
            summary_lines.extend([
                "",
                "## Policy Notes",
                "- allow clean operator baseline to outweigh minor warnings",
                f"- delivered runs: {str(operator_baseline.get('delivered_runs') or 0)}",
                f"- failed runs: {str(operator_baseline.get('failed_runs') or 0)}",
                f"- deferred runs: {str(operator_baseline.get('deferred_runs') or 0)}",
            ])
        if warnings:
            summary_lines.extend(["", "## Readiness Warnings"])
            summary_lines.extend(f"- {warning}" for warning in warnings[:10])
        if degraded_tools:
            summary_lines.extend(["", "## Tool Warnings"])
            summary_lines.extend(f"- {warning}" for warning in degraded_tools[:10])
        summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
        master = MasterTaskList(filepath=task_path)
        description = "\n".join(
            [
                f"Operator snapshot: {snapshot_path.name}",
                f"Execution summary: {summary_path.name}",
                "Use the generated operator/runtime snapshot as the primary replay output.",
            ]
        )
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "operator_runtime"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; snapshot={snapshot_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; snapshot={snapshot_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join(
            [
                str(getattr(completed, "title", "") or ""),
                str(getattr(completed, "description", "") or ""),
                str(getattr(completed, "notes", "") or ""),
                summary_path.read_text(encoding="utf-8"),
            ]
        )
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "operator_runtime_snapshot",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(snapshot_path),
            "execution_artifact_path": str(summary_path),
            "snapshot": snapshot,
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def _execute_state_sync_surface_snapshot(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        snapshot_path = rollout_dir / "state_sync_surface_snapshot.json"
        summary_path = rollout_dir / "execution_summary.md"
        metadata = dict(item.get("metadata") or {})
        policy = str(metadata.get("rollout_policy") or "strict_note_required").strip().lower() or "strict_note_required"
        memory_dir = self.paths.output_dir.parent
        verifier_path = memory_dir / "autonomy_state_sync_verifier.json"
        verifier_events_path = memory_dir / "autonomy_state_sync_verifier_events.jsonl"
        master_path = memory_dir / "MASTER_TODO.md"
        cadence_path = memory_dir / "autonomy_cadence_events.jsonl"
        verifier_state = safe_json_read(verifier_path, default={}) or {}
        verified_tasks = dict(verifier_state.get("verified_tasks") or {})
        task_id = str(metadata.get("task_id") or "").strip()
        if not task_id and verified_tasks:
            task_id = sorted(verified_tasks.keys())[-1]
        task_marker = f"[STATE-SYNC-VERIFIED:{task_id}]" if task_id else ""
        master_text = master_path.read_text(encoding="utf-8", errors="ignore") if master_path.exists() else ""
        task_excerpt_lines: List[str] = []
        if master_text:
            for line in master_text.splitlines():
                if task_id and task_id in line:
                    task_excerpt_lines.append(line)
                elif task_marker and task_marker in line:
                    task_excerpt_lines.append(line)
            if not task_excerpt_lines and task_marker:
                idx = master_text.find(task_marker)
                if idx >= 0:
                    task_excerpt_lines.append(master_text[idx : idx + 600])
        verified_row = dict(verified_tasks.get(task_id) or {}) if task_id else {}
        verifier_ok = bool(verified_row.get("last_ok"))
        task_surface_note_present = bool(task_marker and task_marker in master_text)
        if policy == "verifier_state_only":
            repair_needed = not (verifier_ok or task_surface_note_present)
            state_sync_ok = bool(verifier_ok or task_surface_note_present)
            decision = "verifier_state_accepted" if state_sync_ok else "needs_repair"
        else:
            repair_needed = not task_surface_note_present
            state_sync_ok = bool(task_surface_note_present and (verifier_ok or not task_id or task_id in verified_tasks))
            decision = "note_and_verifier_aligned" if state_sync_ok else "needs_repair"
        snapshot = {
            "captured_at_utc": utc_iso(),
            "policy": policy,
            "task_id": task_id,
            "task_surface_note_present": task_surface_note_present,
            "verified_tasks_count": len(verified_tasks),
            "verifier_ok": verifier_ok,
            "state_sync_ok": state_sync_ok,
            "repair_needed": repair_needed,
            "decision": decision,
            "verifier_state": verifier_state,
            "task_excerpt": "\n".join(task_excerpt_lines)[:4000],
            "verifier_event_tail": self._tail_text_lines(verifier_events_path, limit=12),
            "cadence_tail": self._tail_text_lines(cadence_path, limit=6),
        }
        atomic_json_write(snapshot_path, snapshot, indent=2)
        summary_lines = [
            f"# Rollout Deliverable: {str(envelope.get('title') or '').strip()}",
            "",
            "verification hook",
            "repair write",
            "follow-up replay",
            "",
            f"Rollout ID: {rollout_id}",
            f"Policy: {policy}",
            f"Task ID: {task_id}",
            f"Task Surface Note Present: {str(bool(snapshot.get('task_surface_note_present'))).lower()}",
            f"Verified Tasks Count: {int(snapshot.get('verified_tasks_count') or 0)}",
            f"Verifier OK: {str(bool(snapshot.get('verifier_ok'))).lower()}",
            f"Repair Decision: {decision}",
        ]
        if snapshot.get("task_excerpt"):
            summary_lines.extend(["", "## Task Surface Excerpt", str(snapshot.get("task_excerpt") or "")[:2000]])
        summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")
        master = MasterTaskList(filepath=task_path)
        description = "\n".join(
            [
                f"State-sync snapshot: {snapshot_path.name}",
                f"Execution summary: {summary_path.name}",
                "Use the generated task/memory state-sync snapshot as the primary replay output.",
            ]
        )
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "state_sync_surface"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; snapshot={snapshot_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; snapshot={snapshot_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join(
            [
                str(getattr(completed, "title", "") or ""),
                str(getattr(completed, "description", "") or ""),
                str(getattr(completed, "notes", "") or ""),
                summary_path.read_text(encoding="utf-8"),
            ]
        )
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "state_sync_surface_snapshot",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(snapshot_path),
            "execution_artifact_path": str(summary_path),
            "snapshot": snapshot,
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def _execute_week1_ops_surface_snapshot(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        snapshot_path = rollout_dir / "week1_ops_surface_snapshot.json"
        summary_path = rollout_dir / "execution_summary.md"
        copied = self._copy_week1_ops_inputs(rollout_dir)
        metadata = dict(item.get("metadata") or {})
        policy = str(metadata.get("rollout_policy") or "strict_hold_aware").strip().lower() or "strict_hold_aware"

        schedule = safe_json_read(copied.get("schedule", Path("_missing_")), default={}) or {}
        ops_state = safe_json_read(copied.get("ops_state", Path("_missing_")), default={}) or {}
        executor_state = safe_json_read(copied.get("executor_state", Path("_missing_")), default={}) or {}
        event_rows = self._load_jsonl_rows(copied.get("events", Path("_missing_")), limit=20) if copied.get("events") else []

        schedule_items = list(schedule.get("items") or []) if isinstance(schedule, dict) else []
        ops_items = dict(ops_state.get("items") or {}) if isinstance(ops_state, dict) else {}
        completed_events = dict(executor_state.get("completed_events") or {}) if isinstance(executor_state, dict) else {}

        held_items: List[Dict[str, Any]] = []
        eligible_items: List[Dict[str, Any]] = []
        for row in schedule_items:
            if not isinstance(row, dict):
                continue
            title = str(row.get("parent_title") or row.get("task") or "").strip()
            if not title:
                continue
            state_row = dict(ops_items.get(title) or {})
            entry = {
                "title": title,
                "scheduled_local": str(row.get("scheduled_local") or ""),
                "focus_slot": str(row.get("focus_slot") or ""),
                "start_step": str(row.get("start_step") or ""),
                "priority": str(row.get("priority") or ""),
                "category_key": str(row.get("category_key") or ""),
                "awaiting_human_followthrough": bool(state_row.get("awaiting_human_followthrough")),
                "resume_after_utc": str(state_row.get("resume_after_utc") or state_row.get("next_eligible_utc") or ""),
                "last_task_id": str(state_row.get("last_task_id") or ""),
                "last_status": str(state_row.get("last_status") or ""),
            }
            if entry["awaiting_human_followthrough"]:
                held_items.append(entry)
            else:
                eligible_items.append(entry)

        recent_channels: Dict[str, int] = {}
        recent_event_ids: List[str] = []
        for row in event_rows:
            channel = str(row.get("delivery_channel") or "unknown").strip() or "unknown"
            recent_channels[channel] = int(recent_channels.get(channel) or 0) + 1
            event_id = str(row.get("event_id") or "").strip()
            if event_id and event_id not in recent_event_ids:
                recent_event_ids.append(event_id)

        if policy == "raw_schedule":
            next_focus = []
            for row in schedule_items[:3]:
                if not isinstance(row, dict):
                    continue
                next_focus.append(
                    {
                        "title": str(row.get("parent_title") or row.get("task") or "").strip(),
                        "scheduled_local": str(row.get("scheduled_local") or ""),
                        "focus_slot": str(row.get("focus_slot") or ""),
                        "start_step": str(row.get("start_step") or ""),
                        "priority": str(row.get("priority") or ""),
                        "category_key": str(row.get("category_key") or ""),
                    }
                )
        else:
            next_focus = eligible_items[:3]
        snapshot = {
            "captured_at_utc": utc_iso(),
            "policy": policy,
            "schedule_source_mode": str(schedule.get("source_mode") or "") if isinstance(schedule, dict) else "",
            "schedule_source_ref": str(schedule.get("source_ref") or "") if isinstance(schedule, dict) else "",
            "schedule_item_count": len(schedule_items),
            "ops_state_item_count": len(ops_items),
            "held_item_count": len(held_items),
            "eligible_item_count": len(eligible_items),
            "next_focus_items": next_focus,
            "held_items": held_items[:5],
            "recent_event_count": len(event_rows),
            "recent_channels": recent_channels,
            "recent_event_ids": recent_event_ids[:10],
            "last_run_utc": str(executor_state.get("last_run_utc") or "") if isinstance(executor_state, dict) else "",
            "completed_event_count": len(completed_events),
        }
        atomic_json_write(snapshot_path, snapshot, indent=2)

        summary_lines = [
            f"# Rollout Deliverable: {str(envelope.get('title') or '').strip()}",
            "",
            "focus lane",
            "human followthrough holds",
            "next focus slots",
            "",
            f"Rollout ID: {rollout_id}",
            f"Policy: {policy}",
            f"Schedule Source Mode: {snapshot['schedule_source_mode']}",
            f"Schedule Item Count: {snapshot['schedule_item_count']}",
            f"Held Item Count: {snapshot['held_item_count']}",
            f"Eligible Item Count: {snapshot['eligible_item_count']}",
            f"Recent Event Count: {snapshot['recent_event_count']}",
            f"Last Run UTC: {snapshot['last_run_utc']}",
            "",
            "## Next Focus Slots",
        ]
        if next_focus:
            summary_lines.extend(
                f"- {row['title']} @ {row['scheduled_local']} ({row['focus_slot']})"
                for row in next_focus
            )
        else:
            summary_lines.append("- none")
        summary_lines.extend(["", "## Human Followthrough Holds"])
        if held_items:
            summary_lines.extend(
                f"- {row['title']} until {row['resume_after_utc']} via {row['last_task_id'] or 'no_task_id'}"
                for row in held_items[:5]
            )
        else:
            summary_lines.append("- none")
        summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")

        master = MasterTaskList(filepath=task_path)
        description = "\n".join(
            [
                f"Week1 ops surface snapshot: {snapshot_path.name}",
                f"Execution summary: {summary_path.name}",
                "Use the generated Week1 ops surface snapshot as the primary replay output.",
            ]
        )
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "week1_ops_surface"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; snapshot={snapshot_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; snapshot={snapshot_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join(
            [
                str(getattr(completed, "title", "") or ""),
                str(getattr(completed, "description", "") or ""),
                str(getattr(completed, "notes", "") or ""),
                summary_path.read_text(encoding="utf-8"),
            ]
        )
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "week1_ops_surface_snapshot",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(snapshot_path),
            "execution_artifact_path": str(summary_path),
            "snapshot": snapshot,
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def _execute_autonomy_queue_surface_snapshot(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        snapshot_path = rollout_dir / "autonomy_queue_surface_snapshot.json"
        summary_path = rollout_dir / "execution_summary.md"
        copied = self._copy_autonomy_queue_inputs(rollout_dir)

        queue_payload = safe_json_read(copied.get("work_jar", Path("_missing_")), default={}) or {}
        verifier_state = safe_json_read(copied.get("state_sync", Path("_missing_")), default={}) or {}
        pending_items = list(queue_payload.get("items") or []) if isinstance(queue_payload, dict) else []
        archived_items = list(queue_payload.get("archived_items") or []) if isinstance(queue_payload, dict) else []
        verified_tasks = dict(verifier_state.get("verified_tasks") or {}) if isinstance(verifier_state, dict) else {}

        pending_summary = [
            {
                "id": str(row.get("id") or ""),
                "title": str(row.get("title") or ""),
                "status": str(row.get("status") or ""),
                "tool_choice": str(row.get("tool_choice") or ""),
            }
            for row in pending_items[:5]
            if isinstance(row, dict)
        ]
        archived_summary = [
            {
                "id": str(row.get("id") or ""),
                "title": str(row.get("title") or ""),
                "status": str(row.get("status") or ""),
                "completed_by_task_id": str(((row.get("metadata") or {}).get("completed_by_task_id")) or row.get("completed_by_task_id") or ""),
            }
            for row in archived_items[:5]
            if isinstance(row, dict)
        ]
        snapshot = {
            "captured_at_utc": utc_iso(),
            "pending_count": len(pending_items),
            "archived_count": len(archived_items),
            "pending_summary": pending_summary,
            "archived_summary": archived_summary,
            "verified_task_count": len(verified_tasks),
            "oldest_pending_id": pending_summary[0]["id"] if pending_summary else "",
            "latest_archived_id": archived_summary[-1]["id"] if archived_summary else "",
        }
        atomic_json_write(snapshot_path, snapshot, indent=2)

        summary_lines = [
            f"# Rollout Deliverable: {str(envelope.get('title') or '').strip()}",
            "",
            "pending items",
            "archived items",
            "queue health",
            "",
            f"Rollout ID: {rollout_id}",
            f"Pending Count: {snapshot['pending_count']}",
            f"Archived Count: {snapshot['archived_count']}",
            f"Verified Task Count: {snapshot['verified_task_count']}",
            f"Oldest Pending ID: {snapshot['oldest_pending_id']}",
            f"Latest Archived ID: {snapshot['latest_archived_id']}",
            "",
            "## Pending Items",
        ]
        if pending_summary:
            summary_lines.extend(
                f"- {row['id']} [{row['status']}] {row['title']} ({row['tool_choice']})"
                for row in pending_summary
            )
        else:
            summary_lines.append("- none")
        summary_lines.extend(["", "## Archived Items"])
        if archived_summary:
            summary_lines.extend(
                f"- {row['id']} [{row['status']}] {row['title']} via {row['completed_by_task_id'] or 'no_task_id'}"
                for row in archived_summary
            )
        else:
            summary_lines.append("- none")
        summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")

        master = MasterTaskList(filepath=task_path)
        description = "\n".join(
            [
                f"Autonomy queue surface snapshot: {snapshot_path.name}",
                f"Execution summary: {summary_path.name}",
                "Use the generated autonomy queue surface snapshot as the primary replay output.",
            ]
        )
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "autonomy_queue_surface"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; snapshot={snapshot_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; snapshot={snapshot_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join(
            [
                str(getattr(completed, "title", "") or ""),
                str(getattr(completed, "description", "") or ""),
                str(getattr(completed, "notes", "") or ""),
                summary_path.read_text(encoding="utf-8"),
            ]
        )
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "autonomy_queue_surface_snapshot",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(snapshot_path),
            "execution_artifact_path": str(summary_path),
            "snapshot": snapshot,
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def _execute_autonomy_queue_repair(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        repaired_path = rollout_dir / "autonomy_work_jar_repaired.json"
        summary_path = rollout_dir / "execution_summary.md"
        copied = self._copy_autonomy_queue_repair_inputs(rollout_dir)
        metadata = dict(item.get("metadata") or {})
        policy = str(metadata.get("rollout_policy") or "verified_only").strip().lower() or "verified_only"

        queue_payload = safe_json_read(copied.get("work_jar", Path("_missing_")), default={}) or {}
        verifier_state = safe_json_read(copied.get("state_sync", Path("_missing_")), default={}) or {}
        repair_result = self._archive_verified_complete_items_in_payload(queue_payload, verifier_state, limit=50, policy=policy)
        atomic_json_write(repaired_path, queue_payload, indent=2)

        summary_lines = [
            f"# Rollout Deliverable: {str(envelope.get('title') or '').strip()}",
            "",
            "verified complete",
            "archived items",
            "queue repair",
            "",
            f"Rollout ID: {rollout_id}",
            f"Policy: {policy}",
            f"Pending Before: {repair_result['pending_before']}",
            f"Pending After: {repair_result['pending_after']}",
            f"Archived Before: {repair_result['archived_before']}",
            f"Archived After: {repair_result['archived_after']}",
            f"Archived IDs: {', '.join(repair_result['archived_item_ids'])}",
        ]
        summary_path.write_text("\n".join(summary_lines).strip() + "\n", encoding="utf-8")

        master = MasterTaskList(filepath=task_path)
        description = "\n".join(
            [
                f"Repaired queue snapshot: {repaired_path.name}",
                f"Execution summary: {summary_path.name}",
                "Use the generated repaired autonomy queue as the primary replay output.",
            ]
        )
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "autonomy_queue_repair"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; repaired={repaired_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; repaired={repaired_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join(
            [
                str(getattr(completed, "title", "") or ""),
                str(getattr(completed, "description", "") or ""),
                str(getattr(completed, "notes", "") or ""),
                summary_path.read_text(encoding="utf-8"),
            ]
        )
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "autonomy_queue_repair",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(repaired_path),
            "execution_artifact_path": str(summary_path),
            "repair_result": repair_result,
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def _execute_toolless_work_item(self, item: Dict[str, Any], envelope: Dict[str, Any], artifact_path: Optional[Path], artifact_score: Dict[str, Any]) -> Dict[str, Any]:
        executor_kind = self._select_local_executor_kind(item)
        if executor_kind == "state_sync_surface_snapshot":
            return self._execute_state_sync_surface_snapshot(item, envelope, artifact_path, artifact_score)
        if executor_kind == "autonomy_queue_repair":
            return self._execute_autonomy_queue_repair(item, envelope, artifact_path, artifact_score)
        if executor_kind == "autonomy_queue_surface_snapshot":
            return self._execute_autonomy_queue_surface_snapshot(item, envelope, artifact_path, artifact_score)
        if executor_kind == "week1_ops_surface_snapshot":
            return self._execute_week1_ops_surface_snapshot(item, envelope, artifact_path, artifact_score)
        if executor_kind == "operator_runtime_snapshot":
            return self._execute_operator_runtime_snapshot(item, envelope, artifact_path, artifact_score)
        if executor_kind == "week1_validation_snapshot":
            return self._execute_week1_validation_snapshot(item, envelope, artifact_path, artifact_score)
        if executor_kind == "flight_ledger_verify":
            return self._execute_flight_ledger_verify(item, envelope, artifact_path, artifact_score)
        if executor_kind == "improvement_archive_operator_surface":
            return self._execute_improvement_archive_operator_surface(item, envelope, artifact_path, artifact_score)
        if executor_kind == "improvement_archive_materialize":
            return self._execute_improvement_archive_materialize(item, envelope, artifact_path, artifact_score)
        if executor_kind == "improvement_archive_suggest":
            return self._execute_improvement_archive_suggest(item, envelope, artifact_path, artifact_score)
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        rollout_dir = self._rollout_dir(rollout_id)
        rollout_dir.mkdir(parents=True, exist_ok=True)
        task_path = rollout_dir / "MASTER_TODO.md"
        deliverable_path = rollout_dir / "deliverable.md"
        summary_path = rollout_dir / "execution_summary.md"
        master = MasterTaskList(filepath=task_path)
        deliverable_text = self._build_executor_artifact_text(envelope, artifact_path, artifact_score)
        deliverable_path.write_text(deliverable_text, encoding="utf-8")
        summary_path.write_text(
            "\n".join([
                f"rollout_id={rollout_id}",
                f"deliverable={deliverable_path.name}",
                f"source_artifact={str(artifact_path) if artifact_path else ''}",
            ]) + "\n",
            encoding="utf-8",
        )
        description = "\n".join([
            f"Deliverable file: {deliverable_path.name}",
            f"Execution summary: {summary_path.name}",
            "Use the deliverable file as the primary replay output.",
        ])
        task = master.add_task(
            title=str(envelope.get("title") or "Replay work item").strip() or "Replay work item",
            priority=TaskPriority.MEDIUM,
            description=description,
            tags=["rollout", "work_jar_replay", "local_action"],
            notes=f"rollout_id={rollout_id}",
        )
        master.update_status(task.id, TaskStatus.IN_PROGRESS, notes=f"rollout_id={rollout_id}; status=in_progress")
        master.update_task(task.id, notes=f"rollout_id={rollout_id}; deliverable={deliverable_path.name}; summary={summary_path.name}")
        master.update_status(task.id, TaskStatus.COMPLETED, notes=f"rollout_id={rollout_id}; deliverable={deliverable_path.name}; summary={summary_path.name}; status=completed")
        completed = master.get_by_id(task.id)
        task_text = "\n".join(
            [
                str(getattr(completed, "title", "") or ""),
                str(getattr(completed, "description", "") or ""),
                str(getattr(completed, "notes", "") or ""),
                deliverable_text,
            ]
        )
        evaluation = self._score_task_contract(
            envelope,
            task_text=task_text,
            task_status=str(getattr(completed, "status", TaskStatus.PENDING).value),
            task_id=task.id,
        )
        return {
            "executor_kind": "isolated_toolless_task",
            "task_id": task.id,
            "task_path": str(task_path),
            "deliverable_path": str(deliverable_path),
            "execution_artifact_path": str(summary_path),
            "completion_evaluation": evaluation,
            "ok": bool(evaluation.get("satisfied")),
            "reason": str(evaluation.get("reason") or "executor_completed"),
        }

    def run_work_item_rollout(
        self,
        *,
        item_id: str,
        include_archived: bool = False,
        artifact_override: Optional[Path] = None,
        mode: str = "auto",
        policy_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        item = self.find_work_item(item_id, include_archived=include_archived)
        normalized_mode = str(mode or "auto").strip().lower()
        tool_choice_hint = str(item.get("tool_choice") or "auto").strip().lower()
        executor_kind_hint = self._select_local_executor_kind(item) if tool_choice_hint == "none" else ""
        promoted_entry = self._get_promoted_policy_entry(executor_kind=executor_kind_hint)
        effective_mode = normalized_mode
        mode_source = "explicit"
        if normalized_mode == "registry":
            effective_mode = str(promoted_entry.get("preferred_mode") or "auto").strip().lower() or "auto"
            mode_source = "registry" if str(promoted_entry.get("preferred_mode") or "").strip() else "default"
        effective_policy = str(policy_override or "").strip().lower()
        policy_source = "explicit" if effective_policy else "none"
        if not effective_policy:
            effective_policy = str(promoted_entry.get("preferred_policy") or "").strip().lower()
            if effective_policy:
                policy_source = "registry"
        resolution = self.resolve_best_artifact(item, artifact_override)
        artifact_path = resolution.get("artifact_path")
        envelope = self.build_work_item_envelope(
            item=item,
            artifact_path=artifact_path if isinstance(artifact_path, Path) else None,
            policy_override=effective_policy or None,
        )
        rollout_id = str(envelope.get("rollout_id") or f"rollout_{uuid.uuid4().hex[:16]}")
        envelope["rollout_id"] = rollout_id
        metadata = dict(envelope.get("metadata") or {})
        metadata["rollout_effective_mode"] = effective_mode
        metadata["rollout_mode_source"] = mode_source
        metadata["rollout_policy_source"] = policy_source
        if effective_policy:
            metadata["rollout_policy"] = effective_policy
        if promoted_entry:
            metadata["rollout_registry_entry"] = {
                "executor_kind": str(promoted_entry.get("executor_kind") or ""),
                "preferred_mode": str(promoted_entry.get("preferred_mode") or ""),
                "preferred_policy": str(promoted_entry.get("preferred_policy") or ""),
                "source_work_item_id": str(promoted_entry.get("source_work_item_id") or ""),
            }
        envelope["metadata"] = metadata
        started_at = utc_iso()
        candidate_paths = [str(p) for p in self._candidate_artifact_paths(item, artifact_override)]
        steps: List[Dict[str, Any]] = [
            {
                "step": "load_work_item",
                "ok": True,
                "item_id": item_id,
                "include_archived": include_archived,
                "policy_override": str(policy_override or ""),
                "effective_policy": effective_policy,
                "policy_source": policy_source,
                "effective_mode": effective_mode,
                "mode_source": mode_source,
            },
            {
                "step": "resolve_artifact",
                "ok": bool(artifact_path),
                "artifact_path": str(artifact_path) if artifact_path else "",
                "candidate_paths": candidate_paths,
            },
        ]
        artifact_score = dict(resolution.get("score") or {})
        tool_choice = str(((envelope.get("tool_policy") or {}).get("tool_choice") or "auto")).strip().lower()
        executor_result: Dict[str, Any] = {}
        if effective_mode in {"auto", "executor"} and tool_choice == "none":
            executor_result = self._execute_toolless_work_item(item, envelope, artifact_path if isinstance(artifact_path, Path) else None, artifact_score)
            steps.append(
                {
                    "step": "execute_toolless_work_item",
                    "ok": bool(executor_result.get("ok")),
                    "task_id": str(executor_result.get("task_id") or ""),
                    "deliverable_path": str(executor_result.get("deliverable_path") or ""),
                    "execution_artifact_path": str(executor_result.get("execution_artifact_path") or ""),
                    "reason": str(executor_result.get("reason") or ""),
                }
            )
            evaluation = dict(executor_result.get("completion_evaluation") or {})
            score = {
                "ok": bool(evaluation.get("satisfied")),
                "artifact_exists": bool(executor_result.get("deliverable_path")),
                "artifact_path": str(executor_result.get("deliverable_path") or ""),
                "artifact_kind": "text",
                "required_markers": list(evaluation.get("required_markers") or []),
                "marker_hits": list(evaluation.get("present_markers") or []),
                "missing_markers": list(evaluation.get("missing_markers") or []),
                "passed_checks": ["artifact_exists"] + (["required_markers_present"] if bool(evaluation.get("satisfied")) else []),
                "failed_checks": [] if bool(evaluation.get("satisfied")) else ["required_markers_present"],
                "task_id": str(evaluation.get("task_id") or executor_result.get("task_id") or ""),
                "task_status": str(evaluation.get("task_status") or ""),
                "executor_kind": str(executor_result.get("executor_kind") or ""),
            }
            trajectory_kind = "work_jar_executor_replay"
            reason = "executor_checks_passed" if score.get("ok") else "executor_checks_failed"
        else:
            score = artifact_score
            steps.append(
                {
                    "step": "score_artifact",
                    "ok": bool(score.get("ok")),
                    "passed_checks": list(score.get("passed_checks") or []),
                    "failed_checks": list(score.get("failed_checks") or []),
                }
            )
            trajectory_kind = "work_jar_replay"
            reason = "mechanical_checks_passed" if score.get("ok") else "mechanical_checks_failed"
        result = {
            "ok": bool(score.get("ok")),
            "reason": reason,
            "rollout_id": rollout_id,
            "work_item_id": item_id,
            "started_at_utc": started_at,
            "finished_at_utc": utc_iso(),
            "envelope": envelope,
            "trajectory": {
                "kind": trajectory_kind,
                "steps": steps,
            },
            "score": score,
            "effective_mode": effective_mode,
            "mode_source": mode_source,
            "effective_policy": effective_policy,
            "policy_source": policy_source,
        }
        if executor_result:
            result["executor_result"] = executor_result
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.paths.output_dir / f"{rollout_id}.json"
        atomic_json_write(output_path, result, indent=2)
        result["rollout_path"] = str(output_path)
        self._record_rollout(result)
        return result

    def compare_work_item_rollout(
        self,
        *,
        item_id: str,
        modes: List[str],
        include_archived: bool = False,
        artifact_override: Optional[Path] = None,
        policies: Optional[List[str]] = None,
        promote: bool = False,
    ) -> Dict[str, Any]:
        normalized_modes: List[str] = []
        for mode in modes:
            value = str(mode or "").strip().lower()
            if value and value not in normalized_modes:
                normalized_modes.append(value)
        if not normalized_modes:
            normalized_modes = ["artifact", "auto"]

        normalized_policies: List[str] = []
        for policy in list(policies or []):
            value = str(policy or "").strip().lower()
            if value and value not in normalized_policies:
                normalized_policies.append(value)
        if not normalized_policies:
            normalized_policies = [""]

        started_at = utc_iso()
        comparisons: List[Dict[str, Any]] = []
        for mode in normalized_modes:
            for policy in normalized_policies:
                result = self.run_work_item_rollout(
                    item_id=item_id,
                    include_archived=include_archived,
                    artifact_override=artifact_override,
                    mode=mode,
                    policy_override=policy or None,
                )
                comparisons.append(
                    {
                        "mode": mode,
                        "policy": policy or "",
                        "ok": bool(result.get("ok")),
                        "reason": str(result.get("reason") or ""),
                        "rollout_id": str(result.get("rollout_id") or ""),
                        "rollout_path": str(result.get("rollout_path") or ""),
                        "trajectory_kind": str(((result.get("trajectory") or {}).get("kind")) or ""),
                        "executor_kind": str(((result.get("score") or {}).get("executor_kind")) or ""),
                        "artifact_path": str(((result.get("score") or {}).get("artifact_path")) or ""),
                        "passed_checks": list(((result.get("score") or {}).get("passed_checks")) or []),
                        "failed_checks": list(((result.get("score") or {}).get("failed_checks")) or []),
                        "missing_markers": list(((result.get("score") or {}).get("missing_markers")) or []),
                        "task_id": str(((result.get("score") or {}).get("task_id")) or ""),
                    }
                )

        preferred = sorted(
            comparisons,
            key=lambda row: (
                -int(bool(row.get("ok"))),
                -len(list(row.get("passed_checks") or [])),
                len(list(row.get("failed_checks") or [])),
                self._policy_preference_rank(str(row.get("policy") or "")),
                row.get("mode") != "auto",
            ),
        )[0]
        result = {
            "ok": bool(preferred.get("ok")),
            "work_item_id": item_id,
            "started_at_utc": started_at,
            "finished_at_utc": utc_iso(),
            "modes": normalized_modes,
            "policies": normalized_policies,
            "preferred_mode": str(preferred.get("mode") or ""),
            "preferred_policy": str(preferred.get("policy") or ""),
            "preferred_rollout_id": str(preferred.get("rollout_id") or ""),
            "comparisons": comparisons,
        }
        if promote:
            result["registry_promotion"] = self.promote_comparison_result(result)
        return result

    def _record_rollout(self, result: Dict[str, Any]) -> None:
        recorder = FlightRecorder(base_dir=self.paths.flight_recorder_dir, enabled=True)
        score = dict(result.get("score") or {})
        ok = bool(result.get("ok"))
        air = AIRResult(score=0.5 if ok else -0.5, reason="rollout_pass" if ok else "rollout_fail")
        recorder.log_transition(
            state_snapshot=json.dumps(result.get("envelope") or {}, ensure_ascii=True, default=str),
            action={
                "type": "rollout_replay",
                "rollout_id": result.get("rollout_id"),
                "work_item_id": result.get("work_item_id"),
                "trajectory_kind": ((result.get("trajectory") or {}).get("kind")),
            },
            result={
                "success": ok,
                "rollout_path": result.get("rollout_path"),
                "failed_checks": list(score.get("failed_checks") or []),
                "passed_checks": list(score.get("passed_checks") or []),
                "task_id": str(score.get("task_id") or ""),
            },
            air=air,
            meta={
                "success": ok,
                "rollout_id": result.get("rollout_id"),
                "work_item_id": result.get("work_item_id"),
            },
            provenance={
                "source_type": "rollout_service",
                "rollout_path": result.get("rollout_path"),
            },
        )


def default_paths(root: Path) -> RolloutPaths:
    return RolloutPaths(
        work_jar_path=root / "vera_memory" / "autonomy_work_jar.json",
        output_dir=root / "vera_memory" / "rollouts",
        flight_recorder_dir=root / "vera_memory" / "flight_recorder",
    )
