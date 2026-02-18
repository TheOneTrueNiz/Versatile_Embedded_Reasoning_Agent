"""
Message Chunking
=================

Splits long messages into chunks that respect channel limits
while preserving Markdown formatting (code blocks, etc.).

Ported from Moltbot's Discord message chunking pattern.
"""

from typing import List


def chunk_message(text: str, limit: int = 2000) -> List[str]:
    """Split a long message into chunks respecting code block boundaries.

    Rules:
    1. Never split inside a code block (```)
    2. Prefer splitting at paragraph boundaries (double newline)
    3. Fall back to line boundaries
    4. Last resort: hard split at limit

    Args:
        text: The full message text
        limit: Maximum characters per chunk

    Returns:
        List of message chunks, each within the limit
    """
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Find a good split point within the limit
        split_at = _find_split_point(remaining, limit)
        chunk = remaining[:split_at].rstrip()
        remaining = remaining[split_at:].lstrip("\n")

        # Handle unclosed code blocks
        if chunk.count("```") % 2 != 0:
            # Code block is split - close it in this chunk, reopen in next
            chunk += "\n```"
            remaining = "```\n" + remaining

        if chunk:
            chunks.append(chunk)

    return chunks if chunks else [text[:limit]]


def _find_split_point(text: str, limit: int) -> int:
    """Find the best split point within the limit.

    Priority: paragraph break > line break > space > hard limit.
    Avoids splitting inside code blocks.
    """
    # Check if we're inside a code block at the limit
    prefix = text[:limit]
    in_code_block = prefix.count("```") % 2 != 0

    if in_code_block:
        # Try to find the start of this code block and split before it
        last_fence = prefix.rfind("```")
        if last_fence > 0:
            # Split before the code block start
            line_before = prefix.rfind("\n", 0, last_fence)
            if line_before > limit // 4:  # Don't split too early
                return line_before

    # Try paragraph break (double newline)
    para_break = prefix.rfind("\n\n")
    if para_break > limit // 3:
        return para_break

    # Try line break
    line_break = prefix.rfind("\n")
    if line_break > limit // 3:
        return line_break

    # Try space
    space = prefix.rfind(" ")
    if space > limit // 2:
        return space

    # Hard split at limit
    return limit
