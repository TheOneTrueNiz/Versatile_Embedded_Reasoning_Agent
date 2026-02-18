#!/usr/bin/env python3
"""
Run unattended Vera soak checks with periodic production-gate validation.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: List[str], timeout: float) -> Dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1.0, timeout),
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
            "elapsed_s": round(time.time() - started, 3),
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": -9,
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "").strip() if isinstance(exc.stderr, str) else "",
            "elapsed_s": round(time.time() - started, 3),
            "cmd": cmd,
            "timeout": True,
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "elapsed_s": round(time.time() - started, 3),
            "cmd": cmd,
        }


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _preview(text: str, limit: int = 220) -> str:
    if not text:
        return ""
    single = text.replace("\n", " ").strip()
    return single[:limit]


def _build_checklist_cmd(python_bin: str, root: Path, host: str, port: int, out: Path) -> List[str]:
    return [
        python_bin,
        str(root / "scripts" / "vera_production_checklist.py"),
        "--host",
        host,
        "--port",
        str(port),
        "--min-running-mcp",
        "8",
        "--output",
        str(out),
    ]


def _build_regression_cmd(
    python_bin: str,
    root: Path,
    base_url: str,
    out: Path,
    limit: int,
    max_seconds: float,
    wait: float,
) -> List[str]:
    return [
        python_bin,
        str(root / "scripts" / "vera_regression_runner.py"),
        "--base-url",
        base_url,
        "--limit",
        str(max(0, limit)),
        "--max-seconds",
        str(max(0.0, max_seconds)),
        "--wait",
        str(max(0.0, wait)),
        "--output",
        str(out),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vera soak checks")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--duration-hours", type=float, default=12.0)
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--check-timeout", type=float, default=360.0)
    parser.add_argument("--run-regression", action="store_true")
    parser.add_argument("--regression-limit", type=int, default=4)
    parser.add_argument("--regression-max-seconds", type=float, default=180.0)
    parser.add_argument("--regression-wait", type=float, default=30.0)
    parser.add_argument("--failure-threshold", type=int, default=3)
    parser.add_argument("--auto-recover", action="store_true")
    parser.add_argument("--recover-command", default="sudo systemctl restart vera2.service")
    parser.add_argument(
        "--warmup-min-running-mcp",
        type=int,
        default=20,
        help="Treat call-me-only failures as warmup while tools_list_servers_count is below this value",
    )
    parser.add_argument(
        "--recovery-cooldown-seconds",
        type=int,
        default=180,
        help="Grace period after successful recovery where failures do not increment counters",
    )
    parser.add_argument("--output", default="")
    parser.add_argument("--summary-output", default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = _utc_ts()
    output = Path(args.output) if args.output else (root / "tmp" / "soak" / f"vera_soak_{ts}.jsonl")
    summary = Path(args.summary_output) if args.summary_output else (root / "tmp" / "soak" / f"vera_soak_summary_{ts}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    summary.parent.mkdir(parents=True, exist_ok=True)

    python_bin = str(root / ".venv" / "bin" / "python")
    if not Path(python_bin).exists():
        python_bin = "python3"

    start = time.time()
    deadline = start + max(0.05, args.duration_hours) * 3600.0
    consecutive_failures = 0
    cycles = 0
    passes = 0
    failures = 0
    recoveries = 0
    recovery_grace_until = 0.0

    print(
        f"Starting soak: duration={args.duration_hours:.2f}h interval={args.interval_seconds}s "
        f"regression={'on' if args.run_regression else 'off'} output={output}",
        flush=True,
    )

    while time.time() < deadline:
        cycles += 1
        cycle_started = time.time()
        cycle_ts = _utc_ts()
        checklist_out = root / "tmp" / "soak" / f"checklist_{cycle_ts}.json"
        checklist_cmd = _build_checklist_cmd(python_bin, root, args.host, args.port, checklist_out)
        checklist_run = _run(checklist_cmd, timeout=args.check_timeout)
        checklist_payload = _load_json(checklist_out) if checklist_out.exists() else {}

        if checklist_payload:
            if "overall_ok" in checklist_payload:
                checklist_ok = bool(checklist_payload.get("overall_ok"))
            else:
                checklist_ok = bool(checklist_payload.get("ok"))
        else:
            checklist_ok = bool(checklist_run.get("ok"))
        critical_failures = int(checklist_payload.get("critical_failures") or 0) if checklist_payload else None
        checklist_tools_servers_count = int(checklist_payload.get("tools_list_servers_count") or 0) if checklist_payload else 0
        failed_critical_names: List[str] = []
        if checklist_payload and isinstance(checklist_payload.get("results"), list):
            for item in checklist_payload.get("results", []):
                if not isinstance(item, dict):
                    continue
                if item.get("critical") and not item.get("ok"):
                    failed_critical_names.append(str(item.get("name") or ""))

        reg_run: Optional[Dict[str, Any]] = None
        reg_ok: Optional[bool] = None
        reg_out: Optional[Path] = None
        if args.run_regression:
            reg_out = root / "tmp" / "soak" / f"regression_{cycle_ts}.jsonl"
            reg_cmd = _build_regression_cmd(
                python_bin,
                root,
                args.base_url,
                reg_out,
                args.regression_limit,
                args.regression_max_seconds,
                args.regression_wait,
            )
            reg_run = _run(reg_cmd, timeout=max(args.regression_max_seconds + 120.0, args.check_timeout))
            reg_ok = bool(reg_run.get("ok"))

        cycle_ok = checklist_ok and (reg_ok is not False)
        warmup_exempt = False
        warmup_allowed_failures = {"mcp_server:call-me", "call_me_tools"}
        if not cycle_ok and failed_critical_names:
            if (
                set(failed_critical_names).issubset(warmup_allowed_failures)
                and checklist_tools_servers_count <= max(1, args.warmup_min_running_mcp)
            ):
                warmup_exempt = True
                cycle_ok = True

        in_recovery_grace = time.time() < recovery_grace_until
        count_failure = (not cycle_ok) and (not in_recovery_grace)
        if cycle_ok:
            passes += 1
            consecutive_failures = 0
        else:
            failures += 1
            if count_failure:
                consecutive_failures += 1

        recovery: Dict[str, Any] = {"attempted": False, "ok": False}
        if (
            not cycle_ok
            and args.auto_recover
            and consecutive_failures >= max(1, args.failure_threshold)
        ):
            recovery["attempted"] = True
            recovery["command"] = args.recover_command
            recovery_run = _run(["bash", "-lc", args.recover_command], timeout=180.0)
            recovery["ok"] = bool(recovery_run.get("ok"))
            recovery["returncode"] = recovery_run.get("returncode")
            recovery["stdout_preview"] = _preview(str(recovery_run.get("stdout", "")))
            recovery["stderr_preview"] = _preview(str(recovery_run.get("stderr", "")))
            if recovery["ok"]:
                recoveries += 1
                consecutive_failures = 0
                recovery_grace_until = time.time() + max(0, args.recovery_cooldown_seconds)

        row = {
            "cycle": cycles,
            "started_at_utc": _utc_iso(),
            "checklist_output": str(checklist_out),
            "checklist_ok": checklist_ok,
            "checklist_critical_failures": critical_failures,
            "checklist_returncode": checklist_run.get("returncode"),
            "checklist_stdout_preview": _preview(str(checklist_run.get("stdout", ""))),
            "checklist_stderr_preview": _preview(str(checklist_run.get("stderr", ""))),
            "regression_output": str(reg_out) if reg_out else "",
            "regression_ok": reg_ok,
            "regression_returncode": reg_run.get("returncode") if reg_run else None,
            "regression_stdout_preview": _preview(str(reg_run.get("stdout", ""))) if reg_run else "",
            "failed_critical_names": failed_critical_names,
            "warmup_exempt": warmup_exempt,
            "in_recovery_grace": in_recovery_grace,
            "count_failure": count_failure,
            "recovery": recovery,
            "cycle_ok": cycle_ok,
            "consecutive_failures": consecutive_failures,
            "elapsed_s": round(time.time() - cycle_started, 3),
        }
        _append_jsonl(output, row)

        print(
            f"[cycle {cycles}] ok={cycle_ok} checklist_ok={checklist_ok} "
            f"reg_ok={reg_ok if args.run_regression else 'n/a'} "
            f"consecutive_failures={consecutive_failures} warmup_exempt={warmup_exempt} "
            f"recovery_grace={in_recovery_grace}",
            flush=True,
        )

        if time.time() >= deadline:
            break
        sleep_for = max(0, args.interval_seconds - int(time.time() - cycle_started))
        if sleep_for > 0:
            time.sleep(sleep_for)

    final = {
        "started_at_utc": datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at_utc": _utc_iso(),
        "duration_hours": round((time.time() - start) / 3600.0, 3),
        "cycles": cycles,
        "passes": passes,
        "failures": failures,
        "recoveries": recoveries,
        "auto_recover": bool(args.auto_recover),
        "failure_threshold": args.failure_threshold,
        "log_jsonl": str(output),
    }
    summary.write_text(json.dumps(final, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Soak complete: cycles={cycles} passes={passes} failures={failures} summary={summary}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
