"""Example: deterministic cross-channel continuity probe.

Integration target:
- scripts/ (new validation script)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Optional

import httpx


@dataclass
class ProbeResult:
    ok: bool
    detail: str
    channel_a_reply: str
    channel_b_reply: str


def _extract_text(resp_json: Dict[str, object]) -> str:
    choices = resp_json.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    msg = first.get("message", {}) if isinstance(first.get("message"), dict) else {}
    return str(msg.get("content", ""))


def run_probe(base_url: str = "http://127.0.0.1:8788") -> ProbeResult:
    marker = "continuity_marker_42"

    payload_a = {
        "model": "grok-4-1-fast-reasoning",
        "messages": [{"role": "user", "content": f"Remember this marker exactly: {marker}"}],
        "conversation_id": "continuity-a",
    }
    payload_b = {
        "model": "grok-4-1-fast-reasoning",
        "messages": [{"role": "user", "content": "What marker did I ask you to remember?"}],
        "conversation_id": "continuity-b",
        # Adapter hint is illustrative; wire to real channel linking implementation.
        "session_link": "partner-shared-thread-1",
    }

    with httpx.Client(timeout=45.0) as client:
        a = client.post(f"{base_url.rstrip('/')}/v1/chat/completions", json=payload_a)
        b = client.post(f"{base_url.rstrip('/')}/v1/chat/completions", json=payload_b)

    a.raise_for_status()
    b.raise_for_status()

    a_text = _extract_text(a.json())
    b_text = _extract_text(b.json())
    ok = marker in b_text
    detail = "continuity_preserved" if ok else "continuity_missing"

    return ProbeResult(ok=ok, detail=detail, channel_a_reply=a_text[:240], channel_b_reply=b_text[:240])


if __name__ == "__main__":
    result = run_probe()
    print(json.dumps(result.__dict__, ensure_ascii=True, indent=2))
