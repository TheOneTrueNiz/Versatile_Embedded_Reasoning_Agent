"""
Discord Formatting
===================

Discord-specific message formatting utilities.
Handles embeds, code blocks, mention stripping, etc.
"""

import re
from typing import Any, Dict, List, Optional


def strip_mentions(text: str) -> str:
    """Remove Discord mention patterns from text."""
    # User mentions: <@123456> or <@!123456>
    text = re.sub(r"<@!?\d+>", "", text)
    # Role mentions: <@&123456>
    text = re.sub(r"<@&\d+>", "", text)
    # Channel mentions: <#123456>
    text = re.sub(r"<#\d+>", "", text)
    return text.strip()


def build_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: int = 0x5865F2,  # Discord blurple
    fields: Optional[List[Dict[str, Any]]] = None,
    footer: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    image_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Discord embed dict.

    Can be passed to discord.py's Embed.from_dict() or sent raw.
    """
    embed: Dict[str, Any] = {"color": color}

    if title:
        embed["title"] = title[:256]
    if description:
        embed["description"] = description[:4096]
    if fields:
        embed["fields"] = [
            {
                "name": f.get("name", "")[:256],
                "value": f.get("value", "")[:1024],
                "inline": f.get("inline", False),
            }
            for f in fields[:25]
        ]
    if footer:
        embed["footer"] = {"text": footer[:2048]}
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}
    if image_url:
        embed["image"] = {"url": image_url}

    return embed


def escape_markdown(text: str) -> str:
    """Escape Discord markdown characters."""
    chars = ["\\", "*", "_", "~", "`", "|", ">"]
    for char in chars:
        text = text.replace(char, f"\\{char}")
    return text


def format_code_block(code: str, language: str = "") -> str:
    """Wrap code in a Discord code block."""
    return f"```{language}\n{code}\n```"
