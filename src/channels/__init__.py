"""
VERA 2.0 Channel System
========================

Moltbot-style channel abstraction with pluggable adapters.
Keeps the dock lightweight (no I/O, no auth) - heavy logic in adapters.
"""

from channels.types import (
    ChannelAdapter,
    ChannelCapabilities,
    ChannelMeta,
    ChatType,
    InboundMessage,
    OutboundMessage,
)
from channels.dock import ChannelDock

__all__ = [
    "ChannelAdapter",
    "ChannelCapabilities",
    "ChannelMeta",
    "ChannelDock",
    "ChatType",
    "InboundMessage",
    "OutboundMessage",
]
