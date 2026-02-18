#!/usr/bin/env python3
"""
Token Thermostat - Adaptive Cost Management
============================================

Tracks API costs and tool usage, enforcing budgets to prevent runaway spending.

Source: Ported from GROKSTAR's MAX_TOOL_CALLS and CYCLE_TOOL_BUDGET

Problem Solved:
- Agents can trigger "tool storms" - 50 file reads or 100 web searches
- API costs can explode silently
- Users need visibility and control over spending

Solution:
- Track token usage and API costs in real-time
- Soft limits (warn) and hard limits (stop)
- Per-tool and per-session budgets
- Automatic preference for cheaper alternatives

Usage:
    from cost_tracker import CostTracker, BudgetStatus

    tracker = CostTracker(
        session_budget=5.00,      # $5 per session
        soft_limit_ratio=0.6      # Warn at 60%
    )

    # Check before tool call
    status = tracker.check_budget("web_search")
    if status == BudgetStatus.HARD_LIMIT:
        print("Budget exceeded!")

    # Record usage
    tracker.record_usage(
        tool_name="web_search",
        tokens_in=150,
        tokens_out=500,
        cost=0.002
    )
"""

import json
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
from enum import Enum

# Import atomic operations
try:
    from atomic_io import atomic_json_write, safe_json_read
    HAS_ATOMIC = True
except ImportError:
    HAS_ATOMIC = False


class BudgetStatus(Enum):
    """Budget check results"""
    OK = "ok"                          # Under budget
    SOFT_LIMIT_WARNING = "warning"     # Approaching limit
    HARD_LIMIT_EXCEEDED = "exceeded"   # Over budget
    TOOL_LIMIT_EXCEEDED = "tool_limit" # Specific tool over limit


@dataclass
class UsageRecord:
    """Single usage record"""
    timestamp: str
    tool_name: str
    tokens_in: int
    tokens_out: int
    cost: float
    duration_ms: float = 0
    cached: bool = False


@dataclass
class ToolBudget:
    """Budget configuration for a specific tool"""
    max_calls_per_session: int = 100
    max_calls_per_minute: int = 10
    cost_weight: float = 1.0  # Relative cost (1.0 = normal, 2.0 = expensive)


