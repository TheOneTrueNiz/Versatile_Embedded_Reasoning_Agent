#!/usr/bin/env python3
"""
VERA system-level audit gate (non-MCP focused).

Validates runtime systems outside per-tool MCP matrices:
- API/readiness/runtime health
- inner life reflections + journal persistence
- self-improvement/architect plumbing
- quorum/memory/editor/voice/push/channel surfaces
- critical workflow scripts
- targeted non-MCP test suite (optional)
- recent log anomaly scan
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx


@dataclass
class CheckResult:
    name: str
    ok: bool
    critical: bool
    detail: str


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs: Any,
) -> Tuple[bool, Any, str]:
    try:
        response = client.request(method, url, **kwargs)
    except Exception as exc:
        return False, None, f"request failed: {exc}"

    if response.status_code >= 400:
        detail = response.text.strip()
        return False, None, f"HTTP {response.status_code}: {detail or 'request failed'}"

    try:
        return True, response.json(), ""
    except Exception:
        return False, None, "response was not valid JSON"


def _run_cmd(
    cmd: List[str],
    timeout: float,
    cwd: Path,
) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout),
            cwd=str(cwd),
            check=False,
        )
    except Exception as exc:
        return False, f"failed to execute: {exc}"

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    preview = stdout or stderr or "<no output>"
    preview = preview.replace("\n", " ")[:260]
    if proc.returncode == 0:
        return True, preview
    return False, f"rc={proc.returncode}; {preview}"


def _print_check(result: CheckResult) -> None:
    status = "OK" if result.ok else ("FAIL" if result.critical else "WARN")
    level = "critical" if result.critical else "non-critical"
    print(f"[{status}] {result.name} ({level}) - {result.detail}", flush=True)


def _tail_lines(path: Path, max_lines: int) -> List[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    if max_lines <= 0:
        return lines
    return lines[-max_lines:]


def _parse_log_timestamp(line: str) -> datetime | None:
    if len(line) < 19:
        return None
    try:
        return datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _as_dict(data: Any) -> Dict[str, Any]:
    return data if isinstance(data, dict) else {}


def _add(
    checks: List[CheckResult],
    name: str,
    ok: bool,
    critical: bool,
    detail: str,
) -> None:
    result = CheckResult(name=name, ok=ok, critical=critical, detail=detail)
    checks.append(result)
    _print_check(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="VERA system-level audit gate")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--http-timeout", type=float, default=20.0)
    parser.add_argument("--min-running-mcp", type=int, default=20)
    parser.add_argument("--mcp-wait-seconds", type=float, default=120.0)
    parser.add_argument("--min-native-devices", type=int, default=1)
    parser.add_argument("--trigger-reflect", action="store_true", help="Trigger manual inner-life reflection and verify journal increments")
    parser.add_argument("--reflect-wait-seconds", type=float, default=120.0)
    parser.add_argument("--with-tests", action="store_true", help="Run targeted non-MCP pytest suite")
    parser.add_argument("--pytest-timeout", type=float, default=900.0)
    parser.add_argument("--log-tail-lines", type=int, default=4000)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(args.output) if args.output else (root / "tmp" / f"system_audit_{ts}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base_url = f"http://{args.host}:{args.port}"
    audit_started_local = datetime.now()

    checks: List[CheckResult] = []
    details: Dict[str, Any] = {}

    with httpx.Client(timeout=args.http_timeout) as client:
        ok, health, err = _request_json(client, "GET", f"{base_url}/api/health")
        health_obj = _as_dict(health)
        details["health"] = health_obj
        _add(checks, "api_health", ok and health_obj.get("ok") is True, True, err or f"ok={health_obj.get('ok')}")

        ok, readiness, err = _request_json(client, "GET", f"{base_url}/api/readiness")
        readiness_obj = _as_dict(readiness)
        details["readiness"] = readiness_obj
        ready = readiness_obj.get("ready") is True
        pending = readiness_obj.get("pending_servers") or []
        _add(
            checks,
            "readiness",
            ok and ready,
            True,
            err or f"ready={ready}; pending={pending or 'none'}",
        )

        ok, tools_payload, err = _request_json(client, "GET", f"{base_url}/api/tools")
        tools_obj = _as_dict(tools_payload)
        mcp = _as_dict(tools_obj.get("mcp"))
        running = int(mcp.get("total_running") or 0)
        total = int(mcp.get("total_configured") or 0)
        waited = 0.0
        mcp_deadline = time.time() + max(0.0, float(args.mcp_wait_seconds))
        while ok and running < max(0, int(args.min_running_mcp)) and time.time() < mcp_deadline:
            time.sleep(2.0)
            waited += 2.0
            ok2, tools_payload2, _ = _request_json(client, "GET", f"{base_url}/api/tools")
            if not ok2:
                continue
            tools_obj = _as_dict(tools_payload2)
            mcp = _as_dict(tools_obj.get("mcp"))
            running = int(mcp.get("total_running") or 0)
            total = int(mcp.get("total_configured") or 0)
        details["tools"] = {"running": running, "configured": total}
        _add(
            checks,
            "mcp_runtime_count",
            ok and running >= max(0, int(args.min_running_mcp)),
            True,
            err
            or (
                f"running={running}, configured={total}, required>={args.min_running_mcp}, "
                f"waited_s={int(waited)}"
            ),
        )

        ok, models_payload, err = _request_json(client, "GET", f"{base_url}/v1/models")
        models_obj = _as_dict(models_payload)
        models = models_obj.get("data") if isinstance(models_obj.get("data"), list) else []
        model_ids = [str(item.get("id")) for item in models if isinstance(item, dict)]
        details["models"] = model_ids
        _add(
            checks,
            "models_endpoint",
            ok and len(model_ids) > 0,
            True,
            err or f"models={model_ids or 'none'}",
        )

        ok, memory_payload, err = _request_json(client, "GET", f"{base_url}/api/memory/stats")
        memory_obj = _as_dict(memory_payload)
        details["memory_stats"] = memory_obj
        has_stats = isinstance(memory_obj.get("stats"), dict)
        _add(checks, "memory_stats", ok and has_stats, True, err or f"stats_present={has_stats}")

        ok, quorum_status_payload, err = _request_json(client, "GET", f"{base_url}/api/quorum/status")
        quorum_status_obj = _as_dict(quorum_status_payload)
        details["quorum_status"] = quorum_status_obj
        state = _as_dict(quorum_status_obj.get("state"))
        _add(
            checks,
            "quorum_status",
            ok and bool(state),
            True,
            err or f"state={state.get('status', 'unknown')}",
        )

        ok, quorum_list_payload, err = _request_json(client, "GET", f"{base_url}/api/quorum/list")
        quorum_list_obj = _as_dict(quorum_list_payload)
        quorums = quorum_list_obj.get("quorums") if isinstance(quorum_list_obj.get("quorums"), list) else []
        details["quorum_count"] = len(quorums)
        _add(
            checks,
            "quorum_catalog",
            ok and len(quorums) > 0,
            True,
            err or f"quorums={len(quorums)}",
        )

        ok, inner_payload, err = _request_json(client, "GET", f"{base_url}/api/innerlife/status")
        inner_obj = _as_dict(inner_payload)
        inner_stats = _as_dict(inner_obj.get("stats"))
        details["innerlife_before"] = inner_stats
        enabled = bool(inner_stats.get("enabled"))
        journal_entries = int(inner_stats.get("journal_entries") or 0)
        last_reflection = str(inner_stats.get("last_reflection") or "").strip()
        last_reflection_ok = not (journal_entries > 0 and (not last_reflection or last_reflection == "never"))
        _add(
            checks,
            "innerlife_status",
            ok and enabled and last_reflection_ok,
            True,
            err or (
                f"enabled={enabled}; journal_entries={journal_entries}; "
                f"last_reflection={last_reflection or 'missing'}"
            ),
        )

        if args.trigger_reflect:
            ok, reflect_payload, err = _request_json(
                client,
                "POST",
                f"{base_url}/api/innerlife/reflect",
                json={"wait": True, "timeout_seconds": float(args.reflect_wait_seconds)},
                timeout=max(args.http_timeout, float(args.reflect_wait_seconds) + 15.0),
            )
            reflect_obj = _as_dict(reflect_payload)
            scheduled = bool(reflect_obj.get("scheduled"))
            completed = bool(reflect_obj.get("completed"))
            reflect_result = _as_dict(reflect_obj.get("result"))
            if ok and completed and reflect_result.get("outcome") == "skipped_already_running":
                time.sleep(2.0)
                ok_retry, reflect_payload_retry, _ = _request_json(
                    client,
                    "POST",
                    f"{base_url}/api/innerlife/reflect",
                    json={"wait": True, "timeout_seconds": float(args.reflect_wait_seconds)},
                    timeout=max(args.http_timeout, float(args.reflect_wait_seconds) + 15.0),
                )
                if ok_retry:
                    reflect_obj = _as_dict(reflect_payload_retry)
                    scheduled = bool(reflect_obj.get("scheduled"))
                    completed = bool(reflect_obj.get("completed"))
                    reflect_result = _as_dict(reflect_obj.get("result"))
            _add(
                checks,
                "innerlife_reflect_trigger",
                ok and scheduled and completed,
                True,
                err or f"scheduled={scheduled}; completed={completed}",
            )
            target_entries = journal_entries + 1
            updated = False
            latest_stats = inner_stats
            ok2, inner2, err2 = _request_json(client, "GET", f"{base_url}/api/innerlife/status")
            if ok2:
                stats2 = _as_dict(_as_dict(inner2).get("stats"))
                latest_stats = stats2
                if int(stats2.get("journal_entries") or 0) >= target_entries:
                    updated = True
            else:
                details["innerlife_after_error"] = err2
            details["innerlife_after"] = latest_stats
            _add(
                checks,
                "innerlife_reflect_persistence",
                updated,
                True,
                (
                    f"journal_entries_before={journal_entries}, "
                    f"after={int(latest_stats.get('journal_entries') or 0)}, "
                    f"wait_s={int(args.reflect_wait_seconds)}; "
                    f"completed={completed}"
                ),
            )

        ok, si_status_payload, err = _request_json(client, "GET", f"{base_url}/api/self_improvement/status")
        si_status = _as_dict(si_status_payload)
        details["self_improvement_status"] = si_status
        si_last_error = str(si_status.get("last_error") or "").strip()
        _add(
            checks,
            "self_improvement_status",
            ok and si_last_error == "",
            True,
            err or f"running={si_status.get('running')}; action={si_status.get('action') or 'n/a'}; last_error={si_last_error or 'none'}",
        )

        ok, si_logs_payload, err = _request_json(client, "GET", f"{base_url}/api/self_improvement/logs", params={"lines": 80})
        si_logs = _as_dict(si_logs_payload)
        log_text = str(si_logs.get("log") or "")
        details["self_improvement_logs_tail"] = log_text[-2000:]
        _add(
            checks,
            "self_improvement_logs",
            ok and len(log_text) > 0,
            False,
            err or f"log_chars={len(log_text)}",
        )

        ok, si_budget_payload, err = _request_json(client, "GET", f"{base_url}/api/self_improvement/budget")
        si_budget = _as_dict(si_budget_payload)
        details["self_improvement_budget"] = si_budget
        budget_ok = bool(_as_dict(si_budget.get("config")))
        _add(
            checks,
            "self_improvement_budget",
            ok and budget_ok,
            True,
            err or f"config_present={budget_ok}",
        )

        ok, si_sim_payload, err = _request_json(
            client,
            "POST",
            f"{base_url}/api/self_improvement/simulate",
            json={"patch": []},
        )
        si_sim = _as_dict(si_sim_payload)
        details["self_improvement_simulate"] = si_sim
        _add(
            checks,
            "self_improvement_simulate",
            ok and bool(si_sim.get("valid", False)),
            True,
            err or f"valid={si_sim.get('valid')}; errors={si_sim.get('errors') or []}",
        )

        ok, push_native_payload, err = _request_json(client, "GET", f"{base_url}/api/push/native/status")
        push_native = _as_dict(push_native_payload)
        details["push_native_status"] = push_native
        configured = bool(push_native.get("configured"))
        device_count = int(push_native.get("device_count") or 0)
        _add(
            checks,
            "native_push_status",
            ok and configured and device_count >= max(0, int(args.min_native_devices)),
            True,
            err or f"configured={configured}; devices={device_count}; required>={args.min_native_devices}",
        )

        ok, voice_payload, err = _request_json(client, "GET", f"{base_url}/api/voice/status")
        voice_obj = _as_dict(voice_payload)
        details["voice_status"] = voice_obj
        voice_enabled = bool(voice_obj.get("enabled"))
        api_key_present = bool(voice_obj.get("api_key_present"))
        _add(
            checks,
            "voice_status",
            ok and voice_enabled and api_key_present,
            False,
            err or f"enabled={voice_enabled}; api_key_present={api_key_present}; backend={voice_obj.get('backend')}",
        )

        ok, channels_payload, err = _request_json(client, "GET", f"{base_url}/api/channels/status")
        channels_obj = _as_dict(channels_payload)
        active_channels = channels_obj.get("active") if isinstance(channels_obj.get("active"), list) else []
        details["channels_status"] = {"active_count": len(active_channels)}
        _add(
            checks,
            "channels_status",
            ok and len(active_channels) >= 1,
            False,
            err or f"active_channels={len(active_channels)}",
        )

        ok, git_payload, err = _request_json(client, "GET", f"{base_url}/api/git/status")
        git_obj = _as_dict(git_payload)
        details["git_status"] = git_obj
        _add(
            checks,
            "git_status_endpoint",
            ok and isinstance(git_obj.get("is_repo"), bool),
            False,
            err or f"is_repo={git_obj.get('is_repo')}",
        )

    canvas_ok, canvas_detail = _run_cmd(
        [
            sys.executable,
            str(root / "scripts" / "run_canvas_workflow_check.py"),
            "--base-url",
            base_url,
            "--workspace",
            str(root),
        ],
        timeout=120.0,
        cwd=root,
    )
    _add(checks, "canvas_workflow_check", canvas_ok, True, canvas_detail)

    architect_help_ok, architect_help_detail = _run_cmd(
        [sys.executable, str(root / "scripts" / "vera_architect.py"), "--help"],
        timeout=30.0,
        cwd=root,
    )
    _add(checks, "architect_script_help", architect_help_ok, False, architect_help_detail)

    if args.with_tests:
        test_targets = [
            "src/tests/test_inner_life_engine.py",
            "src/tests/test_flight_recorder.py",
            "src/tests/test_genome_config.py",
            "src/tests/test_genome_patch.py",
            "src/tests/test_internal_critic.py",
            "src/tests/test_llm_bridge.py",
        ]
        pytest_ok, pytest_detail = _run_cmd(
            [str(root / ".venv" / "bin" / "pytest"), "-q", *test_targets],
            timeout=args.pytest_timeout,
            cwd=root,
        )
        _add(checks, "non_mcp_pytests", pytest_ok, True, pytest_detail)

    log_path = root / "logs" / "vera_debug.log"
    log_tail = _tail_lines(log_path, int(args.log_tail_lines))
    scan_floor = audit_started_local - timedelta(seconds=2)
    scoped_lines: List[str] = []
    for line in log_tail:
        ts = _parse_log_timestamp(line)
        if ts is None or ts >= scan_floor:
            scoped_lines.append(line)
    benign_warning_tokens = (
        "No API key - MoA executor requires XAI_API_KEY",
        "Tool call blocked:",
    )
    error_lines: List[str] = []
    warning_lines: List[str] = []
    for line in scoped_lines:
        upper = line.upper()
        if "ERROR" in upper or "TRACEBACK" in upper:
            error_lines.append(line)
        elif "WARNING" in upper:
            warning_lines.append(line)

    unknown_warnings = [
        line for line in warning_lines
        if not any(token in line for token in benign_warning_tokens)
    ]
    _add(
        checks,
        "log_error_scan",
        len(error_lines) == 0,
        True,
        f"errors={len(error_lines)} since audit start (scanned_lines={len(scoped_lines)})",
    )
    _add(
        checks,
        "log_warning_scan",
        len(unknown_warnings) == 0,
        False,
        (
            f"warnings={len(warning_lines)} "
            f"(unknown={len(unknown_warnings)}, known_benign={len(warning_lines)-len(unknown_warnings)})"
        ),
    )

    details["log_scan"] = {
        "log_path": str(log_path),
        "tail_lines_loaded": len(log_tail),
        "lines_scanned": len(scoped_lines),
        "error_count": len(error_lines),
        "warning_count": len(warning_lines),
        "unknown_warning_count": len(unknown_warnings),
        "errors_sample": error_lines[:20],
        "unknown_warnings_sample": unknown_warnings[:20],
    }

    critical_failures = sum(1 for item in checks if item.critical and not item.ok)
    warnings = sum(1 for item in checks if (not item.critical) and (not item.ok))
    report: Dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "ok": critical_failures == 0,
        "critical_failures": critical_failures,
        "warnings": warnings,
        "results": [item.__dict__ for item in checks],
        "details": details,
    }
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {output_path}")
    print(f"Critical failures: {critical_failures}")
    print(f"Warnings: {warnings}")
    return 1 if critical_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
