"""
Channel Dock
=============

Lightweight channel metadata registry with pluggable adapters.
Ported from Moltbot's dock.ts pattern.

The dock itself does no I/O and holds no auth - it's a pure
registry that maps channel IDs to their adapters and capabilities.
"""

import logging
from typing import Dict, List, Optional

from channels.types import ChannelAdapter, ChannelCapabilities, ChannelMeta

logger = logging.getLogger(__name__)


class ChannelDock:
    """Registry for channel adapters.

    Keeps the dock cheap - no I/O, no auth flows.
    Push heavy logic into the channel adapters themselves.
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter."""
        cid = adapter.channel_id
        self._adapters[cid] = adapter
        logger.info(f"Channel registered: {cid} ({adapter.meta.label})")

    def unregister(self, channel_id: str) -> bool:
        """Unregister a channel adapter. Returns True if found."""
        if channel_id in self._adapters:
            del self._adapters[channel_id]
            return True
        return False

    def get(self, channel_id: str) -> Optional[ChannelAdapter]:
        """Get an adapter by channel ID."""
        return self._adapters.get(channel_id)

    def list_channels(self) -> List[ChannelMeta]:
        """List metadata for all registered channels."""
        metas = [a.meta for a in self._adapters.values()]
        metas.sort(key=lambda m: m.order)
        return metas

    def list_capabilities(self) -> Dict[str, ChannelCapabilities]:
        """Map of channel ID to capabilities."""
        return {cid: a.capabilities for cid, a in self._adapters.items()}

    def list_ids(self) -> List[str]:
        """List all registered channel IDs."""
        return list(self._adapters.keys())

    @property
    def channel_count(self) -> int:
        return len(self._adapters)

    async def start_all(self) -> None:
        """Start all registered channel adapters."""
        for cid, adapter in self._adapters.items():
            try:
                await adapter.start()
                logger.info(f"Channel started: {cid}")
            except Exception as e:
                logger.error(f"Failed to start channel {cid}: {e}")

    async def stop_all(self) -> None:
        """Stop all registered channel adapters."""
        for cid, adapter in self._adapters.items():
            try:
                await adapter.stop()
                logger.debug(f"Channel stopped: {cid}")
            except Exception as e:
                logger.warning(f"Error stopping channel {cid}: {e}")