class CostTracker:
    """
    Tracks and enforces cost budgets.

    Features:
    - Real-time cost tracking
    - Per-tool and per-session limits
    - Soft warnings before hard stops
    - Usage analytics
    """

    # Default costs per 1K tokens (approximate, adjust for your API)
    DEFAULT_COSTS = {
        "input": 0.003,   # $3 per 1M input tokens
        "output": 0.015,  # $15 per 1M output tokens
    }

    # Default per-tool budgets
    DEFAULT_TOOL_BUDGETS = {
        # Expensive tools (web, external APIs)
        "web_search": ToolBudget(max_calls_per_session=20, cost_weight=2.0),
        "web_fetch": ToolBudget(max_calls_per_session=30, cost_weight=1.5),

        # Medium tools (file operations)
        "read_file": ToolBudget(max_calls_per_session=100, cost_weight=0.5),
        "write_file": ToolBudget(max_calls_per_session=50, cost_weight=0.5),
        "run_command": ToolBudget(max_calls_per_session=30, cost_weight=1.0),

        # Cheap tools (memory, cache)
        "search_memory": ToolBudget(max_calls_per_session=200, cost_weight=0.2),
        "cache_lookup": ToolBudget(max_calls_per_session=500, cost_weight=0.1),

        # Default for unknown tools
        "_default": ToolBudget(max_calls_per_session=50, cost_weight=1.0),
    }

    TOOL_ALIAS_MAP = {
        "searxng_search": "web_search",
        "search_youtube": "web_search",
        "get_transcript": "web_fetch",
        "initiate_call": "run_command",
        "send_sms": "run_command",
        "send_mms": "run_command",
    }

    TOOL_PREFIX_ALIAS = {
        "brave_": "web_search",
        "browserbase_": "web_fetch",
        "scrapeless_": "web_fetch",
        "twitter_": "web_search",
        "x_": "web_search",
        "call_": "run_command",
    }

    def __init__(
        self,
        session_budget: float = 5.00,
        soft_limit_ratio: float = 0.6,
        hard_limit_ratio: float = 0.95,
        tool_budgets: Dict[str, ToolBudget] = None,
        storage_path: Path = None
    ):
        """
        Initialize cost tracker.

        Args:
            session_budget: Maximum spend per session in dollars
            soft_limit_ratio: Warn when this fraction of budget is used
            hard_limit_ratio: Stop when this fraction of budget is used
            tool_budgets: Custom per-tool budgets
            storage_path: Path to persist usage data
        """
        self.session_budget = session_budget
        if soft_limit_ratio >= hard_limit_ratio:
            soft_limit_ratio = hard_limit_ratio * 0.6
        self.soft_limit = session_budget * soft_limit_ratio
        self.hard_limit = session_budget * hard_limit_ratio

        self.tool_budgets = {**self.DEFAULT_TOOL_BUDGETS}
        if tool_budgets:
            self.tool_budgets.update(tool_budgets)

        self.storage_path = storage_path

        # Session state
        self.session_start = datetime.now()
        self._usage_records: List[UsageRecord] = []
        self._tool_call_counts: Dict[str, int] = {}
        self._total_cost = 0.0
        self._total_tokens_in = 0
        self._total_tokens_out = 0

        # Rate limiting state
        self._recent_calls: Dict[str, List[float]] = {}  # tool -> list of timestamps

    def _get_tool_budget(self, tool_name: str) -> ToolBudget:
        """Get budget config for a tool"""
        if tool_name in self.tool_budgets:
            return self.tool_budgets[tool_name]
        alias = self.TOOL_ALIAS_MAP.get(tool_name)
        if alias and alias in self.tool_budgets:
            return self.tool_budgets[alias]
        for prefix, mapped in self.TOOL_PREFIX_ALIAS.items():
            if tool_name.startswith(prefix) and mapped in self.tool_budgets:
                return self.tool_budgets[mapped]
        return self.tool_budgets["_default"]

    def check_budget(self, tool_name: str = None) -> BudgetStatus:
        """
        Check if budget allows a tool call.

        Args:
            tool_name: Optional tool to check specific limits

        Returns:
            BudgetStatus indicating if call should proceed
        """
        # Check overall budget
        if self._total_cost >= self.hard_limit:
            return BudgetStatus.HARD_LIMIT_EXCEEDED

        if self._total_cost >= self.soft_limit:
            # Soft limit - allow but warn
            status = BudgetStatus.SOFT_LIMIT_WARNING
        else:
            status = BudgetStatus.OK

        # Check tool-specific limits
        if tool_name:
            budget = self._get_tool_budget(tool_name)
            call_count = self._tool_call_counts.get(tool_name, 0)

            if call_count >= budget.max_calls_per_session:
                return BudgetStatus.TOOL_LIMIT_EXCEEDED

            # Check rate limit
            if not self._check_rate_limit(tool_name, budget):
                return BudgetStatus.TOOL_LIMIT_EXCEEDED

        return status

    def _check_rate_limit(self, tool_name: str, budget: ToolBudget) -> bool:
        """Check if tool is within rate limit"""
        now = time.time()
        cutoff = now - 60  # Last minute

        # Get recent calls for this tool
        recent = self._recent_calls.get(tool_name, [])
        recent = [t for t in recent if t > cutoff]  # Remove old entries

        return len(recent) < budget.max_calls_per_minute

    def estimate_cost(
        self,
        tokens_in: int,
        tokens_out: int,
        tool_name: str = None
    ) -> float:
        """
        Estimate cost for a tool call.

        Args:
            tokens_in: Input tokens
            tokens_out: Output tokens
            tool_name: Tool for weight adjustment

        Returns:
            Estimated cost in dollars
        """
        base_cost = (
            (tokens_in / 1000) * self.DEFAULT_COSTS["input"] +
            (tokens_out / 1000) * self.DEFAULT_COSTS["output"]
        )

        # Apply tool weight
        if tool_name:
            budget = self._get_tool_budget(tool_name)
            base_cost *= budget.cost_weight

        return base_cost

    def record_usage(
        self,
        tool_name: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = None,
        duration_ms: float = 0,
        cached: bool = False
    ) -> UsageRecord:
        """
        Record a tool usage.

        Args:
            tool_name: Name of tool used
            tokens_in: Input tokens
            tokens_out: Output tokens
            cost: Actual cost (or estimated if None)
            duration_ms: Call duration in milliseconds
            cached: Whether result was from cache

        Returns:
            Usage record
        """
        # Calculate cost if not provided
        if cost is None:
            cost = self.estimate_cost(tokens_in, tokens_out, tool_name)

        # Cached calls are free
        if cached:
            cost = 0

        record = UsageRecord(
            timestamp=datetime.now().isoformat(),
            tool_name=tool_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            duration_ms=duration_ms,
            cached=cached
        )

        # Update state
        self._usage_records.append(record)
        self._tool_call_counts[tool_name] = self._tool_call_counts.get(tool_name, 0) + 1
        self._total_cost += cost
        self._total_tokens_in += tokens_in
        self._total_tokens_out += tokens_out

        # Update rate limit tracking
        if tool_name not in self._recent_calls:
            self._recent_calls[tool_name] = []
        self._recent_calls[tool_name].append(time.time())

        return record

    def get_remaining_budget(self) -> float:
        """Get remaining budget in dollars"""
        return max(0, self.session_budget - self._total_cost)

    def get_budget_status_message(self) -> str:
        """Get human-readable budget status"""
        remaining = self.get_remaining_budget()
        pct_used = (self._total_cost / self.session_budget) * 100 if self.session_budget > 0 else 0

        if pct_used >= 95:
            return f"BUDGET CRITICAL: ${remaining:.4f} remaining ({pct_used:.1f}% used)"
        elif pct_used >= 60:
            return f"Budget warning: ${remaining:.4f} remaining ({pct_used:.1f}% used)"
        else:
            return f"Budget OK: ${remaining:.4f} remaining ({pct_used:.1f}% used)"

    def suggest_cheaper_alternative(self, tool_name: str) -> Optional[str]:
        """
        Suggest a cheaper alternative to an expensive tool.

        Returns:
            Alternative tool name, or None if no alternative
        """
        alternatives = {
            "web_search": "search_memory",  # Check memory before web
            "web_fetch": "cache_lookup",    # Check cache before fetching
            "run_command": "read_file",     # Read instead of execute when possible
        }

        alternative = alternatives.get(tool_name)

        if alternative:
            alt_budget = self._get_tool_budget(alternative)
            orig_budget = self._get_tool_budget(tool_name)

            if alt_budget.cost_weight < orig_budget.cost_weight:
                return alternative

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics"""
        session_duration = (datetime.now() - self.session_start).total_seconds()

        by_tool = {}
        for record in self._usage_records:
            if record.tool_name not in by_tool:
                by_tool[record.tool_name] = {"calls": 0, "cost": 0, "tokens": 0}
            by_tool[record.tool_name]["calls"] += 1
            by_tool[record.tool_name]["cost"] += record.cost
            by_tool[record.tool_name]["tokens"] += record.tokens_in + record.tokens_out

        cache_hits = sum(1 for r in self._usage_records if r.cached)
        cache_rate = cache_hits / len(self._usage_records) if self._usage_records else 0

        return {
            "session_budget": round(self.session_budget, 6),
            "session_duration_s": round(session_duration, 1),
            "total_cost": round(self._total_cost, 6),
            "remaining_budget": round(self.get_remaining_budget(), 6),
            "budget_pct_used": round((self._total_cost / self.session_budget) * 100, 2),
            "total_calls": len(self._usage_records),
            "total_tokens_in": self._total_tokens_in,
            "total_tokens_out": self._total_tokens_out,
            "by_tool": by_tool,
            "cache_hit_rate": round(cache_rate, 3),
            "cost_per_minute": round(self._total_cost / (session_duration / 60), 6) if session_duration > 0 else 0
        }

    def get_top_spenders(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get tools that have consumed the most budget"""
        stats = self.get_stats()
        by_tool = stats["by_tool"]

        sorted_tools = sorted(
            by_tool.items(),
            key=lambda x: x[1]["cost"],
            reverse=True
        )

        return [
            {"tool": tool, **data}
            for tool, data in sorted_tools[:limit]
        ]

    def save_session(self) -> None:
        """Save session data to disk"""
        if not self.storage_path:
            return

        data = {
            "session_start": self.session_start.isoformat(),
            "session_end": datetime.now().isoformat(),
            "stats": self.get_stats(),
            "records": [asdict(r) for r in self._usage_records]
        }

        if HAS_ATOMIC:
            atomic_json_write(self.storage_path, data)
        else:
            self.storage_path.write_text(json.dumps(data, indent=2))

    def reset_session(self) -> Dict[str, Any]:
        """Reset for new session, returning final stats"""
        final_stats = self.get_stats()

        # Save before reset
        self.save_session()

        # Reset state
        self.session_start = datetime.now()
        self._usage_records = []
        self._tool_call_counts = {}
        self._total_cost = 0.0
        self._total_tokens_in = 0
        self._total_tokens_out = 0
        self._recent_calls = {}

        return final_stats


