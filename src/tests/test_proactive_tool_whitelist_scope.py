"""Ensure proactive tool whitelist is scoped to autonomy conversations only."""

from __future__ import annotations

import pytest

from core.runtime.vera import VERA


class _ToolOrchestratorStub:
    async def execute_tool(self, tool_name, params, **kwargs):  # noqa: ANN001
        return f"ok:{tool_name}"


@pytest.mark.asyncio
async def test_proactive_whitelist_does_not_block_user_context():
    vera = object.__new__(VERA)
    vera.tool_orchestrator = _ToolOrchestratorStub()
    vera._proactive_tool_whitelist = {"time"}

    result = await VERA.execute_tool(
        vera,
        "create_event",
        {"title": "x"},
        context={"conversation_id": "default"},
    )

    assert result == "ok:create_event"


@pytest.mark.asyncio
async def test_proactive_whitelist_blocks_autonomy_context():
    vera = object.__new__(VERA)
    vera.tool_orchestrator = _ToolOrchestratorStub()
    vera._proactive_tool_whitelist = {"time"}

    result = await VERA.execute_tool(
        vera,
        "create_event",
        {"title": "x"},
        context={"conversation_id": "autonomy:test:1"},
    )

    assert "not available in proactive mode" in result


@pytest.mark.asyncio
async def test_proactive_whitelist_allows_autonomy_allowed_tool():
    vera = object.__new__(VERA)
    vera.tool_orchestrator = _ToolOrchestratorStub()
    vera._proactive_tool_whitelist = {"time"}

    result = await VERA.execute_tool(
        vera,
        "time",
        {},
        context={"conversation_id": "autonomy:test:2"},
    )

    assert result == "ok:time"
