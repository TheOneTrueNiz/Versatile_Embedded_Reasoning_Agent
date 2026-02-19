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


DEFAULT_PROTOCOL = "config/doctor_professor/vera_professor_protocol.md"
DEFAULT_SCENARIOS = "config/doctor_professor/vera_tool_exam_tier2_scenarios.json"


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
    return "grok-4-1-fast-reasoning"


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
    session_prefix: str,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    passed = 0
    failed = 0
    skipped = 0
    total = len(tools)

    for idx, tool_name in enumerate(tools, start=1):
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

        for attempt in range(1, max(1, retries + 1) + 1):
            prompt = (
                "Direct Tool Exam.\n"
                f"You MUST call tool `{tool_name}` exactly once in this turn, using safe minimal arguments.\n"
                "If the tool fails due auth/network/remote constraints, report that failure explicitly.\n"
                "After the tool call, reply with: EXAM_COMPLETE."
            )
            start_local = dt.datetime.now()
            code, preview, _ = _send_chat(
                v1_url=v1_url,
                model=model,
                protocol_text=protocol_text,
                conversation_id=convo,
                prompt=prompt,
                timeout=timeout,
                tool_choice_name=tool_name,
            )
            used = _wait_for_tools(
                transitions_path=transitions_path,
                conversation_id=convo,
                start_local=start_local,
                wait_seconds=2.0,
            )
            for name in used:
                if name not in used_union:
                    used_union.append(name)

            invoked = tool_name in used_union
            attempts.append(
                {
                    "attempt": attempt,
                    "http": code,
                    "used_tools": used,
                    "invoked": invoked,
                    "reply_preview": preview,
                }
            )
            last_http = code
            last_preview = preview
            if invoked and code == 200:
                break

        status = "passed" if invoked else "failed"
        if status == "passed":
            passed += 1
        else:
            failed += 1

        rows.append(
            {
                "tool": tool_name,
                "status": status,
                "invoked": invoked,
                "http": last_http,
                "used_tools": used_union,
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
    session_prefix: str,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    passed = 0
    failed = 0
    skipped = 0

    for idx, scenario in enumerate(scenarios, start=1):
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

        for attempt in range(1, max(1, retries + 1) + 1):
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
            used = _wait_for_tools(
                transitions_path=transitions_path,
                conversation_id=convo,
                start_local=start_local,
                wait_seconds=2.0,
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
                    "missing_after_attempt": missing_after,
                    "forced_tool_choice": forced,
                    "reply_preview": preview,
                }
            )
            last_http = code
            last_preview = preview
            if code == 200 and not remaining_groups and len(used_union) >= min_distinct:
                break

        ok = bool(last_http == 200 and not remaining_groups and len(used_union) >= min_distinct)
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

    ts = _utc_ts()
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
            "tool_filter": str(args.tool_filter or ""),
            "include_side_effects": bool(args.include_side_effects),
            "max_tier1_failures": int(args.max_tier1_failures),
            "max_tier2_failures": int(args.max_tier2_failures),
            "wait_ready_seconds": float(args.wait_ready_seconds),
            "ready_streak": int(args.ready_streak),
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
            session_prefix=f"tool-exam-{ts}",
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
            session_prefix=f"tool-exam-{ts}",
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
