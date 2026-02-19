#!/usr/bin/env python3
"""
In-house CI-style gate for Doctor/Professor harness validation.

Runs Doctor_Codex harness reports plus Vera-native memory probes and emits a
single PASS/FAIL manifest in an in-house logs directory.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib import error, request


PROFESSOR_EQUIVALENT_TOOL_GROUPS: Dict[str, List[List[str]]] = {
    "web_knowledge_chain": [
        ["brave_web_search", "brave_ai_search", "searxng_search"],
        ["search_wikipedia", "get_summary", "get_article", "search", "get_page", "get_page_content"],
    ],
}


@dataclass
class RunResult:
    name: str
    cmd: List[str]
    returncode: int
    ok: bool
    elapsed_s: float
    stdout_log: str
    stderr_log: str
    report_path: str


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_cmd(
    name: str,
    cmd: List[str],
    report_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_s: float,
) -> RunResult:
    start = datetime.now(timezone.utc)
    ok = False
    rc = 124
    out_text = ""
    err_text = ""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout_s),
            check=False,
        )
        rc = int(proc.returncode)
        out_text = proc.stdout or ""
        err_text = proc.stderr or ""
        ok = rc == 0
    except subprocess.TimeoutExpired as exc:
        out_text = exc.stdout or ""
        err_text = (exc.stderr or "") + "\nTIMEOUT"
    except Exception as exc:
        err_text = f"failed to execute: {exc}"

    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text(out_text, encoding="utf-8")
    stderr_path.write_text(err_text, encoding="utf-8")
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    return RunResult(
        name=name,
        cmd=cmd,
        returncode=rc,
        ok=ok,
        elapsed_s=elapsed,
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
        report_path=str(report_path),
    )


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _wait_for_readiness(
    base_url: str,
    timeout_s: float,
    ready_streak: int = 3,
    poll_s: float = 1.0,
) -> bool:
    timeout = max(0.0, float(timeout_s))
    if timeout <= 0.0:
        return True
    required_streak = max(1, int(ready_streak))
    deadline = time.time() + timeout
    streak = 0
    url = f"{base_url.rstrip('/')}/api/readiness"
    while time.time() < deadline:
        try:
            req = request.Request(url, method="GET")
            with request.urlopen(req, timeout=max(2.0, poll_s + 1.5)) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                payload = json.loads(raw)
                ready = bool(resp.getcode() == 200 and isinstance(payload, dict) and payload.get("ready") is True)
        except Exception:
            ready = False

        if ready:
            streak += 1
            if streak >= required_streak:
                return True
        else:
            streak = 0
        time.sleep(max(0.1, poll_s))
    return False


def _record_memory_event(
    base_url: str,
    overall_ok: bool,
    ts_utc: str,
    manifest_path: Path,
    checks: Dict[str, Any],
) -> Dict[str, Any]:
    status = "PASS" if overall_ok else "FAIL"
    doctor = checks.get("doctor", {})
    professor = checks.get("professor", {})
    native_probe = checks.get("native_memory_probe", {})
    archive_probe = checks.get("archive_retrieval_probe", {})
    drift_check = checks.get("tool_discovery_drift_check", {})
    doctor_external = (doctor.get("detail") or {}).get("external_failures") if isinstance(doctor.get("detail"), dict) else []
    doctor_unexpected = (doctor.get("detail") or {}).get("unexpected_failures") if isinstance(doctor.get("detail"), dict) else []

    content = (
        f"Doctor/Professor CI {status} at {ts_utc}. "
        f"participants=[Niz, Vera, Doctor Codex, Professor Codex], "
        f"systems=[api_readiness, mcp_tools, native_memory, archive, tool_discovery], "
        f"doctor(exec={doctor.get('exec_ok')},logic={doctor.get('logic_ok')}), "
        f"professor(exec={professor.get('exec_ok')},logic={professor.get('logic_ok')}), "
        f"native(exec={native_probe.get('exec_ok')},logic={native_probe.get('logic_ok')}), "
        f"archive(exec={archive_probe.get('exec_ok')},logic={archive_probe.get('logic_ok')}), "
        f"drift(exec={drift_check.get('exec_ok')},logic={drift_check.get('logic_ok')}), "
        f"doctor_external={doctor_external}, doctor_unexpected={doctor_unexpected}, "
        f"manifest={manifest_path}"
    )

    payload = {
        "name": "encode_event",
        "arguments": {
            "content": content,
            "type": "system_event",
            "tags": [
                "doctor-codex",
                "professor-codex",
                "ci-gate",
                "migration-readiness",
                "interaction-memory",
                "multi-agent",
                "niz",
                "vera",
                "pass" if overall_ok else "fail",
            ],
            "provenance": {
                "source_type": "system",
                "source_id": "vera_doctor_professor_ci_gate",
                "participants": ["Niz", "Vera", "Doctor Codex", "Professor Codex"],
                "systems": ["api", "mcp", "native_memory", "archive", "doctor_harness", "professor_harness"],
            },
        },
    }
    req = request.Request(
        f"{base_url.rstrip('/')}/api/tools/call",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            body = json.loads(raw)
            ok = resp.getcode() == 200 and isinstance(body, dict) and body.get("type") == "native"
            return {
                "attempted": True,
                "ok": bool(ok),
                "http": resp.getcode(),
                "type": body.get("type") if isinstance(body, dict) else None,
            }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"attempted": True, "ok": False, "http": exc.code, "error": body[:400]}
    except Exception as exc:
        return {"attempted": True, "ok": False, "http": 0, "error": str(exc)}


def _doctor_ok(payload: Dict[str, Any], allowed_failures: set[str]) -> Tuple[bool, Dict[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, list):
        return False, {"reason": "missing results"}

    unexpected: List[str] = []
    allowed: List[str] = []
    external: List[str] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "fail":
            continue
        pair = f"{row.get('server')}:{row.get('tool')}"
        failure_class = str(row.get("failure_class") or "")
        if pair in allowed_failures:
            allowed.append(pair)
        elif failure_class == "external":
            external.append(pair)
        else:
            unexpected.append(pair)
    return len(unexpected) == 0, {
        "unexpected_failures": sorted(set(unexpected)),
        "allowed_failures": sorted(set(allowed)),
        "external_failures": sorted(set(external)),
    }


def _professor_ok(payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    lessons = payload.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        return False, {"reason": "missing lessons"}

    def _tools_cover_groups(used: List[str], groups: List[List[str]]) -> bool:
        used_set = {str(item).strip() for item in used if str(item).strip()}
        if not used_set:
            return False
        for group in groups:
            names = [str(name).strip() for name in group if str(name).strip()]
            if names and not any(name in used_set for name in names):
                return False
        return True

    total = len(lessons)
    passed = 0
    failed = 0
    missing: Dict[str, List[str]] = {}
    compat_recovered: List[str] = []
    for lesson in lessons:
        if not isinstance(lesson, dict):
            failed += 1
            continue
        lesson_id = str(lesson.get("id") or "unknown")
        lesson_passed = bool(lesson.get("passed") is True)
        if not lesson_passed:
            groups = PROFESSOR_EQUIVALENT_TOOL_GROUPS.get(lesson_id)
            used_tools = [str(x) for x in lesson.get("used_tools") or [] if isinstance(x, str)]
            if groups and _tools_cover_groups(used_tools, groups):
                lesson_passed = True
                compat_recovered.append(lesson_id)
        if lesson_passed:
            passed += 1
            continue
        failed += 1
        miss = lesson.get("missing_tools")
        missing[lesson_id] = [str(x) for x in miss] if isinstance(miss, list) else []
    ok = passed == total and failed == 0 and not missing
    return ok, {
        "total": total,
        "passed": passed,
        "failed": failed,
        "missing_tools": missing,
        "compatibility_recovered": sorted(set(compat_recovered)),
    }


def _probe_ok(payload: Dict[str, Any], key: str = "overall_ok") -> bool:
    return bool(payload.get(key) is True)


def _guided_ok(payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    lessons = payload.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        return False, {"reason": "missing lessons"}
    passed = int(payload.get("pass") or 0)
    failed = int(payload.get("fail") or 0)
    skipped = int(payload.get("skip") or 0)
    hard_failures = payload.get("hard_failures")
    if not isinstance(hard_failures, list):
        hard_failures = []
    ok = bool(payload.get("overall_ok") is True)
    return ok, {
        "total": len(lessons),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "hard_failures": [str(x) for x in hard_failures],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Doctor/Professor CI-style gate for Vera")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--harness-root", default="/home/nizbot-macmini/projects/Doctor_Codex")
    parser.add_argument("--logs-dir", default="", help="Default: <harness-root>/logs/vera_ci/<ts>")
    parser.add_argument("--doctor-timeout", type=float, default=900.0)
    parser.add_argument("--professor-timeout", type=float, default=1500.0)
    parser.add_argument("--native-probe-timeout", type=float, default=300.0)
    parser.add_argument("--archive-probe-timeout", type=float, default=300.0)
    parser.add_argument("--drift-check-timeout", type=float, default=180.0)
    parser.add_argument("--guided-timeout", type=float, default=1800.0)
    parser.add_argument(
        "--professor-protocol",
        default="",
        help="Optional protocol markdown passed to Doctor_Codex professor_curriculum.py",
    )
    parser.add_argument(
        "--run-guided-learning",
        action="store_true",
        help="Run Vera-side guided curriculum in addition to Doctor_Codex professor curriculum.",
    )
    parser.add_argument(
        "--guided-curriculum",
        default="config/doctor_professor/vera_guided_learning_curriculum.json",
    )
    parser.add_argument(
        "--guided-protocol",
        default="config/doctor_professor/vera_professor_protocol.md",
    )
    parser.add_argument(
        "--guided-inventory",
        default="vera_tools_list_for_guided_learning",
    )
    parser.add_argument("--guided-retries", type=int, default=2)
    parser.add_argument(
        "--wait-ready-seconds",
        type=float,
        default=0.0,
        help="Wait for /api/readiness ready=true before each CI sub-run (0 disables wait).",
    )
    parser.add_argument(
        "--ready-streak",
        type=int,
        default=3,
        help="Consecutive ready=true checks required when --wait-ready-seconds > 0.",
    )
    parser.add_argument(
        "--allow-doctor-failure",
        action="append",
        default=[],
        help="Allow listed doctor failures (server:tool). Can be repeated.",
    )
    parser.add_argument("--skip-native-probe", action="store_true")
    parser.add_argument("--skip-archive-probe", action="store_true")
    parser.add_argument("--skip-drift-check", action="store_true")
    parser.add_argument("--skip-memory-record", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = _utc_ts()
    harness_root = Path(args.harness_root).resolve()
    logs_dir = Path(args.logs_dir).resolve() if args.logs_dir else (harness_root / "logs" / "vera_ci" / ts)
    logs_dir.mkdir(parents=True, exist_ok=True)

    if args.professor_protocol:
        professor_protocol_path = Path(args.professor_protocol)
        if not professor_protocol_path.is_absolute():
            professor_protocol_path = root / professor_protocol_path
    else:
        professor_protocol_path = root / "config" / "doctor_professor" / "vera_professor_protocol.md"

    guided_curriculum_path = Path(args.guided_curriculum)
    if not guided_curriculum_path.is_absolute():
        guided_curriculum_path = root / guided_curriculum_path
    guided_protocol_path = Path(args.guided_protocol)
    if not guided_protocol_path.is_absolute():
        guided_protocol_path = root / guided_protocol_path
    guided_inventory_path = Path(args.guided_inventory)
    if not guided_inventory_path.is_absolute():
        guided_inventory_path = root / guided_inventory_path

    allowed_failures = {
        "x-twitter:get_trends",
        "scrapeless:google_search",
    }
    for item in args.allow_doctor_failure:
        item = str(item).strip()
        if item:
            allowed_failures.add(item)

    doctor_report = logs_dir / f"doctor_clinic_{ts}.json"
    professor_report = logs_dir / f"professor_curriculum_{ts}.json"
    native_probe_report = logs_dir / f"doctor_professor_native_memory_probe_{ts}.json"
    archive_probe_report = logs_dir / f"archive_retrieval_probe_{ts}.json"
    drift_check_report = logs_dir / f"tool_discovery_drift_check_{ts}.json"
    guided_report = logs_dir / f"guided_curriculum_{ts}.json"

    professor_cmd = [
        sys.executable,
        str(harness_root / "professor_curriculum.py"),
        "--base-url",
        args.base_url,
        "--output",
        str(professor_report),
    ]
    if professor_protocol_path.exists():
        professor_cmd.extend(["--protocol", str(professor_protocol_path)])

    runs: List[RunResult] = []
    run_inputs: List[Tuple[str, List[str], Path, float]] = [
        (
            "doctor_clinic",
            [sys.executable, str(harness_root / "doctor_clinic.py"), "--base-url", args.base_url, "--output", str(doctor_report)],
            doctor_report,
            args.doctor_timeout,
        ),
        (
            "professor_curriculum",
            professor_cmd,
            professor_report,
            args.professor_timeout,
        ),
    ]

    if not args.skip_native_probe:
        run_inputs.append(
            (
                "native_memory_probe",
                [sys.executable, str(root / "scripts" / "vera_doctor_professor_native_memory_probe.py"), "--base-url", args.base_url, "--output", str(native_probe_report)],
                native_probe_report,
                args.native_probe_timeout,
            )
        )
    if not args.skip_archive_probe:
        run_inputs.append(
            (
                "archive_retrieval_probe",
                [sys.executable, str(root / "scripts" / "vera_archive_retrieval_probe.py"), "--base-url", args.base_url, "--output", str(archive_probe_report)],
                archive_probe_report,
                args.archive_probe_timeout,
            )
        )
    if not args.skip_drift_check:
        run_inputs.append(
            (
                "tool_discovery_drift_check",
                [sys.executable, str(root / "scripts" / "vera_tool_discovery_drift_check.py"), "--base-url", args.base_url, "--output", str(drift_check_report)],
                drift_check_report,
                args.drift_check_timeout,
            )
        )
    if args.run_guided_learning:
        run_inputs.append(
            (
                "guided_learning_curriculum",
                [
                    sys.executable,
                    str(root / "scripts" / "vera_guided_learning_curriculum.py"),
                    "--base-url",
                    args.base_url,
                    "--curriculum",
                    str(guided_curriculum_path),
                    "--protocol",
                    str(guided_protocol_path),
                    "--inventory",
                    str(guided_inventory_path),
                    "--retries",
                    str(args.guided_retries),
                    "--output",
                    str(guided_report),
                ],
                guided_report,
                args.guided_timeout,
            )
        )

    for name, cmd, report_path, timeout_s in run_inputs:
        stdout_path = logs_dir / f"{name}_{ts}.stdout.log"
        stderr_path = logs_dir / f"{name}_{ts}.stderr.log"
        if float(args.wait_ready_seconds) > 0.0:
            ready_ok = _wait_for_readiness(
                base_url=args.base_url,
                timeout_s=float(args.wait_ready_seconds),
                ready_streak=int(args.ready_streak),
            )
            if not ready_ok:
                msg = (
                    f"readiness_not_stable before {name}: "
                    f"wait={float(args.wait_ready_seconds):.1f}s streak={int(args.ready_streak)}"
                )
                stdout_path.parent.mkdir(parents=True, exist_ok=True)
                stdout_path.write_text("", encoding="utf-8")
                stderr_path.write_text(msg + "\n", encoding="utf-8")
                runs.append(
                    RunResult(
                        name=name,
                        cmd=cmd,
                        returncode=1,
                        ok=False,
                        elapsed_s=0.0,
                        stdout_log=str(stdout_path),
                        stderr_log=str(stderr_path),
                        report_path=str(report_path),
                    )
                )
                continue
        runs.append(_run_cmd(name, cmd, report_path, stdout_path, stderr_path, timeout_s))

    doctor_payload = _load_json(doctor_report)
    professor_payload = _load_json(professor_report)
    native_payload = _load_json(native_probe_report) if not args.skip_native_probe else {}
    archive_payload = _load_json(archive_probe_report) if not args.skip_archive_probe else {}
    drift_payload = _load_json(drift_check_report) if not args.skip_drift_check else {}
    guided_payload = _load_json(guided_report) if args.run_guided_learning else {}

    doctor_ok, doctor_detail = _doctor_ok(doctor_payload, allowed_failures)
    professor_ok, professor_detail = _professor_ok(professor_payload)
    native_ok = True if args.skip_native_probe else _probe_ok(native_payload)
    archive_ok = True if args.skip_archive_probe else _probe_ok(archive_payload)
    drift_ok = True if args.skip_drift_check else _probe_ok(drift_payload)
    guided_ok = True
    guided_detail: Dict[str, Any] = {"skipped": True}
    if args.run_guided_learning:
        guided_ok, guided_detail = _guided_ok(guided_payload)

    run_map = {item.name: item for item in runs}
    doctor_exec_ok = bool(run_map.get("doctor_clinic") and run_map["doctor_clinic"].ok)
    professor_exec_ok = bool(run_map.get("professor_curriculum") and run_map["professor_curriculum"].ok)
    native_exec_ok = True if args.skip_native_probe else bool(run_map.get("native_memory_probe") and run_map["native_memory_probe"].ok)
    archive_exec_ok = True if args.skip_archive_probe else bool(run_map.get("archive_retrieval_probe") and run_map["archive_retrieval_probe"].ok)
    drift_exec_ok = True if args.skip_drift_check else bool(run_map.get("tool_discovery_drift_check") and run_map["tool_discovery_drift_check"].ok)
    guided_exec_ok = True if not args.run_guided_learning else bool(run_map.get("guided_learning_curriculum") and run_map["guided_learning_curriculum"].ok)

    overall_ok = all([
        doctor_exec_ok,
        professor_exec_ok,
        native_exec_ok,
        archive_exec_ok,
        drift_exec_ok,
        guided_exec_ok,
        doctor_ok,
        professor_ok,
        native_ok,
        archive_ok,
        drift_ok,
        guided_ok,
    ])

    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "base_url": args.base_url,
        "harness_root": str(harness_root),
        "logs_dir": str(logs_dir),
        "overall_ok": overall_ok,
        "allowed_doctor_failures": sorted(allowed_failures),
        "checks": {
            "doctor": {"exec_ok": doctor_exec_ok, "logic_ok": doctor_ok, "detail": doctor_detail},
            "professor": {"exec_ok": professor_exec_ok, "logic_ok": professor_ok, "detail": professor_detail},
            "native_memory_probe": {"exec_ok": native_exec_ok, "logic_ok": native_ok},
            "archive_retrieval_probe": {"exec_ok": archive_exec_ok, "logic_ok": archive_ok},
            "tool_discovery_drift_check": {"exec_ok": drift_exec_ok, "logic_ok": drift_ok},
            "guided_learning_curriculum": {"exec_ok": guided_exec_ok, "logic_ok": guided_ok, "detail": guided_detail},
        },
        "run_artifacts": [
            {
                "name": r.name,
                "ok": r.ok,
                "returncode": r.returncode,
                "elapsed_s": r.elapsed_s,
                "cmd": r.cmd,
                "report_path": r.report_path,
                "stdout_log": r.stdout_log,
                "stderr_log": r.stderr_log,
            }
            for r in runs
        ],
        "reports": {
            "doctor": str(doctor_report),
            "professor": str(professor_report),
            "native_memory_probe": str(native_probe_report) if not args.skip_native_probe else "",
            "archive_retrieval_probe": str(archive_probe_report) if not args.skip_archive_probe else "",
            "tool_discovery_drift_check": str(drift_check_report) if not args.skip_drift_check else "",
            "guided_learning_curriculum": str(guided_report) if args.run_guided_learning else "",
        },
        "memory_record": {},
    }

    manifest_path = logs_dir / f"ci_manifest_{ts}.json"
    if not args.skip_memory_record:
        manifest["memory_record"] = _record_memory_event(
            base_url=args.base_url,
            overall_ok=overall_ok,
            ts_utc=manifest["timestamp_utc"],
            manifest_path=manifest_path,
            checks=manifest["checks"],
        )
    else:
        manifest["memory_record"] = {"attempted": False, "ok": False, "skipped": True}

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(f"CI manifest: {manifest_path}")
    print(f"Overall: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
