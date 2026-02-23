#!/usr/bin/env python3
"""
Passive proactive soak runner for Vera.

Goal:
- Observe autonomous behavior without forcing reflection/autonomy endpoints.
- Record whether Vera reaches out proactively and whether delivery evidence exists.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _safe_read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _request_json(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Tuple[bool, Any, str, int]:
    try:
        response = client.request(method, url, **kwargs)
    except Exception as exc:
        return False, None, str(exc), 0
    status = int(response.status_code)
    if status >= 400:
        try:
            return False, response.json(), response.text.strip(), status
        except Exception:
            return False, None, response.text.strip(), status
    try:
        return True, response.json(), "", status
    except Exception:
        return False, None, "non-json response", status


def _parse_recent_thoughts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    thoughts = payload.get("recent_thoughts")
    if not isinstance(thoughts, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in thoughts:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "run_id": str(row.get("run_id") or ""),
                "intent": str(row.get("intent") or ""),
                "timestamp": str(row.get("timestamp") or ""),
                "thought": str(row.get("thought") or ""),
            }
        )
    return out


def _parse_status(inner: Dict[str, Any]) -> Dict[str, Any]:
    stats = inner.get("stats") if isinstance(inner.get("stats"), dict) else {}
    autonomy = inner.get("autonomy") if isinstance(inner.get("autonomy"), dict) else {}
    last_cycle = autonomy.get("last_cycle_result") if isinstance(autonomy.get("last_cycle_result"), dict) else {}
    return {
        "total_reflections": int(stats.get("total_reflections") or 0),
        "last_reflection": str(stats.get("last_reflection") or ""),
        "delivery_channels": stats.get("delivery_channels") if isinstance(stats.get("delivery_channels"), list) else [],
        "phase": str(autonomy.get("phase") or ""),
        "cycle_running": bool(autonomy.get("cycle_running")),
        "last_cycle_utc": str(autonomy.get("last_cycle_utc") or ""),
        "seconds_until_transition": int(autonomy.get("seconds_until_transition") or 0),
        "reflection_outcome": str(last_cycle.get("reflection_outcome") or ""),
        "reflection_reason": str(last_cycle.get("reflection_reason") or ""),
        "followthrough_result": last_cycle.get("followthrough_result") if isinstance(last_cycle.get("followthrough_result"), dict) else {},
    }


def _read_log_tail_since(path: Path, start_offset: int) -> List[str]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, start_offset))
            payload = handle.read()
        text = payload.decode("utf-8", errors="replace")
        return text.splitlines()
    except Exception:
        return []


@dataclass
class SoakState:
    seen_run_ids: Set[str] = field(default_factory=set)
    new_reflection_runs: Set[str] = field(default_factory=set)
    reachout_runs: Set[str] = field(default_factory=set)
    readiness_failures: int = 0
    cycle_updates: int = 0
    samples: int = 0
    started_reflections: int = 0
    ended_reflections: int = 0
    last_cycle_utc: str = ""


def run_soak(
    *,
    base_url: str,
    duration_minutes: float,
    interval_seconds: int,
    output_json: Path,
    output_jsonl: Path,
    log_path: Path,
) -> int:
    start_ts = _utc_iso()
    started_at = time.time()
    deadline = started_at + max(1.0, duration_minutes * 60.0)
    state = SoakState()

    log_offset = log_path.stat().st_size if log_path.exists() else 0

    with httpx.Client(timeout=25.0) as client:
        ok, inner, err, code = _request_json(client, "GET", f"{base_url.rstrip('/')}/api/innerlife/status")
        if not ok or not isinstance(inner, dict):
            summary = {
                "ok": False,
                "started_at_utc": start_ts,
                "error": f"Failed to read innerlife status at start: code={code} err={err}",
                "base_url": base_url,
            }
            output_json.parent.mkdir(parents=True, exist_ok=True)
            output_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            return 1

        initial_status = _parse_status(inner)
        state.started_reflections = int(initial_status["total_reflections"])
        state.last_cycle_utc = str(initial_status["last_cycle_utc"] or "")

        for thought in _parse_recent_thoughts(inner):
            run_id = thought["run_id"]
            if run_id:
                state.seen_run_ids.add(run_id)

        while time.time() < deadline:
            sample_time = _utc_iso()
            sample: Dict[str, Any] = {
                "sample_at_utc": sample_time,
            }

            ready_ok, ready_payload, ready_err, ready_code = _request_json(
                client, "GET", f"{base_url.rstrip('/')}/api/readiness"
            )
            sample["readiness_code"] = ready_code
            sample["readiness_ok"] = bool(
                ready_ok
                and isinstance(ready_payload, dict)
                and ready_payload.get("ready") is True
            )
            sample["readiness_phase"] = str(ready_payload.get("phase") if isinstance(ready_payload, dict) else "")
            sample["readiness_error"] = ready_err
            if not sample["readiness_ok"]:
                state.readiness_failures += 1

            inner_ok, inner_payload, inner_err, inner_code = _request_json(
                client, "GET", f"{base_url.rstrip('/')}/api/innerlife/status"
            )
            sample["inner_status_code"] = inner_code
            sample["inner_status_ok"] = inner_ok and isinstance(inner_payload, dict)
            sample["inner_status_error"] = inner_err

            if isinstance(inner_payload, dict):
                parsed = _parse_status(inner_payload)
                sample["autonomy"] = parsed
                current_cycle_utc = str(parsed.get("last_cycle_utc") or "")
                if current_cycle_utc and current_cycle_utc != state.last_cycle_utc:
                    state.cycle_updates += 1
                    state.last_cycle_utc = current_cycle_utc

                thoughts = _parse_recent_thoughts(inner_payload)
                newly_seen: List[Dict[str, Any]] = []
                for thought in thoughts:
                    run_id = thought["run_id"]
                    if not run_id:
                        continue
                    if run_id in state.seen_run_ids:
                        continue
                    state.seen_run_ids.add(run_id)
                    state.new_reflection_runs.add(run_id)
                    newly_seen.append(thought)
                    if thought["intent"].upper() == "REACH_OUT":
                        state.reachout_runs.add(run_id)
                sample["new_runs"] = newly_seen
                sample["new_run_count"] = len(newly_seen)
                sample["reachout_runs_seen_total"] = len(state.reachout_runs)

            state.samples += 1
            _append_jsonl(output_jsonl, sample)

            remaining = deadline - time.time()
            if remaining <= 0:
                break
            time.sleep(min(max(1, interval_seconds), max(1, int(remaining))))

    final_inner = _safe_read_json(Path("/dev/null"))
    with httpx.Client(timeout=25.0) as client:
        ok, data, err, code = _request_json(client, "GET", f"{base_url.rstrip('/')}/api/innerlife/status")
        if ok and isinstance(data, dict):
            final_inner = data

    final_status = _parse_status(final_inner) if final_inner else {}
    state.ended_reflections = int(final_status.get("total_reflections") or state.started_reflections)

    added_logs = _read_log_tail_since(log_path, log_offset)
    run_outcome_pattern = re.compile(r"run_id=([a-f0-9]+)\s+outcome=([a-z_]+)")
    outcome_rows: List[Dict[str, str]] = []
    for line in added_logs:
        match = run_outcome_pattern.search(line)
        if not match:
            continue
        outcome_rows.append({"run_id": match.group(1), "outcome": match.group(2), "line": line})

    reachout_log_runs = [row for row in outcome_rows if row.get("outcome") == "reached_out"]
    fcm_success_pattern = re.compile(r"/fcm/send/.*HTTP/1\.1\"\s+201")
    fcm_success_count = sum(1 for line in added_logs if fcm_success_pattern.search(line))

    reached_out_with_fcm = 0
    for row in reachout_log_runs:
        line = row["line"]
        try:
            idx = added_logs.index(line)
        except ValueError:
            continue
        window = added_logs[idx : min(len(added_logs), idx + 120)]
        if any(fcm_success_pattern.search(w) for w in window):
            reached_out_with_fcm += 1

    pass_flags = {
        "service_ready_during_soak": state.readiness_failures == 0,
        "autonomy_cycles_observed": state.cycle_updates >= 1,
        "new_reflections_observed": (state.ended_reflections - state.started_reflections) >= 1 or len(state.new_reflection_runs) >= 1,
        "proactive_reachout_observed": len(state.reachout_runs) >= 1 or len(reachout_log_runs) >= 1,
        "delivery_evidence_observed": reached_out_with_fcm >= 1 or fcm_success_count >= 1,
    }
    overall_ok = all(pass_flags.values())

    summary = {
        "ok": overall_ok,
        "started_at_utc": start_ts,
        "ended_at_utc": _utc_iso(),
        "duration_minutes": duration_minutes,
        "interval_seconds": interval_seconds,
        "base_url": base_url,
        "log_path": str(log_path),
        "log_offset_start": log_offset,
        "samples_jsonl": str(output_jsonl),
        "samples_count": state.samples,
        "started_reflections": state.started_reflections,
        "ended_reflections": state.ended_reflections,
        "reflection_delta": state.ended_reflections - state.started_reflections,
        "autonomy_cycle_updates": state.cycle_updates,
        "readiness_failures": state.readiness_failures,
        "new_reflection_runs": sorted(state.new_reflection_runs),
        "reachout_runs_from_recent_thoughts": sorted(state.reachout_runs),
        "log_run_outcomes": outcome_rows[-40:],
        "log_reached_out_runs": reachout_log_runs[-20:],
        "fcm_success_count": fcm_success_count,
        "reached_out_with_fcm_count": reached_out_with_fcm,
        "pass_flags": pass_flags,
        "final_status": final_status,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"ok": overall_ok, "summary": str(output_json), "samples": str(output_jsonl)}, indent=2))
    return 0 if overall_ok else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Passive proactive soak runner for Vera")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--duration-minutes", type=float, default=60.0)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--output", default="")
    parser.add_argument("--samples-output", default="")
    parser.add_argument("--log-path", default="logs/vera_debug.log")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ts = _utc_ts()
    output = Path(args.output) if args.output else (root / "tmp" / "soak" / f"vera_proactive_soak_summary_{ts}.json")
    samples = (
        Path(args.samples_output)
        if args.samples_output
        else (root / "tmp" / "soak" / f"vera_proactive_soak_samples_{ts}.jsonl")
    )
    log_path = Path(args.log_path)
    if not log_path.is_absolute():
        log_path = root / log_path

    return run_soak(
        base_url=args.base_url,
        duration_minutes=max(1.0, args.duration_minutes),
        interval_seconds=max(5, args.interval_seconds),
        output_json=output,
        output_jsonl=samples,
        log_path=log_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
