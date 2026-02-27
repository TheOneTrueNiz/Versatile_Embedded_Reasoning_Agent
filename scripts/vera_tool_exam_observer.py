#!/usr/bin/env python3
"""Live observer for long-running Vera tool exam battery campaigns.

Tracks:
- active process state
- per-tier progress inferred from flight-recorder transitions
- elapsed and ETA
- stall detection
- final pass/fail counts once report JSON is written
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, request


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_json_load(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_json_dump(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _extract_conversation_id(context_snapshot: Any) -> str:
    if isinstance(context_snapshot, dict):
        value = context_snapshot.get("conversation_id")
        return str(value) if value not in (None, "") else ""
    if isinstance(context_snapshot, str) and "conversation_id" in context_snapshot:
        try:
            parsed = json.loads(context_snapshot)
        except Exception:
            return ""
        if isinstance(parsed, dict):
            value = parsed.get("conversation_id")
            return str(value) if value not in (None, "") else ""
    return ""


def _parse_iso_naive(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _seconds_since(ts_iso: str) -> Optional[int]:
    ts = _parse_iso_naive(ts_iso)
    if ts is None:
        return None
    return max(0, int((datetime.now() - ts).total_seconds()))


def _human_seconds(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    seconds = int(max(0, value))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h{m:02d}m"
    if m > 0:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _http_json(url: str, timeout: float = 5.0) -> Tuple[bool, Any, str]:
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=max(0.5, float(timeout))) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return True, json.loads(raw), ""
            except Exception:
                return False, None, "non_json_response"
    except error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return False, None, f"http_{exc.code}:{body[:180]}"
    except Exception as exc:
        return False, None, str(exc)


def _discover_tier1_total(base_url: str) -> Optional[int]:
    ok, payload, _ = _http_json(f"{base_url.rstrip('/')}/api/tools/list", timeout=8.0)
    if not ok or not isinstance(payload, dict):
        return None
    tool_names: set[str] = set()
    servers = payload.get("tools")
    if isinstance(servers, dict):
        for names in servers.values():
            if isinstance(names, list):
                for item in names:
                    value = str(item or "").strip()
                    if value:
                        tool_names.add(value)
    native = payload.get("native_tools")
    if isinstance(native, list):
        for item in native:
            value = str(item or "").strip()
            if value:
                tool_names.add(value)
    if not tool_names:
        return None
    return len(tool_names)


def _load_tier2_total(path: Path) -> int:
    payload = _safe_json_load(path)
    scenarios = payload.get("scenarios")
    if isinstance(scenarios, list):
        return len([row for row in scenarios if isinstance(row, dict)])
    return 0


def _find_running_process(process_pattern: str, run_id: str) -> Dict[str, Any]:
    cmd = ["bash", "-lc", f"pgrep -af \"{process_pattern}\" || true"]
    try:
        raw = subprocess.check_output(cmd, text=True)
    except Exception:
        raw = ""
    rows: List[Tuple[int, str]] = []
    self_pid = os.getpid()
    for line in (raw or "").splitlines():
        parts = line.strip().split(" ", 1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except Exception:
            continue
        if pid == self_pid:
            continue
        command = parts[1] if len(parts) > 1 else ""
        if "pgrep -af" in command:
            continue
        if "vera_tool_exam_observer.py" in command:
            continue
        if run_id and run_id not in command:
            continue
        rows.append((pid, command))

    if not rows and run_id:
        for line in (raw or "").splitlines():
            parts = line.strip().split(" ", 1)
            if not parts:
                continue
            try:
                pid = int(parts[0])
            except Exception:
                continue
            if pid == self_pid:
                continue
            command = parts[1] if len(parts) > 1 else ""
            if "pgrep -af" in command:
                continue
            if "vera_tool_exam_observer.py" in command:
                continue
            rows.append((pid, command))

    if not rows:
        return {
            "running": False,
            "pid": None,
            "cmd": "",
            "elapsed_s": None,
        }

    pid, command = rows[0]
    elapsed_s: Optional[int] = None
    try:
        out = subprocess.check_output(
            ["bash", "-lc", f"ps -o etimes= -p {pid}"],
            text=True,
        ).strip()
        if out:
            elapsed_s = int(out)
    except Exception:
        elapsed_s = None

    return {
        "running": True,
        "pid": pid,
        "cmd": command,
        "elapsed_s": elapsed_s,
    }


@dataclass
class ProgressState:
    tier1_seen: set[int] = field(default_factory=set)
    tier2_seen: set[int] = field(default_factory=set)
    tier1_max_idx: int = 0
    tier2_max_idx: int = 0
    first_transition_ts: str = ""
    last_transition_ts: str = ""
    last_conversation_id: str = ""
    lines_scanned: int = 0
    file_offset: int = 0


def _apply_transition_line(state: ProgressState, line: str, run_id: str, t1_re: re.Pattern[str], t2_re: re.Pattern[str]) -> None:
    text = line.strip()
    if not text:
        return
    try:
        payload = json.loads(text)
    except Exception:
        return
    context_snapshot = payload.get("context_snapshot")
    conversation_id = _extract_conversation_id(context_snapshot)
    if not conversation_id:
        return
    if run_id and run_id not in conversation_id:
        return
    state.last_conversation_id = conversation_id

    timestamp = str(payload.get("timestamp") or "")
    if timestamp:
        if not state.first_transition_ts:
            state.first_transition_ts = timestamp
        state.last_transition_ts = timestamp

    t1_match = t1_re.search(conversation_id)
    if t1_match:
        idx = int(t1_match.group(1))
        state.tier1_seen.add(idx)
        if idx > state.tier1_max_idx:
            state.tier1_max_idx = idx

    t2_match = t2_re.search(conversation_id)
    if t2_match:
        idx = int(t2_match.group(1))
        state.tier2_seen.add(idx)
        if idx > state.tier2_max_idx:
            state.tier2_max_idx = idx


def _parse_current_test(conversation_id: str, run_id: str) -> Dict[str, Any]:
    cid = str(conversation_id or "").strip()
    if not cid:
        return {}
    if run_id and not cid.startswith(f"{run_id}-"):
        return {}
    suffix = cid[len(run_id) + 1 :] if run_id else cid
    m1 = re.match(r"tier1-(\d{4})-(.+)$", suffix)
    if m1:
        return {
            "tier": "tier1",
            "index": int(m1.group(1)),
            "label": m1.group(2),
            "conversation_id": cid,
        }
    m2 = re.match(r"tier2-(\d{3})-(.+)$", suffix)
    if m2:
        return {
            "tier": "tier2",
            "index": int(m2.group(1)),
            "label": m2.group(2),
            "conversation_id": cid,
        }
    return {"tier": "unknown", "index": None, "label": suffix, "conversation_id": cid}


def _bootstrap_transitions(path: Path, run_id: str, state: ProgressState, t1_re: re.Pattern[str], t2_re: re.Pattern[str]) -> None:
    if not path.exists():
        state.file_offset = 0
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            state.lines_scanned += 1
            _apply_transition_line(state, line, run_id, t1_re, t2_re)
        state.file_offset = handle.tell()


def _update_transitions(path: Path, run_id: str, state: ProgressState, t1_re: re.Pattern[str], t2_re: re.Pattern[str]) -> None:
    if not path.exists():
        state.file_offset = 0
        return
    size = path.stat().st_size
    if size < state.file_offset:
        state.file_offset = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(state.file_offset)
        for line in handle:
            state.lines_scanned += 1
            _apply_transition_line(state, line, run_id, t1_re, t2_re)
        state.file_offset = handle.tell()


def _report_counts(report_path: Path) -> Dict[str, Any]:
    if not report_path.exists():
        return {"exists": False}
    payload = _safe_json_load(report_path)
    if not isinstance(payload, dict):
        return {"exists": False, "invalid_report": True}
    # Guard against observer/campaign files that may also contain tier1/tier2 keys.
    if "overall_ok" not in payload or "config" not in payload or "discovery" not in payload:
        return {"exists": False, "invalid_report": True}
    tier1_obj = payload.get("tier1")
    tier2_obj = payload.get("tier2")
    if not isinstance(tier1_obj, dict) or not isinstance(tier2_obj, dict):
        return {"exists": False, "invalid_report": True}
    tier1 = tier1_obj
    tier2 = tier2_obj
    return {
        "exists": True,
        "overall_ok": bool(payload.get("overall_ok")),
        "tier1": {k: int(tier1.get(k) or 0) for k in ("passed", "failed", "skipped", "total")},
        "tier2": {k: int(tier2.get(k) or 0) for k in ("passed", "failed", "skipped", "total")},
    }


def _build_snapshot(
    *,
    run_id: str,
    process: Dict[str, Any],
    base_url: str,
    tier1_total: Optional[int],
    tier2_total: int,
    state: ProgressState,
    report_info: Dict[str, Any],
    stall_seconds: int,
    halted: bool,
) -> Dict[str, Any]:
    api_ok, health_payload, api_error = _http_json(f"{base_url.rstrip('/')}/api/health", timeout=4.0)
    readiness_ok, readiness_payload, readiness_error = _http_json(
        f"{base_url.rstrip('/')}/api/readiness", timeout=4.0
    )

    t1_seen = len(state.tier1_seen)
    t2_seen = len(state.tier2_seen)
    # Tier indexes are monotonic and better reflect campaign progress than
    # sparse transition counts when some attempts emit fewer transition rows.
    t1_progress = max(t1_seen, int(state.tier1_max_idx))
    t2_progress = max(t2_seen, int(state.tier2_max_idx))
    processed = t1_progress + t2_progress
    total: Optional[int] = None
    if tier1_total is not None and tier1_total > 0:
        total = int(tier1_total) + int(max(0, tier2_total))

    report_exists = bool(report_info.get("exists"))
    passed: Optional[int] = None
    failed: Optional[int] = None
    skipped: Optional[int] = None
    if report_exists:
        t1 = report_info.get("tier1", {})
        t2 = report_info.get("tier2", {})
        passed = int(t1.get("passed", 0)) + int(t2.get("passed", 0))
        failed = int(t1.get("failed", 0)) + int(t2.get("failed", 0))
        skipped = int(t1.get("skipped", 0)) + int(t2.get("skipped", 0))
        total = int(t1.get("total", 0)) + int(t2.get("total", 0))
        processed = total

    remaining: Optional[int] = None
    if total is not None:
        remaining = max(0, int(total) - int(processed))

    elapsed_s: Optional[int] = process.get("elapsed_s")
    if elapsed_s is None and state.first_transition_ts:
        first = _parse_iso_naive(state.first_transition_ts)
        if first is not None:
            elapsed_s = max(0, int((datetime.now() - first).total_seconds()))

    eta_s: Optional[float] = None
    if elapsed_s is not None and total is not None and processed > 0 and remaining is not None and remaining > 0:
        rate = float(processed) / float(max(1, elapsed_s))
        if rate > 0:
            eta_s = float(remaining) / rate

    since_last = _seconds_since(state.last_transition_ts) if state.last_transition_ts else None
    stalled = bool(
        process.get("running")
        and since_last is not None
        and since_last >= max(30, int(stall_seconds))
    )

    if report_exists:
        run_state = "completed"
    elif halted and not process.get("running"):
        run_state = "halted"
    elif halted and not (api_ok or readiness_ok):
        run_state = "halted"
    elif process.get("running"):
        run_state = "stalled" if stalled else "running"
    else:
        run_state = "stopped"

    current_test = _parse_current_test(state.last_conversation_id, run_id)

    snapshot: Dict[str, Any] = {
        "timestamp_utc": _utc_iso(),
        "run_id": run_id,
        "state": run_state,
        "process": process,
        "api": {
            "health_reachable": bool(api_ok),
            "health_ok": bool(api_ok and isinstance(health_payload, dict) and health_payload.get("ok") is True),
            "health_error": api_error,
            "readiness_reachable": bool(readiness_ok),
            "readiness_ready": bool(
                readiness_ok and isinstance(readiness_payload, dict) and readiness_payload.get("ready") is True
            ),
            "readiness_error": readiness_error,
        },
        "tier1": {
            "seen_count": t1_seen,
            "max_index_seen": int(state.tier1_max_idx),
            "progress_index": int(t1_progress),
            "total_expected": tier1_total,
            "remaining_estimate": (None if tier1_total is None else max(0, int(tier1_total) - int(t1_progress))),
        },
        "tier2": {
            "seen_count": t2_seen,
            "max_index_seen": int(state.tier2_max_idx),
            "progress_index": int(t2_progress),
            "total_expected": int(max(0, tier2_total)),
            "remaining_estimate": max(0, int(max(0, tier2_total)) - int(t2_progress)),
        },
        "tests": {
            "processed": int(processed),
            "total": total,
            "remaining": remaining,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pass_fail_known": report_exists,
        },
        "timing": {
            "elapsed_s": elapsed_s,
            "elapsed_human": _human_seconds(elapsed_s),
            "eta_s": eta_s,
            "eta_human": _human_seconds(eta_s),
            "last_transition_ts": state.last_transition_ts,
            "seconds_since_last_transition": since_last,
        },
        "stall": {
            "threshold_s": int(stall_seconds),
            "is_stalled": stalled,
        },
        "runtime": {
            "manual_halt": bool(halted),
        },
        "current_test": current_test,
        "report": report_info,
        "observer": {
            "lines_scanned": int(state.lines_scanned),
            "file_offset": int(state.file_offset),
        },
    }
    return snapshot


def _infer_report_path(root: Path, run_id: str) -> Optional[Path]:
    if not run_id:
        return None
    candidate = root / "tmp" / "audits" / f"{run_id}_tool_exam_full_post_patch_8788.json"
    if candidate.exists():
        return candidate
    hits = sorted((root / "tmp" / "audits").glob(f"{run_id}*.json"))
    for hit in reversed(hits):
        name = hit.name
        if "observer" in name:
            continue
        payload = _safe_json_load(hit)
        if (
            isinstance(payload, dict)
            and "overall_ok" in payload
            and "config" in payload
            and "discovery" in payload
            and isinstance(payload.get("tier1"), dict)
            and isinstance(payload.get("tier2"), dict)
        ):
            return hit
    return None


def _print_line(snapshot: Dict[str, Any]) -> None:
    tests = snapshot.get("tests", {})
    timing = snapshot.get("timing", {})
    stall = snapshot.get("stall", {})
    api = snapshot.get("api", {})
    current_test = snapshot.get("current_test", {})
    current_tier = str(current_test.get("tier") or "n/a")
    current_idx = current_test.get("index")
    current_label = str(current_test.get("label") or "n/a")
    if current_idx is None:
        current_id = f"{current_tier}:{current_label}"
    else:
        current_id = f"{current_tier}:{current_idx}:{current_label}"
    print(
        (
            f"[{snapshot.get('timestamp_utc')}] state={snapshot.get('state')} "
            f"current={current_id} "
            f"processed={tests.get('processed')}/{tests.get('total') or '?'} "
            f"remaining={tests.get('remaining') if tests.get('remaining') is not None else '?'} "
            f"pass={tests.get('passed') if tests.get('passed') is not None else '?'} "
            f"fail={tests.get('failed') if tests.get('failed') is not None else '?'} "
            f"elapsed={timing.get('elapsed_human')} "
            f"eta={timing.get('eta_human')} "
            f"api_ready={api.get('readiness_ready')} "
            f"stalled={stall.get('is_stalled')} "
            f"last_event_age={_human_seconds(timing.get('seconds_since_last_transition'))}"
        ),
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe Vera tool exam battery progress")
    parser.add_argument("--run-id", required=True, help="Run id prefix used in conversation IDs (tool-exam-<ts>)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--transitions", default="vera_memory/flight_recorder/transitions.ndjson")
    parser.add_argument(
        "--scenarios-path",
        default="config/doctor_professor/vera_tool_exam_tier2_scenarios.json",
    )
    parser.add_argument("--tier1-total", type=int, default=0, help="Override expected tier1 total (0=discover)")
    parser.add_argument("--report-path", default="", help="Expected final report path")
    parser.add_argument("--process-pattern", default="vera_tool_exam_battery.py")
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--stall-seconds", type=int, default=600)
    parser.add_argument("--watch", action="store_true", help="Loop until completion/stall/max-seconds")
    parser.add_argument("--exit-on-stall", action="store_true")
    parser.add_argument("--max-seconds", type=int, default=0, help="Stop after N seconds when --watch is enabled")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-jsonl", default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    run_id = str(args.run_id).strip()
    transitions_path = root / args.transitions
    halt_path = root / "vera_memory" / "manual_halt"
    tier2_total = _load_tier2_total(root / args.scenarios_path)

    report_path = Path(args.report_path).expanduser() if args.report_path else None
    if report_path is None or str(report_path).strip() == "":
        report_path = _infer_report_path(root, run_id)
    if report_path is None:
        report_path = root / "tmp" / "audits" / f"{run_id}_tool_exam_report.json"

    ts = _utc_ts()
    out_json = Path(args.output_json) if args.output_json else (root / "tmp" / "audits" / f"{run_id}_observer_{ts}.json")
    out_jsonl = Path(args.output_jsonl) if args.output_jsonl else (root / "tmp" / "audits" / f"{run_id}_observer_{ts}.jsonl")

    t1_re = re.compile(rf"{re.escape(run_id)}-tier1-(\d{{4}})-")
    t2_re = re.compile(rf"{re.escape(run_id)}-tier2-(\d{{3}})-")
    state = ProgressState()
    _bootstrap_transitions(transitions_path, run_id, state, t1_re, t2_re)

    discovered_tier1_total: Optional[int] = int(args.tier1_total) if int(args.tier1_total) > 0 else None
    start_time = time.time()

    def _sample() -> Dict[str, Any]:
        nonlocal discovered_tier1_total
        _update_transitions(transitions_path, run_id, state, t1_re, t2_re)
        process = _find_running_process(args.process_pattern, run_id)
        if discovered_tier1_total is None:
            discovered_tier1_total = _discover_tier1_total(args.base_url)
        report_info = _report_counts(report_path)
        snapshot = _build_snapshot(
            run_id=run_id,
            process=process,
            base_url=args.base_url,
            tier1_total=discovered_tier1_total,
            tier2_total=tier2_total,
            state=state,
            report_info=report_info,
            stall_seconds=max(30, int(args.stall_seconds)),
            halted=halt_path.exists(),
        )
        _safe_json_dump(out_json, snapshot)
        _append_jsonl(out_jsonl, snapshot)
        _print_line(snapshot)
        return snapshot

    snapshot = _sample()
    if not args.watch:
        return 0

    deadline = start_time + max(0, int(args.max_seconds)) if int(args.max_seconds) > 0 else None
    while True:
        if snapshot.get("state") == "completed":
            report = snapshot.get("report", {})
            return 0 if bool(report.get("overall_ok")) else 1
        if args.exit_on_stall and bool((snapshot.get("stall") or {}).get("is_stalled")):
            return 2
        if deadline is not None and time.time() >= deadline:
            return 0
        time.sleep(max(2, int(args.poll_seconds)))
        snapshot = _sample()


if __name__ == "__main__":
    raise SystemExit(main())
