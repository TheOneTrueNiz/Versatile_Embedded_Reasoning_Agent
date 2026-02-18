#!/usr/bin/env python3
"""
Self-Improvement Budget Guard
=============================

Tracks daily spend and call limits for self-improvement LLM workflows
to avoid runaway API costs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from core.atomic_io import atomic_json_write, safe_json_read

DEFAULT_BUDGET_PATH = Path("vera_memory/flight_recorder/self_improvement_budget.json")
DEFAULT_CONFIG_PATH = Path("vera_memory/flight_recorder/self_improvement_budget_config.json")


def _env_bool(name: str, default: str = "1") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value not in {"0", "false", "off", "no"}


def _coerce_bool(value: Any, fallback: bool) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no", ""}
    return fallback


def _coerce_int(value: Any, fallback: int) -> int:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.strip()))
        except ValueError:
            return fallback
    return fallback


def _coerce_float(value: Any, fallback: float) -> float:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return fallback
    return fallback


def estimate_tokens(text: str) -> int:
    """Approximate token count from text length."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_cost(tokens_in: int, tokens_out: int) -> float:
    """Estimate cost using the default token pricing."""
    input_cost = (tokens_in / 1000) * 0.003
    output_cost = (tokens_out / 1000) * 0.015
    return input_cost + output_cost


@dataclass
class BudgetConfig:
    enabled: bool
    daily_budget_usd: float
    daily_token_budget: int
    daily_call_budget: int
    max_tokens_per_call: int


def budget_config_to_dict(config: BudgetConfig) -> Dict[str, Any]:
    return {
        "enabled": bool(config.enabled),
        "daily_budget_usd": float(config.daily_budget_usd),
        "daily_token_budget": int(config.daily_token_budget),
        "daily_call_budget": int(config.daily_call_budget),
        "max_tokens_per_call": int(config.max_tokens_per_call),
    }


def load_budget_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Tuple[BudgetConfig, str]:
    base = BudgetConfig(
        enabled=_env_bool("VERA_SELF_IMPROVEMENT_BUDGET_ENABLED", "1"),
        daily_budget_usd=float(os.getenv("VERA_SELF_IMPROVEMENT_DAILY_BUDGET_USD", "1.0")),
        daily_token_budget=int(os.getenv("VERA_SELF_IMPROVEMENT_DAILY_TOKEN_BUDGET", "12000")),
        daily_call_budget=int(os.getenv("VERA_SELF_IMPROVEMENT_DAILY_CALL_BUDGET", "6")),
        max_tokens_per_call=int(os.getenv("VERA_SELF_IMPROVEMENT_MAX_TOKENS_PER_CALL", "2000")),
    )
    stored = safe_json_read(config_path, default={}) or {}
    source = "env"
    if stored:
        source = "file"
        base.enabled = _coerce_bool(stored.get("enabled"), base.enabled)
        base.daily_budget_usd = _coerce_float(stored.get("daily_budget_usd"), base.daily_budget_usd)
        base.daily_token_budget = _coerce_int(stored.get("daily_token_budget"), base.daily_token_budget)
        base.daily_call_budget = _coerce_int(stored.get("daily_call_budget"), base.daily_call_budget)
        base.max_tokens_per_call = _coerce_int(stored.get("max_tokens_per_call"), base.max_tokens_per_call)
    return base, source


def default_budget_state() -> Dict[str, object]:
    today = datetime.now().date().isoformat()
    return {
        "date": today,
        "spent_usd": 0.0,
        "tokens_used": 0,
        "calls": 0,
        "categories": {},
        "updated_at": datetime.now().isoformat(),
    }


def load_budget_state(storage_path: Path = DEFAULT_BUDGET_PATH) -> Dict[str, object]:
    state = safe_json_read(storage_path, default={}) or {}
    today = datetime.now().date().isoformat()
    if state.get("date") != today:
        return default_budget_state()
    for key, default_value in default_budget_state().items():
        state.setdefault(key, default_value)
    return state


def reset_budget_state(storage_path: Path = DEFAULT_BUDGET_PATH) -> Dict[str, object]:
    state = default_budget_state()
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(storage_path, state)
    return state


class SelfImprovementBudget:
    def __init__(
        self,
        storage_path: Path = DEFAULT_BUDGET_PATH,
        config: BudgetConfig | None = None,
        config_path: Path = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.storage_path = storage_path
        self.config_path = config_path
        self.config_source = "override"
        if config is None:
            self.config, self.config_source = load_budget_config(config_path)
        else:
            self.config = config

    def _default_state(self) -> Dict[str, object]:
        return default_budget_state()

    def _load_state(self) -> Dict[str, object]:
        return load_budget_state(self.storage_path)

    def _save_state(self, state: Dict[str, object]) -> None:
        state["updated_at"] = datetime.now().isoformat()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(self.storage_path, state)

    def check(
        self,
        *,
        category: str,
        estimated_tokens: int,
        estimated_cost: float,
        calls: int = 1
    ) -> Tuple[bool, str]:
        if not self.config.enabled:
            return True, "budget_disabled"

        state = self._load_state()
        daily_calls = int(self.config.daily_call_budget)
        daily_tokens = int(self.config.daily_token_budget)
        daily_budget = float(self.config.daily_budget_usd)
        max_tokens_per_call = int(self.config.max_tokens_per_call)

        if max_tokens_per_call > 0 and estimated_tokens > max_tokens_per_call:
            return False, "max_tokens_per_call_exceeded"

        if daily_calls >= 0 and (state["calls"] + calls) > daily_calls:
            return False, "daily_call_budget_exceeded"

        if daily_tokens >= 0 and (state["tokens_used"] + estimated_tokens) > daily_tokens:
            return False, "daily_token_budget_exceeded"

        if daily_budget >= 0 and (state["spent_usd"] + estimated_cost) > daily_budget:
            return False, "daily_budget_usd_exceeded"

        return True, "ok"

    def record_usage(
        self,
        *,
        category: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        calls: int = 1
    ) -> Dict[str, object]:
        state = self._load_state()
        tokens_used = tokens_in + tokens_out
        state["tokens_used"] = int(state.get("tokens_used", 0)) + tokens_used
        state["spent_usd"] = float(state.get("spent_usd", 0.0)) + cost
        state["calls"] = int(state.get("calls", 0)) + calls

        categories = state.get("categories") or {}
        category_state = categories.get(category) or {"tokens_used": 0, "spent_usd": 0.0, "calls": 0}
        category_state["tokens_used"] += tokens_used
        category_state["spent_usd"] += cost
        category_state["calls"] += calls
        categories[category] = category_state
        state["categories"] = categories

        self._save_state(state)
        return state
