"""
Local Loopback Channel Adapter
==============================

Internal channel adapter used for deterministic cross-channel continuity tests.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

from channels.types import (
    ChannelCapabilities,
    ChannelMeta,
    ChatType,
    InboundMessage,
    OutboundMessage,
)

logger = logging.getLogger(__name__)


def _normalize_chat_type(raw: str) -> ChatType:
    value = str(raw or "").strip().lower()
    if value == ChatType.GROUP.value:
        return ChatType.GROUP
    if value == ChatType.CHANNEL.value:
        return ChatType.CHANNEL
    if value == ChatType.THREAD.value:
        return ChatType.THREAD
    return ChatType.DIRECT


class LocalLoopbackAdapter:
    """Local adapter for injecting inbound messages and capturing outbound replies."""

    def __init__(
        self,
        channel_id: str = "local-loopback",
        label: str = "Local Loopback",
        blurb: str = "Deterministic local channel for continuity testing",
        order: int = 95,
    ) -> None:
        self.channel_id = str(channel_id or "local-loopback").strip() or "local-loopback"
        self.capabilities = ChannelCapabilities(
            chat_types=[ChatType.DIRECT, ChatType.GROUP, ChatType.THREAD],
            reactions=False,
            threads=True,
            media=False,
            polls=False,
            native_commands=False,
            text_chunk_limit=0,
        )
        self.meta = ChannelMeta(
            id=self.channel_id,
            label=str(label or "Local Loopback"),
            blurb=str(blurb or ""),
            order=int(order),
        )
        self._handler: Optional[Callable] = None
        self._outbox: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self.running = False

    async def start(self) -> None:
        self.running = True
        logger.info("Local loopback adapter started (%s)", self.channel_id)

    async def stop(self) -> None:
        self.running = False
        logger.info("Local loopback adapter stopped (%s)", self.channel_id)

    async def send(self, message: OutboundMessage) -> Dict[str, Any]:
        payload = {
            "text": message.text,
            "target_id": message.target_id,
            "channel_id": message.channel_id,
            "thread_id": message.thread_id,
            "reply_to_id": message.reply_to_id,
            "metadata": message.metadata,
            "sent_at": time.time(),
        }
        async with self._lock:
            self._outbox.append(payload)
        return {"status": "ok", "channel": self.channel_id, "outbox_size": len(self._outbox)}

    def set_message_handler(
        self,
        handler: Callable[
            [InboundMessage],
            Union[None, Coroutine[Any, Any, None]],
        ],
    ) -> None:
        self._handler = handler

    async def inject_inbound(
        self,
        *,
        text: str,
        sender_id: str = "loopback-user",
        sender_name: Optional[str] = None,
        conversation_id: Optional[str] = None,
        session_link_id: Optional[str] = None,
        chat_type: str = "direct",
        thread_id: Optional[str] = None,
        reply_to_id: Optional[str] = None,
        raw: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self._handler:
            return {"status": "error", "error": "message_handler_not_set"}

        cleaned_text = str(text or "").strip()
        if not cleaned_text:
            return {"status": "error", "error": "empty_text"}

        raw_payload: Dict[str, Any] = dict(raw or {})
        if session_link_id and "session_link_id" not in raw_payload:
            raw_payload["session_link_id"] = str(session_link_id).strip()

        inbound = InboundMessage(
            text=cleaned_text,
            sender_id=str(sender_id or "loopback-user").strip() or "loopback-user",
            sender_name=sender_name,
            channel_id=str(conversation_id or sender_id or "loopback-room").strip() or "loopback-room",
            chat_type=_normalize_chat_type(chat_type),
            thread_id=str(thread_id).strip() if thread_id else None,
            reply_to_id=str(reply_to_id).strip() if reply_to_id else None,
            raw=raw_payload,
            timestamp=time.time(),
        )

        result = self._handler(inbound)
        if asyncio.iscoroutine(result):
            await result

        return {"status": "ok", "channel": self.channel_id}

    async def clear_outbox(self) -> int:
        async with self._lock:
            count = len(self._outbox)
            self._outbox.clear()
        return count

    async def outbox_snapshot(self, limit: int = 20) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        async with self._lock:
            if not self._outbox:
                return []
            return list(self._outbox[-safe_limit:])

