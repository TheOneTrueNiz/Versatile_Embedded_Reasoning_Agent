"""
Channel Types
==============

Core types for the channel abstraction layer.
Ported from Moltbot's dock/types pattern.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Protocol, Union


class ChatType(Enum):
    """Type of chat interaction."""
    DIRECT = "direct"
    GROUP = "group"
    CHANNEL = "channel"
    THREAD = "thread"


@dataclass
class ChannelCapabilities:
    """What a channel supports."""
    chat_types: List[ChatType] = field(default_factory=lambda: [ChatType.DIRECT])
    reactions: bool = False
    threads: bool = False
    media: bool = False
    polls: bool = False
    native_commands: bool = False
    text_chunk_limit: int = 4000  # Max chars per message


@dataclass
class ChannelMeta:
    """Lightweight metadata for a channel."""
    id: str
    label: str
    blurb: str = ""
    order: int = 0


@dataclass
class InboundMessage:
    """Normalized inbound message from any channel.

    Every channel adapter converts its native message format
    into this canonical structure before passing to VERA.
    """
    text: str
    sender_id: str
    sender_name: Optional[str] = None
    channel_id: str = ""
    chat_type: ChatType = ChatType.DIRECT
    guild_id: Optional[str] = None
    thread_id: Optional[str] = None
    reply_to_id: Optional[str] = None
    media_urls: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[float] = None


@dataclass
class OutboundMessage:
    """Normalized outbound message to any channel.

    VERA produces this canonical structure, and each channel
    adapter converts it to its native format for sending.
    """
    text: str
    target_id: str
    channel_id: str = ""
    thread_id: Optional[str] = None
    reply_to_id: Optional[str] = None
    media: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(Protocol):
    """Interface that each channel adapter must implement.

    Adapters handle the translation between VERA's canonical
    message format and the channel's native format.
    """

    @property
    def channel_id(self) -> str:
        """Unique identifier for this channel type."""
        ...

    @property
    def capabilities(self) -> ChannelCapabilities:
        """What this channel supports."""
        ...

    @property
    def meta(self) -> ChannelMeta:
        """Lightweight metadata."""
        ...

    async def start(self) -> None:
        """Start the channel adapter (connect, authenticate, etc.)."""
        ...

    async def stop(self) -> None:
        """Stop the channel adapter (disconnect, cleanup)."""
        ...

    async def send(self, message: OutboundMessage) -> Dict[str, Any]:
        """Send a message through this channel. Returns send result."""
        ...

    def set_message_handler(
        self,
        handler: Callable[
            [InboundMessage],
            Union[None, Coroutine[Any, Any, None]],
        ],
    ) -> None:
        """Set the callback for incoming messages."""
        ...
