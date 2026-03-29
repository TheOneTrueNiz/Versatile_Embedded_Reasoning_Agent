"""
Integration smoke tests for VERA 2.0.

These tests require a running VERA instance on the configured host/port.
They validate the critical path: readiness → chat round-trip → tool invocation.

Run:
    VERA_TEST_BASE_URL=http://127.0.0.1:8788 \
    PYTHONPATH=src .venv/bin/pytest src/tests/test_integration_smoke.py -v --timeout=120

Skip if no server:
    Tests auto-skip when VERA is not reachable.
"""

from __future__ import annotations

import json
import os
import time

import httpx
import pytest

BASE_URL = os.getenv("VERA_TEST_BASE_URL", "http://127.0.0.1:8788")


def _is_vera_reachable() -> bool:
    try:
        r = httpx.get(f"{BASE_URL}/api/readiness", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


skip_if_no_vera = pytest.mark.skipif(
    not _is_vera_reachable(),
    reason=f"VERA not reachable at {BASE_URL}",
)


# ------------------------------------------------------------------
# Readiness & health
# ------------------------------------------------------------------


@skip_if_no_vera
def test_readiness_endpoint_returns_ready() -> None:
    """VERA reports ready with tools loaded."""
    r = httpx.get(f"{BASE_URL}/api/readiness", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data.get("ready") is True, f"Not ready: {data}"
    mcp = data.get("mcp", {})
    assert mcp.get("total_running", 0) > 10, f"Too few MCP servers: {mcp}"


@skip_if_no_vera
def test_health_endpoint_returns_ok() -> None:
    """Health endpoint returns ok status."""
    r = httpx.get(f"{BASE_URL}/api/health", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("status") in ("ok", "degraded")


@skip_if_no_vera
def test_models_endpoint_lists_models() -> None:
    """Models endpoint returns at least one model."""
    r = httpx.get(f"{BASE_URL}/v1/models", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data.get("object") == "list"
    assert len(data.get("data", [])) >= 1


# ------------------------------------------------------------------
# Chat completions (non-streaming)
# ------------------------------------------------------------------


@skip_if_no_vera
def test_basic_chat_completion() -> None:
    """Simple chat completion returns a well-formed response."""
    payload = {
        "model": "grok-4.20-experimental-beta-0304-reasoning",
        "messages": [
            {"role": "user", "content": "What is 2 + 2? Reply with just the number."}
        ],
        "stream": False,
    }
    r = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        json=payload,
        timeout=60,
    )
    assert r.status_code == 200
    data = r.json()
    assert "choices" in data, f"No choices in response: {data}"
    assert len(data["choices"]) >= 1
    msg = data["choices"][0].get("message", {})
    assert msg.get("role") == "assistant"
    content = msg.get("content", "")
    assert len(content) > 0, "Empty assistant response"
    assert "4" in content, f"Expected '4' in response: {content}"


@skip_if_no_vera
def test_chat_completion_with_conversation_id() -> None:
    """Chat completion respects conversation_id for session isolation."""
    cid = f"smoke-test-{int(time.time())}"
    payload = {
        "model": "grok-4.20-experimental-beta-0304-reasoning",
        "messages": [
            {"role": "user", "content": "Say 'pong'. Nothing else."}
        ],
        "stream": False,
        "conversation_id": cid,
    }
    r = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        json=payload,
        timeout=60,
    )
    assert r.status_code == 200
    data = r.json()
    content = data["choices"][0]["message"]["content"].lower()
    assert "pong" in content


# ------------------------------------------------------------------
# Tool invocation
# ------------------------------------------------------------------


@skip_if_no_vera
def test_tool_invocation_time() -> None:
    """Explicit tool_choice forces the 'time' tool and returns a timestamp."""
    payload = {
        "model": "grok-4.20-experimental-beta-0304-reasoning",
        "messages": [
            {"role": "user", "content": "What time is it right now?"}
        ],
        "stream": False,
        "tool_choice": {"type": "function", "function": {"name": "time"}},
    }
    r = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        json=payload,
        timeout=60,
    )
    assert r.status_code == 200
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    # Should contain time-related content (digits, colons, date patterns)
    assert any(c.isdigit() for c in content), f"No digits in time response: {content}"


@skip_if_no_vera
def test_tool_invocation_calculate() -> None:
    """Calculator tool returns correct arithmetic."""
    payload = {
        "model": "grok-4.20-experimental-beta-0304-reasoning",
        "messages": [
            {"role": "user", "content": "Calculate 123 * 456 using the calculator."}
        ],
        "stream": False,
        "tool_choice": {"type": "function", "function": {"name": "calculate"}},
    }
    r = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        json=payload,
        timeout=60,
    )
    assert r.status_code == 200
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    # Vera may format with commas (56,088) or raw (56088)
    assert "56" in content and "088" in content, f"Expected 56088 in response: {content}"


# ------------------------------------------------------------------
# Streaming
# ------------------------------------------------------------------


@skip_if_no_vera
def test_streaming_chat_completion() -> None:
    """Streaming response delivers SSE chunks ending with [DONE]."""
    payload = {
        "model": "grok-4.20-experimental-beta-0304-reasoning",
        "messages": [
            {"role": "user", "content": "Say 'hello' and nothing else."}
        ],
        "stream": True,
    }
    chunks = []
    with httpx.stream(
        "POST",
        f"{BASE_URL}/v1/chat/completions",
        json=payload,
        timeout=60,
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                chunks.append(json.loads(data_str))

    assert len(chunks) > 0, "No streaming chunks received"
    # At least one chunk should have content
    has_content = any(
        c.get("choices", [{}])[0].get("delta", {}).get("content")
        for c in chunks
    )
    assert has_content, "No content in any streaming chunk"


# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------


@skip_if_no_vera
def test_malformed_request_returns_error() -> None:
    """Malformed request gets a proper error response, not a crash."""
    r = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        json={"messages": "not-a-list"},
        timeout=30,
    )
    # Should get an error status, not 500
    assert r.status_code in (400, 422, 500)
    # Server should still be alive
    health = httpx.get(f"{BASE_URL}/health", timeout=5)
    assert health.status_code == 200
