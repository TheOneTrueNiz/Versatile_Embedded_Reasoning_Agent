#!/usr/bin/env python3
"""
Deterministic Week1 operating executor for Vera.

Runs as a periodic tick (via ProactiveManager autonomy cadence), not a one-shot
startup bootstrap. It is idempotent across restarts via persistent state.

Responsibilities:
- Daily Week1 task import/reconciliation (idempotent).
- Due-time anchors (wake call, morning/midday/closeout pushes, email briefs).
- Retry/fallback behavior for transient failures.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _utc_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _resolve_local_now(now_override: str, timezone_name: str) -> dt.datetime:
    tz = ZoneInfo(timezone_name)
    if not now_override or not now_override.strip():
        return dt.datetime.now(tz)

    raw = now_override.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return dict(default)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _extract_result_text(tool_response: Dict[str, Any]) -> str:
    result = tool_response.get("result")
    if not isinstance(result, dict):
        return ""
    content = result.get("content")
    if isinstance(content, list):
        for entry in content:
            if isinstance(entry, dict):
                text = entry.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("content", "result", "text"):
            value = structured.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _norm(text: str) -> str:
    cleaned = (text or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return " ".join(cleaned.split())


def _call_tool(
    base_url: str,
    server: str,
    name: str,
    arguments: Dict[str, Any],
    timeout_seconds: float = 30.0,
) -> Tuple[bool, Dict[str, Any], str]:
    payload = {
        "server": server,
        "name": name,
        "arguments": arguments,
        "timeout": float(timeout_seconds),
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/tools/call",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
        if isinstance(data, dict):
            return True, data, ""
        return False, {}, "invalid_response"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, {}, f"HTTP {exc.code}: {body}"
    except Exception as exc:
        return False, {}, str(exc)


def _is_retryable_delivery_error(error: str) -> bool:
    lowered = str(error or "").strip().lower()
    if not lowered:
        return False
    if lowered.startswith("http 5"):
        return True
    transient_tokens = (
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection refused",
        "connection reset",
        "broken pipe",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "errno 111",
        "errno 104",
    )
    return any(token in lowered for token in transient_tokens)


def _is_service_not_ready_error(error: str, service_name: str) -> bool:
    lowered = str(error or "").strip().lower()
    target = str(service_name or "").strip().lower()
    if not lowered or not target:
        return False
    return f"mcp server {target} not running" in lowered


def _call_tool_with_retry(
    base_url: str,
    server: str,
    name: str,
    arguments: Dict[str, Any],
    *,
    timeout_seconds: float = 30.0,
    max_attempts: int = 2,
    retry_sleep_seconds: float = 0.35,
) -> Tuple[bool, Dict[str, Any], str]:
    attempts = max(1, int(max_attempts))
    last_data: Dict[str, Any] = {}
    last_err = ""
    for attempt in range(1, attempts + 1):
        ok, data, err = _call_tool(
            base_url,
            server,
            name,
            arguments,
            timeout_seconds=timeout_seconds,
        )
        if ok:
            return True, data, ""
        last_data = data
        last_err = err
        if attempt >= attempts or not _is_retryable_delivery_error(err):
            break
        if retry_sleep_seconds > 0:
            time.sleep(retry_sleep_seconds)
    return False, last_data, last_err


def _resolve_user_email(cli_value: str) -> str:
    if cli_value and cli_value.strip():
        return cli_value.strip().lower()

    env_value = os.getenv("GOOGLE_WORKSPACE_USER_EMAIL", "").strip().lower()
    if env_value:
        return env_value

    creds_path = Path.home() / "Documents" / "creds" / "google" / "user_email"
    if creds_path.exists():
        try:
            text = creds_path.read_text(encoding="utf-8").strip().lower()
            if text:
                return text
        except Exception:
            pass

    return "jeffnyzio@gmail.com"


def _resolve_docx_path(cli_value: str, vera_root: Path) -> Optional[Path]:
    candidates: List[Path] = []
    if cli_value and cli_value.strip():
        candidates.append(Path(cli_value).expanduser())

    env_value = os.getenv("VERA_WEEK1_DOCX_PATH", "").strip()
    if env_value:
        candidates.append(Path(env_value).expanduser())

    candidates.extend(
        [
            Path.home() / "Desktop" / "Vera_Week1_Operating_System_v10.docx",
            vera_root / "ops" / "week1" / "Vera_Week1_Operating_System_v10.docx",
        ]
    )

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _parse_task_list_ids(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    pattern = re.compile(r"^-\s+(.+?)\s+\(ID:\s*([A-Za-z0-9_\-]+)\)", re.MULTILINE)
    for match in pattern.finditer(text):
        title = match.group(1).strip()
        list_id = match.group(2).strip()
        out[title] = list_id
    return out


def _parse_top_tasks(text: str, limit: int = 3) -> List[str]:
    tasks: List[str] = []
    seen: set[str] = set()
    pattern = re.compile(r"^-\s+\[(P\d)\]\s+(.+?)\s+\(ID:\s*[A-Za-z0-9_\-]+\)")
    for raw in text.splitlines():
        line = raw.strip()
        match = pattern.match(line)
        if not match:
            continue
        item = f"[{match.group(1)}] {match.group(2).strip()}"
        if item in seen:
            continue
        seen.add(item)
        tasks.append(item)
        if len(tasks) >= limit:
            break
    return tasks


def _load_week1_task_schedule(path: Path) -> List[Dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        parent_title = str(row.get("parent_title") or "").strip()
        scheduled_local = str(row.get("scheduled_local") or "").strip()
        if not parent_title or not scheduled_local:
            continue
        out.append(
            {
                "parent_title": parent_title,
                "scheduled_local": scheduled_local,
                "priority": str(row.get("priority") or "").strip(),
                "category": str(row.get("category") or "").strip(),
                "focus_slot": str(row.get("focus_slot") or "").strip(),
            }
        )
    return out


def _rank_week1_focus_tasks_from_schedule(
    task_titles: List[str],
    schedule_items: List[Dict[str, Any]],
    *,
    local_now: dt.datetime,
    limit: int = 3,
) -> List[str]:
    if not task_titles or not schedule_items:
        return task_titles[:limit]

    live_by_norm = {_norm(title): title for title in task_titles if title}

    def _priority_rank_local(priority: str) -> int:
        return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(str(priority or "").strip(), 9)

    ranked: List[Tuple[Tuple[int, float, int, str], str]] = []
    seen: set[str] = set()
    for row in schedule_items:
        title = live_by_norm.get(_norm(str(row.get("parent_title") or "")))
        if not title or title in seen:
            continue
        try:
            scheduled_local = dt.datetime.fromisoformat(str(row.get("scheduled_local") or ""))
        except Exception:
            continue
        if scheduled_local.tzinfo is None:
            scheduled_local = scheduled_local.replace(tzinfo=local_now.tzinfo)
        delta_minutes = (scheduled_local - local_now).total_seconds() / 60.0
        abs_delta = abs(delta_minutes)
        if abs_delta <= 18 * 60:
            bucket = 0
        elif 0 < delta_minutes <= 48 * 60:
            bucket = 1
        elif -48 * 60 <= delta_minutes < 0:
            bucket = 2
        elif delta_minutes > 0:
            bucket = 3
        else:
            bucket = 4
        ranked.append(
            (
                (
                    bucket,
                    abs_delta,
                    _priority_rank_local(str(row.get("priority") or "")),
                    title.lower(),
                ),
                title,
            )
        )
        seen.add(title)

    ranked.sort(key=lambda item: item[0])
    ordered = [title for _, title in ranked]
    for title in task_titles:
        if title not in seen:
            ordered.append(title)
    return ordered[:limit]


def _default_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "last_run_utc": "",
        "last_import_local_date": "",
        "completed_events": {},
        "attempts": {},
        "deferred_not_ready": {},
        "updated_at_utc": _utc_iso(),
    }


def _default_probe_schedule_path(vera_root: Path) -> Path:
    return vera_root / "vera_memory" / "week1_probe_schedule.json"


def _prune_state_maps(state: Dict[str, Any], keep_days: int = 14, reference_date: Optional[dt.date] = None) -> None:
    anchor = reference_date or dt.date.today()
    cutoff = (anchor - dt.timedelta(days=max(1, keep_days))).isoformat()

    def _fresh(key: str) -> bool:
        if not isinstance(key, str) or ":" not in key:
            return False
        prefix = key.split(":", 1)[0]
        return prefix >= cutoff

    completed = state.get("completed_events")
    if isinstance(completed, dict):
        state["completed_events"] = {k: v for k, v in completed.items() if _fresh(k)}
    else:
        state["completed_events"] = {}

    attempts = state.get("attempts")
    if isinstance(attempts, dict):
        state["attempts"] = {k: v for k, v in attempts.items() if _fresh(k)}
    else:
        state["attempts"] = {}

    deferred_not_ready = state.get("deferred_not_ready")
    if isinstance(deferred_not_ready, dict):
        state["deferred_not_ready"] = {k: v for k, v in deferred_not_ready.items() if _fresh(k)}
    else:
        state["deferred_not_ready"] = {}


def _parse_iso_datetime(value: Any) -> Optional[dt.datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _load_probe_schedule(path: Path) -> List["ScheduledEvent"]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        return []

    if not isinstance(raw, list):
        return []

    events: List[ScheduledEvent] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled", True) is False:
            continue
        event_id = str(entry.get("event_id", "")).strip()
        hhmm = str(entry.get("hhmm", "")).strip()
        kind = str(entry.get("kind", "")).strip().lower()
        try:
            catchup_minutes = int(entry.get("catchup_minutes", 180))
        except Exception:
            continue
        if not event_id or not hhmm or kind not in {"call", "push", "email"}:
            continue
        if not re.fullmatch(r"\d{2}:\d{2}", hhmm):
            continue
        events.append(ScheduledEvent(event_id, hhmm, catchup_minutes, kind))
    return events


def _iter_scheduled_events(only_event_id: str, probe_schedule_path: Path) -> List[ScheduledEvent]:
    merged: List[ScheduledEvent] = list(SCHEDULE)
    merged.extend(_load_probe_schedule(probe_schedule_path))

    deduped: Dict[str, ScheduledEvent] = {}
    for event in merged:
        deduped[event.event_id] = event

    events = sorted(
        deduped.values(),
        key=lambda event: (event.hhmm, event.event_id),
    )
    if only_event_id and only_event_id.strip():
        target = only_event_id.strip()
        return [event for event in events if event.event_id == target]
    return events


@dataclass(frozen=True)
class ScheduledEvent:
    event_id: str
    hhmm: str
    catchup_minutes: int
    kind: str  # call|push|email


@dataclass(frozen=True)
class DeliveryOutcome:
    ok: bool
    status: str
    detail: str
    delivery_channel: str = ""
    primary_channel: str = ""
    fallback_channel: str = ""
    primary_error: str = ""
    fallback_error: str = ""


SCHEDULE: Tuple[ScheduledEvent, ...] = (
    ScheduledEvent("isaac_learning_boost", "07:30", 240, "email"),
    ScheduledEvent("wake_call", "08:00", 240, "call"),
    ScheduledEvent("daily_sweep", "08:05", 240, "push"),
    ScheduledEvent("morning_merge", "08:10", 240, "push"),
    ScheduledEvent("midday_check", "12:00", 180, "push"),
    ScheduledEvent("low_dopamine_start", "12:05", 180, "push"),
    ScheduledEvent("followup_factory", "15:00", 180, "push"),
    ScheduledEvent("closeout", "20:30", 180, "push"),
    ScheduledEvent("tomorrow_brief", "20:45", 180, "email"),
)


def _render_event_payload(
    event: ScheduledEvent,
    local_now: dt.datetime,
    user_email: str,
    top_tasks: List[str],
) -> Dict[str, str]:
    date_label = local_now.strftime("%A, %B %d, %Y")
    top_block = "\n".join(f"- {item}" for item in (top_tasks or ["No high-priority Week1 tasks detected."]))

    if event.event_id == "isaac_learning_boost":
        subject = f"Isaac Learning Boost - {local_now.strftime('%Y-%m-%d')}"
        body = (
            f"Isaac Learning Boost ({date_label})\n\n"
            "Focus:\n"
            "- Confirm lesson timeline and JOINED checkpoints (T-30/T-10/T-2).\n"
            "- Keep escalation budget-aware and low-noise.\n\n"
            "Current Week1 priorities:\n"
            f"{top_block}\n"
        )
        return {"subject": subject, "body": body, "to": user_email}

    if event.event_id == "wake_call":
        message = (
            "Good morning. Wake-up check: hydrate now and send ACK token WATER. "
            "First commitment is on deck; I have your Week1 priorities queued."
        )
        push = "Wake call fallback: hydrate now (WATER), then check your top 3 for this block."
        return {"message": message, "push_fallback": push, "title": "VERA Wake Check"}

    if event.event_id == "daily_sweep":
        message = (
            "08:05 Daily Sweep ready. Top Week1 priorities:\n"
            f"{top_block}\n"
            "Reply with DONE / STARTED / SNOOZE 10 / RESCHEDULE for your first step."
        )
        return {"title": "VERA Daily Sweep", "message": message}

    if event.event_id == "morning_merge":
        message = (
            "08:10 Morning Merge Card:\n"
            "YOUR DAY: top outcomes aligned.\n"
            "ISAAC DAY: reminder chain armed.\n"
            "CONFLICTS: monitor and resolve early.\n"
            f"Top tasks:\n{top_block}"
        )
        return {"title": "VERA Morning Merge", "message": message}

    if event.event_id == "midday_check":
        message = (
            "12:00 Midday check-in: report Top 3 status + blockers + next action. "
            "If lunch not logged, send ATE after food."
        )
        return {"title": "VERA Midday Check", "message": message}

    if event.event_id == "low_dopamine_start":
        message = (
            "12:05 START STEP prompt: do one 10-minute action now. "
            "Reply STARTED, DONE, SNOOZE 10, or RESCHEDULE."
        )
        return {"title": "VERA Start Step", "message": message}

    if event.event_id == "followup_factory":
        message = (
            "15:00 Follow-up factory checkpoint: close one P0/P1 thread and queue next action. "
            "Reply DONE/STARTED/SNOOZE 10/RESCHEDULE."
        )
        return {"title": "VERA Follow-Up", "message": message}

    if event.event_id == "closeout":
        message = (
            "20:30 Closeout: summarize shipped/slipped/rescheduled and draft tomorrow Top 3. "
            "Send notification quality: helpful / acceptable / noisy."
        )
        return {"title": "VERA Closeout", "message": message}

    if event.event_id == "tomorrow_brief":
        subject = f"Tomorrow Brief - {local_now.strftime('%Y-%m-%d')}"
        body = (
            f"Tomorrow Brief ({date_label})\n\n"
            "Proposed Top 3:\n"
            f"{top_block}\n\n"
            "Status reply options for first block: DONE / STARTED / SNOOZE 10 / RESCHEDULE.\n"
        )
        return {"subject": subject, "body": body, "to": user_email}

    return {"title": "VERA Week1", "message": "Week1 checkpoint."}


def _send_push(base_url: str, title: str, message: str) -> DeliveryOutcome:
    ok, data, err = _call_tool_with_retry(
        base_url,
        "call-me",
        "send_native_push",
        {"title": title, "message": message},
    )
    if ok:
        return DeliveryOutcome(
            ok=True,
            status="ok",
            detail=_extract_result_text(data) or "native_push_sent",
            delivery_channel="native_push",
            primary_channel="native_push",
        )

    ok2, data2, err2 = _call_tool_with_retry(
        base_url,
        "call-me",
        "send_mobile_push",
        {"title": title, "message": message},
    )
    if ok2:
        return DeliveryOutcome(
            ok=True,
            status="ok",
            detail=_extract_result_text(data2) or "mobile_push_sent",
            delivery_channel="mobile_push",
            primary_channel="native_push",
            fallback_channel="mobile_push",
            primary_error=err,
        )
    return DeliveryOutcome(
        ok=False,
        status="failed",
        detail=f"native_push_failed={err}; mobile_push_failed={err2}",
        primary_channel="native_push",
        fallback_channel="mobile_push",
        primary_error=err,
        fallback_error=err2,
    )


def _send_call_with_fallback(base_url: str, message: str, fallback_title: str, fallback_message: str) -> DeliveryOutcome:
    max_attempts = max(1, int(os.getenv("VERA_WEEK1_WAKE_CALL_ATTEMPTS", "2") or 2))
    retry_sleep_seconds = max(0.0, float(os.getenv("VERA_WEEK1_WAKE_CALL_RETRY_SLEEP_SECONDS", "5.0") or 5.0))
    ok, data, err = _call_tool_with_retry(
        base_url,
        "call-me",
        "initiate_call",
        {"message": message},
        timeout_seconds=75.0,
        max_attempts=max_attempts,
        retry_sleep_seconds=retry_sleep_seconds,
    )
    if ok:
        return DeliveryOutcome(
            ok=True,
            status="ok",
            detail=_extract_result_text(data) or "call_initiated",
            delivery_channel="call",
            primary_channel="call",
        )

    push_result = _send_push(base_url, fallback_title, fallback_message)
    if push_result.ok:
        return DeliveryOutcome(
            ok=True,
            status="partial_ok_fallback_push",
            detail=push_result.detail,
            delivery_channel=push_result.delivery_channel,
            primary_channel="call",
            fallback_channel=push_result.delivery_channel,
            primary_error=err,
        )
    return DeliveryOutcome(
        ok=False,
        status="failed",
        detail=push_result.detail,
        primary_channel="call",
        fallback_channel=push_result.delivery_channel or "push",
        primary_error=err,
        fallback_error=push_result.detail,
    )


def _send_or_draft_email(
    base_url: str,
    user_email: str,
    to_email: str,
    subject: str,
    body: str,
    email_mode: str,
) -> DeliveryOutcome:
    tool_name = "send_gmail_message" if email_mode == "send" else "draft_gmail_message"
    arguments: Dict[str, Any] = {
        "user_google_email": user_email,
        "subject": subject,
        "body": body,
        "to": to_email,
    }
    if tool_name == "draft_gmail_message":
        # Drafts support to, but if provider rejects it, fall back to required-only.
        pass

    ok, data, err = _call_tool(base_url, "google-workspace", tool_name, arguments)
    if ok:
        return DeliveryOutcome(
            ok=True,
            status="ok",
            detail=_extract_result_text(data) or f"{tool_name}_ok",
            delivery_channel=tool_name,
            primary_channel=tool_name,
        )

    if tool_name == "draft_gmail_message":
        retry_args = {
            "user_google_email": user_email,
            "subject": subject,
            "body": body,
        }
        ok2, data2, err2 = _call_tool(base_url, "google-workspace", tool_name, retry_args)
        if ok2:
            return DeliveryOutcome(
                ok=True,
                status="ok",
                detail=_extract_result_text(data2) or f"{tool_name}_ok",
                delivery_channel=tool_name,
                primary_channel=tool_name,
            )
        return DeliveryOutcome(
            ok=False,
            status="failed",
            detail=f"{err}; fallback={err2}",
            primary_channel=tool_name,
            primary_error=err,
            fallback_error=err2,
        )

    return DeliveryOutcome(
        ok=False,
        status="failed",
        detail=err,
        primary_channel=tool_name,
        primary_error=err,
    )


def _find_week1_task_list_id(base_url: str, user_email: str, task_list_title: str) -> Optional[str]:
    ok, data, _ = _call_tool(
        base_url,
        "google-workspace",
        "list_task_lists",
        {"user_google_email": user_email},
    )
    if not ok:
        return None
    text = _extract_result_text(data)
    ids = _parse_task_list_ids(text)
    return ids.get(task_list_title)


def _fetch_top_week1_tasks(
    base_url: str,
    user_email: str,
    task_list_title: str,
    limit: int = 3,
    *,
    schedule_path: Optional[Path] = None,
    timezone_name: str = "America/Chicago",
    local_now: Optional[dt.datetime] = None,
) -> List[str]:
    task_list_id = _find_week1_task_list_id(base_url, user_email, task_list_title)
    if not task_list_id:
        return []
    ok, data, _ = _call_tool(
        base_url,
        "google-workspace",
        "list_tasks",
        {
            "user_google_email": user_email,
            "task_list_id": task_list_id,
            "show_completed": False,
            "show_deleted": False,
            "max_results": max(20, limit * 8),
        },
    )
    if not ok:
        return []
    text = _extract_result_text(data)
    task_titles = _parse_top_tasks(text, limit=max(20, limit * 8))
    if schedule_path is not None:
        schedule_items = _load_week1_task_schedule(schedule_path)
        now_local = local_now or dt.datetime.now(ZoneInfo(timezone_name))
        task_titles = _rank_week1_focus_tasks_from_schedule(
            task_titles,
            schedule_items,
            local_now=now_local,
            limit=limit,
        )
    return task_titles[:limit]


def _ensure_week1_import(
    args: argparse.Namespace,
    local_date_iso: str,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    if state.get("last_import_local_date") == local_date_iso:
        return {"ok": True, "skipped": True, "reason": "already_imported_today"}

    docx_path = _resolve_docx_path(args.docx, args.vera_root)
    seed_csv_path = args.seed_csv if isinstance(args.seed_csv, Path) else Path(args.seed_csv).expanduser().resolve()
    if docx_path is None and not seed_csv_path.exists():
        return {"ok": False, "skipped": True, "reason": "week1_source_missing"}

    script_path = args.vera_root / "scripts" / "import_week1_operating_tasks.py"
    if not script_path.exists():
        return {"ok": False, "skipped": True, "reason": "import_script_missing"}

    python_bin = args.python_bin
    if not python_bin:
        local_venv = args.vera_root / ".venv" / "bin" / "python"
        python_bin = str(local_venv) if local_venv.exists() else "python3"

    output_report = args.vera_root / "tmp" / "audits" / "week1_task_import_report.json"
    schedule_report = args.vera_root / "vera_memory" / "week1_task_schedule.json"
    cmd = [
        python_bin,
        str(script_path),
        "--base-url",
        args.base_url,
        "--user-email",
        args.user_email,
        "--seed-csv",
        str(seed_csv_path),
        "--task-list-title",
        args.task_list_title,
        "--timezone",
        args.timezone,
        "--output",
        str(output_report),
        "--schedule-output",
        str(schedule_report),
    ]
    if docx_path is not None:
        cmd.extend(["--docx", str(docx_path)])

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(args.vera_root),
            capture_output=True,
            text=True,
            timeout=max(120, int(args.import_timeout_seconds)),
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "skipped": False, "reason": f"import_exec_error:{exc}"}

    result: Dict[str, Any] = {
        "ok": proc.returncode == 0,
        "skipped": False,
        "returncode": int(proc.returncode),
        "stdout": (proc.stdout or "")[-600:],
        "stderr": (proc.stderr or "")[-600:],
    }

    if output_report.exists():
        try:
            report_data = json.loads(output_report.read_text(encoding="utf-8"))
            if isinstance(report_data, dict):
                result["report"] = {
                    "parsed_items": report_data.get("parsed_items"),
                    "created_parent_tasks": report_data.get("created_parent_tasks"),
                    "created_start_step_subtasks": report_data.get("created_start_step_subtasks"),
                    "skipped_existing_parent_tasks": report_data.get("skipped_existing_parent_tasks"),
                    "skipped_existing_start_step_subtasks": report_data.get("skipped_existing_start_step_subtasks"),
                }
        except Exception:
            pass

    if result.get("ok"):
        state["last_import_local_date"] = local_date_iso

    return result


def _execute_event(
    base_url: str,
    event: ScheduledEvent,
    payload: Dict[str, str],
    user_email: str,
    email_mode: str,
) -> DeliveryOutcome:
    if event.kind == "push":
        return _send_push(base_url, payload.get("title", "VERA"), payload.get("message", ""))
    if event.kind == "call":
        return _send_call_with_fallback(
            base_url,
            payload.get("message", ""),
            payload.get("title", "VERA Wake Check"),
            payload.get("push_fallback", payload.get("message", "")),
        )
    if event.kind == "email":
        return _send_or_draft_email(
            base_url,
            user_email=user_email,
            to_email=payload.get("to", user_email),
            subject=payload.get("subject", "VERA Brief"),
            body=payload.get("body", ""),
            email_mode=email_mode,
        )
    return DeliveryOutcome(
        ok=False,
        status="failed",
        detail=f"unsupported_event_kind:{event.kind}",
        primary_channel=event.kind,
        primary_error=f"unsupported_event_kind:{event.kind}",
    )


def run(args: argparse.Namespace) -> int:
    state = _load_json(args.state_path, _default_state())
    if not isinstance(state, dict):
        state = _default_state()
    for key, value in _default_state().items():
        state.setdefault(key, value)

    probe_schedule_path = args.probe_schedule_path
    if not isinstance(probe_schedule_path, Path):
        probe_schedule_path = Path(probe_schedule_path)

    local_now = _resolve_local_now(args.now_override, args.timezone)
    _prune_state_maps(state, reference_date=local_now.date())
    now_utc = local_now.astimezone(dt.timezone.utc)
    local_date = local_now.date().isoformat()
    completed = state.get("completed_events") if isinstance(state.get("completed_events"), dict) else {}
    attempts = state.get("attempts") if isinstance(state.get("attempts"), dict) else {}
    deferred_not_ready = (
        state.get("deferred_not_ready") if isinstance(state.get("deferred_not_ready"), dict) else {}
    )
    defer_holdoff_seconds = max(
        60,
        int(os.getenv("VERA_WEEK1_NOT_READY_HOLDOFF_SECONDS", "900") or 900),
    )
    scheduled_events = _iter_scheduled_events(args.only_event_id, probe_schedule_path)

    if args.probe_due:
        due_events: List[Dict[str, Any]] = []
        for event in scheduled_events:
            event_key = f"{local_date}:{event.event_id}"
            if event_key in completed:
                continue
            hour, minute = [int(part) for part in event.hhmm.split(":", 1)]
            due_local = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if local_now < due_local:
                continue
            minutes_late = int((local_now - due_local).total_seconds() // 60)
            if minutes_late > int(event.catchup_minutes):
                continue
            deferred_row = deferred_not_ready.get(event_key)
            deferred_until = None
            if isinstance(deferred_row, dict):
                deferred_until = _parse_iso_datetime(deferred_row.get("until_utc"))
            if deferred_until is not None and deferred_until > now_utc:
                continue
            prior_attempts = int(attempts.get(event_key, 0) or 0)
            if prior_attempts >= int(args.max_retries_per_event):
                continue
            due_events.append(
                {
                    "event_id": event.event_id,
                    "kind": event.kind,
                    "due_local": due_local.isoformat(),
                    "minutes_late": minutes_late,
                    "attempts": prior_attempts,
                }
            )
        summary = {
            "ok": True,
            "probe_due": True,
            "timezone": args.timezone,
            "local_now": local_now.isoformat(),
            "due_count": len(due_events),
            "due_events": due_events[: int(max(1, args.max_actions_per_run))],
        }
        print(json.dumps(summary, indent=2, ensure_ascii=True))
        return 0

    if args.dry_run:
        import_result = {"ok": True, "skipped": True, "reason": "dry_run"}
    elif args.skip_import:
        import_result = {"ok": True, "skipped": True, "reason": "skip_import"}
    else:
        import_result = _ensure_week1_import(args, local_date, state)

    top_tasks = _fetch_top_week1_tasks(
        args.base_url,
        args.user_email,
        args.task_list_title,
        limit=3,
        schedule_path=args.vera_root / "vera_memory" / "week1_task_schedule.json",
        timezone_name=args.timezone,
        local_now=local_now,
    )

    events_report: List[Dict[str, Any]] = []
    actions_attempted = 0

    for event in scheduled_events:
        event_key = f"{local_date}:{event.event_id}"
        if event_key in completed:
            continue

        hour, minute = [int(part) for part in event.hhmm.split(":", 1)]
        due_local = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if local_now < due_local:
            continue

        minutes_late = int((local_now - due_local).total_seconds() // 60)
        if minutes_late > int(event.catchup_minutes):
            deferred_not_ready.pop(event_key, None)
            if not args.dry_run:
                completed[event_key] = {
                    "status": "skipped_stale",
                    "due_local": due_local.isoformat(),
                    "attempted_local": local_now.isoformat(),
                    "detail": f"late_by={minutes_late}m > catchup={event.catchup_minutes}m",
                }
            events_report.append({
                "event_id": event.event_id,
                "status": "skipped_stale_dry_run" if args.dry_run else "skipped_stale",
                "minutes_late": minutes_late,
            })
            continue

        if actions_attempted >= int(args.max_actions_per_run):
            break

        prior_attempts = int(attempts.get(event_key, 0) or 0)
        if prior_attempts >= int(args.max_retries_per_event):
            deferred_not_ready.pop(event_key, None)
            if not args.dry_run:
                completed[event_key] = {
                    "status": "failed_exhausted",
                    "due_local": due_local.isoformat(),
                    "attempted_local": local_now.isoformat(),
                    "detail": f"max_retries_reached:{prior_attempts}",
                }
            events_report.append({
                "event_id": event.event_id,
                "status": "failed_exhausted_dry_run" if args.dry_run else "failed_exhausted",
                "attempts": prior_attempts,
            })
            continue

        payload = _render_event_payload(event, local_now, args.user_email, top_tasks)
        deferred_row = deferred_not_ready.get(event_key)
        deferred_until = None
        if isinstance(deferred_row, dict):
            deferred_until = _parse_iso_datetime(deferred_row.get("until_utc"))
        if deferred_until is not None and deferred_until > now_utc:
            continue
        if args.dry_run:
            actions_attempted += 1
            events_report.append({
                "event_id": event.event_id,
                "status": "dry_run_due",
                "would_attempt": prior_attempts + 1,
                "due_local": due_local.isoformat(),
                "attempted_local": local_now.isoformat(),
                "payload_preview": {
                    "title": payload.get("title", ""),
                    "subject": payload.get("subject", ""),
                },
            })
            continue
        outcome = _execute_event(
            args.base_url,
            event,
            payload,
            user_email=args.user_email,
            email_mode=args.email_mode,
        )
        if not outcome.ok and event.kind in {"push", "call"} and _is_service_not_ready_error(outcome.detail, "call-me"):
            deferred_until_utc = now_utc + dt.timedelta(seconds=defer_holdoff_seconds)
            deferred_not_ready[event_key] = {
                "until_utc": deferred_until_utc.isoformat().replace("+00:00", "Z"),
                "detail": outcome.detail[:400],
                "updated_at_utc": _utc_iso(),
            }
            events_report.append({
                "event_id": event.event_id,
                "status": "deferred_not_ready",
                "attempt": prior_attempts,
                "due_local": due_local.isoformat(),
                "attempted_local": local_now.isoformat(),
                "detail": outcome.detail[:400],
                "holdoff_seconds": defer_holdoff_seconds,
                "deferred_until_utc": deferred_until_utc.isoformat().replace("+00:00", "Z"),
            })
            _append_jsonl(
                args.event_log_path,
                {
                    "ts_utc": _utc_iso(),
                    "event_id": event.event_id,
                    "status": "deferred_not_ready",
                    "attempt": prior_attempts,
                    "due_local": due_local.isoformat(),
                    "attempted_local": local_now.isoformat(),
                    "detail": outcome.detail[:400],
                    "holdoff_seconds": defer_holdoff_seconds,
                    "deferred_until_utc": deferred_until_utc.isoformat().replace("+00:00", "Z"),
                },
            )
            continue
        actions_attempted += 1
        attempts[event_key] = prior_attempts + 1
        deferred_not_ready.pop(event_key, None)

        event_row = {
            "event_id": event.event_id,
            "status": outcome.status,
            "attempt": attempts[event_key],
            "due_local": due_local.isoformat(),
            "attempted_local": local_now.isoformat(),
            "detail": outcome.detail[:400],
            "delivery_channel": outcome.delivery_channel,
            "primary_channel": outcome.primary_channel,
            "fallback_channel": outcome.fallback_channel,
        }
        if outcome.primary_error:
            event_row["primary_error"] = outcome.primary_error[:400]
        if outcome.fallback_error:
            event_row["fallback_error"] = outcome.fallback_error[:400]
        events_report.append(event_row)
        _append_jsonl(args.event_log_path, {"ts_utc": _utc_iso(), **event_row})

        if outcome.ok:
            completed[event_key] = {
                "status": outcome.status,
                "due_local": due_local.isoformat(),
                "attempted_local": local_now.isoformat(),
                "detail": outcome.detail[:400],
                "delivery_channel": outcome.delivery_channel,
                "primary_channel": outcome.primary_channel,
                "fallback_channel": outcome.fallback_channel,
            }

    if not args.dry_run:
        state["completed_events"] = completed
        state["attempts"] = attempts
        state["deferred_not_ready"] = deferred_not_ready
        state["last_run_utc"] = _utc_iso()
        state["updated_at_utc"] = _utc_iso()
        _atomic_write_json(args.state_path, state)

    summary = {
        "ok": True,
        "dry_run": bool(args.dry_run),
        "timezone": args.timezone,
        "local_now": local_now.isoformat(),
        "import_result": import_result,
        "actions_attempted": actions_attempted,
        "events_report": events_report,
        "top_tasks": top_tasks,
        "state_path": str(args.state_path),
        "event_log_path": str(args.event_log_path),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one deterministic Week1 executor tick")
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--vera-root", type=Path, default=default_root, help="Vera repo root")
    parser.add_argument("--base-url", default=os.getenv("VERA_BASE_URL", "http://127.0.0.1:8788"))
    parser.add_argument("--timezone", default=os.getenv("VERA_WEEK1_TIMEZONE", "America/Chicago"))
    parser.add_argument("--user-email", default="", help="Google Workspace email (auto-resolved when blank)")
    parser.add_argument("--docx", default="", help="Optional Week1 docx override path")
    parser.add_argument(
        "--seed-csv",
        type=Path,
        default=default_root / "ops" / "week1" / "WEEK1_SEEDED_TASK_BACKLOG.csv",
        help="Seed CSV for Week1 import",
    )
    parser.add_argument(
        "--task-list-title",
        default="VERA Week1 Operating System v10",
        help="Google Task list title",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=default_root / "vera_memory" / "week1_executor_state.json",
        help="Executor state path",
    )
    parser.add_argument(
        "--event-log-path",
        type=Path,
        default=default_root / "vera_memory" / "week1_executor_events.jsonl",
        help="Executor event log path",
    )
    parser.add_argument(
        "--probe-schedule-path",
        type=Path,
        default=default_root / "vera_memory" / "week1_probe_schedule.json",
        help="Optional JSON file with extra reversible scheduled probe events",
    )
    parser.add_argument("--max-actions-per-run", type=int, default=3)
    parser.add_argument("--max-retries-per-event", type=int, default=3)
    parser.add_argument("--import-timeout-seconds", type=int, default=600)
    parser.add_argument("--python-bin", default=os.getenv("VERA_PYTHON_BIN", ""))
    parser.add_argument(
        "--now-override",
        default="",
        help="Optional ISO8601 local/offset timestamp to use instead of current wall clock",
    )
    parser.add_argument(
        "--only-event-id",
        default="",
        help="Restrict evaluation to a single scheduled event_id",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="Skip the daily Week1 import step but still evaluate due events",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report due events without side effects or state writes")
    parser.add_argument(
        "--probe-due",
        action="store_true",
        help="Report currently due events without import, side effects, or state writes",
    )
    parser.add_argument(
        "--email-mode",
        choices=["send", "draft"],
        default=os.getenv("VERA_WEEK1_EMAIL_MODE", "send").strip().lower() or "send",
        help="Send real Gmail messages or create drafts",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    args.vera_root = args.vera_root.expanduser().resolve()
    args.seed_csv = args.seed_csv.expanduser().resolve()
    args.state_path = args.state_path.expanduser().resolve()
    args.event_log_path = args.event_log_path.expanduser().resolve()
    args.user_email = _resolve_user_email(args.user_email)

    try:
        return run(args)
    except Exception as exc:
        err = {
            "ok": False,
            "error": str(exc),
            "ts_utc": _utc_iso(),
        }
        print(json.dumps(err, indent=2, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
