#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_BASE_URL = "http://127.0.0.1:8788"
DEFAULT_CASES = [
    {
        "id": "calendar",
        "query": "Check my calendar for upcoming events and reminders. If there are any today, summarize them briefly.",
    },
    {
        "id": "gmail_workspace",
        "query": "Check my Gmail for urgent messages from today and summarize anything that needs follow-up.",
    },
    {
        "id": "web_research",
        "query": "Research the latest public information about local LLM inference acceleration and summarize the top findings with sources.",
    },
    {
        "id": "filesystem_local_memory",
        "query": "Inspect the local Vera project files and memory notes to find the latest diary checkpoint about autonomy work.",
    },
]


def _http_json(url: str, *, method: str = "GET", payload: Dict[str, Any] | None = None, timeout: float = 30.0) -> Dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))



def _wait_ready(base_url: str, timeout_seconds: float) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        try:
            payload = _http_json(f"{base_url}/api/readiness", timeout=5.0)
            last = payload
            if payload.get("ready") is True:
                return payload
        except Exception:
            pass
        time.sleep(2.0)
    raise RuntimeError(f"runtime_not_ready: last={last}")



def _capture_case(base_url: str, case: Dict[str, str], preview_timeout: float) -> Dict[str, Any]:
    started = time.time()
    preview_error = ""
    preview_payload: Dict[str, Any] = {}
    try:
        preview_payload = _http_json(
            f"{base_url}/api/tools/preview",
            method="POST",
            payload={"context": case["query"]},
            timeout=preview_timeout,
        )
    except urllib.error.HTTPError as exc:
        preview_error = f"http_error:{exc.code}"
    except Exception as exc:  # noqa: BLE001
        preview_error = f"{type(exc).__name__}:{exc}"

    last_payload = {}
    try:
        last_payload = _http_json(f"{base_url}/api/tools/last_payload", timeout=10.0).get("payload", {})
    except Exception as exc:  # noqa: BLE001
        last_payload = {"_error": f"{type(exc).__name__}:{exc}"}

    payload = preview_payload.get("payload") if isinstance(preview_payload, dict) else {}
    effective = payload or last_payload or {}
    return {
        "id": case["id"],
        "query": case["query"],
        "preview_ok": bool(preview_payload.get("ok")) if isinstance(preview_payload, dict) else False,
        "preview_error": preview_error,
        "duration_seconds": round(time.time() - started, 3),
        "selected_servers": effective.get("selected_servers", []),
        "selected_categories": effective.get("selected_categories", []),
        "tool_names": effective.get("tool_names", []),
        "mcp_shortlist_names": effective.get("mcp_shortlist_names", []),
        "mcp_shortlist_context_intents": effective.get("mcp_shortlist_context_intents", []),
        "mcp_shortlist_preserve_names": effective.get("mcp_shortlist_preserve_names", []),
        "raw_preview": preview_payload,
        "raw_last_payload": last_payload,
    }



def main() -> int:
    parser = argparse.ArgumentParser(description="Run a multi-query tool-routing preview regression matrix.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--readiness-timeout", type=float, default=120.0)
    parser.add_argument("--preview-timeout", type=float, default=45.0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    _wait_ready(args.base_url, args.readiness_timeout)

    results: List[Dict[str, Any]] = []
    for case in DEFAULT_CASES:
        results.append(_capture_case(args.base_url, case, args.preview_timeout))

    summary = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "case_count": len(results),
        "cases": results,
    }

    output_path = args.output.strip()
    if not output_path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = f"tmp/audits/tool_preview_regression_matrix_{stamp}.json"
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
