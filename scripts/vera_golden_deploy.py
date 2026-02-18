#!/usr/bin/env python3
"""
One-command golden deployment gate for Vera_2.0.

Flow:
1) Ensure API is up (optionally launch Vera if down)
2) Wait for /api/readiness -> ready=true
3) Run production checklist with MCP golden gate
4) Capture a release snapshot
5) Emit a timestamped evidence bundle with PASS/FAIL manifest
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _request_json(url: str, timeout: float) -> Tuple[bool, Any, str, int]:
    req = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, timeout)) as resp:
            status = int(getattr(resp, "status", 200))
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return False, None, f"HTTP {exc.code}: {body.strip() or 'request failed'}", int(exc.code)
    except Exception as exc:
        return False, None, f"request failed: {exc}", 0

    text = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except Exception:
        return False, None, "response was not valid JSON", status
    return True, payload, "", status


def _is_api_healthy(base_url: str, timeout: float) -> bool:
    ok, payload, _, _ = _request_json(f"{base_url}/api/health", timeout=timeout)
    return ok and isinstance(payload, dict) and bool(payload.get("ok"))


def _wait_for_readiness(base_url: str, timeout_s: float, poll_s: float, http_timeout: float) -> Dict[str, Any]:
    started = time.time()
    history: List[Dict[str, Any]] = []
    last_payload: Dict[str, Any] = {}
    last_error = ""

    while (time.time() - started) <= max(1.0, timeout_s):
        ok, payload, err, _ = _request_json(f"{base_url}/api/readiness", timeout=http_timeout)
        now_iso = _utc_iso()
        if ok and isinstance(payload, dict):
            last_payload = payload
            history.append(
                {
                    "at_utc": now_iso,
                    "ready": bool(payload.get("ready") is True),
                    "phase": str(payload.get("phase") or ""),
                    "message": str(payload.get("message") or ""),
                    "pending_servers": payload.get("pending_servers") or [],
                    "mcp_total_running": ((payload.get("mcp") or {}).get("total_running") if isinstance(payload.get("mcp"), dict) else None),
                }
            )
            if payload.get("ready") is True:
                return {
                    "ok": True,
                    "elapsed_s": round(time.time() - started, 3),
                    "last_payload": last_payload,
                    "history": history,
                    "error": "",
                }
        else:
            last_error = err or "readiness request failed"
            history.append({"at_utc": now_iso, "error": last_error})
        time.sleep(max(0.5, poll_s))

    return {
        "ok": False,
        "elapsed_s": round(time.time() - started, 3),
        "last_payload": last_payload,
        "history": history,
        "error": last_error or "timeout waiting for readiness",
    }


def _run_cmd(cmd: List[str], cwd: Path, timeout: float) -> Dict[str, Any]:
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
            "cmd": cmd,
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": -9,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "") if isinstance(exc.stderr, str) else "",
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
            "timeout": False,
        }


def _resolve_python(root: Path) -> str:
    venv_py = root / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable or "python3"


def _launch_vera(root: Path, launch_cmd: str, log_path: Path) -> Dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("a", encoding="utf-8")
    log_handle.write(f"\n[{_utc_iso()}] launch cmd: {launch_cmd}\n")
    log_handle.flush()
    cmd = shlex.split(launch_cmd)
    proc = subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    return {
        "pid": int(proc.pid),
        "cmd": cmd,
        "log_path": str(log_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one-command Vera golden deploy gate")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--http-timeout", type=float, default=10.0)
    parser.add_argument("--readiness-timeout", type=float, default=420.0)
    parser.add_argument("--readiness-poll", type=float, default=3.0)
    launch_group = parser.add_mutually_exclusive_group()
    launch_group.add_argument("--launch-if-down", dest="launch_if_down", action="store_true")
    launch_group.add_argument("--no-launch-if-down", dest="launch_if_down", action="store_false")
    parser.set_defaults(launch_if_down=True)
    parser.add_argument(
        "--launch-cmd",
        default="./scripts/run_vera_full.sh --no-ui --no-verify",
        help="Command used to launch Vera when API is down",
    )
    parser.add_argument("--checklist-timeout", type=float, default=2100.0)
    parser.add_argument("--mcp-golden-gate-timeout", type=float, default=1500.0)
    parser.add_argument("--with-chat-check", action="store_true", help="Do not pass --skip-chat to checklist")
    parser.add_argument("--skip-release-snapshot", action="store_true")
    parser.add_argument("--snapshot-timeout", type=float, default=90.0)
    parser.add_argument(
        "--output-dir",
        default="",
        help="Bundle directory (default: tmp/deploy_gates/golden_<timestamp>)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = _utc_ts()
    out_dir = Path(args.output_dir) if args.output_dir else (root / "tmp" / "deploy_gates" / f"golden_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    base_url = args.base_url.strip() or f"http://{args.host}:{args.port}"
    python_bin = _resolve_python(root)
    launch_log = out_dir / "launch.log"
    checklist_stdout_path = out_dir / "checklist_stdout.log"
    checklist_stderr_path = out_dir / "checklist_stderr.log"
    checklist_json_path = out_dir / "production_checklist.json"
    readiness_path = out_dir / "readiness_wait.json"
    snapshot_path = out_dir / "release_snapshot.json"
    manifest_path = out_dir / "manifest.json"

    started_at = _utc_iso()
    manifest: Dict[str, Any] = {
        "started_at_utc": started_at,
        "base_url": base_url,
        "bundle_dir": str(out_dir),
        "launch": {},
        "readiness": {},
        "checklist": {},
        "release_snapshot": {},
    }

    api_preexisting = _is_api_healthy(base_url, timeout=args.http_timeout)
    manifest["launch"]["api_preexisting"] = api_preexisting

    if not api_preexisting:
        if not args.launch_if_down:
            manifest["launch"]["attempted"] = False
            manifest["launch"]["error"] = "API down and launch disabled"
            manifest["overall_ok"] = False
            manifest["finished_at_utc"] = _utc_iso()
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
            print(f"[FAIL] API is down at {base_url} and --no-launch-if-down was set")
            print(f"Manifest: {manifest_path}")
            return 1
        try:
            launch_meta = _launch_vera(root, args.launch_cmd, launch_log)
            manifest["launch"]["attempted"] = True
            manifest["launch"]["ok"] = True
            manifest["launch"]["meta"] = launch_meta
            print(f"[INFO] Launched Vera pid={launch_meta.get('pid')} using: {args.launch_cmd}")
        except Exception as exc:
            manifest["launch"]["attempted"] = True
            manifest["launch"]["ok"] = False
            manifest["launch"]["error"] = str(exc)
            manifest["overall_ok"] = False
            manifest["finished_at_utc"] = _utc_iso()
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
            print(f"[FAIL] Failed to launch Vera: {exc}")
            print(f"Manifest: {manifest_path}")
            return 1
    else:
        manifest["launch"]["attempted"] = False
        manifest["launch"]["ok"] = True
        print(f"[INFO] Vera API already healthy at {base_url}")

    readiness = _wait_for_readiness(
        base_url=base_url,
        timeout_s=args.readiness_timeout,
        poll_s=args.readiness_poll,
        http_timeout=args.http_timeout,
    )
    readiness_path.write_text(json.dumps(readiness, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    manifest["readiness"] = {
        "ok": bool(readiness.get("ok")),
        "elapsed_s": readiness.get("elapsed_s"),
        "path": str(readiness_path),
        "last_payload": readiness.get("last_payload") or {},
        "error": readiness.get("error") or "",
    }
    if not readiness.get("ok"):
        manifest["overall_ok"] = False
        manifest["finished_at_utc"] = _utc_iso()
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"[FAIL] Readiness timeout/error: {readiness.get('error')}")
        print(f"Manifest: {manifest_path}")
        return 1
    print(f"[INFO] Readiness OK in {readiness.get('elapsed_s')}s")

    checklist_cmd = [
        python_bin,
        str(root / "scripts" / "vera_production_checklist.py"),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--with-mcp-golden-gate",
        "--mcp-golden-gate-timeout",
        str(args.mcp_golden_gate_timeout),
        "--output",
        str(checklist_json_path),
    ]
    if not args.with_chat_check:
        checklist_cmd.append("--skip-chat")

    checklist_run = _run_cmd(checklist_cmd, cwd=root, timeout=args.checklist_timeout)
    checklist_stdout_path.write_text(checklist_run.get("stdout", ""), encoding="utf-8")
    checklist_stderr_path.write_text(checklist_run.get("stderr", ""), encoding="utf-8")
    manifest["checklist"] = {
        "ok": bool(checklist_run.get("ok")),
        "returncode": checklist_run.get("returncode"),
        "timeout": bool(checklist_run.get("timeout")),
        "elapsed_s": checklist_run.get("elapsed_s"),
        "cmd": checklist_cmd,
        "json_report": str(checklist_json_path),
        "stdout_log": str(checklist_stdout_path),
        "stderr_log": str(checklist_stderr_path),
    }

    snapshot_ok = True
    if not args.skip_release_snapshot:
        snapshot_cmd = [
            python_bin,
            str(root / "scripts" / "vera_release_snapshot.py"),
            "--base-url",
            base_url,
            "--output",
            str(snapshot_path),
        ]
        snapshot_run = _run_cmd(snapshot_cmd, cwd=root, timeout=args.snapshot_timeout)
        snapshot_ok = bool(snapshot_run.get("ok"))
        manifest["release_snapshot"] = {
            "ok": snapshot_ok,
            "returncode": snapshot_run.get("returncode"),
            "elapsed_s": snapshot_run.get("elapsed_s"),
            "cmd": snapshot_cmd,
            "json_report": str(snapshot_path),
        }
    else:
        manifest["release_snapshot"] = {"ok": True, "skipped": True}

    overall_ok = bool(checklist_run.get("ok")) and snapshot_ok
    manifest["overall_ok"] = overall_ok
    manifest["finished_at_utc"] = _utc_iso()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    status = "PASS" if overall_ok else "FAIL"
    print(f"[{status}] Golden deploy gate complete")
    print(f"Manifest: {manifest_path}")
    print(f"Checklist JSON: {checklist_json_path}")
    if not args.skip_release_snapshot:
        print(f"Snapshot JSON: {snapshot_path}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
