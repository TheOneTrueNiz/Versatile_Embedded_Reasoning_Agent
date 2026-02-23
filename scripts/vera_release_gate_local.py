#!/usr/bin/env python3
"""Local release gate runner for Vera production pushes.

Runs a small, deterministic check set and writes a single PASS/FAIL manifest
with per-check stdout/stderr logs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence


@dataclass
class CheckResult:
    name: str
    cmd: List[str]
    returncode: int
    ok: bool
    elapsed_s: float
    stdout_log: str
    stderr_log: str


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_check(
    *,
    name: str,
    cmd: Sequence[str],
    cwd: Path,
    logs_dir: Path,
    timeout_s: float,
    env_overrides: Dict[str, str] | None = None,
) -> CheckResult:
    stdout_path = logs_dir / f"{name}.stdout.log"
    stderr_path = logs_dir / f"{name}.stderr.log"
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    started = time.time()
    rc = 124
    out_text = ""
    err_text = ""
    ok = False
    try:
        proc = subprocess.run(
            list(cmd),
            cwd=str(cwd),
            env=env,
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
    return CheckResult(
        name=name,
        cmd=list(cmd),
        returncode=rc,
        ok=ok,
        elapsed_s=elapsed,
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vera local release gate checks")
    parser.add_argument("--logs-dir", default="", help="Default: tmp/release_gate/<timestamp>")
    parser.add_argument("--base-url", default=os.getenv("VERA_API_BASE", "http://127.0.0.1:8788"))
    parser.add_argument("--run-regression", action="store_true")
    parser.add_argument("--regression-limit", type=int, default=3)
    parser.add_argument("--regression-wait", type=float, default=10.0)
    parser.add_argument("--regression-max-seconds", type=float, default=120.0)

    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--skip-api-help", action="store_true")
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--skip-monolithic-help", action="store_true")

    parser.add_argument("--pytest-timeout", type=float, default=600.0)
    parser.add_argument("--help-timeout", type=float, default=120.0)
    parser.add_argument("--bootstrap-timeout", type=float, default=600.0)
    parser.add_argument("--regression-timeout", type=float, default=600.0)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = _utc_ts()
    logs_dir = Path(args.logs_dir).resolve() if args.logs_dir else (root / "tmp" / "release_gate" / ts)
    logs_dir.mkdir(parents=True, exist_ok=True)

    venv_python = root / ".venv" / "bin" / "python"
    py_bin = str(venv_python if venv_python.exists() else Path(sys.executable).resolve())
    monolithic_python = os.getenv("PYTHON", "python3")

    pytest_targets: List[str] = []
    for candidate in [
        root / "src" / "tests" / "test_llm_bridge_workflow_guards.py",
        root / "src" / "tests" / "test_proactive_manager_initiative_gates.py",
    ]:
        if candidate.exists():
            pytest_targets.append(str(candidate.relative_to(root)))

    checks: List[CheckResult] = []

    if not args.skip_pytest and pytest_targets:
        checks.append(
            _run_check(
                name="pytest_core_guards",
                cmd=[py_bin, "-m", "pytest", "-q", *pytest_targets],
                cwd=root,
                logs_dir=logs_dir,
                timeout_s=args.pytest_timeout,
                env_overrides={"PYTHONPATH": "src"},
            )
        )

    if not args.skip_api_help:
        checks.append(
            _run_check(
                name="run_vera_api_help",
                cmd=[py_bin, "run_vera_api.py", "--help"],
                cwd=root,
                logs_dir=logs_dir,
                timeout_s=args.help_timeout,
            )
        )

    if not args.skip_bootstrap:
        checks.append(
            _run_check(
                name="run_vera_bootstrap_no_run",
                cmd=["./scripts/run_vera.sh"],
                cwd=root,
                logs_dir=logs_dir,
                timeout_s=args.bootstrap_timeout,
                env_overrides={"VERA_NO_RUN": "1"},
            )
        )

    if not args.skip_monolithic_help:
        checks.append(
            _run_check(
                name="run_vera_monolithic_help",
                cmd=[monolithic_python, "run_vera_monolithic.py", "--help"],
                cwd=root,
                logs_dir=logs_dir,
                timeout_s=args.help_timeout,
            )
        )

    if args.run_regression:
        regression_output = logs_dir / f"regression_results_{ts}.jsonl"
        checks.append(
            _run_check(
                name="regression_runner",
                cmd=[
                    py_bin,
                    "scripts/vera_regression_runner.py",
                    "--base-url",
                    args.base_url,
                    "--limit",
                    str(max(0, int(args.regression_limit))),
                    "--wait",
                    str(max(0.0, float(args.regression_wait))),
                    "--max-seconds",
                    str(max(0.0, float(args.regression_max_seconds))),
                    "--output",
                    str(regression_output),
                ],
                cwd=root,
                logs_dir=logs_dir,
                timeout_s=args.regression_timeout,
            )
        )

    overall_ok = bool(checks) and all(item.ok for item in checks)

    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo_root": str(root),
        "logs_dir": str(logs_dir),
        "overall_ok": overall_ok,
        "python": {
            "selected": py_bin,
            "venv_exists": venv_python.exists(),
            "sys_executable": sys.executable,
        },
        "checks": [asdict(item) for item in checks],
    }

    manifest_path = logs_dir / f"release_gate_manifest_{ts}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(f"Release gate manifest: {manifest_path}")
    for item in checks:
        state = "PASS" if item.ok else "FAIL"
        print(f"[{state}] {item.name} rc={item.returncode} elapsed={item.elapsed_s:.1f}s")
    print(f"Overall: {'PASS' if overall_ok else 'FAIL'}")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
