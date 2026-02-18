#!/usr/bin/env python3
"""
Build a migration handoff pack with latest PASS artifacts.

Outputs:
- handoff directory with evidence files + manifest
- tar.gz archive for transfer to another machine
"""

from __future__ import annotations

import argparse
import glob
import json
import shutil
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _latest(pattern: str) -> Path:
    matches = sorted(glob.glob(pattern))
    return Path(matches[-1]) if matches else Path("")


def _latest_mtime(pattern: str) -> Path:
    matches = [Path(item) for item in glob.glob(pattern)]
    if not matches:
        return Path("")
    matches.sort(key=lambda path: path.stat().st_mtime)
    return matches[-1]


def _latest_where(pattern: str, predicate: Callable[[Dict[str, Any]], bool]) -> Path:
    matches = sorted(glob.glob(pattern))
    chosen = Path("")
    for item in matches:
        path = Path(item)
        payload = _load_json(path)
        try:
            if predicate(payload):
                chosen = path
        except Exception:
            continue
    if chosen:
        return chosen
    return Path(matches[-1]) if matches else Path("")


def _copy_with_label(src: Path, dst_dir: Path, label: str) -> str:
    if not src or not src.exists():
        return ""
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{label}__{src.name}"
    shutil.copy2(src, dst)
    return str(dst)


def _request_json(url: str, timeout: float = 10.0) -> Dict[str, Any]:
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    return payload if isinstance(payload, dict) else {}


def _followthrough_ledger_counts(path: Path) -> Dict[str, int]:
    counts = {"completed": 0, "failed": 0, "missed": 0, "planned": 0, "running": 0, "pending": 0, "other": 0}
    payload = _load_json(path)
    rows = payload.get("commitments")
    if not isinstance(rows, dict):
        rows = payload.get("actions")
    if not isinstance(rows, dict):
        return counts
    for value in rows.values():
        if not isinstance(value, dict):
            counts["other"] += 1
            continue
        status = str(value.get("status") or "")
        if status in counts:
            counts[status] += 1
        else:
            counts["other"] += 1
    return counts


