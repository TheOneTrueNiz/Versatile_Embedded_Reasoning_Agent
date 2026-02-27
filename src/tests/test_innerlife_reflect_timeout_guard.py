from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from api.server import innerlife_reflect


class _DummyRequest:
    def __init__(self, vera: object, payload: dict):
        self.app = {"vera": vera}
        self.can_read_body = True
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


class _DummyResult:
    def to_dict(self) -> dict:
        return {"outcome": "internal"}


def _make_vera(run_reflection_cycle):
    inner_life = SimpleNamespace(config=SimpleNamespace(enabled=True))
    return SimpleNamespace(inner_life=inner_life, _run_reflection_cycle=run_reflection_cycle)


@pytest.mark.asyncio
async def test_innerlife_reflect_timeout_keeps_background_task_running() -> None:
    state = {"started": False, "completed": False, "cancelled": False}

    async def _run_reflection_cycle(trigger: str = "manual", force: bool = True):
        state["started"] = True
        try:
            await asyncio.sleep(1.2)
            state["completed"] = True
            return _DummyResult()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    vera = _make_vera(_run_reflection_cycle)
    request = _DummyRequest(vera, {"wait": True, "timeout_seconds": 1})

    response = await innerlife_reflect(request)
    payload = json.loads(response.text)

    assert response.status == 202
    assert payload["scheduled"] is True
    assert payload["completed"] is False
    assert payload["in_progress"] is True

    await asyncio.sleep(0.3)
    assert state["started"] is True
    assert state["completed"] is True
    assert state["cancelled"] is False
