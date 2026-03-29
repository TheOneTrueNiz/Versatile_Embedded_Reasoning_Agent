#!/usr/bin/env python3
"""
Run regression prompts against the VERA API.
"""

import argparse
import json
import os
import time
from pathlib import Path
from typing import List, Dict, Any

import httpx


DEFAULT_CASES = Path("vera_memory/flight_recorder/regression_cases.jsonl")
DEFAULT_RESULTS = Path("vera_memory/flight_recorder/regression_results.jsonl")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def _write_jsonl(path: Path, items: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")


def _resolve_model(client: httpx.Client) -> str:
    response = client.get("/v1/models")
    response.raise_for_status()
    data = response.json()
    models = data.get("data", [])
    if not models:
        return os.getenv("VERA_MODEL", "grok-4.20-experimental-beta-0304-reasoning")
    return models[0].get("id") or os.getenv("VERA_MODEL", "grok-4.20-experimental-beta-0304-reasoning")


def _wait_for_api(client: httpx.Client, timeout_seconds: float = 60.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            response = client.get("/api/health")
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1.0)
    raise RuntimeError(f"VERA API not ready at {client.base_url} ({last_error})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--base-url", type=str, default=os.getenv("VERA_API_BASE", "http://127.0.0.1:8788"))
    parser.add_argument("--model", type=str, default=os.getenv("VERA_MODEL", ""))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--wait", type=float, default=60.0)
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=float(os.getenv("VERA_REGRESSION_REQUEST_TIMEOUT", "90")),
        help="Per-request timeout in seconds for /v1/chat/completions",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=0.0,
        help="Optional total runtime cap in seconds (0 disables cap).",
    )
    args = parser.parse_args()

    cases = _read_jsonl(args.cases)
    if not cases:
        print("No regression cases found.", flush=True)
        return 0

    if args.limit and args.limit > 0:
        cases = cases[: args.limit]

    print(
        f"Running {len(cases)} regression case(s) "
        f"(request_timeout={args.request_timeout}s, max_seconds={args.max_seconds or 'off'})",
        flush=True,
    )
    started_at = time.time()
    timed_out = False

    with httpx.Client(base_url=args.base_url, timeout=args.request_timeout) as client:
        _wait_for_api(client, timeout_seconds=max(0.0, args.wait))
        model = args.model or _resolve_model(client)
        results: List[Dict[str, Any]] = []
        total = len(cases)
        for index, item in enumerate(cases, start=1):
            if args.max_seconds > 0 and (time.time() - started_at) >= args.max_seconds:
                timed_out = True
                print(
                    f"Reached max runtime ({args.max_seconds}s). "
                    f"Stopping at case {index}/{total}.",
                    flush=True,
                )
                break
            prompt = (item.get("prompt") or "").strip()
            if not prompt:
                continue
            preview = prompt.replace("\n", " ")[:80]
            print(f"[{index}/{total}] Running regression case: {preview}", flush=True)
            case_started = time.time()
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }
            ok = True
            error = ""
            response_payload: Dict[str, Any] = {}
            try:
                response = client.post("/v1/chat/completions", json=payload)
                if response.status_code >= 400:
                    ok = False
                    error = response.text.strip()
                else:
                    response_payload = response.json()
            except Exception as exc:
                ok = False
                error = str(exc)

            content = ""
            if response_payload:
                choices = response_payload.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "") or ""
            results.append({
                "prompt": prompt,
                "ok": ok,
                "error": error,
                "response_preview": content[:200],
            })
            # Persist incrementally so partial runs still produce usable output.
            _write_jsonl(args.output, results)

            case_elapsed = time.time() - case_started
            status = "OK" if ok else "FAIL"
            if ok:
                print(f"[{index}/{total}] {status} ({case_elapsed:.1f}s)", flush=True)
            else:
                err_preview = (error or "").replace("\n", " ")[:160]
                print(f"[{index}/{total}] {status} ({case_elapsed:.1f}s): {err_preview}", flush=True)

    # Ensure final file is in sync.
    _write_jsonl(args.output, results)
    passed = sum(1 for item in results if item.get("ok"))
    failed = len(results) - passed
    total_elapsed = time.time() - started_at
    print(
        f"Wrote {len(results)} regression results to {args.output} "
        f"(passed={passed}, failed={failed}, elapsed={total_elapsed:.1f}s)",
        flush=True,
    )
    if timed_out:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
