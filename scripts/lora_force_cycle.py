#!/usr/bin/env python3
"""
Force one learning cycle and print LoRA-focused outcome summary.

Useful for production cutover validation when you want a single command to:
- trigger /api/learning/run-cycle
- wait for completion
- inspect lora_training/reward_training fields
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict


def _extract_cycle_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    run_payload = payload.get("result") or {}
    # run-cycle returns {"scheduled":..., "result": <run_once payload>}
    cycle = run_payload.get("result") if isinstance(run_payload, dict) else {}
    if not isinstance(cycle, dict):
        cycle = {}
    return {
        "scheduled": bool(payload.get("scheduled", False)),
        "completed": bool(payload.get("completed", False)),
        "run_reason": str(run_payload.get("reason") or ""),
        "due_now": bool(run_payload.get("due_now", False)),
        "run_at": str(cycle.get("run_at") or ""),
        "total_examples": int(cycle.get("total_examples", 0) or 0),
        "lora_training": cycle.get("lora_training") or {},
        "reward_training": cycle.get("reward_training") or {},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Force one VERA learning cycle and summarize LoRA outcome")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--require-trained", action="store_true", help="Exit non-zero unless lora_training.trained is true")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    request_payload = {
        "force": True,
        "wait": True,
        "timeout_seconds": max(1.0, min(float(args.timeout), 300.0)),
    }

    try:
        req = urllib.request.Request(
            f"{base_url}/api/learning/run-cycle",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=args.timeout + 5.0) as resp:
            status_code = int(getattr(resp, "status", 200) or 200)
            raw_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        print(
            json.dumps(
                {"ok": False, "error": f"http_{int(exc.code)}", "body": body},
                ensure_ascii=True,
            )
        )
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"request_failed: {exc}"}, ensure_ascii=True))
        return 2

    if status_code >= 400:
        print(
            json.dumps(
                {"ok": False, "error": f"http_{status_code}", "body": raw_body},
                ensure_ascii=True,
            )
        )
        return 2

    try:
        payload = json.loads(raw_body)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"invalid_json: {exc}"}, ensure_ascii=True))
        return 2

    summary = _extract_cycle_result(payload if isinstance(payload, dict) else {})
    summary["ok"] = True

    if args.compact:
        print(json.dumps(summary, ensure_ascii=True))
    else:
        print(json.dumps(summary, indent=2, ensure_ascii=True))

    if args.require_trained and not bool((summary.get("lora_training") or {}).get("trained", False)):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
