"""
JSONL Transcript Reader/Writer
================================

Persists conversation transcripts as JSONL (JSON Lines) files.
Each line is a JSON object representing one message turn.
Uses atomic writes for crash safety.

Ported from Moltbot's session transcript pattern.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def append_to_transcript(
    path: Path,
    entry: Dict[str, Any],
) -> None:
    """Append a single JSONL entry to a transcript file.

    Uses atomic append (open in append mode). For full crash safety,
    use write-to-temp-then-rename for critical operations.

    Args:
        path: Path to the .jsonl transcript file
        entry: Dict to serialize as a single JSON line
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        logger.error(f"Failed to append to transcript {path}: {e}")
        raise


def read_transcript(
    path: Path,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Read entries from a JSONL transcript file.

    Args:
        path: Path to the .jsonl transcript file
        limit: Maximum number of entries to return (from the end)
        offset: Skip this many entries from the start

    Returns:
        List of parsed JSON entries
    """
    if not path.exists():
        return []

    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.debug(f"Skipping malformed JSONL line {i} in {path}")
                    continue
    except OSError as e:
        logger.error(f"Failed to read transcript {path}: {e}")
        return []

    # If limit specified, return only the last N entries
    if limit and len(entries) > limit:
        entries = entries[-limit:]

    return entries


def build_transcript_entry(
    role: str,
    content: str,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    tool_call_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    provider_id: Optional[str] = None,
    model: Optional[str] = None,
    usage: Optional[Dict[str, int]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a transcript entry dict.

    Args:
        role: Message role ("user", "assistant", "tool", "system")
        content: Message content text
        tool_calls: Tool calls made (for assistant messages)
        tool_call_id: ID of the tool call this result is for
        tool_name: Name of the tool
        provider_id: Which LLM provider generated this
        model: Model identifier
        usage: Token usage stats
        **extra: Additional metadata

    Returns:
        Dict suitable for JSONL serialization
    """
    entry: Dict[str, Any] = {
        "role": role,
        "content": content,
        "timestamp": time.time(),
    }

    if tool_calls:
        entry["tool_calls"] = tool_calls
    if tool_call_id:
        entry["tool_call_id"] = tool_call_id
    if tool_name:
        entry["name"] = tool_name
    if provider_id:
        entry["provider_id"] = provider_id
    if model:
        entry["model"] = model
    if usage:
        entry["usage"] = usage
    if extra:
        entry["metadata"] = extra

    return entry


def transcript_to_messages(
    entries: List[Dict[str, Any]],
    max_messages: int = 50,
) -> List[Dict[str, Any]]:
    """Convert transcript entries to OpenAI-format messages.

    Strips metadata fields and returns only the message-relevant
    fields that can be sent to an LLM.

    Args:
        entries: Transcript entries from read_transcript()
        max_messages: Maximum messages to return (from the end)

    Returns:
        List of OpenAI-format message dicts
    """
    messages = []
    for entry in entries:
        msg: Dict[str, Any] = {
            "role": entry.get("role", "user"),
            "content": entry.get("content", ""),
        }

        # Include tool call fields if present
        if entry.get("tool_calls"):
            msg["tool_calls"] = entry["tool_calls"]
        if entry.get("tool_call_id"):
            msg["tool_call_id"] = entry["tool_call_id"]
        if entry.get("name"):
            msg["name"] = entry["name"]

        messages.append(msg)

    if len(messages) > max_messages:
        messages = messages[-max_messages:]

    return messages
