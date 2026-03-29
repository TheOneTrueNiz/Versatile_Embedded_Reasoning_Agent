"""
Autonomy Runplane
=================

Deterministic runtime control-plane for proactive/autonomy jobs.

Provides:
- Durable JobStore + RunStore in a single atomic state file.
- Per-lane serialization (one active run per lane).
- Restart-safe stale lane cleanup.
- Dead-letter tracking for exhausted failures.
- Lightweight SLO snapshot metrics for operator surfaces.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.atomic_io import atomic_json_write, safe_json_read


_ALLOWED_JOB_STATES = {
    "planned",
    "due",
    "deferred",
    "running",
    "delivered",
    "acked",
    "escalated",
    "closed",
    "failed",
    "dead_letter",
}

_ACK_REQUIRED_CHANNELS = {
    "apns",
    "fcm",
    "native_push",
    "push",
    "web_push",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _normalize_delivery_channels(value: Any) -> List[str]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        return []
    out: List[str] = []
    seen = set()
    for item in raw_items:
        channel = str(item or "").strip().lower()
        if not channel or channel in seen:
            continue
        seen.add(channel)
        out.append(channel)
    return out


def _count_by_rows(
    rows: List[Dict[str, Any]],
    *,
    status: str,
    field: str,
    unknown: str = "unknown",
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    target_status = str(status or "").strip().lower()
    target_field = str(field or "").strip()
    if not target_status or not target_field:
        return counts
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").strip().lower() != target_status:
            continue
        raw_value = row.get(target_field)
        value = str(raw_value or "").strip() or unknown
        counts[value] = int(counts.get(value, 0)) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def ack_required_delivery_channels(value: Any) -> List[str]:
    return [channel for channel in _normalize_delivery_channels(value) if channel in _ACK_REQUIRED_CHANNELS]


def run_requires_ack(row: Dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    for container in (row.get("result"), row.get("metadata"), row):
        if not isinstance(container, dict):
            continue
        explicit = _coerce_optional_bool(container.get("ack_expected"))
        if explicit is not None:
            return explicit
        ack_channels = ack_required_delivery_channels(container.get("ack_channels"))
        if ack_channels:
            return True
        delivered_to = ack_required_delivery_channels(container.get("delivered_to"))
        if delivered_to:
            return True
    return False


class AutonomyRunplane:
    """Durable jobs/runs/dead-letter runtime state for autonomy execution."""

    def __init__(
        self,
        storage_dir: Path,
        *,
        max_runs: int = 4000,
        max_dead_letters: int = 800,
        stale_lane_seconds: int = 1800,
    ) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self._storage_dir / "runplane_state.json"
        self._max_runs = max(200, int(max_runs))
        self._max_dead_letters = max(50, int(max_dead_letters))
        self._stale_lane_seconds = max(60, int(stale_lane_seconds))
        self._lock = threading.RLock()
        if not self._state_path.exists():
            self._save_state(self._default_state())

    def _default_state(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "updated_at_utc": _utc_iso(),
            "jobs": {},
            "runs": [],
            "dead_letters": [],
            "active_lanes": {},
        }

    def _load_state(self) -> Dict[str, Any]:
        payload = safe_json_read(self._state_path, default={}) or {}
        if not isinstance(payload, dict) or not payload:
            return self._default_state()
        state = self._default_state()
        state.update(payload)

        jobs = state.get("jobs")
        if not isinstance(jobs, dict):
            state["jobs"] = {}

        runs = state.get("runs")
        if not isinstance(runs, list):
            state["runs"] = []

        dead_letters = state.get("dead_letters")
        if not isinstance(dead_letters, list):
            state["dead_letters"] = []

        active_lanes = state.get("active_lanes")
        if not isinstance(active_lanes, dict):
            state["active_lanes"] = {}

        return state

    def _save_state(self, state: Dict[str, Any]) -> None:
        state["updated_at_utc"] = _utc_iso()
        atomic_json_write(self._state_path, state, indent=2, sort_keys=False)

    @staticmethod
    def _trim_text(value: Any, limit: int = 1600) -> str:
        text = str(value or "")
        return text[:limit]

    def _ensure_job_unlocked(
        self,
        state: Dict[str, Any],
        *,
        job_id: str,
        lane_key: str,
        kind: str,
        metadata: Optional[Dict[str, Any]],
        max_attempts: int,
    ) -> Dict[str, Any]:
        jobs = state.setdefault("jobs", {})
        now = _utc_iso()
        row = jobs.get(job_id)
        if not isinstance(row, dict):
            row = {
                "job_id": job_id,
                "lane_key": lane_key,
                "kind": kind,
                "state": "planned",
                "created_at_utc": now,
                "updated_at_utc": now,
                "attempt_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "max_attempts": max(1, int(max_attempts)),
                "last_run_id": "",
                "last_attempt_at_utc": "",
                "last_success_at_utc": "",
                "last_error": "",
                "last_failure_class": "",
                "last_delivered_at_utc": "",
                "last_acked_at_utc": "",
                "next_retry_at_utc": "",
                "metadata": dict(metadata or {}),
            }
            jobs[job_id] = row
            return row

        row["lane_key"] = lane_key or str(row.get("lane_key") or job_id)
        row["kind"] = kind or str(row.get("kind") or "generic")
        row["max_attempts"] = max(1, int(row.get("max_attempts") or max_attempts or 1))
        if isinstance(metadata, dict) and metadata:
            merged_meta = dict(row.get("metadata") or {})
            merged_meta.update(metadata)
            row["metadata"] = merged_meta
        if str(row.get("state") or "") not in _ALLOWED_JOB_STATES:
            row["state"] = "planned"
        row["updated_at_utc"] = now
        return row

    def _find_run_index_unlocked(self, runs: List[Dict[str, Any]], run_id: str) -> int:
        for idx in range(len(runs) - 1, -1, -1):
            row = runs[idx]
            if isinstance(row, dict) and str(row.get("run_id") or "") == run_id:
                return idx
        return -1

    def _find_alias_run_index_unlocked(self, runs: List[Dict[str, Any]], alias_run_id: str) -> int:
        target = str(alias_run_id or "").strip()
        if not target:
            return -1
        alias_keys = {"external_run_id", "innerlife_run_id", "reachout_run_id"}
        for idx in range(len(runs) - 1, -1, -1):
            row = runs[idx]
            if not isinstance(row, dict):
                continue
            metadata = row.get("metadata")
            if isinstance(metadata, dict):
                for key in alias_keys:
                    if str(metadata.get(key) or "").strip() == target:
                        return idx
            result = row.get("result")
            if isinstance(result, dict):
                for key in alias_keys:
                    if str(result.get(key) or "").strip() == target:
                        return idx
        return -1

    def _cleanup_stale_lanes_unlocked(self, state: Dict[str, Any]) -> int:
        active_lanes = state.setdefault("active_lanes", {})
        if not isinstance(active_lanes, dict) or not active_lanes:
            return 0

        runs = state.setdefault("runs", [])
        jobs = state.setdefault("jobs", {})
        now = _utc_now()
        released = 0
        to_delete: List[str] = []
        for lane_key, lane_row in active_lanes.items():
            if not isinstance(lane_row, dict):
                to_delete.append(lane_key)
                continue

            started_at = _parse_utc(lane_row.get("started_at_utc"))
            run_id = str(lane_row.get("run_id") or "").strip()
            job_id = str(lane_row.get("job_id") or "").strip()
            if not started_at:
                to_delete.append(lane_key)
                continue
            if (now - started_at).total_seconds() < float(self._stale_lane_seconds):
                continue

            to_delete.append(lane_key)
            released += 1

            run_idx = self._find_run_index_unlocked(runs, run_id) if run_id else -1
            if run_idx >= 0:
                run_row = runs[run_idx]
                run_row["status"] = "failed"
                run_row["failure_class"] = "stale_lane"
                run_row["retryable"] = True
                run_row["retry_after_seconds"] = 60
                run_row["finished_at_utc"] = _utc_iso()
                run_row["result"] = {
                    "error": "stale_lane_cleanup",
                    "detail": f"Lane '{lane_key}' released after stale timeout",
                }

            if job_id and isinstance(jobs.get(job_id), dict):
                job_row = jobs[job_id]
                job_row["state"] = "due"
                job_row["last_error"] = "stale_lane_cleanup"
                job_row["last_failure_class"] = "stale_lane"
                job_row["updated_at_utc"] = _utc_iso()
                job_row["next_retry_at_utc"] = (now + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")

        for lane_key in to_delete:
            active_lanes.pop(lane_key, None)
        return released

    def ensure_job(
        self,
        *,
        job_id: str,
        lane_key: str,
        kind: str = "generic",
        metadata: Optional[Dict[str, Any]] = None,
        max_attempts: int = 3,
    ) -> Dict[str, Any]:
        job_id = str(job_id or "").strip()
        if not job_id:
            raise ValueError("job_id is required")
        lane_key = str(lane_key or job_id).strip() or job_id
        with self._lock:
            state = self._load_state()
            self._cleanup_stale_lanes_unlocked(state)
            job = self._ensure_job_unlocked(
                state,
                job_id=job_id,
                lane_key=lane_key,
                kind=kind,
                metadata=metadata,
                max_attempts=max_attempts,
            )
            self._save_state(state)
            return dict(job)

    def begin_run(
        self,
        *,
        job_id: str,
        lane_key: str,
        trigger: str,
        kind: str = "generic",
        metadata: Optional[Dict[str, Any]] = None,
        max_attempts: int = 3,
    ) -> Dict[str, Any]:
        job_id = str(job_id or "").strip()
        if not job_id:
            return {"ok": False, "reason": "missing_job_id"}
        lane_key = str(lane_key or job_id).strip() or job_id
        trigger = str(trigger or "unspecified").strip() or "unspecified"

        with self._lock:
            state = self._load_state()
            self._cleanup_stale_lanes_unlocked(state)
            job = self._ensure_job_unlocked(
                state,
                job_id=job_id,
                lane_key=lane_key,
                kind=kind,
                metadata=metadata,
                max_attempts=max_attempts,
            )

            active_lanes = state.setdefault("active_lanes", {})
            lane_row = active_lanes.get(lane_key)
            if isinstance(lane_row, dict):
                active_run_id = str(lane_row.get("run_id") or "").strip()
                started_at = str(lane_row.get("started_at_utc") or "")
                return {
                    "ok": False,
                    "reason": "lane_busy",
                    "job_id": job_id,
                    "lane_key": lane_key,
                    "active_run_id": active_run_id,
                    "active_started_at_utc": started_at,
                }

            now_iso = _utc_iso()
            run_id = f"run_{uuid.uuid4().hex}"
            attempt_no = int(job.get("attempt_count") or 0) + 1
            run_row: Dict[str, Any] = {
                "run_id": run_id,
                "job_id": job_id,
                "lane_key": lane_key,
                "kind": kind,
                "trigger": trigger,
                "status": "running",
                "attempt_no": attempt_no,
                "started_at_utc": now_iso,
                "finished_at_utc": "",
                "duration_ms": 0,
                "failure_class": "",
                "retryable": False,
                "retry_after_seconds": 0,
                "result": {},
                "metadata": dict(metadata or {}),
            }
            runs = state.setdefault("runs", [])
            runs.append(run_row)
            if len(runs) > self._max_runs:
                state["runs"] = runs[-self._max_runs :]

            active_lanes[lane_key] = {
                "run_id": run_id,
                "job_id": job_id,
                "started_at_utc": now_iso,
            }

            job["state"] = "running"
            job["attempt_count"] = attempt_no
            job["last_run_id"] = run_id
            job["last_attempt_at_utc"] = now_iso
            job["updated_at_utc"] = now_iso

            self._save_state(state)
            return {
                "ok": True,
                "run_id": run_id,
                "job_id": job_id,
                "lane_key": lane_key,
                "attempt_no": attempt_no,
                "started_at_utc": now_iso,
            }

    @staticmethod
    def _compute_backoff_seconds(failure_count: int) -> int:
        # Deterministic bounded exponential backoff.
        step = max(0, int(failure_count) - 1)
        return min(3600, 15 * (2 ** min(step, 7)))

    def complete_run(
        self,
        *,
        job_id: str,
        run_id: str,
        ok: bool,
        result: Optional[Dict[str, Any]] = None,
        failure_class: str = "",
        retryable: bool = False,
        status: str = "",
    ) -> Dict[str, Any]:
        job_id = str(job_id or "").strip()
        run_id = str(run_id or "").strip()
        if not job_id or not run_id:
            return {"ok": False, "reason": "missing_identifiers"}

        with self._lock:
            state = self._load_state()
            runs = state.setdefault("runs", [])
            run_idx = self._find_run_index_unlocked(runs, run_id)
            if run_idx < 0:
                return {"ok": False, "reason": "run_not_found", "job_id": job_id, "run_id": run_id}

            run_row = runs[run_idx]
            jobs = state.setdefault("jobs", {})
            job_row = jobs.get(job_id)
            if not isinstance(job_row, dict):
                job_row = self._ensure_job_unlocked(
                    state,
                    job_id=job_id,
                    lane_key=str(run_row.get("lane_key") or job_id),
                    kind=str(run_row.get("kind") or "generic"),
                    metadata=None,
                    max_attempts=3,
                )

            now = _utc_now()
            now_iso = now.isoformat().replace("+00:00", "Z")
            started = _parse_utc(run_row.get("started_at_utc"))
            duration_ms = 0
            if started is not None:
                duration_ms = max(0, int((now - started).total_seconds() * 1000.0))

            normalized_status = str(status or "").strip().lower()
            if not normalized_status:
                normalized_status = "delivered" if ok else "failed"
            if normalized_status not in _ALLOWED_JOB_STATES:
                normalized_status = "failed" if not ok else "delivered"

            failure_class = str(failure_class or "").strip().lower()
            retryable = bool(retryable)

            run_row["status"] = normalized_status
            run_row["finished_at_utc"] = now_iso
            run_row["duration_ms"] = duration_ms
            run_row["failure_class"] = failure_class
            run_row["retryable"] = retryable
            run_row["result"] = dict(result or {})

            active_lanes = state.setdefault("active_lanes", {})
            lane_key = str(run_row.get("lane_key") or "").strip()
            lane_row = active_lanes.get(lane_key)
            if isinstance(lane_row, dict) and str(lane_row.get("run_id") or "").strip() == run_id:
                active_lanes.pop(lane_key, None)

            if ok:
                job_row["state"] = normalized_status if normalized_status in {"delivered", "acked", "closed"} else "delivered"
                job_row["success_count"] = int(job_row.get("success_count") or 0) + 1
                job_row["last_success_at_utc"] = now_iso
                job_row["last_delivered_at_utc"] = now_iso
                job_row["last_error"] = ""
                job_row["last_failure_class"] = ""
                job_row["next_retry_at_utc"] = ""
            else:
                failure_count = int(job_row.get("failure_count") or 0) + 1
                job_row["failure_count"] = failure_count
                job_row["last_error"] = self._trim_text((result or {}).get("stderr") or (result or {}).get("reason") or "run_failed")
                job_row["last_failure_class"] = failure_class or "unknown"

                max_attempts = max(1, int(job_row.get("max_attempts") or 1))
                if normalized_status == "dead_letter" or (not retryable and failure_count >= max_attempts):
                    job_row["state"] = "dead_letter"
                    dead_letter_row = {
                        "timestamp_utc": now_iso,
                        "job_id": job_id,
                        "run_id": run_id,
                        "lane_key": lane_key,
                        "failure_class": failure_class or "unknown",
                        "failure_count": failure_count,
                        "max_attempts": max_attempts,
                        "result": dict(result or {}),
                    }
                    dead_letters = state.setdefault("dead_letters", [])
                    dead_letters.append(dead_letter_row)
                    if len(dead_letters) > self._max_dead_letters:
                        state["dead_letters"] = dead_letters[-self._max_dead_letters :]
                    run_row["status"] = "dead_letter"
                    run_row["retryable"] = False
                    run_row["retry_after_seconds"] = 0
                    job_row["next_retry_at_utc"] = ""
                elif retryable:
                    backoff = self._compute_backoff_seconds(failure_count)
                    retry_at = now + timedelta(seconds=backoff)
                    job_row["state"] = "due"
                    job_row["next_retry_at_utc"] = retry_at.isoformat().replace("+00:00", "Z")
                    run_row["retry_after_seconds"] = backoff
                    run_row["retryable"] = True
                else:
                    job_row["state"] = normalized_status if normalized_status in _ALLOWED_JOB_STATES else "failed"
                    job_row["next_retry_at_utc"] = ""

            job_row["updated_at_utc"] = now_iso
            self._save_state(state)

            return {
                "ok": True,
                "job_id": job_id,
                "run_id": run_id,
                "job_state": job_row.get("state"),
                "run_status": run_row.get("status"),
                "retryable": bool(run_row.get("retryable")),
                "retry_after_seconds": int(run_row.get("retry_after_seconds") or 0),
            }

    def ack_run(self, run_id: str, *, ack_type: str = "opened", source: str = "unknown") -> Dict[str, Any]:
        run_id = str(run_id or "").strip()
        if not run_id:
            return {"ok": False, "reason": "missing_run_id"}
        with self._lock:
            state = self._load_state()
            runs = state.setdefault("runs", [])
            run_idx = self._find_run_index_unlocked(runs, run_id)
            if run_idx < 0:
                run_idx = self._find_alias_run_index_unlocked(runs, run_id)
            if run_idx < 0:
                return {"ok": False, "reason": "run_not_found", "run_id": run_id}

            run_row = runs[run_idx]
            now_iso = _utc_iso()
            run_row["status"] = "acked"
            run_row["acked_at_utc"] = now_iso
            run_row["ack_type"] = str(ack_type or "opened").strip().lower() or "opened"
            run_row["ack_source"] = str(source or "unknown").strip().lower() or "unknown"

            job_id = str(run_row.get("job_id") or "").strip()
            jobs = state.setdefault("jobs", {})
            job_row = jobs.get(job_id)
            if isinstance(job_row, dict):
                job_row["state"] = "acked"
                job_row["last_acked_at_utc"] = now_iso
                job_row["updated_at_utc"] = now_iso

            self._save_state(state)
            return {
                "ok": True,
                "run_id": str(run_row.get("run_id") or run_id),
                "job_id": job_id,
                "job_state": "acked",
            }

    def list_jobs(self, *, limit: int = 200, state_filter: str = "") -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 200), 2000))
        filter_value = str(state_filter or "").strip().lower()
        with self._lock:
            state = self._load_state()
            jobs = state.get("jobs", {})
            rows = [dict(row) for row in jobs.values() if isinstance(row, dict)]
            if filter_value:
                rows = [row for row in rows if str(row.get("state") or "").strip().lower() == filter_value]
            rows.sort(key=lambda row: str(row.get("updated_at_utc") or ""), reverse=True)
            return rows[:limit]

    def list_runs(
        self,
        *,
        limit: int = 200,
        job_id: str = "",
        status_filter: str = "",
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 200), 4000))
        target_job_id = str(job_id or "").strip()
        target_status = str(status_filter or "").strip().lower()
        with self._lock:
            state = self._load_state()
            runs = [dict(row) for row in state.get("runs", []) if isinstance(row, dict)]
            if target_job_id:
                runs = [row for row in runs if str(row.get("job_id") or "") == target_job_id]
            if target_status:
                runs = [row for row in runs if str(row.get("status") or "").strip().lower() == target_status]
            runs.sort(key=lambda row: str(row.get("started_at_utc") or ""), reverse=True)
            return runs[:limit]

    def list_dead_letters(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 200), 2000))
        with self._lock:
            state = self._load_state()
            dead = [dict(row) for row in state.get("dead_letters", []) if isinstance(row, dict)]
            dead.sort(key=lambda row: str(row.get("timestamp_utc") or ""), reverse=True)
            return dead[:limit]

    def replay_dead_letter(
        self,
        *,
        run_id: str = "",
        job_id: str = "",
        trigger: str = "operator_replay",
    ) -> Dict[str, Any]:
        target_run_id = str(run_id or "").strip()
        target_job_id = str(job_id or "").strip()
        replay_trigger = str(trigger or "operator_replay").strip() or "operator_replay"
        if not target_run_id and not target_job_id:
            return {"ok": False, "reason": "missing_run_or_job_id"}

        with self._lock:
            state = self._load_state()
            dead_letters = state.setdefault("dead_letters", [])
            if not isinstance(dead_letters, list) or not dead_letters:
                return {"ok": False, "reason": "dead_letter_empty"}

            matched_idx = -1
            matched_row: Dict[str, Any] = {}
            for idx in range(len(dead_letters) - 1, -1, -1):
                row = dead_letters[idx]
                if not isinstance(row, dict):
                    continue
                row_run_id = str(row.get("run_id") or "").strip()
                row_job_id = str(row.get("job_id") or "").strip()
                if target_run_id and row_run_id == target_run_id:
                    matched_idx = idx
                    matched_row = row
                    break
                if (not target_run_id) and target_job_id and row_job_id == target_job_id:
                    matched_idx = idx
                    matched_row = row
                    break

            if matched_idx < 0:
                return {"ok": False, "reason": "dead_letter_not_found"}

            selected_run_id = str(matched_row.get("run_id") or "").strip()
            selected_job_id = str(matched_row.get("job_id") or "").strip()
            if not selected_job_id:
                return {"ok": False, "reason": "dead_letter_missing_job_id"}

            jobs = state.setdefault("jobs", {})
            job_row = jobs.get(selected_job_id)
            if not isinstance(job_row, dict):
                return {"ok": False, "reason": "job_not_found", "job_id": selected_job_id}

            now_iso = _utc_iso()
            previous_state = str(job_row.get("state") or "")
            metadata = dict(job_row.get("metadata") or {})
            metadata["last_replay_utc"] = now_iso
            metadata["last_replay_trigger"] = replay_trigger
            metadata["last_replay_from_run_id"] = selected_run_id
            metadata["last_replay_from_dead_letter"] = True

            job_row["metadata"] = metadata
            job_row["state"] = "due"
            job_row["last_failure_class"] = ""
            job_row["last_error"] = ""
            job_row["next_retry_at_utc"] = now_iso
            job_row["updated_at_utc"] = now_iso

            dead_letters.pop(matched_idx)
            self._save_state(state)
            return {
                "ok": True,
                "job_id": selected_job_id,
                "replayed_run_id": selected_run_id,
                "previous_state": previous_state,
                "job_state": "due",
                "remaining_dead_letters": len(dead_letters),
            }

    def mark_run_status(
        self,
        *,
        run_id: str,
        status: str,
        source: str = "operator",
        note: str = "",
    ) -> Dict[str, Any]:
        target_run_id = str(run_id or "").strip()
        target_status = str(status or "").strip().lower()
        status_source = str(source or "operator").strip().lower() or "operator"
        status_note = self._trim_text(note, limit=600)
        if not target_run_id:
            return {"ok": False, "reason": "missing_run_id"}
        if target_status not in _ALLOWED_JOB_STATES:
            return {"ok": False, "reason": "invalid_status", "status": target_status}

        with self._lock:
            state = self._load_state()
            runs = state.setdefault("runs", [])
            run_idx = self._find_run_index_unlocked(runs, target_run_id)
            if run_idx < 0:
                run_idx = self._find_alias_run_index_unlocked(runs, target_run_id)
            if run_idx < 0:
                return {"ok": False, "reason": "run_not_found", "run_id": target_run_id}

            now_iso = _utc_iso()
            run_row = runs[run_idx]
            run_row["status"] = target_status
            run_row["status_updated_at_utc"] = now_iso
            run_row["status_source"] = status_source
            if status_note:
                run_row["status_note"] = status_note
            if target_status in {"closed", "acked", "failed", "dead_letter"}:
                run_row["finished_at_utc"] = now_iso

            job_id = str(run_row.get("job_id") or "").strip()
            jobs = state.setdefault("jobs", {})
            job_row = jobs.get(job_id)
            if isinstance(job_row, dict):
                job_row["state"] = target_status
                job_row["updated_at_utc"] = now_iso
                if target_status == "closed":
                    job_row["next_retry_at_utc"] = ""
                if target_status == "acked":
                    job_row["last_acked_at_utc"] = now_iso
                if target_status in {"failed", "dead_letter"} and status_note:
                    job_row["last_error"] = status_note

            self._save_state(state)
            return {
                "ok": True,
                "run_id": str(run_row.get("run_id") or target_run_id),
                "job_id": job_id,
                "job_state": str(job_row.get("state") or "") if isinstance(job_row, dict) else "",
                "run_status": target_status,
                "status_source": status_source,
            }

    def _run_effective_timestamp(self, row: Dict[str, Any]) -> Optional[datetime]:
        if not isinstance(row, dict):
            return None
        for key in ("finished_at_utc", "started_at_utc"):
            parsed = _parse_utc(row.get(key))
            if parsed is not None:
                return parsed
        return None

    def _build_slo_snapshot(
        self,
        *,
        runs: List[Dict[str, Any]],
        jobs: List[Dict[str, Any]],
        active_lanes: Any,
        window_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        def _pct(num: int, den: int) -> float:
            if den <= 0:
                return 0.0
            return round((float(num) / float(den)) * 100.0, 3)

        total_runs = len(runs)
        delivered_runs = sum(1 for row in runs if str(row.get("status") or "") in {"delivered", "acked", "closed"})
        ack_eligible_runs = sum(
            1
            for row in runs
            if str(row.get("status") or "") in {"delivered", "acked", "closed"} and run_requires_ack(row)
        )
        acked_runs = sum(
            1
            for row in runs
            if str(row.get("status") or "") == "acked" and run_requires_ack(row)
        )
        deferred_runs = sum(1 for row in runs if str(row.get("status") or "") == "deferred")
        failed_runs = sum(1 for row in runs if str(row.get("status") or "") in {"failed", "dead_letter"})
        running_runs = sum(1 for row in runs if str(row.get("status") or "") == "running")
        dead_letter_runs = sum(1 for row in runs if str(row.get("status") or "") == "dead_letter")
        attempted_runs = delivered_runs + failed_runs
        terminal_runs = delivered_runs + deferred_runs + failed_runs

        snapshot = {
            "total_jobs": len(jobs),
            "total_runs": total_runs,
            "delivered_runs": delivered_runs,
            "ack_eligible_runs": ack_eligible_runs,
            "acked_runs": acked_runs,
            "deferred_runs": deferred_runs,
            "failed_runs": failed_runs,
            "running_runs": running_runs,
            "dead_letter_runs": dead_letter_runs,
            "attempted_runs": attempted_runs,
            "terminal_runs": terminal_runs,
            "active_lanes": len(active_lanes) if isinstance(active_lanes, dict) else 0,
            "delivery_success_rate_pct": _pct(delivered_runs, total_runs),
            "attempted_delivery_success_rate_pct": _pct(delivered_runs, attempted_runs),
            "ack_rate_pct": _pct(acked_runs, ack_eligible_runs),
            "deferred_rate_pct": _pct(deferred_runs, total_runs),
            "failure_rate_pct": _pct(failed_runs, total_runs),
            "dead_letter_rate_pct": _pct(dead_letter_runs, total_runs),
            "deferred_by_failure_class": _count_by_rows(runs, status="deferred", field="failure_class"),
            "deferred_by_job": _count_by_rows(runs, status="deferred", field="job_id"),
            "failed_by_failure_class": _count_by_rows(runs, status="failed", field="failure_class"),
            "failed_by_job": _count_by_rows(runs, status="failed", field="job_id"),
            "updated_at_utc": _utc_iso(),
        }
        if window_seconds is not None:
            snapshot["window_seconds"] = int(window_seconds)
        return snapshot

    def slo_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            state = self._load_state()
            runs = [row for row in state.get("runs", []) if isinstance(row, dict)]
            jobs = [row for row in state.get("jobs", {}).values() if isinstance(row, dict)]
            active_lanes = state.get("active_lanes", {})
        return self._build_slo_snapshot(runs=runs, jobs=jobs, active_lanes=active_lanes)

    def operator_baseline_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            state = self._load_state()
            runs = [row for row in state.get("runs", []) if isinstance(row, dict)]
            jobs = [row for row in state.get("jobs", {}).values() if isinstance(row, dict)]
            active_lanes = state.get("active_lanes", {})

        problematic_statuses = {"deferred", "failed", "dead_letter"}
        problematic_rows: List[Dict[str, Any]] = []
        for row in runs:
            if str(row.get("status") or "").strip().lower() not in problematic_statuses:
                continue
            ts = self._run_effective_timestamp(row)
            if ts is None:
                continue
            problematic_rows.append(row)

        latest_problem_row: Optional[Dict[str, Any]] = None
        latest_problem_ts: Optional[datetime] = None
        for row in problematic_rows:
            ts = self._run_effective_timestamp(row)
            if ts is None:
                continue
            if latest_problem_ts is None or ts > latest_problem_ts:
                latest_problem_ts = ts
                latest_problem_row = row

        filtered_runs = list(runs)
        baseline_after_utc = ""
        baseline_reason = "no_problematic_runs"
        if latest_problem_ts is not None:
            baseline_after_utc = latest_problem_ts.isoformat().replace("+00:00", "Z")
            baseline_reason = "since_last_problem_run"
            filtered_runs = [
                row
                for row in runs
                if (self._run_effective_timestamp(row) or latest_problem_ts) > latest_problem_ts
            ]

        snapshot = self._build_slo_snapshot(runs=filtered_runs, jobs=jobs, active_lanes=active_lanes)
        snapshot["scope"] = "operator_baseline"
        snapshot["baseline_reason"] = baseline_reason
        snapshot["baseline_after_utc"] = baseline_after_utc
        snapshot["latest_problem_run"] = {
            "run_id": str((latest_problem_row or {}).get("run_id") or ""),
            "job_id": str((latest_problem_row or {}).get("job_id") or ""),
            "status": str((latest_problem_row or {}).get("status") or ""),
            "failure_class": str((latest_problem_row or {}).get("failure_class") or ""),
            "finished_at_utc": str((latest_problem_row or {}).get("finished_at_utc") or ""),
            "started_at_utc": str((latest_problem_row or {}).get("started_at_utc") or ""),
        }
        return snapshot

    def slo_windows_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            state = self._load_state()
            runs = [row for row in state.get("runs", []) if isinstance(row, dict)]
            jobs = [row for row in state.get("jobs", {}).values() if isinstance(row, dict)]
            active_lanes = state.get("active_lanes", {})

        now = _utc_now()
        windows = {
            "last_1h": 1 * 3600,
            "last_6h": 6 * 3600,
            "last_24h": 24 * 3600,
            "last_168h": 168 * 3600,
        }
        payload: Dict[str, Any] = {}
        for label, seconds in windows.items():
            filtered_runs = []
            for row in runs:
                ts = self._run_effective_timestamp(row)
                if ts is None:
                    continue
                age_seconds = (now - ts).total_seconds()
                if 0 <= age_seconds <= float(seconds):
                    filtered_runs.append(row)
            payload[label] = self._build_slo_snapshot(
                runs=filtered_runs,
                jobs=jobs,
                active_lanes=active_lanes,
                window_seconds=seconds,
            )
        return payload

    def status_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            state = self._load_state()
            active_lanes = state.get("active_lanes", {})
            return {
                "storage_path": str(self._state_path),
                "version": int(state.get("version") or 1),
                "updated_at_utc": str(state.get("updated_at_utc") or ""),
                "job_count": len(state.get("jobs", {})) if isinstance(state.get("jobs"), dict) else 0,
                "run_count": len(state.get("runs", [])) if isinstance(state.get("runs"), list) else 0,
                "dead_letter_count": len(state.get("dead_letters", [])) if isinstance(state.get("dead_letters"), list) else 0,
                "active_lanes": dict(active_lanes) if isinstance(active_lanes, dict) else {},
                "stale_lane_seconds": int(self._stale_lane_seconds),
            }
