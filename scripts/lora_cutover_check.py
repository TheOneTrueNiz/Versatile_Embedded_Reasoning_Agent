#!/usr/bin/env python3
"""
LoRA production cutover gate.

Runs the two operational checks in sequence and emits a single pass/fail report:
1) scripts/lora_readiness_check.py
2) scripts/lora_force_cycle.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple


def _safe_json_parse(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _run_command(cmd: List[str], timeout_seconds: float) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_seconds)),
            check=False,
        )
    except Exception as exc:
        return {
            "invoke_ok": False,
            "exit_code": 2,
            "stdout": "",
            "stderr": str(exc),
            "payload": {},
            "command": list(cmd),
        }

    stdout = str(completed.stdout or "")
    return {
        "invoke_ok": True,
        "exit_code": int(completed.returncode),
        "stdout": stdout,
        "stderr": str(completed.stderr or ""),
        "payload": _safe_json_parse(stdout),
        "command": list(cmd),
    }


def _gate_status(
    name: str,
    run: Dict[str, Any],
    skipped: bool = False,
    skip_reason: str = "",
) -> Dict[str, Any]:
    payload = run.get("payload") if isinstance(run.get("payload"), dict) else {}
    try:
        exit_code = int(run.get("exit_code"))
    except Exception:
        exit_code = 2
    invoke_ok = bool(run.get("invoke_ok", False))
    ok = bool(skipped or (invoke_ok and exit_code == 0))
    return {
        "name": name,
        "ok": ok,
        "skipped": bool(skipped),
        "skip_reason": str(skip_reason or ""),
        "invoke_ok": invoke_ok,
        "exit_code": exit_code,
        "payload": payload,
        "stderr": str(run.get("stderr") or ""),
    }


def _build_report(readiness: Dict[str, Any], cycle: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    if not bool(readiness.get("ok", False)):
        reasons.append("readiness_gate_failed")
    if not bool(cycle.get("skipped", False)) and not bool(cycle.get("ok", False)):
        reasons.append("cycle_gate_failed")
    if not bool(readiness.get("invoke_ok", False)):
        reasons.append("readiness_invocation_failed")
    if not bool(cycle.get("skipped", False)) and not bool(cycle.get("invoke_ok", False)):
        reasons.append("cycle_invocation_failed")

    return {
        "timestamp": datetime.now().isoformat(),
        "ok": len(reasons) == 0,
        "failure_reasons": reasons,
        "gates": {
            "readiness": readiness,
            "cycle": cycle,
        },
    }


def run_cutover_check(
    *,
    repo_root: Path,
    memory_dir: str,
    host: str,
    port: int,
    timeout: float,
    require_trained: bool,
    run_cycle_on_readiness_fail: bool,
    skip_cycle: bool,
    runner: Callable[[List[str], float], Dict[str, Any]] = _run_command,
) -> Tuple[Dict[str, Any], int]:
    readiness_script = repo_root / "scripts" / "lora_readiness_check.py"
    cycle_script = repo_root / "scripts" / "lora_force_cycle.py"
    timeout_value = max(1.0, min(float(timeout), 600.0))

    readiness_cmd = [
        sys.executable,
        str(readiness_script),
        "--compact",
        "--memory-dir",
        str(memory_dir),
    ]
    readiness_run = runner(readiness_cmd, timeout_value)
    readiness_gate = _gate_status("readiness", readiness_run)

    if skip_cycle:
        cycle_gate = _gate_status(
            "cycle",
            {"invoke_ok": True, "exit_code": 0, "payload": {}, "stderr": ""},
            skipped=True,
            skip_reason="disabled_by_flag",
        )
    elif not readiness_gate["ok"] and not run_cycle_on_readiness_fail:
        cycle_gate = _gate_status(
            "cycle",
            {"invoke_ok": True, "exit_code": 0, "payload": {}, "stderr": ""},
            skipped=True,
            skip_reason="readiness_gate_failed",
        )
    else:
        cycle_cmd = [
            sys.executable,
            str(cycle_script),
            "--compact",
            "--host",
            str(host),
            "--port",
            str(port),
            "--timeout",
            str(timeout_value),
        ]
        if require_trained:
            cycle_cmd.append("--require-trained")
        cycle_run = runner(cycle_cmd, timeout_value + 10.0)
        cycle_gate = _gate_status("cycle", cycle_run)

    report = _build_report(readiness_gate, cycle_gate)
    exit_code = 0 if report["ok"] else 1
    if not bool(readiness_gate.get("invoke_ok", False)):
        exit_code = 2
    if (not bool(cycle_gate.get("skipped", False))) and (not bool(cycle_gate.get("invoke_ok", False))):
        exit_code = 2
    return report, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LoRA cutover gates (readiness + force-cycle)")
    parser.add_argument("--memory-dir", default="vera_memory", help="Memory directory path for readiness check")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--require-trained", action="store_true", help="Require lora_training.trained=true in cycle gate")
    parser.add_argument("--run-cycle-on-readiness-fail", action="store_true", help="Run cycle gate even if readiness gate fails")
    parser.add_argument("--skip-cycle", action="store_true", help="Run readiness gate only")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    report, exit_code = run_cutover_check(
        repo_root=repo_root,
        memory_dir=str(args.memory_dir),
        host=str(args.host),
        port=int(args.port),
        timeout=float(args.timeout),
        require_trained=bool(args.require_trained),
        run_cycle_on_readiness_fail=bool(args.run_cycle_on_readiness_fail),
        skip_cycle=bool(args.skip_cycle),
    )

    if args.compact:
        print(json.dumps(report, ensure_ascii=True))
    else:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
