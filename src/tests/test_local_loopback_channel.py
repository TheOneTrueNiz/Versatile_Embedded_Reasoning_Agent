from __future__ import annotations

import asyncio

from channels.local_loopback.adapter import LocalLoopbackAdapter
from channels.types import OutboundMessage


def test_loopback_inject_inbound_preserves_session_link_id() -> None:
    adapter = LocalLoopbackAdapter()
    captured = {}

    async def _handler(message):
        captured["sender_id"] = message.sender_id
        captured["chat_type"] = message.chat_type.value
        captured["session_link_id"] = message.raw.get("session_link_id")
        captured["text"] = message.text

    adapter.set_message_handler(_handler)

    async def _run() -> None:
        await adapter.start()
        result = await adapter.inject_inbound(
            text="hello loopback",
            sender_id="tester",
            chat_type="thread",
            session_link_id="niz@example.com",
        )
        assert result.get("status") == "ok"
        await adapter.stop()

    asyncio.run(_run())

    assert captured["sender_id"] == "tester"
    assert captured["chat_type"] == "thread"
    assert captured["session_link_id"] == "niz@example.com"
    assert captured["text"] == "hello loopback"


def test_loopback_outbox_snapshot_and_clear() -> None:
    adapter = LocalLoopbackAdapter()

    async def _run() -> None:
        await adapter.send(OutboundMessage(text="first", target_id="t1", channel_id="local-loopback"))
        await adapter.send(OutboundMessage(text="second", target_id="t1", channel_id="local-loopback"))
        latest = await adapter.outbox_snapshot(limit=1)
        assert len(latest) == 1
        assert latest[0].get("text") == "second"
        cleared = await adapter.clear_outbox()
        assert cleared == 2
        remaining = await adapter.outbox_snapshot(limit=5)
        assert remaining == []

    asyncio.run(_run())

