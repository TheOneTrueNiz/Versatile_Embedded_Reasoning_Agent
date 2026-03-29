from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api.server import _call_mcp_tool, _default_mcp_tool_timeout_seconds, _extract_mcp_error_text, tools_call


class _FakeRequest:
    def __init__(self, app, payload):
        self.app = app
        self._payload = payload

    async def json(self):
        return self._payload


def test_extract_mcp_error_text_reads_iserror_content() -> None:
    result = {
        "isError": True,
        "content": [{"type": "text", "text": "Error: Push request timed out after 15000ms"}],
    }
    assert _extract_mcp_error_text(result) == "Error: Push request timed out after 15000ms"


def test_default_mcp_tool_timeout_seconds_prefers_longer_call_timeout() -> None:
    assert _default_mcp_tool_timeout_seconds("call-me", "initiate_call") == 75.0
    assert _default_mcp_tool_timeout_seconds("call-me", "send_native_push") == 20.0


@pytest.mark.asyncio
async def test_call_mcp_tool_returns_false_for_iserror_payload() -> None:
    vera = SimpleNamespace(mcp=SimpleNamespace(call_tool=lambda *args, **kwargs: {
        "isError": True,
        "content": [{"type": "text", "text": "Error: Push request timed out after 15000ms"}],
    }))
    ok, detail = await _call_mcp_tool(vera, "call-me", "send_native_push", {}, 5.0)
    assert ok is False
    assert "Push request timed out" in detail


@pytest.mark.asyncio
async def test_tools_call_returns_502_for_mcp_iserror_payload() -> None:
    vera = SimpleNamespace(
        _native_tool_handlers={},
        mcp=SimpleNamespace(call_tool=lambda *args, **kwargs: {
            "isError": True,
            "content": [{"type": "text", "text": "Error: Push request timed out after 15000ms"}],
        }),
    )
    request = _FakeRequest(
        app={"vera": vera, "mcp_call_global_semaphore": None, "mcp_call_server_semaphores": {}, "mcp_call_queue_timeout_seconds": 3.0},
        payload={"server": "call-me", "name": "send_native_push", "arguments": {"title": "t", "message": "m"}},
    )
    response = await tools_call(request)
    assert response.status == 502
    assert b"Push request timed out after 15000ms" in response.body


@pytest.mark.asyncio
async def test_tools_call_returns_502_with_exception_text_for_mcp_failure() -> None:
    vera = SimpleNamespace(
        _native_tool_handlers={},
        mcp=SimpleNamespace(call_tool=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Call answer timeout"))),
    )
    request = _FakeRequest(
        app={"vera": vera, "mcp_call_global_semaphore": None, "mcp_call_server_semaphores": {}, "mcp_call_queue_timeout_seconds": 3.0},
        payload={"server": "call-me", "name": "initiate_call", "arguments": {"message": "Wake up"}},
    )
    response = await tools_call(request)
    assert response.status == 502
    assert b"Call answer timeout" in response.body


@pytest.mark.asyncio
async def test_tools_call_returns_502_when_capacity_wait_times_out_for_stopped_server() -> None:
    server_sem = asyncio.Semaphore(1)
    await server_sem.acquire()
    vera = SimpleNamespace(
        _native_tool_handlers={},
        mcp=SimpleNamespace(
            call_tool=lambda *args, **kwargs: {"content": [{"type": "text", "text": "ok"}]},
            get_status=lambda: {"servers": {"call-me": {"running": False, "health": "stopped"}}},
        ),
    )
    request = _FakeRequest(
        app={
            "vera": vera,
            "mcp_call_global_semaphore": None,
            "mcp_call_server_semaphores": {"call-me": server_sem},
            "mcp_call_queue_timeout_seconds": 0.1,
        },
        payload={"server": "call-me", "name": "send_native_push", "arguments": {"title": "t", "message": "m"}},
    )
    response = await tools_call(request)
    assert response.status == 502
    assert b"MCP server call-me not running" in response.body
    server_sem.release()


@pytest.mark.asyncio
async def test_tools_call_returns_429_when_capacity_wait_times_out_for_running_server() -> None:
    server_sem = asyncio.Semaphore(1)
    await server_sem.acquire()
    vera = SimpleNamespace(
        _native_tool_handlers={},
        mcp=SimpleNamespace(
            call_tool=lambda *args, **kwargs: {"content": [{"type": "text", "text": "ok"}]},
            get_status=lambda: {"servers": {"call-me": {"running": True, "health": "healthy"}}},
        ),
    )
    request = _FakeRequest(
        app={
            "vera": vera,
            "mcp_call_global_semaphore": None,
            "mcp_call_server_semaphores": {"call-me": server_sem},
            "mcp_call_queue_timeout_seconds": 0.1,
        },
        payload={"server": "call-me", "name": "send_native_push", "arguments": {"title": "t", "message": "m"}},
    )
    response = await tools_call(request)
    assert response.status == 429
    assert b"Tool server is busy; please retry." in response.body
    server_sem.release()


@pytest.mark.asyncio
async def test_tools_call_uses_extended_default_timeout_for_initiate_call() -> None:
    seen = {}

    def _call_tool(server, tool, args, timeout):
        seen["server"] = server
        seen["tool"] = tool
        seen["timeout"] = timeout
        return {"content": [{"type": "text", "text": "ok"}]}

    vera = SimpleNamespace(
        _native_tool_handlers={},
        mcp=SimpleNamespace(call_tool=_call_tool),
    )
    request = _FakeRequest(
        app={"vera": vera, "mcp_call_global_semaphore": None, "mcp_call_server_semaphores": {}, "mcp_call_queue_timeout_seconds": 3.0},
        payload={"server": "call-me", "name": "initiate_call", "arguments": {"message": "Wake up"}},
    )
    response = await tools_call(request)
    assert response.status == 200
    assert seen["server"] == "call-me"
    assert seen["tool"] == "initiate_call"
    assert seen["timeout"] == 75.0


@pytest.mark.asyncio
async def test_tools_call_accepts_args_alias() -> None:
    seen = {}

    def _call_tool(server, tool, args, timeout):
        seen["server"] = server
        seen["tool"] = tool
        seen["args"] = args
        seen["timeout"] = timeout
        return {"content": [{"type": "text", "text": "ok"}]}

    vera = SimpleNamespace(
        _native_tool_handlers={},
        mcp=SimpleNamespace(call_tool=_call_tool),
    )
    request = _FakeRequest(
        app={"vera": vera, "mcp_call_global_semaphore": None, "mcp_call_server_semaphores": {}, "mcp_call_queue_timeout_seconds": 3.0},
        payload={"server": "call-me", "name": "send_native_push", "args": {"message": "probe", "title": "Codex"}},
    )
    response = await tools_call(request)
    assert response.status == 200
    assert seen["server"] == "call-me"
    assert seen["tool"] == "send_native_push"
    assert seen["args"] == {"message": "probe", "title": "Codex"}
