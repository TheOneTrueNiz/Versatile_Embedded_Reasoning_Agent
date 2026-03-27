"""Example: resilient chat probe for production checklist.

Integration target:
- scripts/vera_production_checklist.py
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx


@dataclass
class ProbeResult:
    ok: bool
    detail: str
    attempts: int
    elapsed_s: float
    transient_timeout: bool


def _extract_preview(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    msg = first.get("message", {}) if isinstance(first.get("message"), dict) else {}
    return str(msg.get("content", "")).strip()


def run_chat_probe(
    base_url: str,
    model: str,
    message: str,
    attempts: int = 3,
    base_timeout_s: float = 20.0,
    max_tokens: int = 32,
) -> ProbeResult:
    started = time.time()
    transient_timeout = False
    last_error = ""

    for attempt in range(1, max(1, attempts) + 1):
        timeout_s = base_timeout_s + (attempt - 1) * 5.0
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": message}],
            "max_tokens": max_tokens,
        }
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(f"{base_url.rstrip('/')}/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            preview = _extract_preview(data)
            if preview:
                return ProbeResult(
                    ok=True,
                    detail=preview[:160],
                    attempts=attempt,
                    elapsed_s=round(time.time() - started, 3),
                    transient_timeout=transient_timeout,
                )
            last_error = "invalid_chat_response"
        except httpx.TimeoutException:
            transient_timeout = True
            last_error = "request timed out"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)

        if attempt < attempts:
            time.sleep(0.15 + random.uniform(0.0, 0.2))

    return ProbeResult(
        ok=False,
        detail=last_error or "chat_probe_failed",
        attempts=max(1, attempts),
        elapsed_s=round(time.time() - started, 3),
        transient_timeout=transient_timeout,
    )


if __name__ == "__main__":
    result = run_chat_probe(
        base_url="http://127.0.0.1:8788",
        model="grok-4-1-fast-reasoning",
        message="Return exactly: VERA_CHECK_OK",
    )
    print(result)