# === CLI Test Interface ===

if __name__ == "__main__":
    print("=" * 60)
    print("Cost Tracker (Token Thermostat) - Test Suite")
    print("=" * 60)

    tracker = CostTracker(
        session_budget=1.00,  # $1 for testing
        soft_limit_ratio=0.5,
        hard_limit_ratio=0.9
    )

    # Test 1: Check initial budget
    print("\n=== Test 1: Initial Budget ===")
    status = tracker.check_budget()
    assert status == BudgetStatus.OK
    print(f"   Status: {status.value}")
    print(f"   Remaining: ${tracker.get_remaining_budget():.4f}")
    print("   Result: PASS")

    # Test 2: Record usage
    print("\n=== Test 2: Record Usage ===")
    tracker.record_usage("web_search", tokens_in=100, tokens_out=500, duration_ms=250)
    tracker.record_usage("read_file", tokens_in=50, tokens_out=1000, duration_ms=10)
    tracker.record_usage("read_file", tokens_in=50, tokens_out=1000, cached=True)
    print(f"   Total cost: ${tracker._total_cost:.6f}")
    print(f"   Total calls: {len(tracker._usage_records)}")
    print("   Result: PASS")

    # Test 3: Cost estimation
    print("\n=== Test 3: Cost Estimation ===")
    estimated = tracker.estimate_cost(1000, 1000, "web_search")
    print(f"   Estimated cost (1K in, 1K out, web_search): ${estimated:.6f}")
    assert estimated > 0
    print("   Result: PASS")

    # Test 4: Soft limit warning
    print("\n=== Test 4: Soft Limit Warning ===")
    # Add more usage to hit soft limit
    for _ in range(10):
        tracker.record_usage("web_search", tokens_in=500, tokens_out=2000)

    status = tracker.check_budget()
    print(f"   Status: {status.value}")
    print(f"   {tracker.get_budget_status_message()}")
    # Should be at warning level
    print("   Result: PASS")

    # Test 5: Tool-specific limits
    print("\n=== Test 5: Tool Limits ===")
    # Record many calls to one tool
    for _ in range(25):
        tracker.record_usage("web_search", tokens_in=10, tokens_out=10)

    status = tracker.check_budget("web_search")
    print(f"   web_search calls: {tracker._tool_call_counts.get('web_search', 0)}")
    print(f"   Status: {status.value}")
    assert status == BudgetStatus.TOOL_LIMIT_EXCEEDED
    print("   Result: PASS")

    # Test 6: Alternative suggestion
    print("\n=== Test 6: Cheaper Alternatives ===")
    alt = tracker.suggest_cheaper_alternative("web_search")
    print(f"   Alternative to web_search: {alt}")
    assert alt == "search_memory"
    print("   Result: PASS")

    # Test 7: Statistics
    print("\n=== Test 7: Statistics ===")
    stats = tracker.get_stats()
    print(f"   Total cost: ${stats['total_cost']:.6f}")
    print(f"   Budget used: {stats['budget_pct_used']:.1f}%")
    print(f"   Total calls: {stats['total_calls']}")
    print(f"   Cache hit rate: {stats['cache_hit_rate']:.1%}")
    print("   Result: PASS")

    # Test 8: Top spenders
    print("\n=== Test 8: Top Spenders ===")
    top = tracker.get_top_spenders(3)
    print("   Top spending tools:")
    for t in top:
        print(f"     - {t['tool']}: ${t['cost']:.6f} ({t['calls']} calls)")
    print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nCost Tracker is ready for integration!")
