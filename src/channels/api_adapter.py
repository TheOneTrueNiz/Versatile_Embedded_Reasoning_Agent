"""
API Channel Adapter
====================

Wraps VERA's existing aiohttp API as a channel adapter,
so the current HTTP mode works through the channel abstraction.

This is a passthrough adapter - it doesn't actually send/receive
via a messaging platform. Instead, it normalizes HTTP API requests
into InboundMessage and responses into OutboundMessage.
"""

import logging
from typing import Any, Callable, Coroutine, Dict, Optional, Union

from channels.types import (
    ChannelAdapter,
    ChannelCapabilities,
    ChannelMeta,
    ChatType,
    InboundMessage,
    OutboundMessage,
)

logger = logging.getLogger(__name__)


class ApiChannelAdapter:
    """Channel adapter for the HTTP API.

    Makes the existing /v1/chat/completions endpoint work through
    the channel abstraction. This is a logical adapter - messages
    flow through the HTTP request/response cycle, not a persistent
    connection.
    """

    channel_id = "api"
    capabilities = ChannelCapabilities(
        chat_types=[ChatType.DIRECT],
        reactions=False,
        threads=False,
        media=False,
        text_chunk_limit=0,  # No limit for API responses
    )
    meta = ChannelMeta(
        id="api",
        label="HTTP API",
        blurb="OpenAI-compatible chat completions API",
        order=0,
    )

    def __init__(self) -> None:
        self._handler: Optional[Callable] = None

    async def start(self) -> None:
        """No-op for API adapter (server started separately)."""
        logger.debug("API channel adapter ready")

    async def stop(self) -> None:
        """No-op for API adapter."""
        pass

    async def send(self, message: OutboundMessage) -> Dict[str, Any]:
        """No-op - API responses go through HTTP response, not this method."""
        return {"status": "ok", "channel": "api"}

    def set_message_handler(
        self,
        handler: Callable[
            [InboundMessage],
            Union[None, Coroutine[Any, Any, None]],
        ],
    ) -> None:
        self._handler = handler

    @staticmethod
    def inbound_from_api_request(
        messages: list,
        conversation_id: str = "default",
        model: Optional[str] = None,
    ) -> InboundMessage:
        """Convert an OpenAI-format API request into an InboundMessage.

        Extracts the last user message from the messages list.
        """
        last_user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_text = msg.get("content", "")
                break

        return InboundMessage(
            text=last_user_text,
            sender_id="api",
            sender_name="API Client",
            channel_id="api",
            chat_type=ChatType.DIRECT,
            raw={
                "messages": messages,
                "conversation_id": conversation_id,
                "model": model,
            },
        )

    @staticmethod
    def outbound_to_api_response(
        text: str,
        conversation_id: str = "default",
    ) -> OutboundMessage:
        """Convert VERA's response text into an OutboundMessage."""
        return OutboundMessage(
            text=text,
            target_id="api",
            channel_id="api",
            metadata={"conversation_id": conversation_id},
        )
