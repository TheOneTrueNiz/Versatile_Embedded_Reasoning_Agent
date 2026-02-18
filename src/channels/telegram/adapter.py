"""
Telegram Channel Adapter
========================

Implements the ChannelAdapter protocol for Telegram using python-telegram-bot.
Handles polling, group/direct messaging, and basic media capture.
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

try:
    from telegram import Update
    from telegram.constants import ChatAction
    from telegram.ext import Application, ChannelPostHandler, ContextTypes, MessageHandler, filters
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Update = None  # type: ignore
    ChatAction = None  # type: ignore
    Application = None  # type: ignore
    ChannelPostHandler = None  # type: ignore
    ContextTypes = None  # type: ignore
    MessageHandler = None  # type: ignore
    filters = None  # type: ignore
    logger.debug("python-telegram-bot not installed - Telegram adapter unavailable")


class TelegramAdapter:
    """Telegram channel adapter using python-telegram-bot.

    Features:
    - Direct, group, and channel message handling
    - Basic media capture (file ids)
    - Typing indicator during processing
    - Configurable chat/user allowlists
    """

    channel_id = "telegram"
    capabilities = ChannelCapabilities(
        chat_types=[ChatType.DIRECT, ChatType.GROUP, ChatType.CHANNEL],
        reactions=False,
        threads=False,
        media=True,
        native_commands=True,
        text_chunk_limit=4096,
    )
    meta = ChannelMeta(
        id="telegram",
        label="Telegram",
        blurb="Telegram bot via python-telegram-bot",
        order=20,
    )

    def __init__(
        self,
        token: Optional[str] = None,
        allowed_chats: Optional[List[str]] = None,
        allowed_users: Optional[List[str]] = None,
        command_prefix: str = "/",
    ) -> None:
        if not TELEGRAM_AVAILABLE:
            raise ImportError(
                "python-telegram-bot is required for Telegram adapter. "
                "Install with: pip install python-telegram-bot>=20"
            )

        self._token = token or os.getenv("TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_TOKEN", "")
        if not self._token:
            raise ValueError(
                "Telegram bot token required. Set TELEGRAM_BOT_TOKEN env var "
                "or pass token parameter."
            )

        self._allowed_chats = {str(cid) for cid in (allowed_chats or [])}
        self._allowed_users = {str(uid) for uid in (allowed_users or [])}
        self._command_prefix = command_prefix or "/"
        self._handler: Optional[Callable] = None
        self._application: Optional[Application] = None
        self._bot_username: Optional[str] = None
        self.running = False

    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        self._application = Application.builder().token(self._token).build()
        self._application.add_handler(MessageHandler(filters.ALL, self._on_message))
        self._application.add_handler(ChannelPostHandler(self._on_channel_post))

        await self._application.initialize()
        await self._application.start()
        if self._application.updater:
            await self._application.updater.start_polling()
        else:
            logger.warning("Telegram updater unavailable; polling not started")

        try:
            me = await self._application.bot.get_me()
            self._bot_username = me.username
        except Exception as exc:
            logger.warning("Failed to resolve Telegram bot username: %s", exc)

        self.running = True
        logger.info("Telegram adapter started")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if not self._application:
            return
        if self._application.updater:
            await self._application.updater.stop()
        await self._application.stop()
        await self._application.shutdown()
        self.running = False
        logger.info("Telegram adapter stopped")

    async def send(self, message: OutboundMessage) -> Dict[str, Any]:
        """Send a message to a Telegram chat."""
        if not self._application:
            return {"error": "Telegram client not connected"}

        chat_id: Union[str, int] = message.target_id
        if isinstance(chat_id, str) and chat_id.lstrip("-").isdigit():
            chat_id = int(chat_id)

        chunks = chunk_message(message.text, limit=4096)
        sent_ids: List[str] = []

        for chunk in chunks:
            sent = await self._application.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                message_thread_id=message.thread_id,
                reply_to_message_id=message.reply_to_id,
            )
            sent_ids.append(str(sent.message_id))

        return {
            "status": "ok",
            "message_ids": sent_ids,
            "chunk_count": len(chunks),
        }

    def set_message_handler(
        self,
        handler: Callable[
            [InboundMessage],
            Union[None, Coroutine[Any, Any, None]],
        ],
    ) -> None:
        """Set the callback for incoming Telegram messages."""
        self._handler = handler

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if not message:
            return
        await self._handle_message(message, context)

    async def _on_channel_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.channel_post
        if not message:
            return
        await self._handle_message(message, context, force_channel=True)

    async def _handle_message(self, message, context, force_channel: bool = False) -> None:
        if getattr(message.from_user, "is_bot", False):
            return

        chat_id = str(message.chat.id)
        if self._allowed_chats and chat_id not in self._allowed_chats:
            return

        sender_id = str(message.from_user.id) if message.from_user else "channel"
        if self._allowed_users and sender_id not in self._allowed_users:
            return

        chat_type = self._map_chat_type(message.chat.type, force_channel)
        text = message.text or message.caption or ""

        if chat_type == ChatType.GROUP and not self._is_addressed(message, text):
            return

        text = self._strip_bot_mentions(text)
        text = self._strip_command_prefix(text)

        media_urls = self._collect_media(message)

        inbound = InboundMessage(
            text=text.strip(),
            sender_id=sender_id,
            sender_name=self._resolve_sender_name(message),
            channel_id=chat_id,
            chat_type=chat_type,
            thread_id=str(getattr(message, "message_thread_id", "") or "") or None,
            reply_to_id=str(message.reply_to_message.message_id) if message.reply_to_message else None,
            media_urls=media_urls,
            raw={"telegram_message": message},
            timestamp=message.date.timestamp() if message.date else None,
        )

        if self._handler:
            try:
                await context.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
            except Exception:
                logger.debug("Suppressed Exception in adapter")
                pass
            try:
                result = self._handler(inbound)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error("Telegram handler error: %s", exc)
                try:
                    await context.bot.send_message(
                        chat_id=message.chat.id,
                        text=f"I encountered an error processing that. ({type(exc).__name__})",
                        reply_to_message_id=message.message_id,
                    )
                except Exception:
                    logger.debug("Suppressed Exception in adapter")
                    pass

    def _map_chat_type(self, chat_type: str, force_channel: bool) -> ChatType:
        if force_channel:
            return ChatType.CHANNEL
        if chat_type == "private":
            return ChatType.DIRECT
        if chat_type in ("group", "supergroup"):
            return ChatType.GROUP
        if chat_type == "channel":
            return ChatType.CHANNEL
        return ChatType.DIRECT

    def _is_addressed(self, message, text: str) -> bool:
        if text.startswith(self._command_prefix):
            return True
        if self._bot_username and f"@{self._bot_username.lower()}" in text.lower():
            return True
        entities = message.entities or []
        for entity in entities:
            if entity.type == "bot_command":
                return True
            if entity.type == "mention" and self._bot_username:
                mention_text = text[entity.offset: entity.offset + entity.length]
                if mention_text.lower() == f"@{self._bot_username.lower()}":
                    return True
        return False

    def _strip_bot_mentions(self, text: str) -> str:
        if not self._bot_username:
            return text
        return text.replace(f"@{self._bot_username}", "").replace(f"@{self._bot_username.lower()}", "")

    def _strip_command_prefix(self, text: str) -> str:
        if not text.startswith(self._command_prefix):
            return text
        stripped = text[len(self._command_prefix):].strip()
        if not stripped:
            return text
        command, *rest = stripped.split(maxsplit=1)
        if "@" in command:
            command = command.split("@", 1)[0]
        return rest[0] if rest else command

    @staticmethod
    def _resolve_sender_name(message) -> Optional[str]:
        if not message.from_user:
            return None
        if message.from_user.full_name:
            return message.from_user.full_name
        return message.from_user.username

    @staticmethod
    def _collect_media(message) -> List[str]:
        media: List[str] = []

        def add(kind: str, file_id: Optional[str]) -> None:
            if file_id:
                media.append(f"telegram:{kind}:{file_id}")

        if getattr(message, "photo", None):
            photo = message.photo[-1]
            add("photo", getattr(photo, "file_id", None))
        add("document", getattr(getattr(message, "document", None), "file_id", None))
        add("video", getattr(getattr(message, "video", None), "file_id", None))
        add("audio", getattr(getattr(message, "audio", None), "file_id", None))
        add("voice", getattr(getattr(message, "voice", None), "file_id", None))
        add("sticker", getattr(getattr(message, "sticker", None), "file_id", None))

        return media
