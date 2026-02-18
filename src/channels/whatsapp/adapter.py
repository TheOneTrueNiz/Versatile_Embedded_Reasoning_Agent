"""
WhatsApp Channel Adapter
========================

Implements the ChannelAdapter protocol for WhatsApp Cloud API (Meta).
Supports outbound text messages and inbound webhook handling.
"""

import asyncio
import hashlib
import hmac
import logging
import os
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

import httpx

from channels.chunking import chunk_message
from channels.types import (
    ChannelCapabilities,
    ChannelMeta,
    ChatType,
    InboundMessage,
    OutboundMessage,
)

logger = logging.getLogger(__name__)


class WhatsAppAdapter:
    """WhatsApp Cloud API adapter.

    Uses Meta's Cloud API for outbound messages and webhook payloads for inbound.
    """

    channel_id = "whatsapp"
    capabilities = ChannelCapabilities(
        chat_types=[ChatType.DIRECT],
        reactions=False,
        threads=False,
        media=True,
        native_commands=False,
        text_chunk_limit=4096,
    )
    meta = ChannelMeta(
        id="whatsapp",
        label="WhatsApp",
        blurb="WhatsApp Cloud API (Meta)",
        order=30,
    )

    def __init__(
        self,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        verify_token: Optional[str] = None,
        app_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        graph_version: Optional[str] = None,
        allowed_numbers: Optional[List[str]] = None,
    ) -> None:
        self._access_token = (
            access_token
            or os.getenv("WHATSAPP_ACCESS_TOKEN")
            or os.getenv("WHATSAPP_TOKEN")
            or ""
        )
        if not self._access_token:
            raise ValueError(
                "WhatsApp access token required. Set WHATSAPP_ACCESS_TOKEN env var or pass access_token."
            )

        self._phone_number_id = (
            phone_number_id
            or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
            or os.getenv("WHATSAPP_PHONE_ID")
            or ""
        )
        if not self._phone_number_id:
            raise ValueError(
                "WhatsApp phone_number_id required. Set WHATSAPP_PHONE_NUMBER_ID env var or pass phone_number_id."
            )

        self._verify_token = verify_token or os.getenv("WHATSAPP_VERIFY_TOKEN") or ""
        self._app_secret = app_secret or os.getenv("WHATSAPP_APP_SECRET") or ""

        version = (graph_version or os.getenv("WHATSAPP_GRAPH_VERSION") or "v20.0").strip()
        default_base = f"https://graph.facebook.com/{version}"
        self._base_url = (base_url or os.getenv("WHATSAPP_BASE_URL") or default_base).rstrip("/")

        self._allowed_numbers = {str(n) for n in (allowed_numbers or [])}
        self._handler: Optional[Callable] = None
        self._client = httpx.AsyncClient(timeout=30.0)
        self.running = False

    async def start(self) -> None:
        """No-op for webhooks; marks adapter as running."""
        self.running = True
        logger.info("WhatsApp adapter ready")

    async def stop(self) -> None:
        """Close HTTP client."""
        await self._client.aclose()
        self.running = False
        logger.info("WhatsApp adapter stopped")

    def set_message_handler(
        self,
        handler: Callable[
            [InboundMessage],
            Union[None, Coroutine[Any, Any, None]],
        ],
    ) -> None:
        self._handler = handler

    def verify_webhook(self, token: str) -> bool:
        if not self._verify_token:
            return False
        return token == self._verify_token

    def _verify_signature(self, raw_body: bytes, signature: str) -> bool:
        if not self._app_secret:
            return True
        if not signature or not signature.startswith("sha256="):
            return False
        digest = hmac.new(
            self._app_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        expected = f"sha256={digest}"
        return hmac.compare_digest(signature, expected)

    async def handle_webhook(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        raw_body: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """Handle inbound webhook payloads."""
        if headers and raw_body is not None:
            signature = headers.get("X-Hub-Signature-256") or headers.get("x-hub-signature-256") or ""
            if not self._verify_signature(raw_body, signature):
                logger.warning("WhatsApp webhook signature mismatch")
                return {"ok": False, "error": "invalid_signature"}

        delivered = 0
        ignored = 0

        for entry in payload.get("entry", []) or []:
            changes = entry.get("changes", []) or []
            for change in changes:
                value = change.get("value", {}) or {}
                messages = value.get("messages", []) or []
                contacts = value.get("contacts", []) or []
                contact_map = {
                    str(c.get("wa_id")): c for c in contacts if isinstance(c, dict)
                }

                for message in messages:
                    inbound = self._convert_message(message, value, contact_map)
                    if inbound is None:
                        ignored += 1
                        continue

                    if self._allowed_numbers and inbound.sender_id not in self._allowed_numbers:
                        ignored += 1
                        continue

                    delivered += 1
                    if self._handler:
                        try:
                            result = self._handler(inbound)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as exc:
                            logger.error("WhatsApp handler error: %s", exc)
                            ignored += 1

        return {"ok": True, "delivered": delivered, "ignored": ignored}

    def _convert_message(
        self,
        message: Dict[str, Any],
        value: Dict[str, Any],
        contact_map: Dict[str, Dict[str, Any]],
    ) -> Optional[InboundMessage]:
        if not isinstance(message, dict):
            return None

        msg_type = (message.get("type") or "").lower()
        sender_id = str(message.get("from") or "")
        if not sender_id:
            return None

        text = ""
        if msg_type == "text":
            text = message.get("text", {}).get("body", "") or ""
        elif msg_type == "interactive":
            interactive = message.get("interactive", {}) or {}
            text = (
                interactive.get("button_reply", {}).get("title")
                or interactive.get("list_reply", {}).get("title")
                or ""
            )
        elif msg_type == "button":
            text = message.get("button", {}).get("text", "") or ""
        else:
            caption = ""
            if msg_type in message and isinstance(message.get(msg_type), dict):
                caption = message.get(msg_type, {}).get("caption", "") or ""
            text = caption or f"[whatsapp:{msg_type}]"

        contact = contact_map.get(sender_id, {})
        profile = contact.get("profile", {}) if isinstance(contact, dict) else {}
        sender_name = profile.get("name") if isinstance(profile, dict) else None

        timestamp = message.get("timestamp")
        ts_value: Optional[float] = None
        if timestamp:
            try:
                ts_value = float(timestamp)
            except (ValueError, TypeError):
                ts_value = None

        reply_to_id = None
        context = message.get("context", {}) or {}
        if isinstance(context, dict):
            reply_to_id = context.get("id")

        media_urls: List[str] = []
        if msg_type in {"image", "video", "audio", "document", "sticker"}:
            media_id = message.get(msg_type, {}).get("id")
            if media_id:
                media_urls.append(f"whatsapp:{msg_type}:{media_id}")

        return InboundMessage(
            text=text.strip(),
            sender_id=sender_id,
            sender_name=sender_name,
            channel_id=sender_id,
            chat_type=ChatType.DIRECT,
            reply_to_id=str(reply_to_id) if reply_to_id else None,
            media_urls=media_urls,
            raw={"whatsapp_message": message, "whatsapp_value": value},
            timestamp=ts_value,
        )

    async def send(self, message: OutboundMessage) -> Dict[str, Any]:
        """Send a WhatsApp message via Cloud API."""
        url = f"{self._base_url}/{self._phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        chunks = chunk_message(message.text, limit=self.capabilities.text_chunk_limit)
        message_ids: List[str] = []

        for chunk in chunks:
            payload = {
                "messaging_product": "whatsapp",
                "to": message.target_id,
                "type": "text",
                "text": {"body": chunk},
            }
            response = await self._client.post(url, headers=headers, json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = response.text.strip()
                return {"status": "error", "error": detail, "code": response.status_code}

            data = response.json()
            message_id = ""
            messages = data.get("messages") if isinstance(data, dict) else None
            if isinstance(messages, list) and messages:
                message_id = messages[0].get("id", "") or ""
            if message_id:
                message_ids.append(message_id)

        return {"status": "ok", "message_ids": message_ids, "chunk_count": len(chunks)}
