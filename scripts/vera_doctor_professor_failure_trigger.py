#!/usr/bin/env python3
"""
Failure-triggered runner for Doctor/Professor CI gate.

Policy:
- Dual MCP thresholds: target and critical.
- Startup grace window after Vera restarts.
- Warning conditions require consecutive failures before triggering.
- Critical conditions trigger immediately (outside startup grace).
- Edge-triggering: one trigger per active failure signature.
- Cooldown and daily trigger budget.
- Clear active incident only after consecutive healthy polls.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib import error, request


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_ts() -> str:
    return _utc_now().strftime("%Y%m%dT%H%M%SZ")


def _parse_iso(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _request_json(url: str, timeout: float = 8.0) -> Tuple[bool, Dict[str, Any], str]:
    req = request.Request(url=url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(payload, dict):
                return True, payload, ""
            return False, {}, "response is not a JSON object"
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, {}, f"HTTP {exc.code}: {body}"
    except Exception as exc:
        return False, {}, str(exc)


@dataclass
class TriggerDecision:
    should_trigger: bool
    reason: str


@dataclass
class HealthSignal:
    severity: str  # healthy | warning | critical
    signature: str
    failures: List[str]
    details: Dict[str, Any]
    uptime_seconds: float


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _collect_signal(
    base_url: str,
    target_running_mcp: int,
    critical_running_mcp: int,
) -> HealthSignal:
    failures: List[str] = []
    details: Dict[str, Any] = {}
    severity_rank = 0  # 0=healthy, 1=warning, 2=critical
    uptime_seconds = -1.0

    ok_readiness, readiness, err_readiness = _request_json(f"{base_url}/api/readiness")
    if ok_readiness:
        readiness_uptime = readiness.get("uptime_seconds")
        try:
            uptime_seconds = float(readiness_uptime)
        except Exception:
            uptime_seconds = -1.0
        details["readiness"] = {
            "ready": readiness.get("ready"),
            "phase": readiness.get("phase"),
            "pending_servers": readiness.get("pending_servers") or [],
            "missing_servers": readiness.get("missing_servers") or [],
            "checked_at": readiness.get("checked_at"),
            "uptime_seconds": uptime_seconds,
        }
        if readiness.get("ready") is not True:
            failures.append(f"critical:readiness_not_ready:phase={readiness.get('phase')}")
            severity_rank = max(severity_rank, 2)
    else:
        details["readiness"] = {"error": err_readiness}
        failures.append(f"critical:readiness_http_error:{err_readiness}")
        severity_rank = max(severity_rank, 2)

    ok_tools, tools, err_tools = _request_json(f"{base_url}/api/tools")
    details["tools"] = {"ok": ok_tools, "error": err_tools if not ok_tools else ""}
    if not ok_tools:
        failures.append(f"critical:tools_http_error:{err_tools}")
        severity_rank = max(severity_rank, 2)
    else:
        mcp = tools.get("mcp") if isinstance(tools, dict) else {}
        running = 0
        configured = 0
        down_servers: List[str] = []
        if isinstance(mcp, dict):
            running = int(mcp.get("total_running") or 0)
            configured = int(mcp.get("total_configured") or 0)
            servers = mcp.get("servers")
            if isinstance(servers, dict):
                for name, meta in servers.items():
                    if isinstance(meta, dict) and not meta.get("running"):
                        down_servers.append(str(name))
        details["mcp_running"] = {"running": running, "configured": configured}
        details["mcp_down_servers"] = down_servers

        if running < max(0, int(critical_running_mcp)):
            failures.append(f"critical:mcp_running_low:{running}<{critical_running_mcp}")
            severity_rank = max(severity_rank, 2)
        elif running < max(0, int(target_running_mcp)):
            failures.append(f"warning:mcp_running_below_target:{running}<{target_running_mcp}")
            severity_rank = max(severity_rank, 1)

    ok_memory, memory, err_memory = _request_json(f"{base_url}/api/memory/stats")
    details["memory_stats"] = {"ok": ok_memory, "error": err_memory if not ok_memory else ""}
    if not ok_memory:
        failures.append(f"critical:memory_stats_http_error:{err_memory}")
        severity_rank = max(severity_rank, 2)
    else:
        stats = memory.get("stats")
        if not isinstance(stats, dict):
            failures.append("critical:memory_stats_missing_stats")
            severity_rank = max(severity_rank, 2)
        else:
            archive = stats.get("archive") if isinstance(stats.get("archive"), dict) else {}
            slow = stats.get("slow_network") if isinstance(stats.get("slow_network"), dict) else {}
            details["memory_summary"] = {
                "archive_total": archive.get("total_archived"),
                "slow_events_archived": slow.get("events_archived"),
                "quarantine_size": slow.get("quarantine_size"),
            }

    severity = "healthy"
    if severity_rank >= 2:
        severity = "critical"
    elif severity_rank == 1:
        severity = "warning"

    signature = "|".join(sorted(failures))
    return HealthSignal(
        severity=severity,
        signature=signature,
        failures=failures,
        details=details,
        uptime_seconds=uptime_seconds,
    )


def _prune_trigger_history(raw_history: Any) -> List[str]:
    now = _utc_now()
    kept: List[str] = []
    if not isinstance(raw_history, list):
        return kept
    for item in raw_history:
        if not isinstance(item, str):
            continue
        dt = _parse_iso(item)
        if not dt:
            continue
        if now - dt <= timedelta(hours=24):
            kept.append(item)
    return kept


def _decide_trigger(
    signal: HealthSignal,
    state: Dict[str, Any],
    *,
    startup_grace_minutes: int,
    warning_consecutive_failures: int,
    cooldown_minutes: int,
    max_triggers_per_day: int,
) -> TriggerDecision:
    if signal.severity == "healthy":
        return TriggerDecision(False, "healthy")

    if signal.uptime_seconds >= 0.0 and signal.uptime_seconds < max(0, startup_grace_minutes) * 60:
        return TriggerDecision(False, f"startup_grace_active:{int(signal.uptime_seconds)}s")

    observed_signature = str(state.get("observed_failure_signature") or "")
    prev_failure_streak = int(state.get("failure_streak") or 0)
    failure_streak = prev_failure_streak + 1 if signal.signature == observed_signature else 1

    if signal.severity == "warning" and failure_streak < max(1, warning_consecutive_failures):
        return TriggerDecision(False, f"warning_streak:{failure_streak}/{warning_consecutive_failures}")

    active = bool(state.get("active_failure", False))
    active_signature = str(state.get("active_signature") or "")
    if active and signal.signature == active_signature:
        return TriggerDecision(False, "same_failure_still_active")

    now = _utc_now()
    last_trigger_raw = str(state.get("last_trigger_at") or "")
    last_trigger_at = _parse_iso(last_trigger_raw) if last_trigger_raw else None
    if last_trigger_at is not None:
        elapsed = now - last_trigger_at
        if elapsed < timedelta(minutes=max(0, cooldown_minutes)):
            return TriggerDecision(False, f"cooldown_active:{int(elapsed.total_seconds())}s")

    history = _prune_trigger_history(state.get("trigger_history"))
    if len(history) >= max(0, max_triggers_per_day):
        return TriggerDecision(False, f"daily_trigger_budget_exhausted:{len(history)}/{max_triggers_per_day}")

    return TriggerDecision(True, "new_failure_condition")


def _run_ci_gate(
    root: Path,
    base_url: str,
    logs_dir: Path,
    timeout_s: float,
) -> Tuple[int, str, str]:
    cmd = [
        sys.executable,
        str(root / "scripts" / "vera_doctor_professor_ci_gate.py"),
        "--base-url",
        base_url,
        "--logs-dir",
        str(logs_dir),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(60.0, timeout_s),
            check=False,
            cwd=str(root),
        )
        return int(proc.returncode), proc.stdout or "", proc.stderr or ""
    except Exception as exc:
        return 125, "", f"failed to run CI gate: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger Doctor/Professor diagnostics on failures")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--target-running-mcp", type=int, default=23)
    parser.add_argument("--critical-running-mcp", type=int, default=20)
    parser.add_argument("--startup-grace-minutes", type=int, default=12)
    parser.add_argument("--warning-consecutive-failures", type=int, default=2)
    parser.add_argument("--clear-healthy-streak", type=int, default=2)
    parser.add_argument("--cooldown-minutes", type=int, default=60)
    parser.add_argument("--max-triggers-per-day", type=int, default=6)
    parser.add_argument("--state-file", default="tmp/doctor_professor_failure_trigger_state.json")
    parser.add_argument("--events-log", default="tmp/doctor_professor_failure_trigger_events.jsonl")
    parser.add_argument("--trigger-logs-root", default="/home/nizbot-macmini/projects/Doctor_Codex/logs/vera_ci_triggered")
    parser.add_argument("--ci-timeout", type=float, default=2400.0)
    parser.add_argument("--log-all-events", action="store_true")
    args = parser.parse_args()

    if args.critical_running_mcp > args.target_running_mcp:
        raise SystemExit("critical-running-mcp must be <= target-running-mcp")

    root = Path(__file__).resolve().parents[1]
    state_file = Path(args.state_file)
    if not state_file.is_absolute():
        state_file = root / state_file
    events_log = Path(args.events_log)
    if not events_log.is_absolute():
        events_log = root / events_log

    signal = _collect_signal(
        args.base_url.rstrip("/"),
        target_running_mcp=args.target_running_mcp,
        critical_running_mcp=args.critical_running_mcp,
    )

    state = _load_state(state_file)
    prev_state = dict(state)
    state["trigger_history"] = _prune_trigger_history(state.get("trigger_history"))

    decision = _decide_trigger(
        signal,
        state,
        startup_grace_minutes=args.startup_grace_minutes,
        warning_consecutive_failures=args.warning_consecutive_failures,
        cooldown_minutes=args.cooldown_minutes,
        max_triggers_per_day=args.max_triggers_per_day,
    )

    now = _utc_now()
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    prev_observed_signature = str(state.get("observed_failure_signature") or "")
    prev_failure_streak = int(state.get("failure_streak") or 0)
    prev_healthy_streak = int(state.get("healthy_streak") or 0)
    prev_active = bool(state.get("active_failure", False))
    prev_active_sig = str(state.get("active_signature") or "")

    if signal.severity == "healthy":
        state["failure_streak"] = 0
        state["observed_failure_signature"] = ""
        state["healthy_streak"] = prev_healthy_streak + 1
        state["last_status"] = "healthy"
        state["last_failures"] = []
        if prev_active and int(state["healthy_streak"]) >= max(1, args.clear_healthy_streak):
            state["active_failure"] = False
            state["active_signature"] = ""
            state["resolved_at"] = now_iso
        else:
            state["active_failure"] = prev_active
            state["active_signature"] = prev_active_sig
    else:
        state["healthy_streak"] = 0
        state["observed_failure_signature"] = signal.signature
        state["failure_streak"] = prev_failure_streak + 1 if signal.signature == prev_observed_signature else 1
        state["last_status"] = signal.severity
        state["last_failures"] = signal.failures
        if decision.should_trigger:
            state["active_failure"] = True
            state["active_signature"] = signal.signature
            state["active_since"] = now_iso
            state["last_trigger_at"] = now_iso
            state["last_trigger_rc"] = None
            state["last_trigger_logs_dir"] = ""
            history = list(state.get("trigger_history") or [])
            history.append(now_iso)
            state["trigger_history"] = history
        elif prev_active and signal.signature == prev_active_sig:
            state["active_failure"] = True
            state["active_signature"] = prev_active_sig
        else:
            state["active_failure"] = prev_active
            state["active_signature"] = prev_active_sig

    event: Dict[str, Any] = {
        "ts": now_iso,
        "base_url": args.base_url,
        "severity": signal.severity,
        "signature": signal.signature,
        "failures": signal.failures,
        "decision": decision.reason,
        "triggered": False,
        "ci_returncode": None,
        "ci_logs_dir": "",
    }

    if decision.should_trigger:
        ts = _utc_ts()
        trigger_logs_dir = Path(args.trigger_logs_root).resolve() / ts
        rc, stdout_text, stderr_text = _run_ci_gate(root, args.base_url.rstrip("/"), trigger_logs_dir, args.ci_timeout)
        state["last_trigger_rc"] = rc
        state["last_trigger_logs_dir"] = str(trigger_logs_dir)
        event["triggered"] = True
        event["ci_returncode"] = rc
        event["ci_logs_dir"] = str(trigger_logs_dir)
        event["ci_stdout_preview"] = stdout_text.replace("\n", " ")[:280]
        event["ci_stderr_preview"] = stderr_text.replace("\n", " ")[:280]

    state["last_observed_at"] = now_iso
    state["last_details"] = signal.details
    _save_state(state_file, state)

    state_changed = any([
        bool(state.get("active_failure")) != bool(prev_state.get("active_failure")),
        str(state.get("active_signature") or "") != str(prev_state.get("active_signature") or ""),
        str(state.get("last_status") or "") != str(prev_state.get("last_status") or ""),
        str(state.get("observed_failure_signature") or "") != str(prev_state.get("observed_failure_signature") or ""),
    ])

    if args.log_all_events or decision.should_trigger or state_changed:
        events_log.parent.mkdir(parents=True, exist_ok=True)
        with events_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")

    print(json.dumps({
        "ts": now_iso,
        "severity": signal.severity,
        "failures": signal.failures,
        "decision": decision.reason,
        "triggered": event["triggered"],
        "ci_returncode": event["ci_returncode"],
        "ci_logs_dir": event["ci_logs_dir"],
        "failure_streak": state.get("failure_streak"),
        "healthy_streak": state.get("healthy_streak"),
        "active_failure": state.get("active_failure"),
        "trigger_count_24h": len(state.get("trigger_history") or []),
    }, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
