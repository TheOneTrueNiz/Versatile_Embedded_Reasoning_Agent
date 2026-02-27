#!/usr/bin/env python3
"""Run Vera tool exam campaign (tier1 + tier2 + side-effect verification).

This wrapper orchestrates existing scripts and writes one manifest for overnight runs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


@dataclass
class StepResult:
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


def _run_step(
    *,
    name: str,
    cmd: List[str],
    cwd: Path,
    logs_dir: Path,
    report_path: Path,
    timeout_s: float,
) -> StepResult:
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / f"{name}.stdout.log"
    stderr_path = logs_dir / f"{name}.stderr.log"
    started = time.time()

    rc = 124
    ok = False
    out_text = ""
    err_text = ""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
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

    stdout_path.write_text(out_text, encoding="utf-8")
    stderr_path.write_text(err_text, encoding="utf-8")
    elapsed = time.time() - started
    return StepResult(
        name=name,
        cmd=list(cmd),
        returncode=rc,
        ok=ok,
        elapsed_s=elapsed,
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
        report_path=str(report_path),
    )


def _extract_sweep_failures(report_path: Path) -> int:
    if not report_path.exists():
        return 1
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return 1
    try:
        return int(payload.get("failures") or 0)
    except Exception:
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vera tool exam campaign")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--logs-dir", default="")
    parser.add_argument("--timeout-battery", type=float, default=14400.0)
    parser.add_argument("--timeout-sweep", type=float, default=2400.0)
    parser.add_argument("--timeout-verify", type=float, default=1200.0)
    parser.add_argument("--timeout-native-push", type=float, default=900.0)
    parser.add_argument("--tier1-scope", choices=("all", "server", "native"), default="server")
    parser.add_argument("--max-tools", type=int, default=0)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--chat-timeout", type=float, default=40.0)
    parser.add_argument("--wait-ready-seconds", type=float, default=60.0)
    parser.add_argument("--ready-streak", type=int, default=3)
    parser.add_argument("--skip-call-me", action="store_true")
    parser.add_argument("--run-native-push-hardening", action="store_true")
    parser.add_argument("--native-push-no-live-send", action="store_true")
    parser.add_argument(
        "--run-id",
        default="",
        help="Optional stable run id passed through to vera_tool_exam_battery.py.",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = _utc_ts()
    run_id = str(args.run_id or "").strip() or f"tool-exam-{ts}"
    logs_dir = Path(args.logs_dir) if args.logs_dir else (root / "tmp" / "tool_exam_campaign" / ts)
    logs_dir.mkdir(parents=True, exist_ok=True)

    venv_python = root / ".venv" / "bin" / "python"
    py_bin = str(venv_python if venv_python.exists() else Path(sys.executable).resolve())

    battery_report = logs_dir / f"tool_exam_battery_{ts}.json"
    sweep_report = logs_dir / f"prompt_tool_sweep_{ts}.json"
    verify_report = logs_dir / f"tool_verification_{ts}.json"
    native_push_report = logs_dir / f"native_push_hardening_{ts}.json"

    steps: List[StepResult] = []

    battery_cmd = [
        py_bin,
        "scripts/vera_tool_exam_battery.py",
        "--base-url",
        args.base_url,
        "--tier1",
        "--tier2",
        "--tier1-scope",
        str(args.tier1_scope),
        "--retries",
        str(max(0, int(args.retries))),
        "--timeout",
        str(max(1.0, float(args.chat_timeout))),
        "--wait-ready-seconds",
        str(max(0.0, float(args.wait_ready_seconds))),
        "--ready-streak",
        str(max(1, int(args.ready_streak))),
        "--max-tier1-failures",
        "999999",
        "--max-tier2-failures",
        "999999",
        "--run-id",
        str(run_id),
        "--output",
        str(battery_report),
    ]
    if int(args.max_tools) > 0:
        battery_cmd.extend(["--max-tools", str(int(args.max_tools))])

    steps.append(
        _run_step(
            name="tool_exam_battery",
            cmd=battery_cmd,
            cwd=root,
            logs_dir=logs_dir,
            report_path=battery_report,
            timeout_s=float(args.timeout_battery),
        )
    )

    sweep_cmd = [
        py_bin,
        "scripts/vera_prompt_tool_sweep.py",
        "--host",
        args.host,
        "--port",
        str(int(args.port)),
        "--output",
        str(sweep_report),
    ]
    if bool(args.skip_call_me):
        sweep_cmd.append("--skip-call-me")

    sweep_step = _run_step(
        name="prompt_tool_sweep",
        cmd=sweep_cmd,
        cwd=root,
        logs_dir=logs_dir,
        report_path=sweep_report,
        timeout_s=float(args.timeout_sweep),
    )
    # Treat non-critical sweep failures as a failed step if report exists with failures>0.
    if sweep_step.ok and _extract_sweep_failures(sweep_report) > 0:
        sweep_step.ok = False
        sweep_step.returncode = 3
    steps.append(sweep_step)

    verify_cmd = [
        py_bin,
        "scripts/vera_tool_verification.py",
        "--host",
        args.host,
        "--port",
        str(int(args.port)),
        "--wait",
        "30",
    ]
    verify_step = _run_step(
        name="tool_verification",
        cmd=verify_cmd,
        cwd=root,
        logs_dir=logs_dir,
        report_path=verify_report,
        timeout_s=float(args.timeout_verify),
    )
    if not verify_report.exists():
        verify_report.write_text(
            json.dumps(
                {
                    "note": "vera_tool_verification writes stdout only; see step logs",
                    "stdout_log": verify_step.stdout_log,
                    "stderr_log": verify_step.stderr_log,
                },
                ensure_ascii=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    steps.append(verify_step)

    if bool(args.run_native_push_hardening):
        native_cmd = [
            py_bin,
            "scripts/native_push_hardening.py",
            "--base-url",
            args.base_url,
            "--output",
            str(native_push_report),
        ]
        if bool(args.native_push_no_live_send):
            native_cmd.append("--no-live-send")
        steps.append(
            _run_step(
                name="native_push_hardening",
                cmd=native_cmd,
                cwd=root,
                logs_dir=logs_dir,
                report_path=native_push_report,
                timeout_s=float(args.timeout_native_push),
            )
        )

    overall_ok = bool(steps) and all(step.ok for step in steps)

    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo_root": str(root),
        "run_id": run_id,
        "logs_dir": str(logs_dir),
        "overall_ok": overall_ok,
        "python": py_bin,
        "steps": [asdict(step) for step in steps],
    }

    manifest_path = Path(args.output) if args.output else (logs_dir / f"tool_exam_campaign_manifest_{ts}.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    print(f"Campaign manifest: {manifest_path}")
    for step in steps:
        state = "PASS" if step.ok else "FAIL"
        print(f"[{state}] {step.name} rc={step.returncode} elapsed={step.elapsed_s:.1f}s")
    print(f"Overall: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