def _jsonl_line_count(path: Path) -> int:
    if not path or not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _make_tarball(source_dir: Path, tar_path: Path) -> None:
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(source_dir, arcname=source_dir.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create migration handoff pack")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--output-dir", default="", help="Default: tmp/migration_handoff/handoff_<ts>")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = _utc_ts()
    out_dir = Path(args.output_dir) if args.output_dir else (root / "tmp" / "migration_handoff" / f"handoff_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = out_dir / "evidence"

    # Select latest relevant artifacts (prefer PASS artifacts where possible).
    migration_manifest = _latest_where(
        str(root / "tmp" / "deploy_gates" / "migration_ready_*" / "manifest.json"),
        lambda p: bool(p.get("overall_ok") is True),
    )
    ci_manifest = _latest_where(
        "/home/nizbot-macmini/projects/Doctor_Codex/logs/vera_ci/*/ci_manifest_*.json",
        lambda p: bool(p.get("overall_ok") is True),
    )
    ci_triggered_latest = _latest("/home/nizbot-macmini/projects/Doctor_Codex/logs/vera_ci_triggered/*/ci_manifest_*.json")
    soak_summary = _latest_where(
        str(root / "tmp" / "soak" / "vera_soak_controlled_summary_*.json"),
        lambda p: int(p.get("failures") or 0) == 0,
    )
    soak_jsonl = Path(_load_json(soak_summary).get("log_jsonl") or "") if soak_summary else Path("")
    if soak_jsonl and not soak_jsonl.is_absolute():
        soak_jsonl = root / soak_jsonl

    native_probe = _latest_where(
        str(root / "tmp" / "doctor_professor_native_memory_probe_*.json"),
        lambda p: bool(p.get("overall_ok") is True),
    )
    archive_probe = _latest_where(
        str(root / "tmp" / "archive_exerciser" / "archive_retrieval_probe_*.json"),
        lambda p: bool(p.get("overall_ok") is True),
    )
    if not archive_probe:
        archive_probe = _latest_where(
            str(root / "tmp" / "archive_retrieval_probe_*.json"),
            lambda p: bool(p.get("overall_ok") is True),
        )
    drift_check = _latest_where(
        str(root / "tmp" / "tool_discovery_drift_check_*.json"),
        lambda p: bool(p.get("overall_ok") is True),
    )
    followthrough_state = root / "tmp" / "followthrough_state.json"
    followthrough_events = root / "tmp" / "followthrough_events.jsonl"
    followthrough_actions = root / "tmp" / "followthrough_actions.json"
    followthrough_action_events = root / "tmp" / "followthrough_action_events.jsonl"
    followthrough_workflow_stats = root / "tmp" / "followthrough_workflow_stats.json"
    followthrough_learned_workflows = root / "tmp" / "followthrough_learned_workflows.json"
    followthrough_scaffold = _latest_mtime(str(root / "tmp" / "followthrough_runs" / "*" / "*" / "scaffold.md"))
    followthrough_counts = _followthrough_ledger_counts(followthrough_state)
    followthrough_events_count = _jsonl_line_count(followthrough_events)
    followthrough_action_counts = _followthrough_ledger_counts(followthrough_actions)
    followthrough_action_events_count = _jsonl_line_count(followthrough_action_events)
    workflow_stats_obj = _load_json(followthrough_workflow_stats)
    learned_workflows_obj = _load_json(followthrough_learned_workflows)
    workflow_stats_rows = workflow_stats_obj.get("workflows") if isinstance(workflow_stats_obj.get("workflows"), dict) else {}
    learned_workflow_rows = learned_workflows_obj.get("workflows") if isinstance(learned_workflows_obj.get("workflows"), list) else []

    doctor_report = Path("")
    professor_report = Path("")
    if ci_manifest:
        ci_obj = _load_json(ci_manifest)
        reports = ci_obj.get("reports") if isinstance(ci_obj, dict) else {}
        if isinstance(reports, dict):
            doctor_report = Path(reports.get("doctor") or "")
            professor_report = Path(reports.get("professor") or "")

    # Live readiness snapshot.
    readiness: Dict[str, Any] = {}
    readiness_error = ""
    try:
        readiness = _request_json(f"{args.base_url}/api/readiness")
    except Exception as exc:
        readiness_error = str(exc)

    copied = {
        "migration_manifest": _copy_with_label(migration_manifest, evidence_dir, "migration_manifest"),
        "ci_manifest": _copy_with_label(ci_manifest, evidence_dir, "ci_manifest"),
        "ci_triggered_latest": _copy_with_label(ci_triggered_latest, evidence_dir, "ci_triggered_latest"),
        "soak_summary": _copy_with_label(soak_summary, evidence_dir, "soak_summary"),
        "soak_jsonl": _copy_with_label(soak_jsonl, evidence_dir, "soak_jsonl"),
        "native_probe": _copy_with_label(native_probe, evidence_dir, "native_probe"),
        "archive_probe": _copy_with_label(archive_probe, evidence_dir, "archive_probe"),
        "drift_check": _copy_with_label(drift_check, evidence_dir, "drift_check"),
        "doctor_report": _copy_with_label(doctor_report, evidence_dir, "doctor_report"),
        "professor_report": _copy_with_label(professor_report, evidence_dir, "professor_report"),
        "followthrough_state": _copy_with_label(followthrough_state, evidence_dir, "followthrough_state"),
        "followthrough_events": _copy_with_label(followthrough_events, evidence_dir, "followthrough_events"),
        "followthrough_actions": _copy_with_label(followthrough_actions, evidence_dir, "followthrough_actions"),
        "followthrough_action_events": _copy_with_label(followthrough_action_events, evidence_dir, "followthrough_action_events"),
        "followthrough_workflow_stats": _copy_with_label(followthrough_workflow_stats, evidence_dir, "followthrough_workflow_stats"),
        "followthrough_learned_workflows": _copy_with_label(followthrough_learned_workflows, evidence_dir, "followthrough_learned_workflows"),
        "followthrough_scaffold": _copy_with_label(followthrough_scaffold, evidence_dir, "followthrough_scaffold"),
    }

    migration_ok = bool(_load_json(migration_manifest).get("overall_ok") is True)
    ci_ok = bool(_load_json(ci_manifest).get("overall_ok") is True)
    soak_ok = bool(int(_load_json(soak_summary).get("failures") or 0) == 0)
    readiness_ok = bool(readiness.get("ready") is True)
    followthrough_ledger_ok = bool(followthrough_state.exists() and followthrough_counts.get("failed", 0) == 0)
    followthrough_events_ok = bool(followthrough_events.exists() and followthrough_events_count > 0)
    followthrough_action_ledger_ok = bool(followthrough_actions.exists() and followthrough_action_counts.get("failed", 0) == 0)
    followthrough_action_events_ok = bool(followthrough_action_events.exists() and followthrough_action_events_count > 0)
    followthrough_workflow_stats_ok = bool(followthrough_workflow_stats.exists() and isinstance(workflow_stats_rows, dict) and len(workflow_stats_rows) >= 1)

    checks = {
        "migration_manifest_ok": migration_ok,
        "ci_manifest_ok": ci_ok,
        "soak_summary_ok": soak_ok,
        "readiness_ok": readiness_ok,
        "followthrough_ledger_ok": followthrough_ledger_ok,
        "followthrough_events_ok": followthrough_events_ok,
        "followthrough_action_ledger_ok": followthrough_action_ledger_ok,
        "followthrough_action_events_ok": followthrough_action_events_ok,
        "followthrough_workflow_stats_ok": followthrough_workflow_stats_ok,
    }
    overall_ok = all(checks.values())

    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": args.base_url,
        "output_dir": str(out_dir),
        "overall_ok": overall_ok,
        "checks": checks,
        "selected_sources": {
            "migration_manifest": str(migration_manifest) if migration_manifest else "",
            "ci_manifest": str(ci_manifest) if ci_manifest else "",
            "ci_triggered_latest": str(ci_triggered_latest) if ci_triggered_latest else "",
            "soak_summary": str(soak_summary) if soak_summary else "",
            "soak_jsonl": str(soak_jsonl) if soak_jsonl else "",
            "native_probe": str(native_probe) if native_probe else "",
            "archive_probe": str(archive_probe) if archive_probe else "",
            "drift_check": str(drift_check) if drift_check else "",
            "doctor_report": str(doctor_report) if doctor_report else "",
            "professor_report": str(professor_report) if professor_report else "",
            "followthrough_state": str(followthrough_state) if followthrough_state else "",
            "followthrough_events": str(followthrough_events) if followthrough_events else "",
            "followthrough_actions": str(followthrough_actions) if followthrough_actions else "",
            "followthrough_action_events": str(followthrough_action_events) if followthrough_action_events else "",
            "followthrough_workflow_stats": str(followthrough_workflow_stats) if followthrough_workflow_stats else "",
            "followthrough_learned_workflows": str(followthrough_learned_workflows) if followthrough_learned_workflows else "",
            "followthrough_scaffold": str(followthrough_scaffold) if followthrough_scaffold else "",
        },
        "copied_evidence": copied,
        "readiness": readiness,
        "readiness_error": readiness_error,
        "followthrough": {
            "status_counts": followthrough_counts,
            "events_count": followthrough_events_count,
            "action_status_counts": followthrough_action_counts,
            "action_events_count": followthrough_action_events_count,
            "workflow_stats_rows": len(workflow_stats_rows),
            "learned_workflow_rows": len(learned_workflow_rows),
        },
    }

    manifest_path = out_dir / "handoff_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    tar_path = out_dir.parent / f"{out_dir.name}.tar.gz"
    _make_tarball(out_dir, tar_path)

    print(f"Handoff dir: {out_dir}")
    print(f"Handoff manifest: {manifest_path}")
    print(f"Handoff tarball: {tar_path}")
    print(json.dumps({"overall_ok": overall_ok, "checks": checks}, indent=2))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
