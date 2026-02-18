#!/usr/bin/env python3
"""
Capture a release-candidate snapshot for Vera_2.0.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_cmd(cmd: List[str]) -> Dict[str, Any]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=20)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
            "cmd": cmd,
        }
    except Exception as exc:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(exc), "cmd": cmd}


def _read_export_defaults(path: Path, keys: List[str]) -> Dict[str, str]:
    values = {k: "" for k in keys}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("export "):
            continue
        line = line[len("export "):]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in values:
            continue
        values[key] = value.strip()
    return values


def _latest_files(root: Path, pattern: str, limit: int = 5) -> List[str]:
    files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p) for p in files[: max(0, limit)]]


def _api_snapshot(base_url: str, timeout: float = 15.0) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "base_url": base_url,
        "health_ok": False,
        "mcp_running": None,
        "critical_servers": {},
    }
    critical = ["call-me", "memvid", "time", "sequential-thinking", "filesystem", "memory"]
    try:
        with httpx.Client(timeout=timeout) as client:
            health = client.get(f"{base_url}/api/health")
            result["health_ok"] = health.status_code == 200 and bool((health.json() or {}).get("ok"))
            tools = client.get(f"{base_url}/api/tools")
            if tools.status_code == 200:
                payload = tools.json()
                servers = ((payload.get("mcp") or {}).get("servers") or {})
                if isinstance(servers, dict):
                    result["mcp_running"] = sum(1 for info in servers.values() if isinstance(info, dict) and info.get("running"))
                    for name in critical:
                        info = servers.get(name) if isinstance(servers.get(name), dict) else {}
                        result["critical_servers"][name] = {
                            "running": bool(info.get("running")),
                            "health": info.get("health"),
                            "missing_env": info.get("missing_env") or [],
                        }
    except Exception as exc:
        result["error"] = str(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Vera release-candidate snapshot")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON path (default: tmp/release_candidate_snapshot_<ts>.json)",
    )
    parser.add_argument(
        "--memvid-concurrency-baseline",
        type=int,
        default=8,
        help="Recorded recommended memvid concurrency baseline",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.output) if args.output else (root / "tmp" / f"release_candidate_snapshot_{ts}.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    callme_profile = root / "config" / "callme_profiles" / "carol-prod.env"
    vera_env = root / "scripts" / "vera_env.local"
    callme_keys = [
        "CALLME_SMS_MODE",
        "CALLME_SMS_ENABLED",
        "CALLME_SMS_AUTOREPLY",
        "CALLME_SYNC_MESSAGING_WEBHOOK",
        "CALLME_TELNYX_TTS_VOICE",
    ]
    runtime_keys = [
        "VERA_MCP_AUTOSTART",
        "VERA_NATIVE_PUSH_ENABLED",
        "VERA_MEMVID_ENABLED",
        "VERA_MEMVID_MODE",
    ]

    snapshot: Dict[str, Any] = {
        "captured_at_utc": _utc_now(),
        "service_status": _run_cmd(["systemctl", "is-active", "vera2.service"]),
        "service_unit": _run_cmd(["systemctl", "cat", "vera2.service"]),
        "api": _api_snapshot(args.base_url),
        "config": {
            "callme_profile_file": str(callme_profile),
            "callme_defaults": _read_export_defaults(callme_profile, callme_keys),
            "runtime_env_file": str(vera_env),
            "runtime_defaults": _read_export_defaults(vera_env, runtime_keys),
            "memvid_concurrency_baseline": args.memvid_concurrency_baseline,
        },
        "evidence": {
            "production_checklists": _latest_files(root, "tmp/production_checklist_*.json", limit=8),
            "prompt_tool_sweep_gate": _latest_files(root, "tmp/prompt_tool_sweep_gate_*.json", limit=20),
            "call_me_live_smoke": _latest_files(root, "tmp/call_me_live_smoke_*.json", limit=5),
            "memvid_hardening": _latest_files(root, "tmp/memvid_hardening*.json", limit=12),
            "native_push_hardening": _latest_files(root, "tmp/native_push_hardening_*.json", limit=5),
        },
    }

    out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Release snapshot written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
