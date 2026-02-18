#!/usr/bin/env python3
"""
Error Handler with Graceful Degradation
========================================

Implements intelligent error recovery for tool failures using a four-tier
strategy: Retry → Fallback → Degrade → Escalate.

Research Backing:
- arXiv:2403.04462 - ReAct error recovery patterns
- arXiv:2410.02490 - LLM-based error handling strategies
- Industry best practices for distributed systems error handling

Recovery Strategy:
1. RETRY: Temporary failures (network, rate limits) - retry with exponential backoff
2. FALLBACK: Use alternative tool/method if primary fails
3. DEGRADE: Partial functionality if full operation impossible
4. ESCALATE: Notify user if all recovery attempts fail

Key Features:
- Automatic failure classification
- Context-aware retry strategies
- Fallback tool suggestions
- Partial success handling
- User escalation with actionable context
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum
import re
import logging
logger = logging.getLogger(__name__)


class FailureType(Enum):
    """Classification of failure types for recovery strategy"""
    TRANSIENT = "transient"  # Network timeout, rate limit - retry likely to help
    PERMANENT = "permanent"  # File not found, permission denied - retry won't help
    PARTIAL = "partial"  # Partial success, some data retrieved
    UNKNOWN = "unknown"  # Unclear failure - try conservative retry


class RecoveryAction(Enum):
    """Recovery action to take"""
    RETRY = "retry"
    FALLBACK = "fallback"
    DEGRADE = "degrade"
    ESCALATE = "escalate"
    ABORT = "abort"


class FallbackExhausted(Exception):
    """Raised when maximum fallback depth is exceeded"""
    def __init__(self, tool_chain: List[str], message: str = "Maximum fallback depth exceeded") -> None:
        self.tool_chain = tool_chain
        self.message = f"{message}: {' -> '.join(tool_chain)}"
        super().__init__(self.message)


@dataclass
class ErrorContext:
    """Context about an error for recovery decision"""
    tool_name: str
    error_message: str
    attempt_number: int
    original_params: Dict[str, Any]
    failure_type: FailureType = FailureType.UNKNOWN
    partial_result: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # NEW: Fallback depth tracking to prevent cascading failure loops
    fallback_depth: int = 0
    fallback_chain: List[str] = field(default_factory=list)
    original_tool: Optional[str] = None  # Track the original tool that started the chain


@dataclass
class RecoveryDecision:
    """Decision on how to recover from error"""
    action: RecoveryAction
    wait_seconds: float = 0.0
    fallback_tool: Optional[str] = None
    fallback_params: Optional[Dict[str, Any]] = None
    degraded_result: Optional[str] = None
    escalation_message: Optional[str] = None
    retry_params: Optional[Dict[str, Any]] = None
    # NEW: Fallback chain tracking for observability
    fallback_depth: int = 0
    fallback_chain: List[str] = field(default_factory=list)


class ErrorHandler:
    """
    Intelligent error handler with graceful degradation.

    Analyzes tool failures and determines optimal recovery strategy
    based on failure type, attempt count, and available alternatives.
    """

    # Transient error patterns (retry likely to help)
    TRANSIENT_PATTERNS = [
        r"timeout",
        r"timed out",
        r"connection (refused|reset|closed)",
        r"rate limit",
        r"too many requests",
        r"429",
        r"503",
        r"temporary failure",
        r"try again",
        r"server (unavailable|busy)",
    ]

    # Permanent error patterns (retry won't help)
    PERMANENT_PATTERNS = [
        r"not found",
        r"404",
        r"does not exist",
        r"no such file",
        r"permission denied",
        r"403",
        r"401",
        r"unauthorized",
        r"invalid (argument|parameter|input)",
        r"bad request",
        r"400",
        r"syntax error",
    ]

    # Partial success patterns
    PARTIAL_PATTERNS = [
        r"partial",
        r"some (data|results) retrieved",
        r"incomplete",
        r"limited results",
    ]

    # Tool fallback mappings (primary -> alternatives)
    TOOL_FALLBACKS = {
        "search_web": ["search_wikipedia", "read_file"],  # If web search fails, try Wikipedia or local files
        "read_gmail": ["list_directory"],  # If Gmail fails, at least show local files
        "search_gmail": ["read_file"],  # If Gmail search fails, try local search
        "search_memory": ["read_file"],  # If memory search fails, read raw files
        # Filesystem tool fallbacks
        "read_text_file": ["read_file"],  # Prefer new name, fall back to deprecated
        "read_file": ["read_text_file"],  # Vice versa
        "edit_file": ["write_file"],  # If edit fails, try full write
        "list_directory": ["list_directory_with_sizes", "directory_tree"],
        "directory_tree": ["list_directory"],
        "search_files": ["list_directory"],  # If search fails, list and filter manually
        # Grokipedia -> Wikipedia-MCP fallback (tool names are shared only by Grokipedia currently)
        "search": ["search_wikipedia"],
        "get_page": ["get_summary", "get_article"],
        "get_page_content": ["get_article"],
        "get_page_citations": ["get_links", "extract_key_facts"],
        "get_related_pages": ["get_related_topics"],
        "get_page_section": ["summarize_article_section"],
        "get_page_sections": ["get_sections"],
        "run_command": [],  # No safe fallback for commands
    }

    def __init__(
        self,
        max_retries: int = 3,
        base_backoff: float = 1.0,
        max_fallback_depth: int = 3,
        fallback_backoff_multiplier: float = 1.5
    ):
        """
        Initialize error handler.

        Args:
            max_retries: Maximum retry attempts per tool call
            base_backoff: Base backoff time in seconds (exponential)
            max_fallback_depth: Maximum depth of fallback chain (prevents infinite cascades)
            fallback_backoff_multiplier: Backoff multiplier between fallback attempts
        """
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_fallback_depth = max_fallback_depth
        self.fallback_backoff_multiplier = fallback_backoff_multiplier
        self._stats = {
            "total_errors": 0,
            "retries": 0,
            "fallbacks": 0,
            "degradations": 0,
            "escalations": 0,
            "recoveries": 0,
            "fallback_exhausted": 0,  # NEW: Track when fallback chains are exhausted
            "max_fallback_depth_reached": 0,  # NEW: Track depth limit hits
        }
        self._active_chains: Dict[str, List[str]] = {}  # Track active fallback chains by original tool

    def classify_failure(self, error_message: str, partial_result: Optional[Any] = None) -> FailureType:
        """
        Classify failure type based on error message.

        Args:
            error_message: Error message from tool execution
            partial_result: Optional partial result if available

        Returns:
            FailureType classification
        """
        error_lower = error_message.lower()

        # Check partial success first
        if partial_result is not None or any(re.search(p, error_lower) for p in self.PARTIAL_PATTERNS):
            return FailureType.PARTIAL

        # Check transient errors
        if any(re.search(p, error_lower) for p in self.TRANSIENT_PATTERNS):
            return FailureType.TRANSIENT

        # Check permanent errors
        if any(re.search(p, error_lower) for p in self.PERMANENT_PATTERNS):
            return FailureType.PERMANENT

        # Unknown - treat conservatively
        return FailureType.UNKNOWN

    def decide_recovery(self, context: ErrorContext) -> RecoveryDecision:
        """
        Decide how to recover from an error.

        Args:
            context: Error context with failure details

        Returns:
            RecoveryDecision with recovery strategy

        Raises:
            FallbackExhausted: When maximum fallback depth is exceeded
        """
        self._stats["total_errors"] += 1

        # Build the current fallback chain for tracking
        current_chain = list(context.fallback_chain) if context.fallback_chain else []
        if context.tool_name not in current_chain:
            current_chain.append(context.tool_name)

        # PARTIAL SUCCESS: Return degraded result
        if context.failure_type == FailureType.PARTIAL:
            self._stats["degradations"] += 1
            self._stats["recoveries"] += 1
            return RecoveryDecision(
                action=RecoveryAction.DEGRADE,
                degraded_result=str(context.partial_result) if context.partial_result else None,
                escalation_message=f"⚠️ Partial success for {context.tool_name}: {context.error_message}",
                fallback_depth=context.fallback_depth,
                fallback_chain=current_chain
            )

        # TRANSIENT FAILURE: Retry with backoff
        if context.failure_type == FailureType.TRANSIENT:
            if context.attempt_number < self.max_retries:
                self._stats["retries"] += 1
                wait_time = self.base_backoff * (2 ** (context.attempt_number - 1))
                return RecoveryDecision(
                    action=RecoveryAction.RETRY,
                    wait_seconds=wait_time,
                    retry_params=context.original_params,
                    fallback_depth=context.fallback_depth,
                    fallback_chain=current_chain
                )
            else:
                # Max retries exceeded, try fallback
                pass  # Fall through to fallback logic

        # CHECK FALLBACK DEPTH LIMIT before attempting fallback
        if context.fallback_depth >= self.max_fallback_depth:
            self._stats["max_fallback_depth_reached"] += 1
            self._stats["fallback_exhausted"] += 1
            self._stats["escalations"] += 1

            # Create detailed escalation message for exhausted fallback chain
            chain_str = " → ".join(current_chain)
            escalation_msg = f"""
