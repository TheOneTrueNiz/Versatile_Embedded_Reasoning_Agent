"""
Tool Schema Builder
====================

Builds tool schemas for LLM requests from MCP and native tools.
Produces canonical OpenAI-format tool definitions that each
provider can then convert to their own format via normalize_tool_schemas().

This module wraps the tool schema building logic that was originally
embedded in GrokReasoningBridge._build_tool_schemas(). The heavy
keyword-matching, bias scoring, and auto-selection logic remains
in llm_bridge.py for now to avoid a risky refactor of ~1200 lines
of working code. This module provides the clean interface that
the provider system uses.

Future work: incrementally move the scoring and selection logic
from llm_bridge.py into this module.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


async def build_tool_schemas(
    vera_instance: Any,
    context: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Build tool schemas for an LLM request.

    Delegates to the bridge's existing _build_tool_schemas() method
    if available, otherwise collects tools directly from MCP + native.

    Args:
        vera_instance: The VERA runtime instance (has .mcp, ._native_tool_defs)
        context: User message context for smart tool selection

    Returns:
        Tuple of (tool_schemas, forced_tool_choice):
        - tool_schemas: List of OpenAI-format tool definitions
        - forced_tool_choice: Optional tool_choice override (e.g., force a specific tool)
    """
    if vera_instance is None:
        return [], None

    # Collect native tools
    native_tools: List[Dict[str, Any]] = []
    if hasattr(vera_instance, "_native_tool_defs"):
        native_tools = list(vera_instance._native_tool_defs)

    # Collect MCP tools
    mcp_tools: List[Dict[str, Any]] = []
    mcp = getattr(vera_instance, "mcp", None)
    if mcp and hasattr(mcp, "get_available_tool_defs"):
        available_defs = mcp.get_available_tool_defs()
        for server_name, tool_defs in available_defs.items():
            for tool_def in tool_defs:
                if isinstance(tool_def, dict) and tool_def.get("name"):
                    mcp_tools.append(_normalize_mcp_tool(tool_def))

    all_tools = native_tools + mcp_tools
    return all_tools, None


def _normalize_mcp_tool(tool_def: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an MCP tool definition to OpenAI function-calling format.

    MCP tools come in the format:
    {"name": "...", "description": "...", "inputSchema": {"type": "object", ...}}

    OpenAI expects:
    {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
    """
    params = tool_def.get("inputSchema", tool_def.get("parameters", {}))
    if not params:
        params = {"type": "object", "properties": {}}

    return {
        "type": "function",
        "function": {
            "name": tool_def["name"],
            "description": tool_def.get("description", ""),
            "parameters": params,
        },
    }


def filter_tools_by_context(
    tools: List[Dict[str, Any]],
    context: str,
    max_tools: int = 30,
) -> List[Dict[str, Any]]:
    """Simple context-based tool filtering.

    A lightweight alternative to the full router for when the bridge's
    complex bias scoring isn't needed.

    Args:
        tools: All available tool definitions
        context: User message to match against
        max_tools: Maximum number of tools to return

    Returns:
        Filtered list of relevant tools
    """
    if not context or max_tools <= 0 or len(tools) <= max_tools:
        return tools[:max_tools] if max_tools > 0 else tools

    context_lower = context.lower()

    # Score each tool by relevance to context
    scored = []
    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name", "").lower()
        desc = func.get("description", "").lower()

        score = 0.0

        # Direct name mention
        if name in context_lower:
            score += 10.0

        # Word overlap between context and tool name/description
        context_words = set(context_lower.split())
        name_words = set(name.replace("_", " ").split())
        desc_words = set(desc.split())

        name_overlap = len(context_words & name_words)
        desc_overlap = len(context_words & desc_words)
        score += name_overlap * 2.0 + desc_overlap * 0.5

        scored.append((score, tool))

    # Sort by score descending, take top N
    scored.sort(key=lambda x: x[0], reverse=True)
    return [tool for _, tool in scored[:max_tools]]
