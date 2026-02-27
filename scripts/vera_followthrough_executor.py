#!/usr/bin/env python3
"""
Autonomy follow-through ledger + action/event executor.

Purpose:
- Track assistant autonomy commitments from transcript messages.
- Track scheduled action windows and execution evidence.
- Attempt deterministic workflow execution for missed/unresolved commitments.
- Persist outcomes in local ledgers so Doctor assertions can verify follow-through.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


COMMITMENT_RE = re.compile(
    r"\b(plan set:|autonomy engaged|multitasking enabled:|adjusted:\s*now|block queued|summary post-run|queued for)\b",
    re.IGNORECASE,
)
WINDOW_24H_LOCAL_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*[\-\u2013]\s*(\d{1,2}):(\d{2})\s*local\b", re.IGNORECASE)
WINDOW_12H_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(am|pm)\s*(?:to|[\-\u2013])\s*(\d{1,2}):(\d{2})\s*(am|pm)\b", re.IGNORECASE)
WINDOW_12H_TRAILING_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*[\-\u2013]\s*(\d{1,2}):(\d{2})\s*(am|pm)\b", re.IGNORECASE)
SINGLE_24H_QUEUE_RE = re.compile(r"\b(?:queued for|trigger queued for|scheduled for)\s*(\d{1,2}):(\d{2})\b", re.IGNORECASE)
PLANNING_ONLY_TOOLS = {"create_event", "list_calendars", "get_events", "time", "modify_event"}
WORKFLOW_STOP_WORDS = {
    "about",
    "after",
    "before",
    "between",
    "block",
    "calendar",
    "confirmed",
    "event",
    "for",
    "from",
    "have",
    "into",
    "just",
    "local",
    "now",
    "plan",
    "post",
    "queued",
    "set",
    "summary",
    "that",
    "the",
    "this",
    "tool",
    "with",
}
TERMINAL_ACTION_STATES = {"completed", "failed", "missed"}
DEFAULT_WORKFLOW_CATALOG: Dict[str, Any] = {
    "version": 1,
    "workflows": [
        {
            "name": "autonomy_followthrough",
            "description": "Generic plan tracking and execution proof.",
            "keywords": ["plan set", "autonomy engaged", "multitasking enabled"],
            "required_tools": [],
            "default_window_hours": 8.0,
            "steps": [
                {"id": "capture_plan", "title": "Capture commitment", "trigger": "discovered"},
                {"id": "attempt_execution", "title": "Collect execution evidence", "trigger": "execution_evidence"},
                {"id": "close_loop", "title": "Close loop with summary", "trigger": "terminal"},
            ],
        },
        {
            "name": "introspection_toolchain",
            "description": "Run introspection/probe/toolchain checks and summarize outcomes.",
            "keywords": ["introspection", "tool chain", "codex probe", "scaffold", "validation"],
            "required_tools": ["sequentialthinking"],
            "default_window_hours": 8.0,
            "steps": [
                {"id": "capture_plan", "title": "Capture introspection objective", "trigger": "discovered"},
                {"id": "run_checks", "title": "Run probes/checks", "trigger": "execution_evidence"},
                {"id": "report_outcome", "title": "Publish summary/report", "trigger": "terminal"},
            ],
        },
        {
            "name": "calendar_followthrough",
            "description": "Track schedule-bound commitments and verify action in window.",
            "keywords": ["calendar", "event", "schedule", "queued for", "trigger queued"],
            "required_tools": ["create_event"],
            "default_window_hours": 4.0,
            "steps": [
                {"id": "capture_plan", "title": "Capture scheduled commitment", "trigger": "discovered"},
                {"id": "window_started", "title": "Enter scheduled execution window", "trigger": "window_started"},
                {"id": "run_window_task", "title": "Execute scheduled task", "trigger": "execution_evidence"},
                {"id": "close_loop", "title": "Close loop after window", "trigger": "terminal"},
            ],
        },
    ],
}


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _utc_iso() -> str:
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_ts() -> str:
    return _utc_now().strftime("%Y%m%dT%H%M%SZ")


def _default_vera_root() -> Path:
    env_root = os.getenv("VERA_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser()
    return Path(__file__).resolve().parents[1]


def _default_harness_root(vera_root: Path) -> Path:
    return vera_root.parent / "Doctor_Codex"


def _safe_jsonl_iter(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if isinstance(payload, dict):
                yield payload


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "commitments": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "commitments": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "commitments": {}}
    commitments = payload.get("commitments")
    if not isinstance(commitments, dict):
        payload["commitments"] = {}
    return payload


def _save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at_utc"] = _utc_iso()
    path.write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _load_actions(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "actions": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "actions": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "actions": {}}
    actions = payload.get("actions")
    if not isinstance(actions, dict):
        payload["actions"] = {}
    return payload


def _save_actions(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at_utc"] = _utc_iso()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _append_event(path: Path, event: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True) + "\n")


def _load_json_file(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(fallback)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(fallback)
    return payload if isinstance(payload, dict) else dict(fallback)


def _save_json_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _normalize_workflow_steps(steps: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(steps, list):
        return out
    for raw in steps:
        if not isinstance(raw, dict):
            continue
        step_id = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or step_id).strip()
        trigger = str(raw.get("trigger") or "execution_evidence").strip().lower()
        if not step_id:
            continue
        if trigger not in {"discovered", "window_started", "execution_evidence", "executor_success", "terminal"}:
            trigger = "execution_evidence"
        out.append({"id": step_id, "title": title, "trigger": trigger})
    return out


def _normalize_workflow(raw: Dict[str, Any], source: str, catalog_version: int) -> Dict[str, Any]:
    name = str(raw.get("name") or "").strip()
    if not name:
        return {}
    keywords_raw = raw.get("keywords")
    keywords: List[str] = []
    if isinstance(keywords_raw, list):
        for value in keywords_raw:
            text = str(value or "").strip().lower()
            if text:
                keywords.append(text)

    required_tools_raw = raw.get("required_tools")
    required_tools: List[str] = []
    if isinstance(required_tools_raw, list):
        for value in required_tools_raw:
            text = str(value or "").strip()
            if text:
                required_tools.append(text)

    try:
        default_window_hours = float(raw.get("default_window_hours") or 0.0)
    except Exception:
        default_window_hours = 0.0

    steps = _normalize_workflow_steps(raw.get("steps"))
    if not steps:
        steps = [
            {"id": "capture_plan", "title": "Capture commitment", "trigger": "discovered"},
            {"id": "attempt_execution", "title": "Collect execution evidence", "trigger": "execution_evidence"},
            {"id": "close_loop", "title": "Close loop", "trigger": "terminal"},
        ]

    return {
        "name": name,
        "description": str(raw.get("description") or "").strip(),
        "keywords": keywords,
        "required_tools": required_tools,
        "default_window_hours": max(0.0, default_window_hours),
        "steps": steps,
        "source": source,
        "catalog_version": int(catalog_version),
    }


def _load_workflow_catalog(catalog_path: Path, learned_path: Path) -> Dict[str, Any]:
    base = _load_json_file(catalog_path, DEFAULT_WORKFLOW_CATALOG)
    try:
        catalog_version = int(base.get("version") or 1)
    except Exception:
        catalog_version = 1

    workflows_by_name: Dict[str, Dict[str, Any]] = {}
    base_workflows = base.get("workflows")
    if isinstance(base_workflows, list):
        for item in base_workflows:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_workflow(item, source="catalog", catalog_version=catalog_version)
            if normalized:
                workflows_by_name[normalized["name"]] = normalized

    learned = _load_json_file(learned_path, {"version": 1, "workflows": []})
    learned_workflows = learned.get("workflows")
    if isinstance(learned_workflows, list):
        for item in learned_workflows:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_workflow(item, source="learned", catalog_version=catalog_version)
            if normalized:
                workflows_by_name[normalized["name"]] = normalized

    if "autonomy_followthrough" not in workflows_by_name:
        fallback = _normalize_workflow(
            {
                "name": "autonomy_followthrough",
                "description": "Generic fallback workflow",
                "keywords": [],
                "required_tools": [],
                "default_window_hours": 8.0,
            },
            source="fallback",
            catalog_version=catalog_version,
        )
        if fallback:
            workflows_by_name[fallback["name"]] = fallback

    return {"version": catalog_version, "workflows": workflows_by_name}


def _content_tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_]{3,}", str(text or "").lower())


def _infer_workflow(content: str, workflows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    low = str(content or "").lower()
    token_set = set(_content_tokens(low))
    best_name = "autonomy_followthrough"
    best_score = 0.0
    best_hits: List[str] = []

    for name, spec in workflows.items():
        keywords = spec.get("keywords")
        if not isinstance(keywords, list) or not keywords:
            if name == "autonomy_followthrough" and best_score <= 0.0:
                best_name = name
            continue
        hits: List[str] = []
        for keyword in keywords:
            if not isinstance(keyword, str):
                continue
            key = keyword.strip().lower()
            if not key:
                continue
            if " " in key:
                if key in low:
                    hits.append(key)
            else:
                if key in token_set:
                    hits.append(key)
        score = float(len(set(hits))) / float(max(1, len(keywords)))
        if score > best_score:
            best_name = name
            best_score = score
            best_hits = sorted(set(hits))

    confidence = 0.2 + (0.8 * best_score)
    confidence = min(1.0, max(0.0, confidence))
    chosen = workflows.get(best_name, workflows.get("autonomy_followthrough", {}))
    source = str(chosen.get("source") or "fallback")
    if best_score <= 0.0:
        source = "fallback"
        best_name = "autonomy_followthrough"
        best_hits = []
        confidence = 0.2
    return {
        "name": best_name,
        "confidence": round(confidence, 4),
        "matched_keywords": best_hits,
        "source": source,
    }


def _build_learned_workflow(content: str, existing: Dict[str, Dict[str, Any]], min_keywords: int = 3) -> Dict[str, Any]:
    tokens = [t for t in _content_tokens(content) if t not in WORKFLOW_STOP_WORDS]
    if len(tokens) < min_keywords:
        return {}
    deduped: List[str] = []
    seen = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
        if len(deduped) >= 6:
            break
    if len(deduped) < min_keywords:
        return {}
    digest = hashlib.sha1(" ".join(deduped).encode("utf-8")).hexdigest()[:10]
    name = f"learned_{digest}"
    if name in existing:
        return existing[name]
    return {
        "name": name,
        "description": "Auto-learned workflow from repeated commitment language.",
        "keywords": deduped,
        "required_tools": [],
        "default_window_hours": 8.0,
        "steps": [
            {"id": "capture_plan", "title": "Capture learned commitment", "trigger": "discovered"},
            {"id": "attempt_execution", "title": "Collect execution evidence", "trigger": "execution_evidence"},
            {"id": "close_loop", "title": "Close loop", "trigger": "terminal"},
        ],
        "source": "learned",
        "catalog_version": 1,
    }


def _persist_learned_workflow(path: Path, workflow: Dict[str, Any]) -> None:
    if not workflow:
        return
    payload = _load_json_file(path, {"version": 1, "workflows": []})
    workflows = payload.get("workflows")
    if not isinstance(workflows, list):
        workflows = []
        payload["workflows"] = workflows
    name = str(workflow.get("name") or "").strip()
    if not name:
        return
    for row in workflows:
        if isinstance(row, dict) and str(row.get("name") or "").strip() == name:
            return
    workflows.append(
        {
            "name": name,
            "description": str(workflow.get("description") or ""),
            "keywords": list(workflow.get("keywords") or []),
            "required_tools": list(workflow.get("required_tools") or []),
            "default_window_hours": float(workflow.get("default_window_hours") or 8.0),
            "steps": list(workflow.get("steps") or []),
        }
    )
    payload["updated_at_utc"] = _utc_iso()
    _save_json_file(path, payload)


def _build_workflow_steps(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = _normalize_workflow_steps(spec.get("steps"))
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "title": row["title"],
                "trigger": row["trigger"],
                "status": "pending",
                "status_reason": "awaiting_trigger",
                "updated_at_utc": _utc_iso(),
            }
        )
    return out


def _load_workflow_stats(path: Path) -> Dict[str, Any]:
    payload = _load_json_file(path, {"version": 1, "workflows": {}, "action_outcomes": {}})
    if not isinstance(payload.get("workflows"), dict):
        payload["workflows"] = {}
    if not isinstance(payload.get("action_outcomes"), dict):
        payload["action_outcomes"] = {}
    return payload


def _inc_workflow_counter(stats_row: Dict[str, Any], key: str, delta: int) -> None:
    try:
        value = int(stats_row.get(key) or 0)
    except Exception:
        value = 0
    stats_row[key] = max(0, value + int(delta))


def _update_workflow_stats(stats: Dict[str, Any], action: Dict[str, Any]) -> None:
    workflows = stats.get("workflows")
    outcomes = stats.get("action_outcomes")
    if not isinstance(workflows, dict) or not isinstance(outcomes, dict):
        return
    action_id = str(action.get("action_id") or "")
    workflow_name = str(action.get("workflow_name") or "autonomy_followthrough")
    status = str(action.get("status") or "")
    if not action_id or status not in TERMINAL_ACTION_STATES:
        return
    evidence_flag = bool(status == "completed" and bool((action.get("evidence") or {}).get("has_execution_evidence")))
    executor_flag = bool(status == "completed" and bool(action.get("completed_via_executor") is True))
    prev = outcomes.get(action_id)
    if isinstance(prev, dict):
        prev_status = str(prev.get("status") or "")
        prev_workflow = str(prev.get("workflow_name") or workflow_name)
        prev_evidence_flag = bool(prev.get("evidence_completed") is True)
        prev_executor_flag = bool(prev.get("executor_completed") is True)
        if (
            prev_status == status
            and prev_workflow == workflow_name
            and prev_evidence_flag == evidence_flag
            and prev_executor_flag == executor_flag
        ):
            return
        if prev_status in TERMINAL_ACTION_STATES:
            prev_row = workflows.get(prev_workflow)
            if isinstance(prev_row, dict):
                _inc_workflow_counter(prev_row, "terminal_total", -1)
                _inc_workflow_counter(prev_row, prev_status, -1)
                if prev_evidence_flag:
                    _inc_workflow_counter(prev_row, "evidence_completed", -1)
                if prev_executor_flag:
                    _inc_workflow_counter(prev_row, "executor_completed", -1)
    row = workflows.get(workflow_name)
    if not isinstance(row, dict):
        row = {
            "terminal_total": 0,
            "completed": 0,
            "failed": 0,
            "missed": 0,
            "evidence_completed": 0,
            "executor_completed": 0,
        }
        workflows[workflow_name] = row
    _inc_workflow_counter(row, "terminal_total", 1)
    _inc_workflow_counter(row, status, 1)
    if status == "completed":
        if evidence_flag:
            _inc_workflow_counter(row, "evidence_completed", 1)
        if executor_flag:
            _inc_workflow_counter(row, "executor_completed", 1)
    row["last_outcome"] = status
    row["last_action_id"] = action_id
    row["updated_at_utc"] = _utc_iso()
    outcomes[action_id] = {
        "workflow_name": workflow_name,
        "status": status,
        "evidence_completed": evidence_flag,
        "executor_completed": executor_flag,
        "updated_at_utc": _utc_iso(),
    }


def _save_workflow_stats(path: Path, payload: Dict[str, Any]) -> None:
    payload["updated_at_utc"] = _utc_iso()
    _save_json_file(path, payload)


def _acquire_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate(0)
        handle.write(f"pid={os.getpid()} ts_utc={_utc_iso()}\n")
        handle.flush()
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _reconcile_ledger_from_events(state: Dict[str, Any], events_path: Path) -> None:
    ledger = state.get("commitments")
    if not isinstance(ledger, dict) or not events_path.exists():
        return

    latest_by_commitment: Dict[str, Dict[str, Any]] = {}
    for payload in _safe_jsonl_iter(events_path):
        if str(payload.get("type") or "") != "followthrough_attempt":
            continue
        commitment_id = str(payload.get("commitment_id") or "")
        ts_utc = str(payload.get("ts_utc") or "")
        if not commitment_id or not ts_utc:
            continue
        prev = latest_by_commitment.get(commitment_id)
        if not isinstance(prev, dict) or ts_utc >= str(prev.get("ts_utc") or ""):
            latest_by_commitment[commitment_id] = payload

    for commitment_id, event in latest_by_commitment.items():
        row = ledger.get(commitment_id)
        if not isinstance(row, dict):
            continue
        status = str(event.get("status") or "")
        if status not in {"completed", "failed", "dry_run"}:
            continue
        if status == "dry_run":
            continue
        try:
            existing_attempts = int(row.get("attempt_count") or 0)
        except Exception:
            existing_attempts = 0
        try:
            event_attempts = int(event.get("attempt_count") or 0)
        except Exception:
            event_attempts = 0
        if status == "completed" or event_attempts >= existing_attempts:
            row["status"] = status
            row["attempt_count"] = max(existing_attempts, event_attempts)
            row["last_attempt_utc"] = str(event.get("ts_utc") or row.get("last_attempt_utc") or "")
            row["last_attempt_result"] = {
                "executor_returncode": event.get("executor_returncode"),
                "manifest_path": str(event.get("manifest_path") or ""),
                "manifest_overall_ok": bool(event.get("manifest_overall_ok") is True),
            }
            if event.get("artifacts_dir"):
                row["artifacts_dir"] = str(event.get("artifacts_dir"))
            ledger[commitment_id] = row


def _parse_utc_iso(value: str) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        if value.endswith("Z"):
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def _parse_local_naive_iso(value: str) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            parsed = dt.datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _parse_ampm_hour(hour: int, ampm: str) -> int:
    suffix = ampm.lower()
    if suffix == "am":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


def _parse_schedule_window(content: str, anchor_local: dt.datetime) -> Dict[str, str]:
    if not isinstance(content, str):
        return {}

    match = WINDOW_24H_LOCAL_RE.search(content)
    if match:
        sh, sm, eh, em = [int(part) for part in match.groups()]
        start = anchor_local.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = anchor_local.replace(hour=eh, minute=em, second=0, microsecond=0)
        if end <= start:
            end += dt.timedelta(days=1)
        return {
            "start_local": start.isoformat(timespec="seconds"),
            "end_local": end.isoformat(timespec="seconds"),
            "schedule_parse": "24h_local",
        }

    match = WINDOW_12H_RE.search(content)
    if match:
        sh, sm, sampm, eh, em, eampm = match.groups()
        start = anchor_local.replace(
            hour=_parse_ampm_hour(int(sh), sampm),
            minute=int(sm),
            second=0,
            microsecond=0,
        )
        end = anchor_local.replace(
            hour=_parse_ampm_hour(int(eh), eampm),
            minute=int(em),
            second=0,
            microsecond=0,
        )
        if end <= start:
            end += dt.timedelta(days=1)
        return {
            "start_local": start.isoformat(timespec="seconds"),
            "end_local": end.isoformat(timespec="seconds"),
            "schedule_parse": "12h_explicit",
        }

    match = WINDOW_12H_TRAILING_RE.search(content)
    if match:
        sh, sm, eh, em, ampm = match.groups()
        start_hour = _parse_ampm_hour(int(sh), ampm)
        end_hour = _parse_ampm_hour(int(eh), ampm)
        start = anchor_local.replace(hour=start_hour, minute=int(sm), second=0, microsecond=0)
        end = anchor_local.replace(hour=end_hour, minute=int(em), second=0, microsecond=0)
        if end <= start:
            end += dt.timedelta(days=1)
        return {
            "start_local": start.isoformat(timespec="seconds"),
            "end_local": end.isoformat(timespec="seconds"),
            "schedule_parse": "12h_trailing",
        }

    match = SINGLE_24H_QUEUE_RE.search(content)
    if match:
        sh, sm = [int(part) for part in match.groups()]
        start = anchor_local.replace(hour=sh, minute=sm, second=0, microsecond=0)
        if start < anchor_local - dt.timedelta(hours=1):
            start += dt.timedelta(days=1)
        end = start + dt.timedelta(hours=1)
        return {
            "start_local": start.isoformat(timespec="seconds"),
            "end_local": end.isoformat(timespec="seconds"),
            "schedule_parse": "single_24h_queue_plus_1h",
        }

    return {}


def _make_commitment_id(conversation_id: str, ts_epoch: float) -> str:
    return f"{conversation_id}:{int(ts_epoch)}"


def _infer_workflow_name(content: str) -> str:
    low = str(content or "").lower()
    if any(token in low for token in ("introspection", "tool chain", "scaffold", "codex probe")):
        return "introspection_toolchain"
    if any(token in low for token in ("calendar", "schedule", "event")):
        return "calendar_followthrough"
    return "autonomy_followthrough"


def _scan_commitments(transcripts_dir: Path, lookback_hours: float) -> List[Dict[str, Any]]:
    now_local = dt.datetime.now()
    cutoff = now_local - dt.timedelta(hours=max(0.0, float(lookback_hours)))
    out: List[Dict[str, Any]] = []
    for path in sorted(transcripts_dir.glob("*.jsonl")):
        conversation_id = path.stem
        for line_number, payload in enumerate(_safe_jsonl_iter(path), start=1):
            if payload.get("role") != "assistant":
                continue
            content = payload.get("content")
            if not isinstance(content, str) or not COMMITMENT_RE.search(content):
                continue
            ts_raw = payload.get("timestamp")
            try:
                ts_epoch = float(ts_raw)
            except Exception:
                continue
            at_local = dt.datetime.fromtimestamp(ts_epoch)
            if at_local < cutoff or at_local > now_local:
                continue

            schedule = _parse_schedule_window(content, anchor_local=at_local)
            out.append(
                {
                    "commitment_id": _make_commitment_id(conversation_id, ts_epoch),
                    "conversation_id": conversation_id,
                    "ts_epoch": ts_epoch,
                    "at_local": at_local,
                    "at_local_iso": at_local.isoformat(timespec="seconds"),
                    "source": f"{path}:{line_number}",
                    "content": content,
                    "content_excerpt": content[:220],
                    "workflow_name": _infer_workflow_name(content),
                    "schedule_start_local": schedule.get("start_local", ""),
                    "schedule_end_local": schedule.get("end_local", ""),
                    "schedule_parse": schedule.get("schedule_parse", ""),
                }
            )
    out.sort(key=lambda item: float(item["ts_epoch"]))
    return out


def _sanitize_for_path(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def _latest_manifest(path: Path) -> Path | None:
    manifests = sorted(path.glob("ci_manifest_*.json"), key=lambda p: p.stat().st_mtime)
    return manifests[-1] if manifests else None


def _extract_conversation_id_from_snapshot(snapshot: Any) -> str:
    if isinstance(snapshot, dict):
        value = snapshot.get("conversation_id")
        return str(value) if value not in (None, "") else ""
    if isinstance(snapshot, str) and "conversation_id" in snapshot:
        try:
            parsed = json.loads(snapshot)
        except Exception:
            return ""
        if isinstance(parsed, dict):
            value = parsed.get("conversation_id")
            return str(value) if value not in (None, "") else ""
    return ""


def _collect_execution_evidence(
    vera_root: Path,
    conversation_ids: set[str],
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    transitions_path = vera_root / "vera_memory" / "flight_recorder" / "transitions.ndjson"
    decisions_path = vera_root / "vera_memory" / "decisions.ndjson"

    tool_calls_by_conversation: Dict[str, List[Dict[str, Any]]] = {cid: [] for cid in conversation_ids}
    decisions_by_conversation: Dict[str, List[Dict[str, Any]]] = {cid: [] for cid in conversation_ids}

    for payload in _safe_jsonl_iter(transitions_path):
        conversation_id = _extract_conversation_id_from_snapshot(payload.get("context_snapshot"))
        if not conversation_id or conversation_id not in conversation_ids:
            continue
        action = payload.get("action")
        if not isinstance(action, dict) or action.get("type") != "tool_call":
            continue
        tool_name = str(action.get("tool_name") or "")
        at = _parse_local_naive_iso(str(payload.get("timestamp") or ""))
        if not tool_name or at is None:
            continue
        tool_calls_by_conversation.setdefault(conversation_id, []).append({"at": at, "tool_name": tool_name})

    for payload in _safe_jsonl_iter(decisions_path):
        context = payload.get("context")
        if not isinstance(context, dict):
            continue
        conversation_id = str(context.get("conversation_id") or "")
        if not conversation_id or conversation_id not in conversation_ids:
            continue
        tool_name = str(context.get("tool") or "")
        at = _parse_local_naive_iso(str(payload.get("timestamp") or ""))
        if at is None:
            continue
        decisions_by_conversation.setdefault(conversation_id, []).append(
            {
                "at": at,
                "tool_name": tool_name,
                "decision_type": str(payload.get("decision_type") or ""),
            }
        )

    return tool_calls_by_conversation, decisions_by_conversation


def _parse_local_iso(value: str) -> Optional[dt.datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip())
    except Exception:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _window_for_commitment(commitment: Dict[str, Any], default_window_hours: float) -> Tuple[dt.datetime, dt.datetime, bool]:
    start = _parse_local_iso(str(commitment.get("schedule_start_local") or ""))
    end = _parse_local_iso(str(commitment.get("schedule_end_local") or ""))
    if start is not None and end is not None and end > start:
        return start, end, True

    fallback_start = commitment["at_local"]
    fallback_end = fallback_start + dt.timedelta(hours=max(0.0, float(default_window_hours)))
    return fallback_start, fallback_end, False


def _count_window_evidence(
    commitment: Dict[str, Any],
    tool_calls_by_conversation: Dict[str, List[Dict[str, Any]]],
    decisions_by_conversation: Dict[str, List[Dict[str, Any]]],
    default_window_hours: float,
) -> Dict[str, Any]:
    conversation_id = str(commitment["conversation_id"])
    window_start, window_end, used_schedule = _window_for_commitment(commitment, default_window_hours)

    tool_calls = [
        row
        for row in tool_calls_by_conversation.get(conversation_id, [])
        if window_start < row["at"] <= window_end and row["tool_name"] not in PLANNING_ONLY_TOOLS
    ]
    blocked_attempts = [
        row
        for row in decisions_by_conversation.get(conversation_id, [])
        if window_start < row["at"] <= window_end and row["tool_name"] not in PLANNING_ONLY_TOOLS
    ]
    return {
        "window_start_local": window_start.isoformat(timespec="seconds"),
        "window_end_local": window_end.isoformat(timespec="seconds"),
        "window_used_schedule": used_schedule,
        "tool_call_count": len(tool_calls),
        "blocked_attempt_count": len(blocked_attempts),
        # Blocked attempts are diagnostics, not successful execution evidence.
        "has_execution_evidence": bool(tool_calls),
        "has_blocked_evidence": bool(blocked_attempts),
    }


def _write_scaffold_note(
    path: Path,
    commitment: Dict[str, Any],
    status: str,
    rc: int,
    manifest_path: Path | None,
    manifest: Dict[str, Any],
) -> None:
    checks = manifest.get("checks") if isinstance(manifest, dict) else {}
    doctor = checks.get("doctor") if isinstance(checks, dict) else {}
    professor = checks.get("professor") if isinstance(checks, dict) else {}
    content = [
        "# Follow-through Scaffold",
        "",
        f"- Commitment ID: `{commitment['commitment_id']}`",
        f"- Conversation: `{commitment['conversation_id']}`",
        f"- Commitment time (local): `{commitment['at_local_iso']}`",
        f"- Workflow: `{commitment.get('workflow_name', 'autonomy_followthrough')}`",
        f"- Status: `{status}`",
        f"- Executor return code: `{rc}`",
        f"- Manifest: `{manifest_path}`" if manifest_path else "- Manifest: ``",
        "",
        "## Commitment Excerpt",
        commitment["content_excerpt"],
        "",
        "## Check Snapshot",
        f"- doctor: `{doctor}`",
        f"- professor: `{professor}`",
        "",
        "## Next Steps",
        "1. If failed, inspect executor logs in this run directory and clear blockers.",
        "2. Re-run executor once blockers are addressed.",
        "3. Confirm Doctor follow-through audit returns `ok`.",
        "",
    ]
    path.write_text("\n".join(content), encoding="utf-8")


def _run_executor_bundle(
    *,
    vera_root: Path,
    harness_root: Path,
    base_url: str,
    run_dir: Path,
    timeout_s: float,
) -> Tuple[int, str, str, Path | None, Dict[str, Any]]:
    ci_logs = run_dir / "ci"
    cmd = [
        sys.executable,
        str(vera_root / "scripts" / "vera_doctor_professor_ci_gate.py"),
        "--base-url",
        base_url.rstrip("/"),
        "--logs-dir",
        str(ci_logs),
        "--allow-doctor-failure",
        "doctor:followthrough_audit",
        "--harness-root",
        str(harness_root),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(60.0, float(timeout_s)),
            check=False,
            cwd=str(vera_root),
        )
        rc = int(proc.returncode)
        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        rc = 124
        stdout_text = exc.stdout or ""
        stderr_text = (exc.stderr or "") + "\nTIMEOUT"
    except Exception as exc:
        rc = 125
        stdout_text = ""
        stderr_text = str(exc)

    manifest_path = _latest_manifest(ci_logs)
    manifest_payload: Dict[str, Any] = {}
    if manifest_path and manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest_payload = loaded
        except Exception:
            manifest_payload = {}
    return rc, stdout_text, stderr_text, manifest_path, manifest_payload


def _set_action_status(
    *,
    action: Dict[str, Any],
    new_status: str,
    reason: str,
    action_events_path: Path,
) -> None:
    old_status = str(action.get("status") or "")
    old_reason = str(action.get("status_reason") or "")
    action["status"] = new_status
    action["status_reason"] = reason
    action["updated_at_utc"] = _utc_iso()
    if old_status != new_status or old_reason != reason:
        _append_event(
            action_events_path,
            {
                "ts_utc": _utc_iso(),
                "type": "action_status_changed",
                "action_id": action.get("action_id"),
                "from_status": old_status,
                "to_status": new_status,
                "reason": reason,
            },
        )


def _workflow_effective_window_hours(
    action: Dict[str, Any],
    workflow_specs: Dict[str, Dict[str, Any]],
    fallback_hours: float,
) -> float:
    workflow_name = str(action.get("workflow_name") or "autonomy_followthrough")
    spec = workflow_specs.get(workflow_name, {})
    try:
        candidate = float(spec.get("default_window_hours") or 0.0)
    except Exception:
        candidate = 0.0
    if candidate <= 0.0:
        candidate = float(fallback_hours)
    return max(0.5, candidate)


def _step_status_for_trigger(
    trigger: str,
    *,
    action: Dict[str, Any],
    evidence: Dict[str, Any],
    now_local: dt.datetime,
) -> Tuple[str, str]:
    status = str(action.get("status") or "")
    if trigger == "discovered":
        return "completed", "commitment_discovered"
    if trigger == "window_started":
        start = _parse_local_iso(str(action.get("schedule_start_local") or ""))
        if start is not None and now_local >= start:
            return "completed", "window_started"
        return "pending", "awaiting_window_start"
    if trigger == "execution_evidence":
        if bool(evidence.get("has_execution_evidence")):
            return "completed", "execution_evidence"
        if bool(action.get("completed_via_executor") is True):
            return "completed", "executor_validated"
        if status == "completed" and str(action.get("status_reason") or "") == "ledger_completed_verified":
            return "completed", "ledger_validated"
        if int(evidence.get("blocked_attempt_count") or 0) > 0:
            return "running", "blocked_attempt_recorded"
        if status == "failed":
            return "failed", "workflow_failed_before_evidence"
        if status == "missed":
            return "failed", "window_missed_without_evidence"
        return "pending", "awaiting_execution_evidence"
    if trigger == "executor_success":
        if bool(action.get("completed_via_executor") is True):
            return "completed", "executor_success"
        if status == "failed":
            return "failed", "executor_failure"
        return "pending", "awaiting_executor_success"
    if trigger == "terminal":
        if status == "completed":
            return "completed", "action_completed"
        if status in {"failed", "missed"}:
            return "failed", f"action_{status}"
        return "pending", "awaiting_terminal_status"
    return "pending", "unknown_trigger"


def _sync_action_step_statuses(
    *,
    action: Dict[str, Any],
    evidence: Dict[str, Any],
    now_local: dt.datetime,
    action_events_path: Path,
) -> None:
    steps = action.get("workflow_steps")
    if not isinstance(steps, list):
        return
    changed = False
    for row in steps:
        if not isinstance(row, dict):
            continue
        trigger = str(row.get("trigger") or "execution_evidence")
        old_status = str(row.get("status") or "pending")
        old_reason = str(row.get("status_reason") or "")
        new_status, new_reason = _step_status_for_trigger(
            trigger,
            action=action,
            evidence=evidence,
            now_local=now_local,
        )
        row["status"] = new_status
        row["status_reason"] = new_reason
        row["updated_at_utc"] = _utc_iso()
        if old_status != new_status or old_reason != new_reason:
            changed = True
            _append_event(
                action_events_path,
                {
                    "ts_utc": _utc_iso(),
                    "type": "workflow_step_status_changed",
                    "action_id": action.get("action_id"),
                    "workflow_name": action.get("workflow_name"),
                    "step_id": row.get("id"),
                    "from_status": old_status,
                    "to_status": new_status,
                    "reason": new_reason,
                },
            )
    if changed:
        action["updated_at_utc"] = _utc_iso()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run autonomy follow-through executor and update local ledgers")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--vera-root", default=str(_default_vera_root()))
    parser.add_argument("--harness-root", default="")
    parser.add_argument("--lookback-hours", type=float, default=24.0)
    parser.add_argument("--grace-minutes", type=float, default=30.0)
    parser.add_argument("--attempt-cooldown-minutes", type=float, default=45.0)
    parser.add_argument("--max-runs-per-pass", type=int, default=1)
    parser.add_argument("--executor-timeout", type=float, default=2400.0)
    parser.add_argument("--default-window-hours", type=float, default=8.0)
    parser.add_argument("--state-file", default="tmp/followthrough_state.json")
    parser.add_argument("--events-log", default="tmp/followthrough_events.jsonl")
    parser.add_argument("--actions-file", default="tmp/followthrough_actions.json")
    parser.add_argument("--action-events-log", default="tmp/followthrough_action_events.jsonl")
    parser.add_argument("--workflow-catalog-file", default="config/followthrough_workflows.json")
    parser.add_argument("--learned-workflows-file", default="tmp/followthrough_learned_workflows.json")
    parser.add_argument("--workflow-stats-file", default="tmp/followthrough_workflow_stats.json")
    parser.add_argument("--min-workflow-confidence", type=float, default=0.45)
    parser.add_argument("--logs-root", default="tmp/followthrough_runs")
    parser.add_argument("--lock-file", default="tmp/followthrough_executor.lock")
    parser.add_argument("--escalate-failures", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    vera_root = Path(args.vera_root).expanduser().resolve()
    harness_root = _default_harness_root(vera_root).resolve() if not args.harness_root else Path(args.harness_root).expanduser().resolve()

    if not (vera_root / "scripts" / "vera_doctor_professor_ci_gate.py").exists():
        raise SystemExit(f"Missing CI gate under vera root: {vera_root}")
    if not (harness_root / "doctor_clinic.py").exists():
        raise SystemExit(f"Missing Doctor harness root: {harness_root}")

    state_path = Path(args.state_file) if Path(args.state_file).is_absolute() else (vera_root / args.state_file)
    events_path = Path(args.events_log) if Path(args.events_log).is_absolute() else (vera_root / args.events_log)
    actions_path = Path(args.actions_file) if Path(args.actions_file).is_absolute() else (vera_root / args.actions_file)
    action_events_path = Path(args.action_events_log) if Path(args.action_events_log).is_absolute() else (vera_root / args.action_events_log)
    workflow_catalog_path = (
        Path(args.workflow_catalog_file) if Path(args.workflow_catalog_file).is_absolute() else (vera_root / args.workflow_catalog_file)
    )
    learned_workflows_path = (
        Path(args.learned_workflows_file) if Path(args.learned_workflows_file).is_absolute() else (vera_root / args.learned_workflows_file)
    )
    workflow_stats_path = (
        Path(args.workflow_stats_file) if Path(args.workflow_stats_file).is_absolute() else (vera_root / args.workflow_stats_file)
    )
    logs_root = Path(args.logs_root) if Path(args.logs_root).is_absolute() else (vera_root / args.logs_root)
    lock_path = Path(args.lock_file) if Path(args.lock_file).is_absolute() else (vera_root / args.lock_file)

    lock_handle = _acquire_lock(lock_path)
    if lock_handle is None:
        print(
            json.dumps(
                {"ts_utc": _utc_iso(), "skipped": True, "reason": "lock_active", "lock_file": str(lock_path)},
                indent=2,
                ensure_ascii=True,
            )
        )
        return 0

    try:
        transcripts_dir = vera_root / "vera_memory" / "transcripts"
        commitments = _scan_commitments(transcripts_dir, lookback_hours=args.lookback_hours)

        state = _load_state(state_path)
        ledger = state.get("commitments")
        if not isinstance(ledger, dict):
            ledger = {}
            state["commitments"] = ledger
        _reconcile_ledger_from_events(state, events_path)

        actions_payload = _load_actions(actions_path)
        actions = actions_payload.get("actions")
        if not isinstance(actions, dict):
            actions = {}
            actions_payload["actions"] = actions
        workflow_catalog = _load_workflow_catalog(workflow_catalog_path, learned_workflows_path)
        workflow_specs = workflow_catalog.get("workflows")
        if not isinstance(workflow_specs, dict):
            workflow_specs = {}
        workflow_stats = _load_workflow_stats(workflow_stats_path)
        if not workflow_catalog_path.exists():
            _save_json_file(workflow_catalog_path, DEFAULT_WORKFLOW_CATALOG)
        if not learned_workflows_path.exists():
            _save_json_file(learned_workflows_path, {"version": 1, "workflows": [], "updated_at_utc": _utc_iso()})

        conversation_ids = {str(item["conversation_id"]) for item in commitments}
        tool_calls_by_conversation, decisions_by_conversation = _collect_execution_evidence(
            vera_root=vera_root,
            conversation_ids=conversation_ids,
        )

        now_utc = _utc_now()
        now_local = dt.datetime.now()
        grace_cutoff = now_local - dt.timedelta(minutes=max(0.0, float(args.grace_minutes)))
        cooldown = dt.timedelta(minutes=max(0.0, float(args.attempt_cooldown_minutes)))

        for commitment in commitments:
            commitment_id = str(commitment["commitment_id"])
            workflow_match = _infer_workflow(str(commitment.get("content") or ""), workflow_specs)
            workflow_name = str(workflow_match.get("name") or "autonomy_followthrough")
            workflow_spec = workflow_specs.get(workflow_name, workflow_specs.get("autonomy_followthrough", {}))

            if (
                workflow_match.get("source") == "fallback"
                and float(workflow_match.get("confidence") or 0.0) < float(args.min_workflow_confidence)
            ):
                learned_workflow = _build_learned_workflow(str(commitment.get("content") or ""), workflow_specs)
                if learned_workflow:
                    workflow_specs[learned_workflow["name"]] = learned_workflow
                    _persist_learned_workflow(learned_workflows_path, learned_workflow)
                    workflow_name = learned_workflow["name"]
                    workflow_spec = learned_workflow
                    workflow_match = {
                        "name": workflow_name,
                        "confidence": max(float(args.min_workflow_confidence), 0.5),
                        "matched_keywords": list(learned_workflow.get("keywords") or []),
                        "source": "learned_new",
                    }

            if commitment_id not in ledger:
                ledger[commitment_id] = {
                    "commitment_id": commitment_id,
                    "conversation_id": commitment["conversation_id"],
                    "commitment_ts_epoch": commitment["ts_epoch"],
                    "commitment_at_local": commitment["at_local_iso"],
                    "source": commitment["source"],
                    "content_excerpt": commitment["content_excerpt"],
                    "status": "pending",
                    "attempt_count": 0,
                    "last_attempt_utc": "",
                    "last_attempt_result": {},
                    "artifacts_dir": "",
                }

            action = actions.get(commitment_id)
            if not isinstance(action, dict):
                action = {
                    "action_id": commitment_id,
                    "commitment_id": commitment_id,
                    "conversation_id": commitment["conversation_id"],
                    "workflow_name": workflow_name,
                    "workflow_confidence": float(workflow_match.get("confidence") or 0.0),
                    "workflow_match_source": str(workflow_match.get("source") or ""),
                    "workflow_matched_keywords": list(workflow_match.get("matched_keywords") or []),
                    "workflow_required_tools": list(workflow_spec.get("required_tools") or []),
                    "workflow_catalog_version": int(workflow_spec.get("catalog_version") or workflow_catalog.get("version") or 1),
                    "workflow_steps": _build_workflow_steps(workflow_spec),
                    "source": commitment["source"],
                    "content_excerpt": commitment["content_excerpt"],
                    "commitment_at_local": commitment["at_local_iso"],
                    "schedule_start_local": commitment.get("schedule_start_local", ""),
                    "schedule_end_local": commitment.get("schedule_end_local", ""),
                    "schedule_parse": commitment.get("schedule_parse", ""),
                    "status": "planned",
                    "status_reason": "new_commitment",
                    "evidence": {},
                    "completed_via_executor": False,
                    "created_at_utc": _utc_iso(),
                    "updated_at_utc": _utc_iso(),
                }
                actions[commitment_id] = action
                _append_event(
                    action_events_path,
                    {
                        "ts_utc": _utc_iso(),
                        "type": "action_discovered",
                        "action_id": commitment_id,
                        "conversation_id": commitment["conversation_id"],
                        "workflow_name": action["workflow_name"],
                        "workflow_confidence": action.get("workflow_confidence"),
                        "workflow_match_source": action.get("workflow_match_source"),
                    },
                )
                _append_event(
                    action_events_path,
                    {
                        "ts_utc": _utc_iso(),
                        "type": "action_workflow_bound",
                        "action_id": commitment_id,
                        "workflow_name": action["workflow_name"],
                        "workflow_confidence": action.get("workflow_confidence"),
                        "workflow_match_source": action.get("workflow_match_source"),
                        "workflow_matched_keywords": action.get("workflow_matched_keywords", []),
                    },
                )

            if not action.get("workflow_name"):
                action["workflow_name"] = workflow_name
            bound_workflow_name = str(action.get("workflow_name") or workflow_name)
            bound_spec = workflow_specs.get(bound_workflow_name, workflow_spec)
            expected_steps = _normalize_workflow_steps(bound_spec.get("steps"))
            expected_step_ids = [row.get("id") for row in expected_steps]
            current_steps = action.get("workflow_steps")
            if isinstance(current_steps, list):
                current_step_ids = [str(row.get("id") or "") for row in current_steps if isinstance(row, dict)]
                if current_step_ids and expected_step_ids and current_step_ids != expected_step_ids:
                    action["workflow_steps"] = _build_workflow_steps(bound_spec)
                    _append_event(
                        action_events_path,
                        {
                            "ts_utc": _utc_iso(),
                            "type": "workflow_steps_reset",
                            "action_id": commitment_id,
                            "workflow_name": bound_workflow_name,
                            "reason": "step_shape_mismatch",
                        },
                    )
            if not isinstance(action.get("workflow_steps"), list):
                action["workflow_steps"] = _build_workflow_steps(bound_spec)
            if not isinstance(action.get("workflow_required_tools"), list):
                action["workflow_required_tools"] = list(bound_spec.get("required_tools") or [])
            if "workflow_confidence" not in action:
                action["workflow_confidence"] = float(workflow_match.get("confidence") or 0.0)
            if "workflow_match_source" not in action:
                action["workflow_match_source"] = str(workflow_match.get("source") or "")
            if "workflow_matched_keywords" not in action:
                action["workflow_matched_keywords"] = list(workflow_match.get("matched_keywords") or [])
            if "workflow_catalog_version" not in action:
                action["workflow_catalog_version"] = int(bound_spec.get("catalog_version") or workflow_catalog.get("version") or 1)

            if not action.get("schedule_start_local") and commitment.get("schedule_start_local"):
                action["schedule_start_local"] = commitment.get("schedule_start_local", "")
                action["schedule_end_local"] = commitment.get("schedule_end_local", "")
                action["schedule_parse"] = commitment.get("schedule_parse", "")
                _append_event(
                    action_events_path,
                    {
                        "ts_utc": _utc_iso(),
                        "type": "action_schedule_parsed",
                        "action_id": commitment_id,
                        "schedule_start_local": action.get("schedule_start_local", ""),
                        "schedule_end_local": action.get("schedule_end_local", ""),
                        "schedule_parse": action.get("schedule_parse", ""),
                    },
                )

        runs_attempted = 0

        for commitment in commitments:
            commitment_id = str(commitment["commitment_id"])
            entry = ledger.get(commitment_id)
            action = actions.get(commitment_id)
            if not isinstance(entry, dict) or not isinstance(action, dict):
                continue

            evidence = _count_window_evidence(
                commitment=commitment,
                tool_calls_by_conversation=tool_calls_by_conversation,
                decisions_by_conversation=decisions_by_conversation,
                default_window_hours=_workflow_effective_window_hours(
                    action=action,
                    workflow_specs=workflow_specs,
                    fallback_hours=float(args.default_window_hours),
                ),
            )
            action["evidence"] = {**evidence, "last_checked_local": now_local.isoformat(timespec="seconds")}
            required_tools = action.get("workflow_required_tools")
            if isinstance(required_tools, list) and required_tools:
                observed_tools = set()
                for row in tool_calls_by_conversation.get(str(action.get("conversation_id") or ""), []):
                    if isinstance(row, dict):
                        observed_tools.add(str(row.get("tool_name") or ""))
                missing_required = [tool for tool in required_tools if tool not in observed_tools]
            else:
                missing_required = []
            action["missing_required_tools"] = missing_required

            schedule_start = _parse_local_iso(str(action.get("schedule_start_local") or ""))
            schedule_end = _parse_local_iso(str(action.get("schedule_end_local") or ""))
            has_schedule = schedule_start is not None and schedule_end is not None and schedule_end > schedule_start
            legacy_completed_verified = False
            if str(entry.get("status") or "") == "completed":
                last_result = entry.get("last_attempt_result")
                if isinstance(last_result, dict) and bool(last_result.get("manifest_overall_ok") is True):
                    legacy_completed_verified = True
                if bool(action.get("completed_via_executor") is True):
                    legacy_completed_verified = True

            if evidence["has_execution_evidence"]:
                _set_action_status(action=action, new_status="completed", reason="execution_evidence_in_window", action_events_path=action_events_path)
                if str(entry.get("status") or "") != "completed":
                    entry["status"] = "completed"
                    entry["last_attempt_utc"] = _utc_iso()
                    entry["last_attempt_result"] = {
                        "evidence_only": True,
                        "tool_call_count": evidence["tool_call_count"],
                        "blocked_attempt_count": evidence["blocked_attempt_count"],
                        "window_start_local": evidence["window_start_local"],
                        "window_end_local": evidence["window_end_local"],
                    }
            elif str(entry.get("status") or "") == "completed" and legacy_completed_verified:
                _set_action_status(action=action, new_status="completed", reason="ledger_completed_verified", action_events_path=action_events_path)
            elif str(entry.get("status") or "") == "completed":
                if has_schedule and schedule_end is not None and now_local > schedule_end:
                    _set_action_status(action=action, new_status="missed", reason="legacy_completed_without_verification", action_events_path=action_events_path)
                else:
                    _set_action_status(action=action, new_status="planned", reason="legacy_completed_without_verification", action_events_path=action_events_path)
            elif str(entry.get("status") or "") == "failed":
                _set_action_status(action=action, new_status="failed", reason="executor_failed", action_events_path=action_events_path)
            elif has_schedule:
                if now_local < schedule_start:
                    _set_action_status(action=action, new_status="planned", reason="before_schedule_window", action_events_path=action_events_path)
                elif schedule_start <= now_local <= schedule_end:
                    _set_action_status(action=action, new_status="running", reason="within_schedule_window", action_events_path=action_events_path)
                else:
                    _set_action_status(action=action, new_status="missed", reason="schedule_window_elapsed_without_evidence", action_events_path=action_events_path)
            else:
                if commitment["at_local"] > grace_cutoff:
                    _set_action_status(action=action, new_status="planned", reason="within_grace_period", action_events_path=action_events_path)
                else:
                    window_end = _parse_local_iso(evidence["window_end_local"])
                    if window_end is not None and now_local > window_end:
                        _set_action_status(action=action, new_status="missed", reason="default_window_elapsed_without_evidence", action_events_path=action_events_path)
                    else:
                        _set_action_status(action=action, new_status="planned", reason="awaiting_execution_evidence", action_events_path=action_events_path)
            _sync_action_step_statuses(
                action=action,
                evidence=evidence,
                now_local=now_local,
                action_events_path=action_events_path,
            )

        for commitment in commitments:
            if runs_attempted >= max(0, int(args.max_runs_per_pass)):
                break

            commitment_id = str(commitment["commitment_id"])
            entry = ledger.get(commitment_id)
            action = actions.get(commitment_id)
            if not isinstance(entry, dict) or not isinstance(action, dict):
                continue
            if str(entry.get("status") or "") == "completed":
                continue

            action_status = str(action.get("status") or "")
            schedule_end = _parse_local_iso(str(action.get("schedule_end_local") or ""))
            has_schedule = schedule_end is not None

            if has_schedule and schedule_end is not None and now_local <= schedule_end and action_status in {"planned", "running"}:
                continue
            if not has_schedule and commitment["at_local"] > grace_cutoff:
                continue

            last_attempt = _parse_utc_iso(str(entry.get("last_attempt_utc") or ""))
            if last_attempt is not None and (now_utc - last_attempt) < cooldown:
                continue

            runs_attempted += 1
            run_stamp = _utc_ts()
            run_dir = logs_root / _sanitize_for_path(commitment_id) / run_stamp
            run_dir.mkdir(parents=True, exist_ok=True)

            if args.dry_run:
                _append_event(
                    events_path,
                    {"ts_utc": _utc_iso(), "type": "followthrough_attempt", "commitment_id": commitment_id, "status": "dry_run", "artifacts_dir": str(run_dir)},
                )
                _append_event(
                    action_events_path,
                    {"ts_utc": _utc_iso(), "type": "action_execution_attempt", "action_id": commitment_id, "status": "dry_run", "artifacts_dir": str(run_dir)},
                )
                _sync_action_step_statuses(
                    action=action,
                    evidence=(action.get("evidence") if isinstance(action.get("evidence"), dict) else {}),
                    now_local=now_local,
                    action_events_path=action_events_path,
                )
                continue

            rc, stdout_text, stderr_text, manifest_path, manifest = _run_executor_bundle(
                vera_root=vera_root,
                harness_root=harness_root,
                base_url=args.base_url,
                run_dir=run_dir,
                timeout_s=float(args.executor_timeout),
            )
            (run_dir / "executor.stdout.log").write_text(stdout_text, encoding="utf-8")
            (run_dir / "executor.stderr.log").write_text(stderr_text, encoding="utf-8")

            overall_ok = bool(isinstance(manifest, dict) and manifest.get("overall_ok") is True)
            status = "completed" if (rc == 0 and overall_ok) else "failed"
            failure_reason = ""
            if status != "completed":
                if rc != 0:
                    failure_reason = f"executor_returncode:{rc}"
                elif not overall_ok:
                    failure_reason = "manifest_not_ok"
                else:
                    failure_reason = "executor_failed"

            _write_scaffold_note(
                run_dir / "scaffold.md",
                commitment=commitment,
                status=status,
                rc=rc,
                manifest_path=manifest_path,
                manifest=manifest,
            )

            try:
                attempt_count = int(entry.get("attempt_count") or 0) + 1
            except Exception:
                attempt_count = 1
            entry["attempt_count"] = attempt_count
            entry["status"] = status
            previous_consecutive_failures = int(entry.get("consecutive_failures") or 0)
            if status == "completed":
                entry["consecutive_failures"] = 0
            else:
                entry["consecutive_failures"] = previous_consecutive_failures + 1
            entry["last_attempt_utc"] = _utc_iso()
            entry["last_attempt_result"] = {
                "executor_returncode": rc,
                "manifest_path": str(manifest_path) if manifest_path else "",
                "manifest_overall_ok": overall_ok,
                "failure_reason": failure_reason,
            }
            entry["artifacts_dir"] = str(run_dir)
            ledger[commitment_id] = entry
            action["last_execution_attempt_utc"] = _utc_iso()
            action["last_execution_attempt_status"] = status
            action["last_execution_failure_reason"] = failure_reason

            _append_event(
                events_path,
                {
                    "ts_utc": _utc_iso(),
                    "type": "followthrough_attempt",
                    "commitment_id": commitment_id,
                    "status": status,
                    "attempt_count": attempt_count,
                    "executor_returncode": rc,
                    "manifest_path": str(manifest_path) if manifest_path else "",
                    "manifest_overall_ok": overall_ok,
                    "failure_reason": failure_reason,
                    "consecutive_failures": int(entry.get("consecutive_failures") or 0),
                    "artifacts_dir": str(run_dir),
                },
            )

            if status == "completed":
                action["completed_via_executor"] = True
                action["needs_human_review"] = False
                action["review_reason"] = ""
                _set_action_status(action=action, new_status="completed", reason="executor_success", action_events_path=action_events_path)
            else:
                status_reason = f"executor_failed:{failure_reason}" if failure_reason else "executor_failed"
                _set_action_status(action=action, new_status="failed", reason=status_reason, action_events_path=action_events_path)
                escalate_threshold = max(1, int(args.escalate_failures))
                if int(entry.get("consecutive_failures") or 0) >= escalate_threshold:
                    action["needs_human_review"] = True
                    action["review_reason"] = (
                        f"consecutive_failures>={escalate_threshold}:{failure_reason or 'executor_failed'}"
                    )
                    _append_event(
                        action_events_path,
                        {
                            "ts_utc": _utc_iso(),
                            "type": "action_escalation_needed",
                            "action_id": commitment_id,
                            "consecutive_failures": int(entry.get("consecutive_failures") or 0),
                            "threshold": escalate_threshold,
                            "failure_reason": failure_reason,
                        },
                    )
            _sync_action_step_statuses(
                action=action,
                evidence=(action.get("evidence") if isinstance(action.get("evidence"), dict) else {}),
                now_local=now_local,
                action_events_path=action_events_path,
            )

            _append_event(
                action_events_path,
                {
                    "ts_utc": _utc_iso(),
                    "type": "action_execution_attempt",
                    "action_id": commitment_id,
                    "status": status,
                    "attempt_count": attempt_count,
                    "executor_returncode": rc,
                    "manifest_path": str(manifest_path) if manifest_path else "",
                    "manifest_overall_ok": overall_ok,
                    "failure_reason": failure_reason,
                    "consecutive_failures": int(entry.get("consecutive_failures") or 0),
                    "artifacts_dir": str(run_dir),
                },
            )

        workflow_stats["workflows"] = {}
        workflow_stats["action_outcomes"] = {}
        for value in actions.values():
            if isinstance(value, dict):
                _update_workflow_stats(workflow_stats, value)

        _save_state(state_path, state)
        _save_actions(actions_path, actions_payload)
        _save_workflow_stats(workflow_stats_path, workflow_stats)

        unresolved = 0
        completed = 0
        failed = 0
        for value in ledger.values():
            if not isinstance(value, dict):
                continue
            status = str(value.get("status") or "")
            if status == "completed":
                completed += 1
            elif status == "failed":
                failed += 1
            else:
                unresolved += 1

        action_status_counts: Dict[str, int] = {}
        actions_needing_human_review = 0
        for value in actions.values():
            if not isinstance(value, dict):
                continue
            status = str(value.get("status") or "unknown")
            action_status_counts[status] = action_status_counts.get(status, 0) + 1
            if bool(value.get("needs_human_review") is True):
                actions_needing_human_review += 1

        workflow_outcome_counts: Dict[str, Dict[str, int]] = {}
        workflows_obj = workflow_stats.get("workflows")
        if isinstance(workflows_obj, dict):
            for name, row in workflows_obj.items():
                if not isinstance(row, dict):
                    continue
                workflow_outcome_counts[str(name)] = {
                    "terminal_total": int(row.get("terminal_total") or 0),
                    "completed": int(row.get("completed") or 0),
                    "failed": int(row.get("failed") or 0),
                    "missed": int(row.get("missed") or 0),
                }

        print(
            json.dumps(
                {
                    "ts_utc": _utc_iso(),
                    "commitments_seen": len(commitments),
                    "actions_seen": len(actions),
                    "runs_attempted": runs_attempted,
                    "completed": completed,
                    "failed": failed,
                    "unresolved": unresolved,
                    "action_status_counts": action_status_counts,
                    "actions_needing_human_review": actions_needing_human_review,
                    "workflow_catalog_size": len(workflow_specs),
                    "workflow_outcome_counts": workflow_outcome_counts,
                    "state_file": str(state_path),
                    "events_log": str(events_path),
                    "actions_file": str(actions_path),
                    "action_events_log": str(action_events_path),
                    "workflow_stats_file": str(workflow_stats_path),
                    "learned_workflows_file": str(learned_workflows_path),
                },
                indent=2,
                ensure_ascii=True,
            )
        )
        return 0
    finally:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
