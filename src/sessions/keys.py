"""
Session Key Derivation
=======================

Derives unique session keys from channel, sender, and scope information.
Ported from Moltbot's session-key.ts pattern.

Key format: "channel:identifier"
Examples:
    "discord:123456789"        - Discord user DM
    "discord:group:987654321"  - Discord guild channel
    "api:default"              - HTTP API session
    "global"                   - Global session
"""

import re
from typing import Optional

from sessions.types import SessionScope

_LINK_SAFE_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


def derive_session_key(
    channel_id: str,
    sender_id: str,
    scope: SessionScope = SessionScope.PER_SENDER,
    group_id: Optional[str] = None,
) -> str:
    """Build a session key from channel and sender context.

    Args:
        channel_id: Channel type ("discord", "api", "telegram", etc.)
        sender_id: Unique sender identifier within the channel
        scope: How conversations are grouped
        group_id: Group/guild/channel ID for group scoping

    Returns:
        Session key string
    """
    if scope == SessionScope.GLOBAL:
        return "global"

    if scope == SessionScope.PER_CHANNEL:
        if group_id:
            return f"{channel_id}:group:{group_id}"
        return f"{channel_id}:channel:{sender_id}"

    # PER_SENDER (default)
    if group_id:
        return f"{channel_id}:{sender_id}@{group_id}"
    return f"{channel_id}:{sender_id}"


def normalize_link_id(raw_link_id: Optional[str]) -> str:
    """Normalize a cross-channel link identifier.

    Keeps ids filesystem and prompt safe while preserving readability.
    """
    value = str(raw_link_id or "").strip()
    if not value:
        return ""
    normalized = _LINK_SAFE_PATTERN.sub("_", value).strip("._-")
    return normalized.lower()


def derive_link_session_key(raw_link_id: Optional[str]) -> str:
    """Build a canonical session key for explicit cross-channel linking."""
    link_id = normalize_link_id(raw_link_id)
    if not link_id:
        return ""
    return f"link:{link_id}"


def parse_session_key(key: str) -> dict:
    """Parse a session key back into its components.

    Returns:
        Dict with 'channel_id', 'sender_id', 'group_id', 'scope'
    """
    if key == "global":
        return {
            "channel_id": "global",
            "sender_id": "global",
            "group_id": None,
            "scope": SessionScope.GLOBAL,
        }

    parts = key.split(":", 1)
    if len(parts) < 2:
        return {
            "channel_id": key,
            "sender_id": "unknown",
            "group_id": None,
            "scope": SessionScope.PER_SENDER,
        }

    channel_id = parts[0]
    remainder = parts[1]

    # Check for group key: "discord:group:123"
    if remainder.startswith("group:"):
        group_id = remainder[6:]
        return {
            "channel_id": channel_id,
            "sender_id": "group",
            "group_id": group_id,
            "scope": SessionScope.PER_CHANNEL,
        }

    # Check for sender@group: "discord:user123@guild456"
    if "@" in remainder:
        sender_id, group_id = remainder.split("@", 1)
        return {
            "channel_id": channel_id,
            "sender_id": sender_id,
            "group_id": group_id,
            "scope": SessionScope.PER_SENDER,
        }

    # Simple per-sender: "discord:user123"
    return {
        "channel_id": channel_id,
        "sender_id": remainder,
        "group_id": None,
        "scope": SessionScope.PER_SENDER,
    }
