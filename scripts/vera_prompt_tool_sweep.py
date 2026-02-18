#!/usr/bin/env python3
"""
Prompt-driven tool sweep for Vera.

Runs one prompt per tool capability and verifies the expected tool shows up in
`/api/tools/last_payload` -> `payload.last_tools_used`.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import httpx


@dataclass
class PromptCase:
    case_id: str
    prompt: str
    expected_tool: str
    timeout: float = 45.0
    critical: bool = True
    require_success_text: bool = False
    success_markers_any: Sequence[str] = field(default_factory=tuple)
    failure_markers_any: Sequence[str] = field(default_factory=tuple)


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs,
) -> Tuple[bool, object, str]:
    try:
        resp = client.request(method, url, **kwargs)
    except Exception as exc:
        return False, None, f"request failed: {exc}"
    if resp.status_code >= 400:
        detail = resp.text.strip()
        return False, None, f"HTTP {resp.status_code}: {detail or 'request failed'}"
    try:
        return True, resp.json(), ""
    except Exception:
        return False, None, "response was not valid JSON"


def _extract_response_text(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return str(content or "").strip()


def _get_last_tools_used(client: httpx.Client, base_url: str) -> Tuple[List[str], str]:
    ok, payload_data, err = _request_json(client, "GET", f"{base_url}/api/tools/last_payload")
    if not ok:
        return [], err
    if not isinstance(payload_data, dict):
        return [], "invalid last_payload response"
    payload = payload_data.get("payload")
    if not isinstance(payload, dict):
        return [], "missing payload in last_payload response"
    last = payload.get("last_tools_used")
    if not isinstance(last, list):
        return [], "missing last_tools_used in payload"
    return [str(item) for item in last], ""


def _find_marker_hits(response_text_lc: str, markers: Sequence[str]) -> List[str]:
    hits: List[str] = []
    for marker in markers:
        marker_lc = marker.lower()
        if marker_lc not in response_text_lc:
            continue
        # Treat "0 failed"/"failed=0" style summaries as success, not failure.
        if marker_lc == "failed":
            if any(token in response_text_lc for token in ("0 failed", "0 failures", "failed=0", "failures=0")):
                continue
        hits.append(marker)
    return hits


def _default_cases() -> List[PromptCase]:
    return [
        PromptCase(
            case_id="time",
            expected_tool="time",
            prompt="Use `time` with timezone UTC and return current ISO timestamp.",
        ),
        PromptCase(
            case_id="filesystem",
            expected_tool="list_allowed_directories",
            prompt="Use `list_allowed_directories` and return the allowed directories.",
        ),
        PromptCase(
            case_id="memory",
            expected_tool="read_graph",
            prompt="Use `read_graph` and report entity/relation counts.",
        ),
        PromptCase(
            case_id="sequential",
            expected_tool="sequentialthinking",
            prompt="Use `sequentialthinking` with 2 concise thoughts to compute 19*23, then return final value.",
        ),
        PromptCase(
            case_id="calculator",
            expected_tool="calculate",
            prompt="Use `calculate` to evaluate 19*23 and return only the number.",
        ),
        PromptCase(
            case_id="wikipedia",
            expected_tool="search_wikipedia",
            prompt="Use `search_wikipedia` with query 'Artificial intelligence' and limit 1, then return the top title.",
        ),
        PromptCase(
            case_id="searxng",
            expected_tool="searxng_search",
            prompt="Use `searxng_search` for 'Vera AI assistant' and return the top result title.",
        ),
        PromptCase(
            case_id="brave",
            expected_tool="brave_web_search",
            prompt="Use `brave_web_search` for 'Vera AI assistant' and return the top result title.",
        ),
        PromptCase(
            case_id="github",
            expected_tool="search_repositories",
            prompt="Use `search_repositories` with query 'model context protocol' and return one repo name.",
        ),
        PromptCase(
            case_id="google_workspace",
            expected_tool="list_calendars",
            prompt="Use `list_calendars` and return how many calendars are available.",
        ),
        PromptCase(
            case_id="memvid",
            expected_tool="memvid_encode_text",
            prompt=(
                "Use `memvid_encode_text` with text 'tool sweep diagnostic', "
                "output_video '/home/nizbot-macmini/projects/Vera_2.0/tmp/tool_sweep_memvid.mp4', "
                "output_index '/home/nizbot-macmini/projects/Vera_2.0/tmp/tool_sweep_memvid.index', "
                "chunk_size 200 and overlap 20. Return success status."
            ),
            timeout=120.0,
            require_success_text=True,
            success_markers_any=("success", "created", "written", "saved"),
            failure_markers_any=("failed", "error", "unable", "cannot", "can't"),
        ),
        PromptCase(
            case_id="call_me_native_push",
            expected_tool="send_native_push",
            prompt=(
                "Use `send_native_push` to send a test notification with title "
                "'VERA Tool Sweep' and body 'send_native_push ok', then confirm outcome."
            ),
            critical=False,
            require_success_text=True,
            success_markers_any=("sent", "success", "delivered", "queued"),
            failure_markers_any=(
                "failed",
                "error",
                "unable",
                "cannot",
                "can't",
                "not configured",
                "budget exceeded",
                "quota exceeded",
                "no notification delivered",
            ),
        ),
        PromptCase(
            case_id="call_me_mobile_push",
            expected_tool="send_mobile_push",
            prompt=(
                "Use `send_mobile_push` to send 'VERA tool sweep mobile push test' "
                "to the configured default target, then confirm outcome."
            ),
            require_success_text=True,
            success_markers_any=("sent", "success", "delivered", "queued"),
            failure_markers_any=(
                "failed",
                "error",
                "unable",
                "cannot",
                "can't",
                "not configured",
                "budget exceeded",
                "no notification delivered",
            ),
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run prompt-driven Vera tool sweep")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--case", action="append", default=[], help="Run only selected case_id(s)")
    parser.add_argument("--skip-call-me", action="store_true", help="Skip call-me push test cases")
    parser.add_argument("--output", default="", help="Write JSON report path")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    root_dir = Path(__file__).resolve().parents[1]
    out_path = (
        Path(args.output)
        if args.output
        else root_dir / "tmp" / f"prompt_tool_sweep_{int(time.time())}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cases = _default_cases()
    if args.skip_call_me:
        cases = [case for case in cases if not case.case_id.startswith("call_me_")]
    if args.case:
        wanted = set(args.case)
        cases = [case for case in cases if case.case_id in wanted]

    report: Dict[str, object] = {
        "base_url": base_url,
        "started_at": int(time.time()),
        "results": [],
    }

    failures = 0
    with httpx.Client(timeout=20.0) as client:
        ok, readiness, err = _request_json(client, "GET", f"{base_url}/api/readiness")
        if (not ok) or (not isinstance(readiness, dict)) or (readiness.get("ready") is not True):
            detail = err or f"readiness: {readiness}"
            print(f"[FAIL] readiness - {detail}")
            report["error"] = detail
            out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            return 1

        for idx, case in enumerate(cases, start=1):
            payload = {
                "model": "grok-4-1-fast-reasoning",
                "vera_conversation_id": f"tool-sweep-{case.case_id}-{idx}",
                "messages": [{"role": "user", "content": case.prompt}],
            }
            ok, data, err = _request_json(
                client,
                "POST",
                f"{base_url}/v1/chat/completions",
                json=payload,
                timeout=case.timeout,
            )
            response_text = _extract_response_text(data)
            used_tools, tools_err = _get_last_tools_used(client, base_url)
            passed = ok and (case.expected_tool in used_tools)
            detail = "ok"
            response_text_lc = response_text.lower()
            success_text_ok = True
            success_markers_hit: List[str] = []
            failure_markers_hit: List[str] = []
            if not ok:
                detail = err or "chat request failed"
            elif tools_err:
                detail = tools_err
            elif case.expected_tool not in used_tools:
                detail = f"expected {case.expected_tool}, saw {used_tools}"
            elif case.require_success_text:
                if case.success_markers_any:
                    success_markers_hit = _find_marker_hits(response_text_lc, case.success_markers_any)
                    success_text_ok = bool(success_markers_hit)
                if case.failure_markers_any:
                    failure_markers_hit = _find_marker_hits(response_text_lc, case.failure_markers_any)
                    if failure_markers_hit:
                        success_text_ok = False
                if not success_text_ok:
                    passed = False
                    detail = (
                        f"tool used but success text check failed; "
                        f"success_hits={success_markers_hit or 'none'}; "
                        f"failure_hits={failure_markers_hit or 'none'}"
                    )

            if passed:
                print(f"[OK] {case.case_id} -> {case.expected_tool}")
            else:
                status = "FAIL" if case.critical else "WARN"
                print(f"[{status}] {case.case_id} -> {detail}")
                if case.critical:
                    failures += 1

            report_result = {
                "case_id": case.case_id,
                "expected_tool": case.expected_tool,
                "used_tools": used_tools,
                "passed": passed,
                "critical": case.critical,
                "detail": detail,
                "response_preview": response_text[:300],
                "require_success_text": case.require_success_text,
                "success_markers_hit": success_markers_hit,
                "failure_markers_hit": failure_markers_hit,
            }
            cast_results = report.get("results")
            if isinstance(cast_results, list):
                cast_results.append(report_result)

    report["finished_at"] = int(time.time())
    report["failures"] = failures
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {out_path}")
    print(f"Critical failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
