#!/usr/bin/env python3
"""
Golden-path MCP deployment gate for Vera.

This gate runs a curated, non-destructive MCP server training pass and applies
strict go/no-go thresholds suitable for deployment decisions.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import httpx


DEFAULT_SERVERS: Tuple[str, ...] = (
    "filesystem",
    "memory",
    "time",
    "sequential-thinking",
    "calculator",
    "wikipedia-mcp",
    "searxng",
    "brave-search",
    "github",
    "google-workspace",
    "memvid",
    "call-me",
)


@dataclass
class GateCheck:
    name: str
    ok: bool
    detail: str
    critical: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "critical": self.critical,
        }


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
        text = response.text.strip()
        return False, None, f"HTTP {response.status_code}: {text or 'request failed'}"
    try:
        return True, response.json(), ""
    except Exception:
        return False, None, "response was not valid JSON"


def _preview(text: str, limit: int = 240) -> str:
    clean = str(text or "").replace("\n", " ").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def _read_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _unique(values: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _print_check(check: GateCheck) -> None:
    status = "OK" if check.ok else ("FAIL" if check.critical else "WARN")
    print(f"[{status}] {check.name} - {check.detail}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Golden MCP deployment gate for Vera")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--http-timeout", type=float, default=20.0)
    parser.add_argument("--trainer-timeout", type=float, default=1500.0)
    parser.add_argument("--prompt-timeout", type=float, default=45.0)
    parser.add_argument("--call-timeout", type=float, default=20.0)
    parser.add_argument("--model", default="grok-4-1-fast-reasoning")
    parser.add_argument("--server", action="append", default=[], help="Server filter (repeatable)")
    parser.add_argument("--require-server", action="append", default=[], help="Required server (repeatable)")
    parser.add_argument("--max-tools-per-server", type=int, default=2)
    parser.add_argument("--skip-routing", action="store_true")
    parser.add_argument("--include-side-effects", action="store_true")
    parser.add_argument("--allow-loading", action="store_true")
    parser.add_argument("--require-trainer-zero-rc", action="store_true")
    parser.add_argument("--min-running-mcp", type=int, default=8)
    parser.add_argument("--min-call-ok", type=int, default=10)
    parser.add_argument("--min-routing-ok", type=int, default=10)
    parser.add_argument("--min-call-ok-ratio", type=float, default=0.75)
    parser.add_argument("--min-routing-ok-ratio", type=float, default=0.75)
    parser.add_argument("--min-call-ok-per-server", type=int, default=0)
    parser.add_argument("--max-failed", type=int, default=0)
    parser.add_argument("--max-blocked", type=int, default=120)
    parser.add_argument("--output", default="", help="Gate JSON report path")
    parser.add_argument("--trainer-output", default="", help="Trainer JSON report path")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[1]
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output_path = Path(args.output) if args.output else (root_dir / "tmp" / f"mcp_golden_gate_{ts}.json")
    trainer_output = (
        Path(args.trainer_output)
        if args.trainer_output
        else (root_dir / "tmp" / f"mcp_server_training_golden_{ts}.json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    trainer_output.parent.mkdir(parents=True, exist_ok=True)

    selected_servers = _unique(args.server or list(DEFAULT_SERVERS))
    required_servers = _unique(args.require_server or selected_servers)
    base_url = f"http://{args.host}:{args.port}"

    report: Dict[str, Any] = {
        "started_at": int(time.time()),
        "base_url": base_url,
        "selected_servers": selected_servers,
        "required_servers": required_servers,
        "thresholds": {
            "min_running_mcp": int(args.min_running_mcp),
            "min_call_ok": int(args.min_call_ok),
            "min_routing_ok": int(args.min_routing_ok),
            "min_call_ok_ratio": float(args.min_call_ok_ratio),
            "min_routing_ok_ratio": float(args.min_routing_ok_ratio),
            "min_call_ok_per_server": int(args.min_call_ok_per_server),
            "max_failed": int(args.max_failed),
            "max_blocked": int(args.max_blocked),
        },
    }

    checks: List[GateCheck] = []
    readiness_payload: Dict[str, Any] = {}
    with httpx.Client(timeout=args.http_timeout) as client:
        ok, data, err = _request_json(client, "GET", f"{base_url}/api/readiness")
        if ok and isinstance(data, dict):
            readiness_payload = data
            ready = data.get("ready") is True
            if ready or args.allow_loading:
                detail = "ready=true" if ready else f"allow_loading=true ({data.get('message') or 'loading'})"
                checks.append(GateCheck("readiness", True, detail, True))
            else:
                checks.append(GateCheck("readiness", False, f"ready=false ({data})", True))
        else:
            checks.append(GateCheck("readiness", False, err or "failed to query /api/readiness", True))

        ok, data, err = _request_json(client, "GET", f"{base_url}/api/tools")
        running_servers = 0
        total_servers = 0
        if ok and isinstance(data, dict):
            mcp = data.get("mcp")
            if isinstance(mcp, dict):
                servers = mcp.get("servers")
                if isinstance(servers, dict):
                    total_servers = len(servers)
                    running_servers = sum(
                        1 for info in servers.values() if isinstance(info, dict) and info.get("running") is True
                    )
        running_ok = running_servers >= max(0, int(args.min_running_mcp))
        checks.append(
            GateCheck(
                "running_mcp_servers",
                running_ok,
                f"running={running_servers}, total={total_servers}, required>={args.min_running_mcp}",
                True,
            )
        )

    trainer_cmd: List[str] = [
        sys.executable,
        str(root_dir / "scripts" / "vera_mcp_server_trainer.py"),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--model",
        args.model,
        "--prompt-timeout",
        str(args.prompt_timeout),
        "--call-timeout",
        str(args.call_timeout),
        "--output",
        str(trainer_output),
    ]
    if args.max_tools_per_server > 0:
        trainer_cmd.extend(["--max-tools-per-server", str(args.max_tools_per_server)])
    if args.skip_routing:
        trainer_cmd.append("--skip-routing")
    if args.allow_loading:
        trainer_cmd.append("--allow-loading")
    if args.include_side_effects:
        trainer_cmd.append("--include-side-effects")
    for server in selected_servers:
        trainer_cmd.extend(["--server", server])

    report["trainer_command"] = trainer_cmd

    trainer_stdout = ""
    trainer_stderr = ""
    trainer_rc = -1
    trainer_timed_out = False
    try:
        trainer_proc = subprocess.run(
            trainer_cmd,
            capture_output=True,
            text=True,
            timeout=max(1.0, args.trainer_timeout),
            check=False,
        )
        trainer_stdout = trainer_proc.stdout or ""
        trainer_stderr = trainer_proc.stderr or ""
        trainer_rc = int(trainer_proc.returncode)
    except subprocess.TimeoutExpired as exc:
        trainer_stdout = exc.stdout or ""
        trainer_stderr = exc.stderr or ""
        trainer_timed_out = True

    checks.append(GateCheck("trainer_timeout", not trainer_timed_out, f"timeout={trainer_timed_out}", True))

    if args.require_trainer_zero_rc:
        checks.append(GateCheck("trainer_exit_code", trainer_rc == 0, f"rc={trainer_rc}", True))
    else:
        checks.append(GateCheck("trainer_exit_code", True, f"rc={trainer_rc} (not enforced)", False))

    trainer_report = _read_json_file(trainer_output)
    summary = trainer_report.get("summary") if isinstance(trainer_report, dict) else None
    if not isinstance(summary, dict):
        checks.append(GateCheck("trainer_output_summary", False, f"missing or invalid summary at {trainer_output}", True))
        summary = {}
    else:
        checks.append(
            GateCheck(
                "trainer_output_summary",
                True,
                f"loaded={trainer_output}",
                True,
            )
        )

    tools_tested = _as_int(summary.get("tools_tested"), 0)
    routing_ok = _as_int(summary.get("routing_ok"), 0)
    call_ok = _as_int(summary.get("call_ok"), 0)
    skipped = _as_int(summary.get("skipped"), 0)
    blocked = _as_int(summary.get("blocked"), 0)
    failed = _as_int(summary.get("failed"), 0)
    servers_tested = _as_int(summary.get("servers_tested"), 0)
    attempted = max(0, tools_tested - skipped - blocked)
    call_ok_ratio = (float(call_ok) / float(attempted)) if attempted > 0 else 0.0
    routing_ok_ratio = (float(routing_ok) / float(attempted)) if attempted > 0 else 0.0

    checks.append(
        GateCheck(
            "summary_failed",
            failed <= max(0, int(args.max_failed)),
            f"failed={failed}, allowed<={args.max_failed}",
            True,
        )
    )
    checks.append(
        GateCheck(
            "summary_blocked_budget",
            blocked <= max(0, int(args.max_blocked)),
            f"blocked={blocked}, allowed<={args.max_blocked}",
            True,
        )
    )
    checks.append(
        GateCheck(
            "summary_call_ok_min",
            call_ok >= max(0, int(args.min_call_ok)),
            f"call_ok={call_ok}, required>={args.min_call_ok}",
            True,
        )
    )
    checks.append(
        GateCheck(
            "summary_call_ok_ratio",
            call_ok_ratio >= max(0.0, float(args.min_call_ok_ratio)),
            f"call_ok_ratio={call_ok_ratio:.3f}, required>={args.min_call_ok_ratio:.3f}, attempted={attempted}",
            True,
        )
    )
    if args.skip_routing:
        checks.append(GateCheck("summary_routing", True, "routing checks skipped by flag", False))
    else:
        checks.append(
            GateCheck(
                "summary_routing_ok_min",
                routing_ok >= max(0, int(args.min_routing_ok)),
                f"routing_ok={routing_ok}, required>={args.min_routing_ok}",
                True,
            )
        )
        checks.append(
            GateCheck(
                "summary_routing_ok_ratio",
                routing_ok_ratio >= max(0.0, float(args.min_routing_ok_ratio)),
                f"routing_ok_ratio={routing_ok_ratio:.3f}, required>={args.min_routing_ok_ratio:.3f}, attempted={attempted}",
                True,
            )
        )

    checks.append(
        GateCheck(
            "servers_tested_count",
            servers_tested >= len(required_servers),
            f"servers_tested={servers_tested}, required_servers={len(required_servers)}",
            True,
        )
    )

    servers_block = trainer_report.get("servers") if isinstance(trainer_report, dict) else None
    if not isinstance(servers_block, dict):
        servers_block = {}
    missing_servers = [name for name in required_servers if name not in servers_block]
    checks.append(
        GateCheck(
            "required_servers_present",
            len(missing_servers) == 0,
            f"missing={missing_servers or 'none'}",
            True,
        )
    )

    per_server_failures: List[str] = []
    for server_name in required_servers:
        server_payload = servers_block.get(server_name)
        if not isinstance(server_payload, dict):
            continue
        server_total_tools = _as_int(server_payload.get("total_tools"), 0)
        server_failed = _as_int(server_payload.get("failed"), 0)
        server_call_ok = _as_int(server_payload.get("call_ok"), 0)
        if server_total_tools <= 0:
            per_server_failures.append(f"{server_name}:total_tools=0")
        if server_failed > 0:
            per_server_failures.append(f"{server_name}:failed={server_failed}")
        if server_call_ok < max(0, int(args.min_call_ok_per_server)):
            per_server_failures.append(
                f"{server_name}:call_ok={server_call_ok}<min({args.min_call_ok_per_server})"
            )
    checks.append(
        GateCheck(
            "required_servers_quality",
            len(per_server_failures) == 0,
            f"issues={per_server_failures or 'none'}",
            True,
        )
    )

    for check in checks:
        _print_check(check)

    overall_ok = all(check.ok for check in checks if check.critical)
    report["checks"] = [check.to_dict() for check in checks]
    report["readiness"] = readiness_payload
    report["trainer"] = {
        "output": str(trainer_output),
        "returncode": trainer_rc,
        "timed_out": trainer_timed_out,
        "stdout_preview": _preview(trainer_stdout, limit=600),
        "stderr_preview": _preview(trainer_stderr, limit=600),
    }
    report["trainer_summary"] = {
        "servers_tested": servers_tested,
        "tools_tested": tools_tested,
        "routing_ok": routing_ok,
        "call_ok": call_ok,
        "skipped": skipped,
        "blocked": blocked,
        "failed": failed,
        "attempted": attempted,
        "routing_ok_ratio": round(routing_ok_ratio, 6),
        "call_ok_ratio": round(call_ok_ratio, 6),
    }
    report["overall_ok"] = overall_ok
    report["finished_at"] = int(time.time())
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nGolden gate report: {output_path}")
    print(f"Trainer report: {trainer_output}")
    print(f"Overall: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
