from observability.self_improvement_budget import (
    SelfImprovementBudget,
    budget_config_to_dict,
    default_budget_state,
    BudgetConfig,
)
from core.atomic_io import atomic_json_write


def test_budget_check_hot_reloads_updated_config(tmp_path):
    budget_path = tmp_path / "budget.json"
    config_path = tmp_path / "config.json"

    # Simulate an existing day where one call has already been spent.
    state = default_budget_state()
    state["calls"] = 1
    atomic_json_write(budget_path, state)

    # Initial budget allows only one call/day, so next call should be blocked.
    initial = BudgetConfig(
        enabled=True,
        daily_budget_usd=3.0,
        daily_token_budget=50000,
        daily_call_budget=1,
        max_tokens_per_call=2500,
    )
    atomic_json_write(config_path, budget_config_to_dict(initial))

    guard = SelfImprovementBudget(storage_path=budget_path, config_path=config_path)
    allowed, reason = guard.check(
        category="inner_life_reflection",
        estimated_tokens=200,
        estimated_cost=0.01,
        calls=1,
    )
    assert allowed is False
    assert reason == "daily_call_budget_exceeded"

    # Raise call budget in config file; running guard should honor it immediately.
    updated = BudgetConfig(
        enabled=True,
        daily_budget_usd=3.0,
        daily_token_budget=50000,
        daily_call_budget=8,
        max_tokens_per_call=2500,
    )
    atomic_json_write(config_path, budget_config_to_dict(updated))

    allowed, reason = guard.check(
        category="inner_life_reflection",
        estimated_tokens=200,
        estimated_cost=0.01,
        calls=1,
    )
    assert allowed is True
    assert reason == "ok"
