from __future__ import annotations

import asyncio
from pathlib import Path

from planning.inner_life_engine import InnerLifeConfig, InnerLifeEngine


class _AdapterStub:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls = 0

    async def send(self, outbound) -> None:
        self.calls += 1
        if self.should_fail:
            raise RuntimeError("send failed")


def _make_engine(tmp_path: Path, channels: list[str]) -> InnerLifeEngine:
    config = InnerLifeConfig(delivery_channels=list(channels))
    engine = InnerLifeEngine(config, tmp_path / "innerlife")
    engine._resolve_delivery_target = lambda channel_id: "target-user"  # type: ignore[assignment]
    return engine


def test_delivery_mode_fallback_stops_after_first_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_INNER_LIFE_DELIVERY_MODE", "fallback")
    engine = _make_engine(tmp_path, ["chan1", "chan2", "chan3"])
    adapter1 = _AdapterStub(should_fail=True)
    adapter2 = _AdapterStub(should_fail=False)
    adapter3 = _AdapterStub(should_fail=False)
    engine._channel_dock = {"chan1": adapter1, "chan2": adapter2, "chan3": adapter3}

    delivered = asyncio.run(engine._deliver_to_channels("hello"))

    assert delivered == ["chan2"]
    assert adapter1.calls == 1
    assert adapter2.calls == 1
    assert adapter3.calls == 0


def test_delivery_mode_broadcast_tries_all_channels(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VERA_INNER_LIFE_DELIVERY_MODE", "broadcast")
    engine = _make_engine(tmp_path, ["chan1", "chan2", "chan3"])
    adapter1 = _AdapterStub(should_fail=True)
    adapter2 = _AdapterStub(should_fail=False)
    adapter3 = _AdapterStub(should_fail=False)
    engine._channel_dock = {"chan1": adapter1, "chan2": adapter2, "chan3": adapter3}

    delivered = asyncio.run(engine._deliver_to_channels("hello"))

    assert delivered == ["chan2", "chan3"]
    assert adapter1.calls == 1
    assert adapter2.calls == 1
    assert adapter3.calls == 1
