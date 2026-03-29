#!/usr/bin/env python3
"""
Pre-migration max-coverage validation for Vera_2.0.

Runs multiple MCP trainer passes, merges per-tool outcomes, and reports:
- full execution coverage (call_ok)
- routing-only coverage
- unresolved tools with blocker categories
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _request_json(url: str, timeout: float = 15.0) -> Dict[str, Any]:
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def _run(cmd: List[str], cwd: Path, timeout: float) -> Dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout),
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": int(proc.returncode),
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "elapsed_s": round(time.time() - started, 3),
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": -9,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "") if isinstance(exc.stderr, str) else "",
            "elapsed_s": round(time.time() - started, 3),
            "timeout": True,
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "elapsed_s": round(time.time() - started, 3),
            "timeout": False,
        }


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _classify_blocker(status: str, blocked: List[str], skipped: List[str], errors: List[str]) -> str:
    if status == "skipped":
        return "side_effect_policy"
    if status == "blocked":
        blob = " ".join(blocked).lower()
        if "missing_preconditions:" in blob:
            return "missing_preconditions"
        external_hints = (
            "rate limit",
            "too many requests",
            "unauthorized",
            "authentication",
            "api key",
            "permission denied",
            "option is not subscribed in the plan",
            "subset of x api",
            "google chat app",
            "google docs api",
            "google sheets api",
            "google drive api",
            "does not match the pattern",
            "instance not found",
        )
        if any(h in blob for h in external_hints):
            return "external_dependency"
        return "blocked_other"
    if status == "error":
        blob = " ".join(errors).lower()
        if "timed out" in blob or "timeout" in blob:
            return "runtime_timeout"
        return "runtime_error"
    if status == "untested":
        return "untested"
    return "none"


@dataclass
class ToolState:
    server: str
    tool: str
    attempts: int = 0
    routed: bool = False
    called: bool = False
    blocked_reasons: List[str] = None
    skip_reasons: List[str] = None
    errors: List[str] = None

    def __post_init__(self) -> None:
        if self.blocked_reasons is None:
            self.blocked_reasons = []
        if self.skip_reasons is None:
            self.skip_reasons = []
        if self.errors is None:
            self.errors = []

    def status(self) -> str:
        if self.called:
            return "called"
        if self.routed:
            return "routed_only"
        if self.blocked_reasons:
            return "blocked"
        if self.skip_reasons:
            return "skipped"
        if self.errors:
            return "error"
        return "untested"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pre-migration max coverage validation")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--model", default="grok-4.20-experimental-beta-0304-reasoning")
    parser.add_argument("--prompt-timeout", type=float, default=45.0)
    parser.add_argument("--call-timeout", type=float, default=20.0)
    parser.add_argument("--trainer-timeout", type=float, default=1800.0)
    parser.add_argument("--stealth-max-tools", type=int, default=20, help="Bound stealth side-effect pass size")
    parser.add_argument("--output-dir", default="", help="Default: tmp/deploy_gates/maxout_<ts>")
    parser.add_argument("--with-call-me-live", action="store_true", help="Run call_me_live_smoke voice-only pass")
    parser.add_argument("--call-me-timeout", type=float, default=90.0)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = _utc_ts()
    out_dir = Path(args.output_dir) if args.output_dir else (root / "tmp" / "deploy_gates" / f"maxout_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    python_bin = str(root / ".venv" / "bin" / "python")
    if not Path(python_bin).exists():
        python_bin = sys.executable or "python3"

    base_url = f"http://{args.host}:{args.port}"
    defs = _request_json(f"{base_url}/api/tools/defs")
    tools_by_server = defs.get("tools") if isinstance(defs, dict) else {}
    if not isinstance(tools_by_server, dict) or not tools_by_server:
        print("Failed to load active tool definitions from /api/tools/defs")
        return 1

    active_servers = sorted(tools_by_server.keys())
    total_tools = sum(len(v) for v in tools_by_server.values() if isinstance(v, list))

    trainer_script = root / "scripts" / "vera_mcp_server_trainer.py"
    passes: List[Dict[str, Any]] = []

    # Pass 1: Full execution (no routing) for all non-side-effect tools.
    p1_out = out_dir / "pass1_full_safe_exec.json"
    p1_cmd = [
        python_bin,
        str(trainer_script),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--model",
        args.model,
        "--skip-routing",
        "--call-timeout",
        str(args.call_timeout),
        "--output",
        str(p1_out),
    ]
    passes.append({"name": "pass1_full_safe_exec", "cmd": p1_cmd, "output": p1_out, "timeout": args.trainer_timeout})

    # Pass 2: Local side-effect execution for local-state servers.
    local_servers = ["filesystem", "memory", "marm-memory", "obsidian-vault", "sandbox"]
    p2_out = out_dir / "pass2_local_side_effects.json"
    p2_cmd = [
        python_bin,
        str(trainer_script),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--model",
        args.model,
        "--skip-routing",
        "--include-side-effects",
        "--call-timeout",
        str(max(args.call_timeout, 25.0)),
        "--output",
        str(p2_out),
    ]
    for s in local_servers:
        if s in active_servers:
            p2_cmd.extend(["--server", s])
    passes.append({"name": "pass2_local_side_effects", "cmd": p2_cmd, "output": p2_out, "timeout": args.trainer_timeout})

    # Pass 3: Stealth browser side-effect execution (direct-call only).
    p3_out = out_dir / "pass3_stealth_side_effects.json"
    p3_cmd = [
        python_bin,
        str(trainer_script),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--model",
        args.model,
        "--skip-routing",
        "--include-side-effects",
        "--call-timeout",
        str(max(args.call_timeout, 30.0)),
        "--max-tools-per-server",
        str(max(1, int(args.stealth_max_tools))),
        "--output",
        str(p3_out),
        "--server",
        "stealth-browser",
    ]
    if "stealth-browser" in active_servers:
        passes.append({"name": "pass3_stealth_side_effects", "cmd": p3_cmd, "output": p3_out, "timeout": min(args.trainer_timeout, 420.0)})

    # Pass 4: Routing sample across all servers (bounded) to validate tool-selection behavior.
    p4_out = out_dir / "pass4_routing_sample.json"
    p4_cmd = [
        python_bin,
        str(trainer_script),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--model",
        args.model,
        "--max-tools-per-server",
        "2",
        "--prompt-timeout",
        str(args.prompt_timeout),
        "--call-timeout",
        str(args.call_timeout),
        "--output",
        str(p4_out),
    ]
    passes.append({"name": "pass4_routing_sample", "cmd": p4_cmd, "output": p4_out, "timeout": max(600.0, args.trainer_timeout)})

    # Optional Pass 4: live call-me voice smoke.
    callme_result: Dict[str, Any] = {}
    if args.with_call_me_live:
        callme_out = out_dir / "call_me_live_smoke.json"
        callme_cmd = [
            python_bin,
            str(root / "scripts" / "call_me_live_smoke.py"),
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--wait",
            "45",
            "--skip-sms",
            "--call-timeout",
            str(args.call_me_timeout),
            "--timeout",
            str(max(args.call_me_timeout + 30.0, 120.0)),
            "--output",
            str(callme_out),
        ]
        callme_result = _run(callme_cmd, cwd=root, timeout=max(args.call_me_timeout + 90.0, 240.0))
        callme_result["name"] = "call_me_live_smoke"
        callme_result["output"] = str(callme_out)

    # Initialize per-tool state from active defs.
    tool_state: Dict[str, ToolState] = {}
    for server, tools in tools_by_server.items():
        if not isinstance(tools, list):
            continue
        for tool_def in tools:
            if not isinstance(tool_def, dict):
                continue
            name = str(tool_def.get("name") or "").strip()
            if not name:
                continue
            key = f"{server}::{name}"
            tool_state[key] = ToolState(server=server, tool=name)

    pass_runs: List[Dict[str, Any]] = []
    for p in passes:
        name = str(p["name"])
        cmd = list(p["cmd"])
        timeout = float(p["timeout"])
        out_path = Path(p["output"])

        print(f"\n[RUN] {name}", flush=True)
        run = _run(cmd, cwd=root, timeout=timeout)
        run["name"] = name
        run["output"] = str(out_path)
        pass_runs.append(run)
        print(f"[RUN] {name} rc={run['returncode']} elapsed={run['elapsed_s']}s", flush=True)

        report = _load_json(out_path)
        servers_block = report.get("servers") if isinstance(report, dict) else {}
        if not isinstance(servers_block, dict):
            continue
        for server, srow in servers_block.items():
            if not isinstance(srow, dict):
                continue
            results = srow.get("results")
            if not isinstance(results, list):
                continue
            for row in results:
                if not isinstance(row, dict):
                    continue
                tool = str(row.get("tool") or "").strip()
                if not tool:
                    continue
                key = f"{server}::{tool}"
                if key not in tool_state:
                    tool_state[key] = ToolState(server=server, tool=tool)
                state = tool_state[key]
                state.attempts += 1
                if row.get("routing_ok") is True:
                    state.routed = True
                if row.get("call_ok") is True:
                    state.called = True
                if row.get("blocked") is True:
                    reason = str(row.get("blocked_reason") or "").strip()
                    if reason:
                        state.blocked_reasons.append(reason)
                if row.get("skipped") is True:
                    reason = str(row.get("skip_reason") or "").strip()
                    if reason:
                        state.skip_reasons.append(reason)
                if row.get("call_ok") is False and row.get("blocked") is not True:
                    detail = str(row.get("call_detail") or "").strip()
                    if detail:
                        state.errors.append(detail)
                if (row.get("routing_ok") is not True) and (row.get("skipped") is not True) and (row.get("blocked") is not True):
                    detail = str(row.get("routing_detail") or "").strip()
                    if detail:
                        state.errors.append(f"routing:{detail}")

    by_status = {"called": 0, "routed_only": 0, "blocked": 0, "skipped": 0, "error": 0, "untested": 0}
    unresolved: List[Dict[str, Any]] = []
    per_server: Dict[str, Dict[str, int]] = {}
    blocker_counts: Dict[str, int] = {}

    for key in sorted(tool_state):
        state = tool_state[key]
        status = state.status()
        by_status[status] += 1
        server_bucket = per_server.setdefault(
            state.server,
            {"total": 0, "called": 0, "routed_only": 0, "blocked": 0, "skipped": 0, "error": 0, "untested": 0},
        )
        server_bucket["total"] += 1
        server_bucket[status] += 1

        if status in {"blocked", "skipped", "error", "untested"}:
            blocker_type = _classify_blocker(status, state.blocked_reasons, state.skip_reasons, state.errors)
            blocker_counts[blocker_type] = blocker_counts.get(blocker_type, 0) + 1
            unresolved.append(
                {
                    "server": state.server,
                    "tool": state.tool,
                    "status": status,
                    "blocker_type": blocker_type,
                    "attempts": state.attempts,
                    "blocked_reasons": state.blocked_reasons[:3],
                    "skip_reasons": state.skip_reasons[:3],
                    "errors": state.errors[:3],
                }
            )

    execution_coverage = (float(by_status["called"]) / float(max(1, len(tool_state))))
    knowledge_coverage = (float(by_status["called"] + by_status["routed_only"]) / float(max(1, len(tool_state))))

    summary = {
        "timestamp_utc": _utc_ts(),
        "base_url": base_url,
        "active_servers": len(active_servers),
        "active_tools": len(tool_state),
        "execution_coverage_ratio": round(execution_coverage, 4),
        "knowledge_coverage_ratio": round(knowledge_coverage, 4),
        "status_counts": by_status,
        "blocker_type_counts": blocker_counts,
    }

    report: Dict[str, Any] = {
        "summary": summary,
        "passes": pass_runs,
        "call_me_live_smoke": callme_result,
        "per_server": per_server,
        "unresolved_tools": unresolved,
    }

    out_report = out_dir / "maxout_report.json"
    out_report.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    # Friendly console output.
    print("\n=== Maxout Summary ===", flush=True)
    print(f"Active servers: {summary['active_servers']}", flush=True)
    print(f"Active tools:   {summary['active_tools']}", flush=True)
    print(f"Called:         {by_status['called']}", flush=True)
    print(f"Routed-only:    {by_status['routed_only']}", flush=True)
    print(f"Blocked:        {by_status['blocked']}", flush=True)
    print(f"Skipped:        {by_status['skipped']}", flush=True)
    print(f"Error:          {by_status['error']}", flush=True)
    print(f"Untested:       {by_status['untested']}", flush=True)
    print(f"Execution cov:  {summary['execution_coverage_ratio']:.2%}", flush=True)
    print(f"Knowledge cov:  {summary['knowledge_coverage_ratio']:.2%}", flush=True)
    print(f"Report:         {out_report}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
