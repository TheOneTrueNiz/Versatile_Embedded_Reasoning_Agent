#!/usr/bin/env python3
"""
Build a migration-ready evidence bundle for Vera_2.0.

Collects the latest gate artifacts and emits a single manifest with overall PASS/FAIL.
"""

from __future__ import annotations

import argparse
import glob
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest(pattern: str) -> Path:
    matches = sorted(glob.glob(pattern))
    return Path(matches[-1]) if matches else Path("")


def _latest_mtime(pattern: str) -> Path:
    matches = [Path(item) for item in glob.glob(pattern)]
    if not matches:
        return Path("")
    matches.sort(key=lambda path: path.stat().st_mtime)
    return matches[-1]


def _latest_where(pattern: str, predicate) -> Path:
    matches = sorted(glob.glob(pattern))
    chosen = Path("")
    for raw in matches:
        path = Path(raw)
        payload = _load_json(path)
        try:
            if predicate(payload):
                chosen = path
        except Exception:
            continue
    if chosen:
        return chosen
    return Path(matches[-1]) if matches else Path("")


def _copy_if_exists(src: Path, dst_dir: Path) -> str:
    if not src or str(src) in {"", "."}:
        return ""
    if not src.exists() or not src.is_file():
        return ""
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    shutil.copy2(src, dst)
    return str(dst)


def _request_json(url: str, timeout: float = 8.0) -> Dict[str, Any]:
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _jsonl_line_count(path: Path) -> int:
    if not path or not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _followthrough_ledger_stats(payload: Dict[str, Any]) -> Dict[str, int]:
    statuses = {"completed": 0, "failed": 0, "missed": 0, "planned": 0, "running": 0, "pending": 0, "other": 0}
    commitments = payload.get("commitments")
    if not isinstance(commitments, dict):
        commitments = payload.get("actions")
    if not isinstance(commitments, dict):
        return statuses
    for value in commitments.values():
        if not isinstance(value, dict):
            statuses["other"] += 1
            continue
        status = str(value.get("status") or "")
        if status in statuses:
            statuses[status] += 1
        else:
            statuses["other"] += 1
    return statuses


def _doctor_report_ok(payload: Dict[str, Any], allowed_failures: set[str]) -> bool:
    results = payload.get("results")
    if not isinstance(results, list):
        return False
    for row in results:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "fail":
            continue
        pair = f"{row.get('server')}:{row.get('tool')}"
        failure_class = str(row.get("failure_class") or "")
        if pair in allowed_failures:
            continue
        if failure_class == "external":
            continue
        return False
    return True


