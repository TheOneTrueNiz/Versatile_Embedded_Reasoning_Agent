"""
Discord Channel Adapter
========================

Implements the ChannelAdapter protocol for Discord using discord.py.
Handles message routing, chunking for 2000-char limit, threads,
reactions, and media.
"""

import asyncio
import logging
import os
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

from channels.types import (
    ChannelCapabilities,
    ChannelMeta,
    ChatType,
    InboundMessage,
    OutboundMessage,
)
from channels.chunking import chunk_message

logger = logging.getLogger(__name__)

# discord.py is an optional dependency
try:
    import discord
    from discord import Intents, Message
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    discord = None  # type: ignore
    Intents = None  # type: ignore
    Message = None  # type: ignore
    logger.debug("discord.py not installed - Discord adapter unavailable")


class DiscordAdapter:
    """Discord channel adapter using discord.py.

    Features:
    - DM, channel, and thread message handling
    - Automatic message chunking for 2000-char limit
    - Reaction support
    - Media/attachment support
    - Typing indicator during processing
    - Configurable guild and user allowlists
    """

    channel_id = "discord"
    capabilities = ChannelCapabilities(
        chat_types=[ChatType.DIRECT, ChatType.CHANNEL, ChatType.THREAD],
        reactions=True,
        threads=True,
        media=True,
        native_commands=True,
        text_chunk_limit=2000,
    )
    meta = ChannelMeta(
        id="discord",
        label="Discord",
        blurb="Discord bot via discord.py",
        order=10,
    )

    def __init__(
        self,
        token: Optional[str] = None,
        allowed_guilds: Optional[List[str]] = None,
        allowed_users: Optional[List[str]] = None,
        command_prefix: str = "!",
    ):
        if not DISCORD_AVAILABLE:
            raise ImportError(
                "discord.py is required for Discord adapter. "
                "Install with: pip install discord.py>=2.3"
            )

        self._token = token or os.getenv("DISCORD_BOT_TOKEN", "")
        if not self._token:
            raise ValueError(
                "Discord bot token required. Set DISCORD_BOT_TOKEN env var "
                "or pass token parameter."
            )

        self._allowed_guilds = set(allowed_guilds or [])
        self._allowed_users = set(allowed_users or [])
        self._command_prefix = command_prefix
        self._handler: Optional[Callable] = None
        self._client: Optional[discord.Client] = None
        self._task: Optional[asyncio.Task] = None
        self.running = False

    async def start(self) -> None:
        """Start the Discord bot in a background task."""
        intents = Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.dm_messages = True

        self._client = discord.Client(intents=intents)
        self._setup_handlers()

        self._task = asyncio.create_task(
            self._client.start(self._token),
            name="discord-adapter",
        )
        self.running = True
        logger.info("Discord adapter starting...")

    async def stop(self) -> None:
        """Stop the Discord bot."""
        if self._client:
            await self._client.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.running = False
        logger.info("Discord adapter stopped")

    async def send(self, message: OutboundMessage) -> Dict[str, Any]:
        """Send a message to a Discord channel/user.

        The target_id in OutboundMessage should be a Discord channel ID.
        Messages are automatically chunked for the 2000-char limit.
        """
        if not self._client:
            return {"error": "Discord client not connected"}

        try:
            channel = self._client.get_channel(int(message.target_id))
            if channel is None:
                # Try fetching if not in cache
                channel = await self._client.fetch_channel(int(message.target_id))

            chunks = chunk_message(message.text, limit=2000)
            sent_ids = []

            for chunk in chunks:
                sent = await channel.send(chunk)
                sent_ids.append(str(sent.id))

            return {
                "status": "ok",
                "message_ids": sent_ids,
                "chunk_count": len(chunks),
            }

        except Exception as e:
            logger.error(f"Discord send failed: {e}")
            return {"error": str(e)}

    def set_message_handler(
        self,
        handler: Callable[
            [InboundMessage],
            Union[None, Coroutine[Any, Any, None]],
        ],
    ) -> None:
        """Set the callback for incoming Discord messages."""
        self._handler = handler

    def _setup_handlers(self) -> None:
        """Register Discord event handlers."""

        @self._client.event
        async def on_ready():
            logger.info(
                f"Discord connected as {self._client.user} "
                f"(guilds: {len(self._client.guilds)})"
            )

        @self._client.event
        async def on_message(message: Message):
            await self._handle_message(message)

    async def _handle_message(self, message: Message) -> None:
        """Process an incoming Discord message."""
        # Ignore own messages
        if message.author == self._client.user:
            return

        # Ignore bots
        if message.author.bot:
            return

        # Guild allowlist check
        if self._allowed_guilds and message.guild:
            if str(message.guild.id) not in self._allowed_guilds:
                return

        # User allowlist check
        if self._allowed_users:
            if str(message.author.id) not in self._allowed_users:
                return

        # Determine chat type
        if isinstance(message.channel, discord.DMChannel):
            chat_type = ChatType.DIRECT
        elif isinstance(message.channel, discord.Thread):
            chat_type = ChatType.THREAD
        else:
            chat_type = ChatType.CHANNEL

        # In guild channels, only respond if mentioned or using command prefix
        if message.guild and chat_type != ChatType.THREAD:
            mentioned = self._client.user in message.mentions
            has_prefix = message.content.startswith(self._command_prefix)
            if not mentioned and not has_prefix:
                return

        # Strip mention from message text
        text = message.content
        if self._client.user:
            text = text.replace(f"<@{self._client.user.id}>", "").strip()
            text = text.replace(f"<@!{self._client.user.id}>", "").strip()
        if text.startswith(self._command_prefix):
            text = text[len(self._command_prefix):].strip()

        # Extract media URLs
        media_urls = [att.url for att in message.attachments]

        # Build normalized inbound message
        inbound = InboundMessage(
            text=text,
            sender_id=str(message.author.id),
            sender_name=message.author.display_name,
            channel_id=str(message.channel.id),
            chat_type=chat_type,
            guild_id=str(message.guild.id) if message.guild else None,
            thread_id=str(message.channel.id) if chat_type == ChatType.THREAD else None,
            reply_to_id=str(message.reference.message_id) if message.reference else None,
            media_urls=media_urls,
            raw={"discord_message": message},
            timestamp=message.created_at.timestamp(),
        )

        # Call handler with typing indicator
        if self._handler:
            async with message.channel.typing():
                try:
                    result = self._handler(inbound)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"Message handler error: {e}")
                    try:
                        await message.channel.send(
                            f"I encountered an error processing that. ({type(e).__name__})"
                        )
                    except Exception:
                        logger.debug("Suppressed Exception in adapter")
                        pass
