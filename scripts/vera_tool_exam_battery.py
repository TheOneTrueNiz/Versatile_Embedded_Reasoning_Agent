#!/usr/bin/env python3
"""
Two-tier tool exam battery for Vera.

Tier 1 (Direct):
  - Tests whether Vera can invoke each tool when explicitly instructed.

Tier 2 (Inference/Chain):
  - Tests whether Vera can infer and chain the right tools from task prompts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib import error, request


DEFAULT_PROTOCOL = "config/guided_learning/vera_guided_learning_protocol.md"
DEFAULT_SCENARIOS = "config/guided_learning/vera_tool_exam_scenarios.json"

# A few MCP tools regularly require longer than the generic chat timeout due to
# upstream latency or large payload hydration. Keep overrides surgical so the
# full battery does not slow down globally.
TIER1_TIMEOUT_OVERRIDES: Dict[str, float] = {
    "directory_tree": 180.0,
    "discover_global_functions": 180.0,
    "get_debug_view": 180.0,
    "get_doc_content": 180.0,
    "get_page_citations": 180.0,
    "get_page_section": 180.0,
}

# Some media-adjacent tools are occasionally ignored on first pass despite
# explicit tool_choice; allow one extra attempt for direct exams.
TIER1_EXTRA_ATTEMPT_TOOLS: Set[str] = {
    "expand_animations",
    "extract_element_animations",
    "extract_element_animations_to_file",
    "get_page_thumbnail",
}

# Confirmation-gated tools are interactive by design and not suitable for an
# unattended tier-1 direct exam pass.
MANUAL_CONFIRMATION_TOOLS: Set[str] = {
    "get_response_content",
}


def _tier1_prompt_for_tool(tool_name: str) -> str:
    if tool_name == "edit_file":
        probe_path = Path("/tmp/vera_exam_edit_file.txt")
        probe_path.write_text("vera tool exam seed\n", encoding="utf-8")
        return (
            "Direct Tool Exam.\n"
            f"You MUST call tool `{tool_name}` exactly once in this turn.\n"
            f"Use this existing file path only: {probe_path}.\n"
            "Apply one minimal safe edit (for example, append one short line).\n"
            "If the tool fails due auth/network/remote constraints, report that failure explicitly.\n"
            "After the tool call, reply with: EXAM_COMPLETE."
        )

    return (
        "Direct Tool Exam.\n"
        f"You MUST call tool `{tool_name}` exactly once in this turn, using safe minimal arguments.\n"
        "If the tool fails due auth/network/remote constraints, report that failure explicitly.\n"
        "After the tool call, reply with: EXAM_COMPLETE."
    )


def _utc_ts() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def normalize_v1(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def api_root(v1_url: str) -> str:
    return v1_url[:-3] if v1_url.endswith("/v1") else v1_url


def http_json(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
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


def choose_model(v1_url: str, override: Optional[str], timeout: float) -> str:
    if override:
        return override
    code, payload, _ = http_json("GET", f"{v1_url}/models", timeout=timeout)
    if code == 200 and isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            model = data[0].get("id")
            if isinstance(model, str) and model:
                return model
    return "grok-4.20-experimental-beta-0304-reasoning"


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


def _extract_reply(payload: Any) -> str:
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


def _tool_equivalents(tool_name: str) -> Set[str]:
    name = str(tool_name or "").strip()
    if not name:
        return set()
    eq: Set[str] = {name}

    # Common browser naming aliases observed across MCP/browser providers.
    if name.startswith("browser_go_"):
        eq.add("browser_" + name[len("browser_go_"):])
    if name == "browser_get_text":
        eq.add("browser_get_content")
    if name == "browser_wait_for":
        eq.add("browser_wait")
    return eq


def _was_tool_invoked(expected_tool: str, used_tools: List[str]) -> bool:
    if not expected_tool:
        return False
    eq = _tool_equivalents(expected_tool)
    return any(str(name).strip() in eq for name in (used_tools or []))


def _parse_local_naive_iso(value: str) -> Optional[dt.datetime]:
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


def _wait_for_tools(
    transitions_path: Path,
    conversation_id: str,
    start_local: dt.datetime,
    wait_seconds: float = 2.0,
) -> List[str]:
    deadline = time.time() + max(0.0, float(wait_seconds))
    latest: List[str] = []
    while time.time() <= deadline:
        latest = _tools_from_transitions(transitions_path, conversation_id, start_local)
        if latest:
            return latest
        time.sleep(0.15)
    return latest


def _wait_for_tools_with_grace(
    *,
    transitions_path: Path,
    conversation_id: str,
    start_local: dt.datetime,
    wait_seconds: float,
    grace_seconds: float,
) -> Tuple[List[str], bool]:
    used = _wait_for_tools(
        transitions_path=transitions_path,
        conversation_id=conversation_id,
        start_local=start_local,
        wait_seconds=wait_seconds,
    )
    if used:
        return used, False
    if max(0.0, float(grace_seconds)) <= 0.0:
        return used, False
    used = _wait_for_tools(
        transitions_path=transitions_path,
        conversation_id=conversation_id,
        start_local=start_local,
        wait_seconds=grace_seconds,
    )
    return used, bool(used)


def _discover_tools(api_url: str, timeout: float) -> Dict[str, Any]:
    by_server: Dict[str, List[str]] = {}
    native: List[str] = []
    all_tools: List[str] = []

    code_list, payload_list, raw_list = http_json("GET", f"{api_url}/api/tools/list", timeout=timeout)
    if code_list == 200 and isinstance(payload_list, dict):
        raw_tools = payload_list.get("tools")
        if isinstance(raw_tools, dict):
            for server, names in raw_tools.items():
                if isinstance(names, list):
                    vals = [str(x).strip() for x in names if isinstance(x, str) and str(x).strip()]
                    by_server[str(server)] = vals
                    all_tools.extend(vals)
        raw_native = payload_list.get("native_tools")
        if isinstance(raw_native, list):
            native = [str(x).strip() for x in raw_native if isinstance(x, str) and str(x).strip()]
            all_tools.extend(native)
    else:
        return {
            "ok": False,
            "error": f"/api/tools/list failed: HTTP {code_list} {str(raw_list)[:200]}",
            "servers": {},
            "native": [],
            "all_tools": [],
        }

    # Include defs-only names as fallback
    code_defs, payload_defs, _ = http_json("GET", f"{api_url}/api/tools/defs", timeout=timeout)
    if code_defs == 200 and isinstance(payload_defs, dict):
        defs_tools = payload_defs.get("tools")
        if isinstance(defs_tools, dict):
            for server, entries in defs_tools.items():
                if not isinstance(entries, list):
                    continue
                current = set(by_server.get(str(server), []))
                for item in entries:
                    if isinstance(item, dict):
                        name = item.get("name")
                        if isinstance(name, str) and name.strip():
                            current.add(name.strip())
                by_server[str(server)] = sorted(current)
        defs_native = payload_defs.get("native_tools")
        if isinstance(defs_native, list):
            merged = set(native)
            for item in defs_native:
                if not isinstance(item, dict):
                    continue
                fn = item.get("function")
                if isinstance(fn, dict):
                    name = fn.get("name")
                    if isinstance(name, str) and name.strip():
                        merged.add(name.strip())
            native = sorted(merged)

    deduped: List[str] = []
    for name in sorted(set(all_tools + native)):
        if name and name not in deduped:
            deduped.append(name)

    return {
        "ok": True,
        "error": "",
        "servers": by_server,
        "native": native,
        "all_tools": deduped,
    }


def _looks_side_effect_tool(tool_name: str) -> bool:
    low = str(tool_name).strip().lower()
    if low in MANUAL_CONFIRMATION_TOOLS:
        return True
    unsafe_tokens = (
        "delete",
        "remove",
        "transfer_ownership",
        "send_",
        "post_",
        "create_",
        "modify_",
        "update_",
        "batch_update",
        "batch_modify",
        "initiate_call",
        "clear_",
        "move_",
        "vote_",
        "favorite_",
        "bookmark_",
        "fork_",
        "merge_",
    )
    safe_exceptions = {
        "create_directory",
        "create_entities",
        "create_relations",
        "create_simple_dynamic_hook",
        "create_persistent_function",
        "create_python_binding",
        "create_dynamic_hook",
    }
    if low in safe_exceptions:
        return False
    return any(token in low for token in unsafe_tokens)


def _tier1_timeout_for_tool(tool_name: str, default_timeout: float) -> float:
    override = float(TIER1_TIMEOUT_OVERRIDES.get(str(tool_name).strip(), 0.0) or 0.0)
    return max(float(default_timeout), override)


def _detect_external_constraint_reason(text: str) -> str:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return ""

    if any(
        token in lowered
        for token in (
            "quota exceeded",
            "rate limit",
            "429",
            "hourly limit",
            "too many requests",
        )
    ):
        return "external_quota_or_rate_limit"

    if any(
        token in lowered
        for token in (
            "authentication needed",
            "authorization",
            "unauthorized",
            "invalid_grant",
            "missing credential",
            "oauth",
            "re-authenticate",
            "not authenticated",
        )
    ):
        return "external_auth_required"

    if any(
        token in lowered
        for token in (
            "service unavailable",
            "upstream unavailable",
            "temporarily unavailable",
            "remote constraint",
            "connection refused",
            "dns",
            "network error",
            "timeout",
            "timed out",
        )
    ):
        return "external_service_unavailable"

    return ""


def _detect_external_constraint_from_attempts(attempts: List[Dict[str, Any]]) -> str:
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        reason = _detect_external_constraint_reason(str(attempt.get("reply_preview") or ""))
        if reason:
            return reason
    return ""


def _detect_tool_runtime_failure_reason(reply_preview: str) -> str:
    lowered = str(reply_preview or "").strip().lower()
    if not lowered:
        return ""

    if "tool failure report" in lowered:
        return "tool_runtime_failure"
    if "failed due" in lowered or "failed:" in lowered:
        return "tool_runtime_failure"
    if "no such file" in lowered or "enoent" in lowered:
        return "tool_runtime_failure"
    if "missing dependencies" in lowered:
        return "tool_runtime_failure"
    if "permission denied" in lowered:
        return "tool_runtime_failure"
    if "traceback" in lowered or "exception" in lowered:
        return "tool_runtime_failure"
    if " tool error" in lowered:
        return "tool_runtime_failure"
    return ""


def _send_chat(
    *,
    v1_url: str,
    model: str,
    protocol_text: str,
    conversation_id: str,
    prompt: str,
    timeout: float,
    tool_choice_name: str = "",
) -> Tuple[int, str, Any]:
    messages: List[Dict[str, str]] = []
    if protocol_text:
        messages.append({"role": "system", "content": protocol_text})
    messages.append({"role": "user", "content": prompt})

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "conversation_id": conversation_id,
    }
    if tool_choice_name:
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": tool_choice_name},
        }

    code, resp, raw = http_json("POST", f"{v1_url}/chat/completions", payload=payload, timeout=timeout)
    preview = _extract_reply(resp)[:320] if isinstance(resp, dict) else (raw or "")[:320]
    return code, preview, resp if isinstance(resp, dict) else raw


def _normalize_expected_groups(scenario: Dict[str, Any]) -> List[List[str]]:
    groups: List[List[str]] = []
    raw_groups = scenario.get("expected_tool_groups_any_order")
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

    legacy_expected = [
        str(x).strip()
        for x in list(scenario.get("expected_tools_any_order") or [])
        if isinstance(x, str) and str(x).strip()
    ]
    return [[name] for name in legacy_expected]


def _run_tier1(
    *,
    v1_url: str,
    model: str,
    protocol_text: str,
    transitions_path: Path,
    tools: List[str],
    retries: int,
    timeout: float,
    include_side_effects: bool,
    transition_wait_seconds: float,
    transition_grace_seconds: float,
    session_prefix: str,
    halt_file: Optional[Path] = None,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    passed = 0
    failed = 0
    skipped = 0
    total = len(tools)

    for idx, tool_name in enumerate(tools, start=1):
        if halt_file is not None and halt_file.exists():
            for remaining_tool in tools[idx - 1 :]:
                rows.append(
                    {
                        "tool": remaining_tool,
                        "status": "skipped",
                        "reason": "manual_halt_active",
                        "attempts": [],
                    }
                )
            skipped += len(tools[idx - 1 :])
            break

        if not include_side_effects and _looks_side_effect_tool(tool_name):
            rows.append(
                {
                    "tool": tool_name,
                    "status": "skipped",
                    "reason": "side_effect_guard",
                    "attempts": [],
                }
            )
            skipped += 1
            continue

        convo = f"{session_prefix}-tier1-{idx:04d}-{tool_name}"
        attempts: List[Dict[str, Any]] = []
        invoked = False
        used_union: List[str] = []
        last_http = 0
        last_preview = ""
        tool_timeout = _tier1_timeout_for_tool(tool_name, timeout)
        attempt_limit = max(1, retries + 1)
        if tool_name in TIER1_EXTRA_ATTEMPT_TOOLS:
            attempt_limit = max(attempt_limit, 2)

        for attempt in range(1, attempt_limit + 1):
            prompt = _tier1_prompt_for_tool(tool_name)
            start_local = dt.datetime.now()
            code, preview, _ = _send_chat(
                v1_url=v1_url,
                model=model,
                protocol_text=protocol_text,
                conversation_id=convo,
                prompt=prompt,
                timeout=tool_timeout,
                tool_choice_name=tool_name,
            )
            used, used_grace_wait = _wait_for_tools_with_grace(
                transitions_path=transitions_path,
                conversation_id=convo,
                start_local=start_local,
                wait_seconds=transition_wait_seconds,
                grace_seconds=transition_grace_seconds,
            )
            for name in used:
                if name not in used_union:
                    used_union.append(name)

            invoked = _was_tool_invoked(tool_name, used_union)
            timed_out = bool(code == 0 and "timed out" in str(preview or "").lower())
            attempts.append(
                {
                    "attempt": attempt,
                    "http": code,
                    "used_tools": used,
                    "used_grace_wait": used_grace_wait,
                    "invoked": invoked,
                    "timed_out": timed_out,
                    "reply_preview": preview,
                }
            )
            last_http = code
            last_preview = preview
            if invoked and (code == 200 or timed_out):
                break

        reason = _detect_external_constraint_from_attempts(attempts)
        runtime_failure_reason = _detect_tool_runtime_failure_reason(last_preview)
        has_runtime_failure = bool(runtime_failure_reason)

        status = "passed"
        if not invoked or has_runtime_failure:
            status = "failed"

        if status == "passed" and not reason:
            passed += 1
        else:
            if reason:
                status = "skipped"
                skipped += 1
            else:
                reason = runtime_failure_reason if has_runtime_failure else ""
                failed += 1

        rows.append(
            {
                "tool": tool_name,
                "status": status,
                "reason": reason,
                "runtime_failure": has_runtime_failure,
                "invoked": invoked,
                "http": last_http,
                "used_tools": used_union,
                "tool_equivalents": sorted(_tool_equivalents(tool_name)),
                "reply_preview": last_preview,
                "attempts": attempts,
            }
        )

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "rows": rows,
    }


def _run_tier2(
    *,
    v1_url: str,
    model: str,
    protocol_text: str,
    transitions_path: Path,
    scenarios: List[Dict[str, Any]],
    available_tools: Set[str],
    retries: int,
    timeout: float,
    transition_wait_seconds: float,
    transition_grace_seconds: float,
    session_prefix: str,
    halt_file: Optional[Path] = None,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    passed = 0
    failed = 0
    skipped = 0

    for idx, scenario in enumerate(scenarios, start=1):
        if halt_file is not None and halt_file.exists():
            for offset, remaining_scenario in enumerate(scenarios[idx - 1 :], start=idx):
                remaining_sid = str(remaining_scenario.get("id") or f"scenario_{offset}")
                rows.append(
                    {
                        "id": remaining_sid,
                        "status": "skipped",
                        "reason": "manual_halt_active",
                        "expected_tools": [],
                        "attempts": [],
                    }
                )
            skipped += len(scenarios[idx - 1 :])
            break

        sid = str(scenario.get("id") or f"scenario_{idx}")
        prompt = str(scenario.get("prompt") or "").strip()
        expected_groups = _normalize_expected_groups(scenario)
        expected: List[str] = []
        for group in expected_groups:
            for name in group:
                if name not in expected:
                    expected.append(name)
        min_distinct = int(scenario.get("min_distinct_tools") or max(1, len(expected_groups)))

        if not prompt:
            rows.append(
                {
                    "id": sid,
                    "status": "skipped",
                    "reason": "empty_prompt",
                    "expected_tools": expected,
                    "attempts": [],
                }
            )
            skipped += 1
            continue

        convo = f"{session_prefix}-tier2-{idx:03d}-{sid}"
        attempts: List[Dict[str, Any]] = []
        used_union: List[str] = []
        last_http = 0
        last_preview = ""
        remaining_groups = list(expected_groups)
        attempt_limit = max(1, retries + 1)
        if len(expected_groups) > 1:
            attempt_limit = max(attempt_limit, 2)

        for attempt in range(1, attempt_limit + 1):
            required_text = "; ".join(" or ".join(group) for group in expected_groups) if expected_groups else "none"
            exam_prompt = (
                f"{prompt}\n\n"
                "Tier-2 inference exam requirements:\n"
                f"- Required tool group(s): {required_text}\n"
                "- Do not claim completion until required tools are actually called.\n"
            )
            forced = ""
            if len(remaining_groups) == 1:
                unresolved = [
                    name for name in remaining_groups[0]
                    if name not in used_union
                ]
                preferred = [name for name in unresolved if name in available_tools]
                candidates = preferred or unresolved
                if candidates:
                    forced = candidates[0]
            start_local = dt.datetime.now()
            code, preview, _ = _send_chat(
                v1_url=v1_url,
                model=model,
                protocol_text=protocol_text,
                conversation_id=convo,
                prompt=exam_prompt,
                timeout=timeout,
                tool_choice_name=forced,
            )
            used, used_grace_wait = _wait_for_tools_with_grace(
                transitions_path=transitions_path,
                conversation_id=convo,
                start_local=start_local,
                wait_seconds=transition_wait_seconds,
                grace_seconds=transition_grace_seconds,
            )
            for name in used:
                if name not in used_union:
                    used_union.append(name)

            remaining_groups = [
                group for group in expected_groups
                if not any(name in used_union for name in group)
            ]
            missing_after = [" or ".join(group) for group in remaining_groups]
            attempts.append(
                {
                    "attempt": attempt,
                    "http": code,
                    "used_tools": used,
                    "used_grace_wait": used_grace_wait,
                    "missing_after_attempt": missing_after,
                    "forced_tool_choice": forced,
                    "reply_preview": preview,
                }
            )
            last_http = code
            last_preview = preview
            timed_out = bool(code == 0 and "timed out" in str(preview or "").lower())
            if (code == 200 or timed_out) and not remaining_groups and len(used_union) >= min_distinct:
                break

        timed_out_final = bool(last_http == 0 and "timed out" in str(last_preview or "").lower())
        ok = bool((last_http == 200 or timed_out_final) and not remaining_groups and len(used_union) >= min_distinct)
        status = "passed" if ok else "failed"
        if ok:
            passed += 1
        else:
            failed += 1

        missing_groups = [" or ".join(group) for group in remaining_groups]

        rows.append(
            {
                "id": sid,
                "status": status,
                "prompt": prompt,
                "expected_tools": expected,
                "expected_tool_groups": expected_groups,
                "min_distinct_tools": min_distinct,
                "used_tools": used_union,
                "missing_tools": missing_groups,
                "missing_tool_groups": missing_groups,
                "http": last_http,
                "reply_preview": last_preview,
                "attempts": attempts,
            }
        )

    return {
        "total": len(scenarios),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Vera two-tier tool exam battery")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument("--tier2-scenarios", default=DEFAULT_SCENARIOS)
    parser.add_argument("--tier1", action="store_true", help="Run tier-1 direct tool exams")
    parser.add_argument("--tier2", action="store_true", help="Run tier-2 inference/chain exams")
    parser.add_argument(
        "--tier1-scope",
        choices=("all", "server", "native"),
        default="all",
        help="Tool source for tier-1 direct exams (default: all).",
    )
    parser.add_argument("--max-tools", type=int, default=0, help="Tier-1 cap (0 = all discovered)")
    parser.add_argument("--tool-filter", default="", help="Regex include filter for tier-1 tool names")
    parser.add_argument("--include-side-effects", action="store_true", help="Include side-effect tools in tier-1")
    parser.add_argument("--max-tier1-failures", type=int, default=0)
    parser.add_argument("--max-tier2-failures", type=int, default=0)
    parser.add_argument(
        "--wait-ready-seconds",
        type=float,
        default=0.0,
        help="Wait for /api/readiness ready=true before discovery (0 disables wait).",
    )
    parser.add_argument(
        "--ready-streak",
        type=int,
        default=3,
        help="Consecutive ready=true checks required when --wait-ready-seconds > 0.",
    )
    parser.add_argument(
        "--transition-wait-seconds",
        type=float,
        default=6.0,
        help="Seconds to wait for transition log ingestion after each request.",
    )
    parser.add_argument(
        "--transition-grace-seconds",
        type=float,
        default=8.0,
        help="Extra seconds to re-check transitions when first pass sees none.",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Optional stable session prefix for conversation ids (example: tool-exam-20260224T230000Z).",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    if not args.tier1 and not args.tier2:
        args.tier1 = True
        args.tier2 = True

    root = Path(__file__).resolve().parents[1]
    v1 = normalize_v1(args.base_url)
    api = api_root(v1)
    model = choose_model(v1, args.model, args.timeout)
    protocol_text = _read_text((root / args.protocol) if not Path(args.protocol).is_absolute() else Path(args.protocol))
    transitions_path = root / "vera_memory" / "flight_recorder" / "transitions.ndjson"
    halt_file = root / "vera_memory" / "manual_halt"

    ts = _utc_ts()
    session_prefix = str(args.run_id or "").strip() or f"tool-exam-{ts}"
    report: Dict[str, Any] = {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_url": api,
        "model": model,
        "config": {
            "tier1": bool(args.tier1),
            "tier2": bool(args.tier2),
            "timeout": float(args.timeout),
            "retries": int(args.retries),
            "max_tools": int(args.max_tools),
            "tier1_scope": str(args.tier1_scope),
            "tool_filter": str(args.tool_filter or ""),
            "include_side_effects": bool(args.include_side_effects),
            "max_tier1_failures": int(args.max_tier1_failures),
            "max_tier2_failures": int(args.max_tier2_failures),
            "wait_ready_seconds": float(args.wait_ready_seconds),
            "ready_streak": int(args.ready_streak),
            "transition_wait_seconds": float(args.transition_wait_seconds),
            "transition_grace_seconds": float(args.transition_grace_seconds),
            "run_id": session_prefix,
        },
        "discovery": {},
        "tier1": {},
        "tier2": {},
        "overall_ok": False,
    }

    if float(args.wait_ready_seconds) > 0.0:
        if not _wait_for_ready(
            api_url=api,
            timeout_s=float(args.wait_ready_seconds),
            ready_streak=int(args.ready_streak),
        ):
            report["discovery"] = {
                "ok": False,
                "error": (
                    f"/api/readiness did not stabilize within "
                    f"{float(args.wait_ready_seconds):.1f}s (streak={int(args.ready_streak)})"
                ),
                "servers": {},
                "native": [],
                "all_tools": [],
            }
            out = Path(args.output) if args.output else (root / "tmp" / f"vera_tool_exam_battery_{ts}.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
            print(f"Report: {out}")
            print("Readiness did not stabilize before discovery.")
            return 1

    discovery = _discover_tools(api, args.timeout)
    report["discovery"] = discovery
    if not discovery.get("ok"):
        out = Path(args.output) if args.output else (root / "tmp" / f"vera_tool_exam_battery_{ts}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        print(f"Report: {out}")
        print("Discovery failed.")
        return 1

    tier1_failed = 0
    tier2_failed = 0

    if args.tier1:
        if args.tier1_scope == "server":
            server_tools: List[str] = []
            for names in (discovery.get("servers") or {}).values():
                if isinstance(names, list):
                    server_tools.extend(
                        str(name).strip()
                        for name in names
                        if isinstance(name, str) and str(name).strip()
                    )
            tools = sorted(set(server_tools))
        elif args.tier1_scope == "native":
            tools = sorted(
                {
                    str(name).strip()
                    for name in list(discovery.get("native") or [])
                    if isinstance(name, str) and str(name).strip()
                }
            )
        else:
            tools = list(discovery.get("all_tools") or [])
        if args.tool_filter:
            rx = re.compile(args.tool_filter)
            tools = [name for name in tools if rx.search(name)]
        if args.max_tools and args.max_tools > 0:
            tools = tools[: args.max_tools]
        tier1 = _run_tier1(
            v1_url=v1,
            model=model,
            protocol_text=protocol_text,
            transitions_path=transitions_path,
            tools=tools,
            retries=max(0, int(args.retries)),
            timeout=float(args.timeout),
            include_side_effects=bool(args.include_side_effects),
            transition_wait_seconds=max(0.5, float(args.transition_wait_seconds)),
            transition_grace_seconds=max(0.0, float(args.transition_grace_seconds)),
            session_prefix=session_prefix,
            halt_file=halt_file,
        )
        tier1_failed = int(tier1.get("failed") or 0)
        report["tier1"] = tier1
        print(
            f"Tier1 direct: passed={tier1.get('passed', 0)} failed={tier1.get('failed', 0)} "
            f"skipped={tier1.get('skipped', 0)} total={tier1.get('total', 0)}"
        )

    if args.tier2:
        scen_path = Path(args.tier2_scenarios)
        if not scen_path.is_absolute():
            scen_path = root / scen_path
        scen_payload = _load_json(scen_path)
        scenarios = scen_payload.get("scenarios")
        if not isinstance(scenarios, list):
            scenarios = []
        tier2 = _run_tier2(
            v1_url=v1,
            model=model,
            protocol_text=protocol_text,
            transitions_path=transitions_path,
            scenarios=[row for row in scenarios if isinstance(row, dict)],
            available_tools=set(str(x) for x in (discovery.get("all_tools") or []) if isinstance(x, str)),
            retries=max(0, int(args.retries)),
            timeout=float(args.timeout),
            transition_wait_seconds=max(0.5, float(args.transition_wait_seconds)),
            transition_grace_seconds=max(0.0, float(args.transition_grace_seconds)),
            session_prefix=session_prefix,
            halt_file=halt_file,
        )
        tier2_failed = int(tier2.get("failed") or 0)
        report["tier2"] = tier2
        print(
            f"Tier2 infer: passed={tier2.get('passed', 0)} failed={tier2.get('failed', 0)} "
            f"skipped={tier2.get('skipped', 0)} total={tier2.get('total', 0)}"
        )

    report["overall_ok"] = bool(
        tier1_failed <= int(args.max_tier1_failures)
        and tier2_failed <= int(args.max_tier2_failures)
    )

    out = Path(args.output) if args.output else (root / "tmp" / f"vera_tool_exam_battery_{ts}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    print(f"Report: {out}")
    print(
        f"Overall: {'PASS' if report['overall_ok'] else 'FAIL'} "
        f"(tier1_failed={tier1_failed}, tier2_failed={tier2_failed})"
    )
    return 0 if report["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