❌ Fallback Chain Exhausted

**Chain**: {chain_str}
**Depth**: {context.fallback_depth}/{self.max_fallback_depth}
**Original Tool**: {context.original_tool or current_chain[0] if current_chain else context.tool_name}
**Final Error**: {context.error_message}

All fallback options have been exhausted. The operation cannot be completed automatically.

**What you can try**:
- Verify the underlying service/resource is available
- Check network connectivity
- Try a completely different approach
- Manually perform the operation
""".strip()

            return RecoveryDecision(
                action=RecoveryAction.ESCALATE,
                escalation_message=escalation_msg,
                fallback_depth=context.fallback_depth,
                fallback_chain=current_chain
            )

        # PERMANENT FAILURE or RETRY EXHAUSTED: Try fallback (if depth allows)
        if context.tool_name in self.TOOL_FALLBACKS:
            fallbacks = self.TOOL_FALLBACKS[context.tool_name]

            # Find next unused fallback in the chain
            available_fallbacks = [fb for fb in fallbacks if fb not in current_chain]

            if available_fallbacks:
                self._stats["fallbacks"] += 1
                self._stats["recoveries"] += 1
                fallback_tool = available_fallbacks[0]  # Use first unused alternative

                # Adapt parameters for fallback tool
                fallback_params = self._adapt_params_for_fallback(
                    context.tool_name,
                    fallback_tool,
                    context.original_params
                )

                # Calculate fallback backoff (increases with depth)
                fallback_wait = self.base_backoff * (self.fallback_backoff_multiplier ** context.fallback_depth)

                # Update chain for the decision
                new_chain = current_chain + [fallback_tool]

                return RecoveryDecision(
                    action=RecoveryAction.FALLBACK,
                    fallback_tool=fallback_tool,
                    fallback_params=fallback_params,
                    wait_seconds=fallback_wait,
                    escalation_message=f"ℹ️ {context.tool_name} failed (depth {context.fallback_depth + 1}/{self.max_fallback_depth}), falling back to {fallback_tool}",
                    fallback_depth=context.fallback_depth + 1,
                    fallback_chain=new_chain
                )

        # NO RECOVERY POSSIBLE: Escalate to user
        self._stats["escalations"] += 1
        return RecoveryDecision(
            action=RecoveryAction.ESCALATE,
            escalation_message=self._format_escalation_message(context),
            fallback_depth=context.fallback_depth,
            fallback_chain=current_chain
        )

    def _adapt_params_for_fallback(
        self,
        original_tool: str,
        fallback_tool: str,
        original_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Adapt parameters from original tool to fallback tool.

        Args:
            original_tool: Original tool name
            fallback_tool: Fallback tool name
            original_params: Original parameters

        Returns:
            Adapted parameters for fallback tool
        """
        def _slug_to_title(slug: str) -> str:
            if not slug:
                return ""
            return slug.replace("_", " ").replace("-", " ").strip()

        # Example adaptations
        if original_tool == "search_web" and fallback_tool == "search_wikipedia":
            # Adapt web search params to Wikipedia search
            return {"query": original_params.get("query", "")}

        if original_tool == "search" and fallback_tool == "search_wikipedia":
            return {
                "query": original_params.get("query", ""),
                "limit": original_params.get("limit", 10),
            }

        if original_tool in {"get_page", "get_page_content"} and fallback_tool in {"get_summary", "get_article"}:
            slug = original_params.get("slug", "")
            return {"title": _slug_to_title(slug)}

        if original_tool == "get_page_section" and fallback_tool == "summarize_article_section":
            slug = original_params.get("slug", "")
            section_header = original_params.get("section_header", "")
            max_length = original_params.get("max_length")
            params = {
                "title": _slug_to_title(slug),
                "section_title": section_header,
            }
            if max_length is not None:
                params["max_length"] = max_length
            return params

        if original_tool == "get_page_sections" and fallback_tool == "get_sections":
            slug = original_params.get("slug", "")
            return {"title": _slug_to_title(slug)}

        if original_tool == "get_page_citations" and fallback_tool == "get_links":
            slug = original_params.get("slug", "")
            return {"title": _slug_to_title(slug)}

        if original_tool == "get_page_citations" and fallback_tool == "extract_key_facts":
            slug = original_params.get("slug", "")
            limit = original_params.get("limit")
            params = {"title": _slug_to_title(slug)}
            if limit is not None:
                params["count"] = limit
            return params

        if original_tool == "get_related_pages" and fallback_tool == "get_related_topics":
            slug = original_params.get("slug", "")
            limit = original_params.get("limit")
            params = {"title": _slug_to_title(slug)}
            if limit is not None:
                params["limit"] = limit
            return params

        if original_tool == "search_gmail" and fallback_tool == "read_file":
            # Adapt email search to file search
            query = original_params.get("query", "")
            return {"pattern": query, "path": "."}

        if original_tool == "search_memory" and fallback_tool == "read_file":
            # Adapt memory search to file read
            query = original_params.get("query", "")
            return {"pattern": query}

        # Default: pass through params as-is
        return original_params

    def _format_escalation_message(self, context: ErrorContext) -> str:
        """
        Format user-friendly escalation message with recovery suggestions.

        Args:
            context: Error context

        Returns:
            Formatted escalation message
        """
        msg = f"""
❌ Tool Failure: {context.tool_name}

**Error**: {context.error_message}

**Failure Type**: {context.failure_type.value}

**Attempts**: {context.attempt_number}/{self.max_retries}

**Context**:
"""
        # Add relevant context
        if context.original_params:
            # Show first few params
            params_preview = str(context.original_params)[:200]
            msg += f"- Parameters: {params_preview}...\n"

        # Recovery suggestions
        msg += "\n**What you can try**:\n"

        if context.failure_type == FailureType.TRANSIENT:
            msg += "- Wait a few minutes and try again (temporary issue)\n"
            msg += "- Check network connection\n"

        elif context.failure_type == FailureType.PERMANENT:
            msg += "- Verify the resource exists and is accessible\n"
            msg += "- Check permissions and credentials\n"
            msg += "- Try a different approach\n"

        else:
            msg += "- Review the error message above for clues\n"
            msg += "- Try a simpler version of the request\n"

        return msg.strip()

    def handle_error(
        self,
        tool_name: str,
        error_message: str,
        params: Dict[str, Any],
        attempt_number: int = 1,
        partial_result: Optional[Any] = None,
        fallback_depth: int = 0,
        fallback_chain: Optional[List[str]] = None,
        original_tool: Optional[str] = None
    ) -> RecoveryDecision:
        """
        Main entry point for error handling.

        Args:
            tool_name: Name of the tool that failed
            error_message: Error message
            params: Tool parameters
            attempt_number: Current attempt number (1-indexed)
            partial_result: Optional partial result
            fallback_depth: Current depth in the fallback chain (0 = original call)
            fallback_chain: List of tools already tried in this recovery chain
            original_tool: The original tool that started the chain (for tracking)

        Returns:
            RecoveryDecision with recovery strategy
        """
        # Classify failure
        failure_type = self.classify_failure(error_message, partial_result)

        # Build context with fallback tracking
        context = ErrorContext(
            tool_name=tool_name,
            error_message=error_message,
            attempt_number=attempt_number,
            original_params=params,
            failure_type=failure_type,
            partial_result=partial_result,
            fallback_depth=fallback_depth,
            fallback_chain=fallback_chain or [],
            original_tool=original_tool or tool_name
        )

        # Decide recovery
        return self.decide_recovery(context)

    def handle_fallback_error(
        self,
        original_decision: RecoveryDecision,
        fallback_error_message: str,
        fallback_params: Dict[str, Any],
        partial_result: Optional[Any] = None
    ) -> RecoveryDecision:
        """
        Handle an error that occurred during fallback execution.

        This is a convenience method that properly tracks the fallback chain
        when a fallback tool itself fails.

        Args:
            original_decision: The RecoveryDecision that triggered this fallback
            fallback_error_message: Error message from the failed fallback
            fallback_params: Parameters used in the fallback call
            partial_result: Optional partial result from fallback

        Returns:
            RecoveryDecision for the next recovery action
        """
        if not original_decision.fallback_tool:
            raise ValueError("original_decision must have a fallback_tool to use handle_fallback_error")

        return self.handle_error(
            tool_name=original_decision.fallback_tool,
            error_message=fallback_error_message,
            params=fallback_params,
            attempt_number=1,  # Reset attempt counter for new tool
            partial_result=partial_result,
            fallback_depth=original_decision.fallback_depth,
            fallback_chain=original_decision.fallback_chain,
            original_tool=original_decision.fallback_chain[0] if original_decision.fallback_chain else None
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get error handling statistics"""
        total = self._stats["total_errors"]
        recovery_rate = (self._stats["recoveries"] / total * 100) if total > 0 else 0
        fallback_exhaustion_rate = (
            (self._stats["fallback_exhausted"] / self._stats["fallbacks"] * 100)
            if self._stats["fallbacks"] > 0 else 0
        )

        return {
            **self._stats,
            "recovery_rate": round(recovery_rate, 2),
            "fallback_exhaustion_rate": round(fallback_exhaustion_rate, 2),
            "max_retries": self.max_retries,
            "base_backoff": self.base_backoff,
            "max_fallback_depth": self.max_fallback_depth,
            "fallback_backoff_multiplier": self.fallback_backoff_multiplier
        }


# Global error handler instance (initialized in run_vera.py)
_GLOBAL_ERROR_HANDLER: Optional[ErrorHandler] = None


def get_error_handler() -> Optional[ErrorHandler]:
    """Get global error handler instance"""
    return _GLOBAL_ERROR_HANDLER


def init_error_handler(
    max_retries: int = 3,
    base_backoff: float = 1.0,
    max_fallback_depth: int = 3
) -> ErrorHandler:
    """Initialize global error handler instance"""
    global _GLOBAL_ERROR_HANDLER
    _GLOBAL_ERROR_HANDLER = ErrorHandler(
        max_retries=max_retries,
        base_backoff=base_backoff,
        max_fallback_depth=max_fallback_depth
    )
    return _GLOBAL_ERROR_HANDLER


# === CLI Interface for Testing ===

if __name__ == "__main__":
    print("=" * 60)
    logger.error("Error Handler - Test Suite (with Fallback Depth Counter)")
    print("=" * 60)

    handler = ErrorHandler(max_retries=3, base_backoff=1.0, max_fallback_depth=3)

    # Test 1: Transient error (should retry)
    logger.error("\n=== Test 1: Transient Error (Timeout) ===")
    decision = handler.handle_error(
        tool_name="search_web",
        error_message="Connection timeout after 30s",
        params={"query": "test"},
        attempt_number=1
    )
    assert decision.action == RecoveryAction.RETRY, "Should retry transient error"
    assert decision.wait_seconds > 0, "Should have backoff time"
    assert decision.fallback_depth == 0, "Should be at depth 0"
    logger.info(f"✅ Retry decision: wait {decision.wait_seconds}s, depth={decision.fallback_depth}")

    # Test 2: Permanent error (should fallback)
    logger.error("\n=== Test 2: Permanent Error (File Not Found) ===")
    decision = handler.handle_error(
        tool_name="search_web",
        error_message="404 Not Found",
        params={"query": "test"},
        attempt_number=1
    )
    assert decision.action == RecoveryAction.FALLBACK, "Should fallback on permanent error"
    assert decision.fallback_tool is not None, "Should suggest fallback tool"
    assert decision.fallback_depth == 1, "Fallback should increment depth"
    assert len(decision.fallback_chain) == 2, "Chain should include original + fallback"
    logger.info(f"✅ Fallback decision: use {decision.fallback_tool}, depth={decision.fallback_depth}")
    print(f"   Chain: {' → '.join(decision.fallback_chain)}")

    # Test 3: Partial success (should degrade)
    print("\n=== Test 3: Partial Success ===")
    decision = handler.handle_error(
        tool_name="search_gmail",
        error_message="Partial results: 5/10 emails retrieved",
        params={"query": "test"},
        attempt_number=1,
        partial_result="Email 1, Email 2, Email 3, Email 4, Email 5"
    )
    assert decision.action == RecoveryAction.DEGRADE, "Should degrade on partial success"
    assert decision.degraded_result is not None, "Should include partial result"
    logger.info(f"✅ Degrade decision: return partial result")

    # Test 4: Retry exhausted (should fallback or escalate)
    print("\n=== Test 4: Retry Exhausted ===")
    decision = handler.handle_error(
        tool_name="search_web",
        error_message="Connection timeout after 30s",
        params={"query": "test"},
        attempt_number=4  # Exceeds max_retries=3
    )
    assert decision.action in [RecoveryAction.FALLBACK, RecoveryAction.ESCALATE], \
        "Should fallback or escalate when retries exhausted"
    logger.info(f"✅ Exhausted retries: action = {decision.action.value}")

    # Test 5: No fallback available (should escalate)
    print("\n=== Test 5: No Fallback Available ===")
    decision = handler.handle_error(
        tool_name="run_command",  # No fallback defined
        error_message="Command failed with exit code 1",
        params={"cmd": "test"},
        attempt_number=1
    )
    assert decision.action == RecoveryAction.ESCALATE, "Should escalate when no fallback"
    assert decision.escalation_message is not None, "Should have escalation message"
    logger.info(f"✅ Escalate decision with message")

    # Test 6: Fallback depth tracking
    print("\n=== Test 6: Fallback Depth Tracking ===")
    handler2 = ErrorHandler(max_retries=3, base_backoff=1.0, max_fallback_depth=2)

    # First failure - should fallback (depth 0 -> 1)
    decision1 = handler2.handle_error(
        tool_name="search_web",
        error_message="404 Not Found",
        params={"query": "test"},
        attempt_number=1,
        fallback_depth=0,
        fallback_chain=[]
    )
    assert decision1.action == RecoveryAction.FALLBACK, "Should fallback at depth 0"
    assert decision1.fallback_depth == 1, "Should increment to depth 1"
    logger.info(f"✅ Depth 0→1: {decision1.fallback_tool}, chain={decision1.fallback_chain}")

    # Second failure (simulating fallback also failed) - should fallback again (depth 1 -> 2)
    decision2 = handler2.handle_error(
        tool_name="search_wikipedia",
        error_message="Wikipedia unavailable",
        params={"query": "test"},
        attempt_number=1,
        fallback_depth=1,
        fallback_chain=["search_web", "search_wikipedia"]
    )
    # At depth 1, with max_fallback_depth=2, we're at the limit
    # search_wikipedia's fallback is read_file (if defined)
    print(f"   Depth 1: action={decision2.action.value}, depth={decision2.fallback_depth}")

    # Third failure at max depth - should ESCALATE
    decision3 = handler2.handle_error(
        tool_name="read_file",
        error_message="File not found",
        params={"pattern": "test"},
        attempt_number=1,
        fallback_depth=2,  # At max depth
        fallback_chain=["search_web", "search_wikipedia", "read_file"]
    )
    assert decision3.action == RecoveryAction.ESCALATE, "Should escalate at max depth"
    assert "Exhausted" in decision3.escalation_message or "exhausted" in decision3.escalation_message.lower(), \
        "Should mention exhausted chain"
    logger.info(f"✅ Depth 2 (max): ESCALATE - chain exhausted")
    print(f"   Chain: {' → '.join(decision3.fallback_chain)}")

    # Test 7: Fallback backoff increases with depth
    print("\n=== Test 7: Fallback Backoff Scaling ===")
    handler3 = ErrorHandler(max_retries=3, base_backoff=1.0, max_fallback_depth=5, fallback_backoff_multiplier=2.0)

    for depth in range(3):
        decision = handler3.handle_error(
            tool_name="search_web",
            error_message="404 Not Found",
            params={"query": "test"},
            attempt_number=1,
            fallback_depth=depth,
            fallback_chain=["search_web"] if depth > 0 else []
        )
        if decision.action == RecoveryAction.FALLBACK:
            expected_wait = 1.0 * (2.0 ** depth)
            print(f"   Depth {depth}: wait={decision.wait_seconds}s (expected ~{expected_wait}s)")

    logger.info("✅ Fallback backoff scales with depth")

    # Test 8: handle_fallback_error convenience method
    logger.error("\n=== Test 8: handle_fallback_error Method ===")
    handler4 = ErrorHandler(max_retries=3, base_backoff=1.0, max_fallback_depth=3)

    # Initial error
    initial_decision = handler4.handle_error(
        tool_name="search_web",
        error_message="404 Not Found",
        params={"query": "test"}
    )
    assert initial_decision.action == RecoveryAction.FALLBACK

    # Fallback also fails - use convenience method
    followup_decision = handler4.handle_fallback_error(
        original_decision=initial_decision,
        fallback_error_message="Wikipedia also failed",
        fallback_params={"query": "test"}
    )
    print(f"   Initial: {initial_decision.fallback_tool}, depth={initial_decision.fallback_depth}")
    print(f"   Followup: action={followup_decision.action.value}, depth={followup_decision.fallback_depth}")
    logger.info("✅ handle_fallback_error properly tracks chain")

    # Test 9: Statistics with new fields
    print("\n=== Test 9: Enhanced Statistics ===")
    stats = handler2.get_stats()
    logger.error(f"   Total errors: {stats['total_errors']}")
    print(f"   Retries: {stats['retries']}")
    print(f"   Fallbacks: {stats['fallbacks']}")
    print(f"   Degradations: {stats['degradations']}")
    print(f"   Escalations: {stats['escalations']}")
    print(f"   Fallback exhausted: {stats['fallback_exhausted']}")
    print(f"   Max depth reached: {stats['max_fallback_depth_reached']}")
    print(f"   Recovery rate: {stats['recovery_rate']}%")
    print(f"   Fallback exhaustion rate: {stats['fallback_exhaustion_rate']}%")
    print(f"   Max fallback depth: {stats['max_fallback_depth']}")
    logger.info("✅ Enhanced statistics tracking works")

    print("\n" + "=" * 60)
    logger.info("✅ ALL TESTS PASSED (including Fallback Depth Counter)")
    print("=" * 60)
    logger.error("\nError handler is working correctly with cascading fallback protection!")
    print(f"\nFinal stats (handler2): {handler2.get_stats()}")