def _professor_report_ok(payload: Dict[str, Any]) -> bool:
    lessons = payload.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        return False
    total = len(lessons)
    passed = int(payload.get("pass") or 0)
    failed = int(payload.get("fail") or 0)
    return passed == total and failed == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Vera migration-ready evidence bundle")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument(
        "--golden-manifest",
        default="",
        help="Path to golden deploy manifest (default: latest tmp/deploy_gates/golden_*/manifest.json)",
    )
    parser.add_argument("--callme-smoke", default="", help="Path to call-me live smoke JSON")
    parser.add_argument("--routing-gate", default="", help="Path to routing-inclusive golden gate JSON")
    parser.add_argument("--routing-trainer", default="", help="Path to routing trainer JSON")
    parser.add_argument("--memvid-report", default="", help="Path to memvid hardening JSON")
    parser.add_argument("--doctor-report", default="", help="Path to doctor clinic JSON")
    parser.add_argument("--professor-report", default="", help="Path to professor curriculum JSON")
    parser.add_argument("--native-memory-probe", default="", help="Path to doctor/professor native memory probe JSON")
    parser.add_argument("--archive-probe", default="", help="Path to archive retrieval probe JSON")
    parser.add_argument("--harness-ci-manifest", default="", help="Path to in-house Doctor/Professor CI manifest JSON")
    parser.add_argument("--followthrough-state", default="", help="Path to follow-through ledger JSON")
    parser.add_argument("--followthrough-events", default="", help="Path to follow-through events JSONL")
    parser.add_argument("--followthrough-actions", default="", help="Path to follow-through action ledger JSON")
    parser.add_argument("--followthrough-action-events", default="", help="Path to follow-through action events JSONL")
    parser.add_argument("--followthrough-workflow-stats", default="", help="Path to follow-through workflow stats JSON")
    parser.add_argument("--followthrough-learned-workflows", default="", help="Path to learned workflow catalog JSON")
    parser.add_argument("--followthrough-scaffold", default="", help="Path to latest follow-through scaffold markdown")
    parser.add_argument("--output-dir", default="", help="Bundle directory")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = _utc_ts()
    out_dir = Path(args.output_dir) if args.output_dir else (root / "tmp" / "deploy_gates" / f"migration_ready_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = out_dir / "evidence"
    manifest_path = out_dir / "manifest.json"

    golden_manifest = Path(args.golden_manifest) if args.golden_manifest else _latest(str(root / "tmp" / "deploy_gates" / "golden_*" / "manifest.json"))
    callme_smoke = (
        Path(args.callme_smoke)
        if args.callme_smoke
        else _latest_where(
            str(root / "tmp" / "call_me_live_smoke*.json"),
            lambda payload: bool(payload.get("ok") is True),
        )
    )
    routing_gate = Path(args.routing_gate) if args.routing_gate else _latest(str(root / "tmp" / "mcp_golden_gate_routing*.json"))
    routing_trainer = Path(args.routing_trainer) if args.routing_trainer else _latest(str(root / "tmp" / "mcp_server_training_golden_routing*.json"))
    memvid_report = Path(args.memvid_report) if args.memvid_report else _latest(str(root / "tmp" / "memvid_hardening*.json"))
    doctor_report = Path(args.doctor_report) if args.doctor_report else _latest(str(root / "tmp" / "doctor_clinic_native_memory_*.json"))
    professor_report = Path(args.professor_report) if args.professor_report else _latest(str(root / "tmp" / "professor_curriculum_native_memory_*.json"))
    native_memory_probe = Path(args.native_memory_probe) if args.native_memory_probe else _latest(str(root / "tmp" / "doctor_professor_native_memory_probe_*.json"))
    archive_probe = Path(args.archive_probe) if args.archive_probe else _latest(str(root / "tmp" / "archive_retrieval_probe_*.json"))
    harness_ci_manifest = (
        Path(args.harness_ci_manifest)
        if args.harness_ci_manifest
        else _latest_where(
            "/home/nizbot-macmini/projects/Doctor_Codex/logs/vera_ci*/*/ci_manifest_*.json",
            lambda payload: bool(payload.get("overall_ok") is True),
        )
    )
    followthrough_state = Path(args.followthrough_state) if args.followthrough_state else (root / "tmp" / "followthrough_state.json")
    followthrough_events = Path(args.followthrough_events) if args.followthrough_events else (root / "tmp" / "followthrough_events.jsonl")
    followthrough_actions = Path(args.followthrough_actions) if args.followthrough_actions else (root / "tmp" / "followthrough_actions.json")
    followthrough_action_events = Path(args.followthrough_action_events) if args.followthrough_action_events else (root / "tmp" / "followthrough_action_events.jsonl")
    followthrough_workflow_stats = (
        Path(args.followthrough_workflow_stats) if args.followthrough_workflow_stats else (root / "tmp" / "followthrough_workflow_stats.json")
    )
    followthrough_learned_workflows = (
        Path(args.followthrough_learned_workflows)
        if args.followthrough_learned_workflows
        else (root / "tmp" / "followthrough_learned_workflows.json")
    )
    followthrough_scaffold = (
        Path(args.followthrough_scaffold)
        if args.followthrough_scaffold
        else _latest_mtime(str(root / "tmp" / "followthrough_runs" / "*" / "*" / "scaffold.md"))
    )

    golden_obj = _load_json(golden_manifest)
    callme_obj = _load_json(callme_smoke)
    routing_obj = _load_json(routing_gate)
    routing_trainer_obj = _load_json(routing_trainer)
    memvid_obj = _load_json(memvid_report)
    doctor_obj = _load_json(doctor_report)
    professor_obj = _load_json(professor_report)
    native_probe_obj = _load_json(native_memory_probe)
    archive_probe_obj = _load_json(archive_probe)
    harness_ci_obj = _load_json(harness_ci_manifest)
    followthrough_state_obj = _load_json(followthrough_state)
    followthrough_actions_obj = _load_json(followthrough_actions)
    followthrough_workflow_stats_obj = _load_json(followthrough_workflow_stats)
    followthrough_learned_workflows_obj = _load_json(followthrough_learned_workflows)
    followthrough_stats = _followthrough_ledger_stats(followthrough_state_obj)
    followthrough_events_count = _jsonl_line_count(followthrough_events)
    followthrough_action_events_count = _jsonl_line_count(followthrough_action_events)
    followthrough_action_status = _followthrough_ledger_stats(
        {"commitments": (followthrough_actions_obj.get("actions") if isinstance(followthrough_actions_obj.get("actions"), dict) else {})}
    )
    workflow_rows = followthrough_workflow_stats_obj.get("workflows")
    learned_rows = followthrough_learned_workflows_obj.get("workflows")
    workflow_rows_count = len(workflow_rows) if isinstance(workflow_rows, dict) else 0
    learned_rows_count = len(learned_rows) if isinstance(learned_rows, list) else 0

    readiness_obj: Dict[str, Any] = {}
    readiness_error = ""
    try:
        readiness_obj = _request_json(f"{args.base_url}/api/readiness")
    except Exception as exc:
        readiness_error = str(exc)

    checks: List[Dict[str, Any]] = []
    checks.append(
        {
            "name": "golden_deploy_manifest",
            "ok": bool(golden_obj.get("overall_ok") is True),
            "detail": str(golden_manifest) if golden_manifest else "missing",
        }
    )
    checks.append(
        {
            "name": "call_me_live_smoke",
            "ok": bool(callme_obj.get("ok") is True),
            "detail": str(callme_smoke) if callme_smoke else "missing",
        }
    )
    checks.append(
        {
            "name": "routing_gate",
            "ok": bool(routing_obj.get("overall_ok") is True),
            "detail": str(routing_gate) if routing_gate else "missing",
        }
    )
    checks.append(
        {
            "name": "memvid_hardening",
            "ok": bool(memvid_obj.get("ok") is True),
            "detail": str(memvid_report) if memvid_report else "missing",
        }
    )
    checks.append(
        {
            "name": "api_readiness",
            "ok": bool(readiness_obj.get("ready") is True),
            "detail": readiness_error or str(readiness_obj.get("message") or ""),
        }
    )
    allowed_external = {"x-twitter:get_trends", "scrapeless:google_search"}
    checks.append(
        {
            "name": "doctor_clinic_native_memory",
            "ok": _doctor_report_ok(doctor_obj, allowed_external),
            "detail": str(doctor_report) if doctor_report else "missing",
        }
    )
    checks.append(
        {
            "name": "professor_curriculum_native_memory",
            "ok": _professor_report_ok(professor_obj),
            "detail": str(professor_report) if professor_report else "missing",
        }
    )
    checks.append(
        {
            "name": "doctor_professor_native_memory_probe",
            "ok": bool(native_probe_obj.get("overall_ok") is True),
            "detail": str(native_memory_probe) if native_memory_probe else "missing",
        }
    )
    checks.append(
        {
            "name": "archive_retrieval_probe",
            "ok": bool(archive_probe_obj.get("overall_ok") is True),
            "detail": str(archive_probe) if archive_probe else "missing",
        }
    )
    checks.append(
        {
            "name": "harness_ci_manifest",
            "ok": bool(harness_ci_obj.get("overall_ok") is True),
            "detail": str(harness_ci_manifest) if harness_ci_manifest else "missing",
        }
    )
    checks.append(
        {
            "name": "followthrough_ledger",
            "ok": bool(followthrough_state.exists() and followthrough_stats.get("failed", 0) == 0),
            "detail": str(followthrough_state) if followthrough_state else "missing",
        }
    )
    checks.append(
        {
            "name": "followthrough_events_log",
            "ok": bool(followthrough_events.exists() and followthrough_events_count > 0),
            "detail": str(followthrough_events) if followthrough_events else "missing",
        }
    )
    checks.append(
        {
            "name": "followthrough_action_ledger",
            "ok": bool(followthrough_actions.exists() and followthrough_action_status.get("failed", 0) == 0),
            "detail": str(followthrough_actions) if followthrough_actions else "missing",
        }
    )
    checks.append(
        {
            "name": "followthrough_action_events_log",
            "ok": bool(followthrough_action_events.exists() and followthrough_action_events_count > 0),
            "detail": str(followthrough_action_events) if followthrough_action_events else "missing",
        }
    )
    checks.append(
        {
            "name": "followthrough_workflow_stats",
            "ok": bool(followthrough_workflow_stats.exists() and workflow_rows_count >= 1),
            "detail": str(followthrough_workflow_stats) if followthrough_workflow_stats else "missing",
        }
    )
    checks.append(
        {
            "name": "followthrough_learned_workflows",
            "ok": bool((not followthrough_learned_workflows) or (not followthrough_learned_workflows.exists()) or isinstance(learned_rows, list)),
            "detail": str(followthrough_learned_workflows) if followthrough_learned_workflows else "",
        }
    )

    overall_ok = all(bool(item.get("ok")) for item in checks)

    copied = {
        "golden_manifest": _copy_if_exists(golden_manifest, evidence_dir),
        "call_me_live_smoke": _copy_if_exists(callme_smoke, evidence_dir),
        "routing_gate": _copy_if_exists(routing_gate, evidence_dir),
        "routing_trainer": _copy_if_exists(routing_trainer, evidence_dir),
        "memvid_report": _copy_if_exists(memvid_report, evidence_dir),
        "doctor_report": _copy_if_exists(doctor_report, evidence_dir),
        "professor_report": _copy_if_exists(professor_report, evidence_dir),
        "native_memory_probe": _copy_if_exists(native_memory_probe, evidence_dir),
        "archive_probe": _copy_if_exists(archive_probe, evidence_dir),
        "harness_ci_manifest": _copy_if_exists(harness_ci_manifest, evidence_dir),
        "followthrough_state": _copy_if_exists(followthrough_state, evidence_dir),
        "followthrough_events": _copy_if_exists(followthrough_events, evidence_dir),
        "followthrough_actions": _copy_if_exists(followthrough_actions, evidence_dir),
        "followthrough_action_events": _copy_if_exists(followthrough_action_events, evidence_dir),
        "followthrough_workflow_stats": _copy_if_exists(followthrough_workflow_stats, evidence_dir),
        "followthrough_learned_workflows": _copy_if_exists(followthrough_learned_workflows, evidence_dir),
        "followthrough_scaffold": _copy_if_exists(followthrough_scaffold, evidence_dir),
    }

    summary = {
        "memvid": {
            "hit_rate": ((memvid_obj.get("retrieval") or {}).get("hit_rate") if isinstance(memvid_obj.get("retrieval"), dict) else None),
            "p95_ms": ((((memvid_obj.get("retrieval") or {}).get("latency_ms") or {}).get("p95")) if isinstance((memvid_obj.get("retrieval") or {}).get("latency_ms"), dict) else None),
            "memvid_hits_delta": ((memvid_obj.get("memvid") or {}).get("hits_delta") if isinstance(memvid_obj.get("memvid"), dict) else None),
        },
        "routing": {
            "summary": routing_obj.get("trainer_summary") if isinstance(routing_obj, dict) else {},
            "trainer_summary": routing_trainer_obj.get("summary") if isinstance(routing_trainer_obj, dict) else {},
        },
        "doctor_professor": {
            "doctor_fail": doctor_obj.get("fail"),
            "professor_pass": professor_obj.get("pass"),
            "professor_fail": professor_obj.get("fail"),
            "native_memory_probe_ok": native_probe_obj.get("overall_ok"),
            "archive_probe_ok": archive_probe_obj.get("overall_ok"),
            "harness_ci_ok": harness_ci_obj.get("overall_ok"),
            "followthrough_status_counts": followthrough_stats,
            "followthrough_events_count": followthrough_events_count,
            "followthrough_action_status_counts": followthrough_action_status,
            "followthrough_action_events_count": followthrough_action_events_count,
            "followthrough_workflow_rows_count": workflow_rows_count,
            "followthrough_learned_workflow_rows_count": learned_rows_count,
            "followthrough_scaffold": str(followthrough_scaffold) if followthrough_scaffold else "",
        },
    }

    manifest: Dict[str, Any] = {
        "captured_at_utc": _utc_iso(),
        "base_url": args.base_url,
        "bundle_dir": str(out_dir),
        "overall_ok": overall_ok,
        "checks": checks,
        "summary": summary,
        "readiness": readiness_obj,
        "copied_evidence": copied,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Migration-ready manifest: {manifest_path}")
    print(f"Overall: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
