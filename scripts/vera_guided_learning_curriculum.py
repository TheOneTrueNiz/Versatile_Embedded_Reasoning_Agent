#!/usr/bin/env python3
"""
Guided learning curriculum runner for Vera.

Runs a configurable multi-lesson session against /v1/chat/completions and
validates expected tool usage per lesson. This is designed to complement the
Doctor/Professor harness with Vera-specific tool-fluency drills.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from urllib import error, request


def normalize_v1(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def api_root(v1_url: str) -> str:
    return v1_url[:-3] if v1_url.endswith("/v1") else v1_url


def http_json(
    method: str,
    url: str,
    payload: Dict[str, Any] | None = None,
    timeout: float = 90.0,
) -> Tuple[int, Any, str]:
    body = None
    headers: Dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = resp.getcode()
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, None, raw
    except Exception as exc:
        return 0, None, str(exc)
    try:
        return code, json.loads(raw), raw
    except Exception:
        return code, None, raw


def _wait_for_ready(
    *,
    api_url: str,
    timeout_s: float,
    ready_streak: int,
    poll_s: float = 1.0,
) -> bool:
    timeout = max(0.0, float(timeout_s))
    if timeout <= 0.0:
        return True
    required_streak = max(1, int(ready_streak))
    deadline = time.time() + timeout
    streak = 0
    readiness_url = f"{api_url.rstrip('/')}/api/readiness"
    while time.time() < deadline:
        code, payload, _ = http_json("GET", readiness_url, timeout=max(2.0, poll_s + 1.5))
        ready = bool(code == 200 and isinstance(payload, dict) and payload.get("ready") is True)
        if ready:
            streak += 1
            if streak >= required_streak:
                return True
        else:
            streak = 0
        time.sleep(max(0.1, poll_s))
    return False


def choose_model(v1_url: str, override: str | None, timeout: float) -> str:
    if override:
        return override
    code, payload, _ = http_json("GET", f"{v1_url}/models", timeout=timeout)
    if code == 200 and isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            model = data[0].get("id")
            if isinstance(model, str) and model:
                return model
    return "grok-4-1-fast-reasoning"


def extract_reply(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _parse_local_naive_iso(value: str) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
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


def _extract_conversation_id(snapshot: Any) -> str:
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


def _tools_from_transitions(
    transitions_path: Path,
    conversation_id: str,
    start_local: dt.datetime,
) -> List[str]:
    if not transitions_path.exists():
        return []
    tools: List[str] = []
    with transitions_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            action = payload.get("action")
            if not isinstance(action, dict) or action.get("type") != "tool_call":
                continue
            ts_local = _parse_local_naive_iso(str(payload.get("timestamp") or ""))
            if ts_local is None or ts_local < start_local:
                continue
            cid = _extract_conversation_id(payload.get("context_snapshot"))
            if cid != conversation_id:
                continue
            tool_name = str(action.get("tool_name") or "").strip()
            if tool_name and tool_name not in tools:
                tools.append(tool_name)
    return tools


def get_last_tools(api_url: str, timeout: float) -> List[str]:
    code, payload, _ = http_json("GET", f"{api_url}/api/tools/last_payload", timeout=timeout)
    if code != 200 or not isinstance(payload, dict):
        return []
    blob = payload.get("payload")
    if not isinstance(blob, dict):
        return []
    tools = blob.get("last_tools_used")
    if not isinstance(tools, list):
        return []
    return [str(item) for item in tools if isinstance(item, str)]


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dedupe(items: List[str]) -> List[str]:
    out: List[str] = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _normalize_expected_groups(lesson_obj: Dict[str, Any]) -> List[List[str]]:
    groups: List[List[str]] = []
    raw_groups = lesson_obj.get("expected_tool_groups_any_order")
    if isinstance(raw_groups, list):
        for entry in raw_groups:
            if isinstance(entry, list):
                group = [
                    str(name).strip()
                    for name in entry
                    if isinstance(name, str) and str(name).strip()
                ]
            elif isinstance(entry, str) and entry.strip():
                group = [entry.strip()]
            else:
                group = []
            if group:
                groups.append(group)
    if groups:
        return groups

    expected = _dedupe(list(lesson_obj.get("expected_tools_any_order") or []))
    return [[name] for name in expected]


def parse_inventory_tools(path: Path) -> Set[str]:
    tool_re = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
    tools: Set[str] = set()
    if not path.exists():
        return tools
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if "," in line:
            for token in line.split(","):
                name = token.strip()
                if tool_re.fullmatch(name):
                    tools.add(name)
            continue
        if tool_re.fullmatch(line):
            # Accept plain one-token tool lines (e.g., "time"), but skip title
            # headers like "Core", "Search", "Knowledge".
            if "_" in line or line.isupper() or line.lower() == line:
                tools.add(line)
    return tools


def fetch_runtime_tools(api_url: str, timeout: float) -> Dict[str, Any]:
    runtime_tools: Set[str] = set()
    diagnostics: Dict[str, Any] = {
        "tools_list_http": 0,
        "tools_defs_http": 0,
        "errors": {},
    }

    list_code, list_payload, list_raw = http_json("GET", f"{api_url}/api/tools/list", timeout=timeout)
    diagnostics["tools_list_http"] = list_code
    if list_code == 200 and isinstance(list_payload, dict):
        servers = list_payload.get("tools")
        if isinstance(servers, dict):
            for _, values in servers.items():
                if isinstance(values, list):
                    for value in values:
                        if isinstance(value, str) and value.strip():
                            runtime_tools.add(value.strip())
        native = list_payload.get("native_tools")
        if isinstance(native, list):
            for value in native:
                if isinstance(value, str) and value.strip():
                    runtime_tools.add(value.strip())
    else:
        diagnostics["errors"]["tools_list"] = (list_raw or "")[:300]

    defs_code, defs_payload, defs_raw = http_json("GET", f"{api_url}/api/tools/defs", timeout=timeout)
    diagnostics["tools_defs_http"] = defs_code
    if defs_code == 200 and isinstance(defs_payload, dict):
        servers = defs_payload.get("tools")
        if isinstance(servers, dict):
            for _, entries in servers.items():
                if not isinstance(entries, list):
                    continue
                for item in entries:
                    if isinstance(item, dict):
                        name = item.get("name")
                        if isinstance(name, str) and name.strip():
                            runtime_tools.add(name.strip())
        native_defs = defs_payload.get("native_tools")
        if isinstance(native_defs, list):
            for item in native_defs:
                if not isinstance(item, dict):
                    continue
                fn = item.get("function")
                if not isinstance(fn, dict):
                    continue
                name = fn.get("name")
                if isinstance(name, str) and name.strip():
                    runtime_tools.add(name.strip())
    else:
        diagnostics["errors"]["tools_defs"] = (defs_raw or "")[:300]

    diagnostics["runtime_tools_count"] = len(runtime_tools)
    diagnostics["runtime_tools"] = sorted(runtime_tools)
    return diagnostics


def _extract_tools_used(
    *,
    transitions_path: Path,
    conversation_id: str,
    start_local: dt.datetime,
    api_url: str,
    timeout: float,
    allow_last_payload_fallback: bool,
) -> List[str]:
    used = _tools_from_transitions(transitions_path, conversation_id, start_local)
    if not used and allow_last_payload_fallback:
        used = get_last_tools(api_url, timeout)
    return used


def _wait_for_tools(
    *,
    transitions_path: Path,
    conversation_id: str,
    start_local: dt.datetime,
    api_url: str,
    timeout: float,
    allow_last_payload_fallback: bool,
    wait_seconds: float,
) -> List[str]:
    deadline = time.time() + max(0.0, float(wait_seconds))
    latest: List[str] = []
    while time.time() <= deadline:
        latest = _extract_tools_used(
            transitions_path=transitions_path,
            conversation_id=conversation_id,
            start_local=start_local,
            api_url=api_url,
            timeout=timeout,
            allow_last_payload_fallback=allow_last_payload_fallback,
        )
        if latest:
            return latest
        time.sleep(0.15)
    return latest


def _compose_prompt(
    *,
    prompt: str,
    expected_tools: List[str],
    expected_groups: List[List[str]],
    retry_missing_groups: List[str],
) -> str:
    if expected_groups:
        expected_text = "; ".join(" or ".join(group) for group in expected_groups)
    else:
        expected_text = ", ".join(expected_tools) if expected_tools else "none"
    text = (
        f"{prompt}\n\n"
        "Execution requirements:\n"
        f"- Required tool(s): {expected_text}\n"
        "- Call required tools before your final answer.\n"
        "- If a required tool is unavailable, say so explicitly.\n"
    )
    if retry_missing_groups:
        missing_csv = ", ".join(retry_missing_groups)
        text += (
            "\nRetry focus:\n"
            f"- Missing from prior attempt: {missing_csv}\n"
            f"- You MUST call: {missing_csv}\n"
        )
    return text


def _looks_like_confirmation_prompt(text: str) -> bool:
    lowered = str(text or "").lower()
    if not lowered:
        return False
    phrases = (
        "reply 'yes' to proceed",
        "reply \"yes\" to proceed",
        "reply with 'yes' to proceed",
        "confirmation required",
        "tool confirmation required",
        "do you want to proceed",
        "proceed? (yes/no)",
        "proceed (yes/no)",
        "proceed? (y/n)",
        "awaiting confirmation",
    )
    return any(phrase in lowered for phrase in phrases)


def _recommendations(
    flag_counts: Counter,
    missing_runtime_tools: List[str],
    missing_executed_tools: List[str],
) -> List[str]:
    recs: List[str] = []
    if flag_counts.get("tool_call_limit_reached", 0) > 0:
        recs.append(
            "Tool-call limit observed. Tighten workflow replay gates and keep acknowledgement turns tool-light."
        )
    if flag_counts.get("confirmation_required", 0) > 0:
        recs.append(
            "Confirmation-gated tools were encountered. Keep auto-confirm enabled for exam runs or pre-authorize safe write/send operations."
        )
    if flag_counts.get("awaiting_confirmation_unexpected", 0) > 0:
        recs.append(
            "Unexpected confirmation prompts observed. Ensure stale pending actions are cleared before normal request routing."
        )
    if flag_counts.get("request_timeout", 0) > 0:
        recs.append(
            "Curriculum requests timed out. Reduce tool fan-out, shorten chain depth, or raise timeout for heavy tool paths."
        )
    if missing_runtime_tools:
        recs.append(
            "Some required curriculum tools were unavailable at runtime. Start required MCP servers or adjust lesson scope."
        )
    if missing_executed_tools:
        recs.append(
            "Some required tools were available but not exercised in replies. Increase retries or tighten lesson prompts."
        )
    if not recs:
        recs.append("No critical blockers observed. Increase curriculum breadth or lesson depth for further gains.")
    return recs


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vera guided-learning curriculum")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--retries", type=int, default=2, help="Additional retries per lesson")
    parser.add_argument(
        "--curriculum",
        default="config/doctor_professor/vera_guided_learning_curriculum.json",
    )
    parser.add_argument(
        "--protocol",
        default="config/doctor_professor/vera_professor_protocol.md",
    )
    parser.add_argument(
        "--inventory",
        default="vera_tools_list_for_guided_learning",
    )
    parser.add_argument("--session-prefix", default="guided")
    parser.add_argument(
        "--wait-ready-seconds",
        type=float,
        default=0.0,
        help="Wait for /api/readiness ready=true before curriculum run (0 disables wait).",
    )
    parser.add_argument(
        "--ready-streak",
        type=int,
        default=3,
        help="Consecutive ready=true checks required when --wait-ready-seconds > 0.",
    )
    parser.add_argument(
        "--last-payload-fallback",
        action="store_true",
        help="Fallback to /api/tools/last_payload when transition attribution is unavailable (can be stale across conversations).",
    )
    parser.add_argument(
        "--tool-wait-seconds",
        type=float,
        default=3.0,
        help="Seconds to wait for attributed tool-call events after each request.",
    )
    parser.add_argument(
        "--no-auto-confirm-pending",
        action="store_true",
        help="Disable automatic 'yes' follow-up when a lesson response requests confirmation.",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    v1 = normalize_v1(args.base_url)
    api = api_root(v1)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model = choose_model(v1, args.model, args.timeout)
    protocol_text = _read_text(Path(args.protocol))
    curriculum_path = Path(args.curriculum)
    curriculum = _load_json(curriculum_path)
    inventory_path = Path(args.inventory)
    inventory_tools = parse_inventory_tools(inventory_path)

    if float(args.wait_ready_seconds) > 0.0:
        ready_ok = _wait_for_ready(
            api_url=api,
            timeout_s=float(args.wait_ready_seconds),
            ready_streak=int(args.ready_streak),
        )
        if not ready_ok:
            report = {
                "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "base_url": api,
                "model": model,
                "curriculum_file": str(curriculum_path),
                "protocol_file": str(Path(args.protocol)),
                "inventory_file": str(inventory_path),
                "inventory_tools_count": len(inventory_tools),
                "runtime": {},
                "lessons": [],
                "pass": 0,
                "fail": 1,
                "skip": 0,
                "flags": {
                    "readiness_not_stable": 1,
                },
                "overall_ok": False,
                "last_payload_fallback": bool(args.last_payload_fallback),
                "tool_wait_seconds": float(args.tool_wait_seconds),
                "auto_confirm_pending": bool(not args.no_auto_confirm_pending),
                "wait_ready_seconds": float(args.wait_ready_seconds),
                "ready_streak": int(args.ready_streak),
            }
            out = Path(args.output) if args.output else (root / "tmp" / f"vera_guided_learning_curriculum_{ts}.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
            print(f"Report: {out}")
            print("Readiness did not stabilize before curriculum run.")
            return 1

    runtime_diag = fetch_runtime_tools(api, args.timeout)
    runtime_tools = set(runtime_diag.get("runtime_tools") or [])
    transitions_path = root / "vera_memory" / "flight_recorder" / "transitions.ndjson"

    lessons_raw = curriculum.get("lessons")
    lessons = lessons_raw if isinstance(lessons_raw, list) else []
    report: Dict[str, Any] = {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_url": api,
        "model": model,
        "curriculum_file": str(curriculum_path),
        "protocol_file": str(Path(args.protocol)),
        "inventory_file": str(inventory_path),
        "inventory_tools_count": len(inventory_tools),
        "runtime": runtime_diag,
        "lessons": [],
        "pass": 0,
        "fail": 0,
        "skip": 0,
        "flags": {},
        "overall_ok": False,
        "last_payload_fallback": bool(args.last_payload_fallback),
        "tool_wait_seconds": float(args.tool_wait_seconds),
        "auto_confirm_pending": bool(not args.no_auto_confirm_pending),
        "wait_ready_seconds": float(args.wait_ready_seconds),
        "ready_streak": int(args.ready_streak),
    }

    if not lessons:
        report["fail"] = 1
        report["flags"] = {"no_lessons_loaded": 1}
        out = Path(args.output) if args.output else (root / "tmp" / f"vera_guided_learning_curriculum_{ts}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"Report: {out}")
        print("Lessons passed: 0/0")
        return 1

    conversation_ids: Dict[str, str] = {}
    flags = Counter()
    missing_runtime_tools_global: Set[str] = set()
    missing_executed_tools_global: Set[str] = set()
    hard_failure_flags = {"tool_call_limit_reached", "request_timeout"}

    for index, lesson_obj in enumerate(lessons, start=1):
        if not isinstance(lesson_obj, dict):
            continue

        lesson_id = str(lesson_obj.get("id") or f"lesson_{index}")
        lesson_title = str(lesson_obj.get("title") or lesson_id)
        prompt = str(lesson_obj.get("prompt") or "").strip()
        expected_groups = _normalize_expected_groups(lesson_obj)
        expected_tools: List[str] = []
        for group_tools in expected_groups:
            for tool_name in group_tools:
                if tool_name not in expected_tools:
                    expected_tools.append(tool_name)

        has_group_expectations = bool(lesson_obj.get("expected_tool_groups_any_order"))
        explicit_required = _dedupe(list(lesson_obj.get("required_tools") or []))
        if explicit_required:
            required_tools = explicit_required
        elif has_group_expectations:
            required_tools = []
        else:
            required_tools = list(expected_tools)
        max_attempts = max(1, int(lesson_obj.get("max_attempts") or (int(args.retries) + 1)))
        skip_if_missing = bool(lesson_obj.get("skip_if_tools_missing", True))
        group = str(lesson_obj.get("conversation_group") or lesson_id).strip()
        objective = str(lesson_obj.get("objective") or "").strip()

        missing_runtime = sorted(tool for tool in required_tools if tool not in runtime_tools)
        missing_runtime_groups = [
            " or ".join(group_tools)
            for group_tools in expected_groups
            if group_tools and not any(tool in runtime_tools for tool in group_tools)
        ]
        missing_inventory = sorted(tool for tool in required_tools if inventory_tools and tool not in inventory_tools)

        if group not in conversation_ids:
            conversation_ids[group] = f"{args.session_prefix}-{group}-{ts}"
        conversation_id = conversation_ids[group]

        if skip_if_missing and (missing_runtime or missing_runtime_groups):
            report["skip"] += 1
            for tool in missing_runtime:
                missing_runtime_tools_global.add(tool)
            for group_label in missing_runtime_groups:
                missing_runtime_tools_global.add(group_label)
            report["lessons"].append(
                {
                    "id": lesson_id,
                    "title": lesson_title,
                    "objective": objective,
                    "conversation_id": conversation_id,
                    "status": "skipped",
                    "reason": "required_tools_missing_runtime",
                    "required_tools": required_tools,
                    "missing_runtime_tools": missing_runtime,
                    "missing_runtime_tool_groups": missing_runtime_groups,
                    "missing_inventory_tools": missing_inventory,
                    "expected_tools": expected_tools,
                    "expected_tool_groups": expected_groups,
                }
            )
            continue

        used_union: List[str] = []
        attempts: List[Dict[str, Any]] = []
        reply_preview = ""
        best_http = 0
        remaining_groups = list(expected_groups)
        retry_missing_groups = [" or ".join(group_tools) for group_tools in remaining_groups]
        lesson_flags: List[str] = []
        forced_tool_attempts: Counter = Counter()
        auto_confirm_pending = bool(not args.no_auto_confirm_pending)

        for attempt in range(1, max_attempts + 1):
            messages: List[Dict[str, str]] = []
            if protocol_text:
                messages.append({"role": "system", "content": protocol_text})
            if objective:
                messages.append({"role": "system", "content": f"Lesson objective: {objective}"})
            messages.append(
                {
                    "role": "user",
                    "content": _compose_prompt(
                        prompt=prompt,
                        expected_tools=expected_tools,
                        expected_groups=expected_groups,
                        retry_missing_groups=retry_missing_groups,
                    ),
                }
            )

            payload: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "conversation_id": conversation_id,
            }
            forced_tool_name = ""
            if len(remaining_groups) == 1:
                unresolved = [name for name in remaining_groups[0] if name not in used_union]
                preferred = [name for name in unresolved if name in runtime_tools]
                candidates = preferred or unresolved
                if candidates:
                    ranked = sorted(
                        enumerate(candidates),
                        key=lambda item: (forced_tool_attempts[item[1]], item[0]),
                    )
                    forced_tool_name = ranked[0][1]
                    forced_tool_attempts[forced_tool_name] += 1
                    payload["tool_choice"] = {
                        "type": "function",
                        "function": {"name": forced_tool_name},
                    }

            start_local = dt.datetime.now()
            code, resp, raw = http_json(
                "POST",
                f"{v1}/chat/completions",
                payload=payload,
                timeout=args.timeout,
            )
            used = _wait_for_tools(
                transitions_path=transitions_path,
                conversation_id=conversation_id,
                start_local=start_local,
                api_url=api,
                timeout=args.timeout,
                allow_last_payload_fallback=bool(args.last_payload_fallback),
                wait_seconds=float(args.tool_wait_seconds),
            )
            for tool in used:
                if tool not in used_union:
                    used_union.append(tool)

            reply_text = extract_reply(resp) if isinstance(resp, dict) else (raw or "")
            reply_preview = reply_text[:320]
            low_reply = reply_text.lower()

            if "tool call limit reached" in low_reply:
                flags["tool_call_limit_reached"] += 1
                if "tool_call_limit_reached" not in lesson_flags:
                    lesson_flags.append("tool_call_limit_reached")
            confirmation_detected = _looks_like_confirmation_prompt(reply_text)
            if confirmation_detected:
                flags["confirmation_required"] += 1
                if "confirmation_required" not in lesson_flags:
                    lesson_flags.append("confirmation_required")
            if "awaiting confirmation" in low_reply:
                flags["awaiting_confirmation_unexpected"] += 1
                if "awaiting_confirmation_unexpected" not in lesson_flags:
                    lesson_flags.append("awaiting_confirmation_unexpected")
            if code == 0 and "timed out" in (raw or "").lower():
                flags["request_timeout"] += 1
                if "request_timeout" not in lesson_flags:
                    lesson_flags.append("request_timeout")

            confirmation_auto_sent = False
            confirmation_http = 0
            confirmation_used: List[str] = []
            confirmation_reply_preview = ""
            if confirmation_detected and auto_confirm_pending:
                confirmation_auto_sent = True
                confirm_payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "yes"}],
                    "conversation_id": conversation_id,
                }
                confirm_start = dt.datetime.now()
                confirm_code, confirm_resp, confirm_raw = http_json(
                    "POST",
                    f"{v1}/chat/completions",
                    payload=confirm_payload,
                    timeout=args.timeout,
                )
                confirmation_http = confirm_code
                confirmation_used = _wait_for_tools(
                    transitions_path=transitions_path,
                    conversation_id=conversation_id,
                    start_local=confirm_start,
                    api_url=api,
                    timeout=args.timeout,
                    allow_last_payload_fallback=bool(args.last_payload_fallback),
                    wait_seconds=float(args.tool_wait_seconds),
                )
                for tool in confirmation_used:
                    if tool not in used_union:
                        used_union.append(tool)
                confirm_text = extract_reply(confirm_resp) if isinstance(confirm_resp, dict) else (confirm_raw or "")
                confirmation_reply_preview = confirm_text[:320]
                low_confirm = confirm_text.lower()
                if "tool call limit reached" in low_confirm:
                    flags["tool_call_limit_reached"] += 1
                    if "tool_call_limit_reached" not in lesson_flags:
                        lesson_flags.append("tool_call_limit_reached")
                if _looks_like_confirmation_prompt(confirm_text):
                    flags["awaiting_confirmation_unexpected"] += 1
                    if "awaiting_confirmation_unexpected" not in lesson_flags:
                        lesson_flags.append("awaiting_confirmation_unexpected")
                if confirm_code == 0 and "timed out" in (confirm_raw or "").lower():
                    flags["request_timeout"] += 1
                    if "request_timeout" not in lesson_flags:
                        lesson_flags.append("request_timeout")
                if confirm_code != 0:
                    best_http = confirm_code
                else:
                    best_http = code
            else:
                best_http = code

            remaining_groups = [
                group_tools
                for group_tools in expected_groups
                if group_tools and not any(tool in used_union for tool in group_tools)
            ]
            missing_after = [" or ".join(group_tools) for group_tools in remaining_groups]
            retry_missing_groups = list(missing_after)

            attempts.append(
                {
                    "attempt": attempt,
                    "http": code,
                    "used_tools": used,
                    "missing_after_attempt": missing_after,
                    "forced_tool_choice": forced_tool_name,
                    "reply_preview": reply_preview,
                    "confirmation_detected": confirmation_detected,
                    "confirmation_auto_sent": confirmation_auto_sent,
                    "confirmation_http": confirmation_http,
                    "confirmation_used_tools": confirmation_used,
                    "confirmation_reply_preview": confirmation_reply_preview,
                }
            )

            if code == 200 and not missing_after:
                break

        missing_final = [" or ".join(group_tools) for group_tools in remaining_groups]
        passed = bool(best_http == 200 and not remaining_groups)
        if passed:
            report["pass"] += 1
            status = "passed"
        else:
            report["fail"] += 1
            status = "failed"

        report["lessons"].append(
            {
                "id": lesson_id,
                "title": lesson_title,
                "objective": objective,
                "conversation_id": conversation_id,
                "status": status,
                "required_tools": required_tools,
                "expected_tools": expected_tools,
                "expected_tool_groups": expected_groups,
                "used_tools": used_union,
                "missing_tools": missing_final,
                "missing_tool_groups": missing_final,
                "missing_inventory_tools": missing_inventory,
                "flags": lesson_flags,
                "http": best_http,
                "reply_preview": reply_preview,
                "attempts": attempts,
            }
        )

        for tool in missing_final:
            missing_executed_tools_global.add(tool)

    report["flags"] = dict(flags)
    hard_failures = [name for name, count in flags.items() if count > 0 and name in hard_failure_flags]
    report["hard_failures"] = hard_failures
    report["recommendations"] = _recommendations(
        flags,
        sorted(missing_runtime_tools_global),
        sorted(missing_executed_tools_global),
    )
    report["overall_ok"] = bool(report["fail"] == 0 and not hard_failures)

    out = Path(args.output) if args.output else (root / "tmp" / f"vera_guided_learning_curriculum_{ts}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(f"Report: {out}")
    print(f"Lessons passed: {report['pass']}/{len(report['lessons'])}")
    print(f"Lessons skipped: {report['skip']}")
    if report["fail"]:
        for lesson in report["lessons"]:
            if lesson.get("status") == "failed":
                print(f"FAIL {lesson.get('id')} missing={lesson.get('missing_tools')}")
    if report["hard_failures"]:
        print(f"Hard failures: {report['hard_failures']}")
    return 0 if report["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
