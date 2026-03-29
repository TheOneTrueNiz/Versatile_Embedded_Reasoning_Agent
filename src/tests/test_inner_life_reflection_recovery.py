from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from planning.inner_life_engine import (
    INTENT_INTERNAL,
    InnerLifeConfig,
    InnerLifeEngine,
    MonologueEntry,
)


def _make_entry() -> MonologueEntry:
    return MonologueEntry(
        timestamp="2026-02-24T00:00:00",
        run_id="run-test",
        trigger="manual",
        intent=INTENT_INTERNAL,
        thought="steady",
        chain_depth=0,
    )


@pytest.mark.asyncio
async def test_execute_reflection_cycle_recovers_from_stale_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = InnerLifeEngine(InnerLifeConfig(), tmp_path / "innerlife")
    monkeypatch.setenv("VERA_REFLECTION_STALE_SECONDS", "30")

    async def _process_messages(*args, **kwargs):
        return "[INTERNAL] steady"

    async def _single_turn(*args, **kwargs):
        return _make_entry()

    engine._process_messages_fn = _process_messages
    engine._execute_single_turn = _single_turn  # type: ignore[assignment]
    engine._reflection_running = True
    engine._reflection_started_monotonic = time.monotonic() - 120.0

    result = await engine.execute_reflection_cycle(trigger="manual", force=True)

    assert result.outcome == "internal"
    assert engine._reflection_running is False
    assert engine._reflection_started_monotonic is None


@pytest.mark.asyncio
async def test_execute_reflection_cycle_forced_verification_prefers_reach_out(
    tmp_path,
) -> None:
    engine = InnerLifeEngine(
        InnerLifeConfig(delivery_channels=["api"]),
        tmp_path / "innerlife",
    )
    engine._channel_dock = {"api": object()}
    engine._resolve_delivery_target = lambda channel_id, **kwargs: "api"  # type: ignore[assignment]

    async def _process_messages(*args, **kwargs):
        messages = kwargs.get("messages") or []
        user_message = str(messages[0].get("content") or "")
        assert "Verification directive:" in user_message
        assert "Prefer [REACH_OUT]" in user_message
        return (
            "[REACH_OUT] Quick verification check-in.\n"
            'PARTNER_MODEL_JSON: {"partner_learning_answer":"No new partner-specific learning today.",'
            '"preferences":[],"goals":[],"frustrations":[],"working_style":[],"long_term_projects":[]}'
        )

    async def _deliver_to_channels(text: str):
        return ["api"]

    engine._process_messages_fn = _process_messages
    engine._deliver_to_channels = _deliver_to_channels  # type: ignore[assignment]

    result = await engine.execute_reflection_cycle(trigger="manual_verification", force=True)

    assert result.outcome == "reached_out"
    assert result.delivered_to == ["api"]


@pytest.mark.asyncio
async def test_execute_single_turn_disables_tools_for_inner_life_calls(tmp_path) -> None:
    engine = InnerLifeEngine(InnerLifeConfig(), tmp_path / "innerlife")

    async def _process_messages(*args, **kwargs):
        assert kwargs.get("tool_choice") == "none"
        return "[INTERNAL] steady"

    engine._process_messages_fn = _process_messages

    entry = await engine._execute_single_turn(
        run_id="run-test",
        trigger="autonomy_cycle",
        chain_depth=0,
        force=False,
    )

    assert entry.intent == INTENT_INTERNAL
    assert entry.thought == "steady"


def test_get_statistics_reports_reflection_running_seconds(tmp_path) -> None:
    engine = InnerLifeEngine(InnerLifeConfig(), tmp_path / "innerlife")
    engine._reflection_running = True
    engine._reflection_started_monotonic = time.monotonic() - 3.0

    stats = engine.get_statistics()

    assert stats["reflection_running"] is True
    assert isinstance(stats["reflection_running_seconds"], float)
    assert stats["reflection_running_seconds"] >= 0.0


def test_autonomy_cycle_prompt_prefers_action(tmp_path) -> None:
    engine = InnerLifeEngine(InnerLifeConfig(), tmp_path / "innerlife")
    engine._get_operational_surface_summary = lambda max_items=3: (  # type: ignore[assignment]
        "### Tasks\n- [P1] Review pending task (TASK-900, pending due 2026-03-12)\n\n"
        "### Active Goals\n- [P4] Keep the runtime honest (g_001, self_improvement)"
    )

    user_message = engine._build_reflection_user_message(trigger="autonomy_cycle", force=False)
    system_prompt = engine._build_reflection_system_prompt(trigger="autonomy_cycle", force=False)

    assert "Operational cadence directive:" in user_message
    assert "choose [ACTION]" in user_message
    assert "Avoid poetic scene-setting" in user_message
    assert "vera_memory/*" in user_message
    assert "Operational Cadence Mode" in system_prompt
    assert "prefer [ACTION]" in system_prompt
    assert "## Actionable Surface" in system_prompt
    assert "TASK-900" in system_prompt
    assert "Keep the runtime honest" in system_prompt
    assert "does not require partner confirmation" in system_prompt


def test_sentinel_prompt_prefers_action(tmp_path) -> None:
    engine = InnerLifeEngine(InnerLifeConfig(), tmp_path / "innerlife")
    engine._get_operational_surface_summary = lambda max_items=3: (  # type: ignore[assignment]
        "### Tasks\n- [P1] Investigate active failure (TASK-901, pending due 2026-03-12)"
    )

    user_message = engine._build_reflection_user_message(trigger="sentinel", force=False)
    system_prompt = engine._build_reflection_system_prompt(trigger="sentinel", force=False)

    assert "Operational cadence directive:" in user_message
    assert "choose [ACTION]" in user_message
    assert "Operational Cadence Mode" in system_prompt
    assert "## Actionable Surface" in system_prompt
    assert "TASK-901" in system_prompt
    assert "vera_memory/*" in user_message


def test_manual_verification_prompt_keeps_reachout_priority(tmp_path) -> None:
    engine = InnerLifeEngine(
        InnerLifeConfig(delivery_channels=["api"]),
        tmp_path / "innerlife",
    )
    engine._channel_dock = {"api": object()}
    engine._resolve_delivery_target = lambda channel_id, **kwargs: "api"  # type: ignore[assignment]

    user_message = engine._build_reflection_user_message(trigger="manual_verification", force=True)
    system_prompt = engine._build_reflection_system_prompt(trigger="manual_verification", force=True)

    assert "Verification directive:" in user_message
    assert "Prefer [REACH_OUT]" in user_message
    assert "Operational cadence directive:" not in user_message
    assert "Operational Cadence Mode" not in system_prompt


def test_action_opportunities_summary_reads_open_tasks(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    task_dir = tmp_path / "vera_memory"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "MASTER_TODO.md").write_text(
        "# VERA Master Task List\n\n"
        "## TASK-100 [P1] [pending] Review issue backlog\n"
        "Created: 2026-03-12T00:00:00\n"
        "Updated: 2026-03-12T00:05:00\n"
        "Due: 2026-03-12\n\n"
        "---\n\n"
        "## TASK-101 [P2] [completed] Done thing\n"
        "Created: 2026-03-12T00:00:00\n"
        "Updated: 2026-03-12T00:05:00\n"
        "Due: 2026-03-12\n",
        encoding="utf-8",
    )
    engine = InnerLifeEngine(InnerLifeConfig(), tmp_path / "innerlife")

    summary = engine._get_action_opportunities_summary()

    assert "TASK-100" in summary
    assert "Review issue backlog" in summary
    assert "pending due 2026-03-12" in summary
    assert "TASK-101" not in summary


def test_operational_surface_summary_includes_goals(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    task_dir = tmp_path / "vera_memory"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "MASTER_TODO.md").write_text(
        "# VERA Master Task List\n\n"
        "## TASK-200 [P1] [pending] Review active project queue\n"
        "Created: 2026-03-12T00:00:00\n"
        "Updated: 2026-03-12T00:05:00\n",
        encoding="utf-8",
    )
    engine = InnerLifeEngine(InnerLifeConfig(), tmp_path / "innerlife")
    engine.add_goal("Reduce proactive noise", category="self_improvement", priority=5)

    summary = engine._get_operational_surface_summary()

    assert "### Tasks" in summary
    assert "TASK-200" in summary
    assert "### Active Goals" in summary
    assert "Reduce proactive noise" in summary


def test_operational_surface_summary_includes_recent_week1_top_tasks(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    task_dir = tmp_path / "vera_memory"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "MASTER_TODO.md").write_text("# VERA Master Task List\n", encoding="utf-8")
    engine = InnerLifeEngine(InnerLifeConfig(), tmp_path / "innerlife")
    proactive_stub = SimpleNamespace(
        runplane=SimpleNamespace(
            list_runs=lambda **kwargs: [
                {
                    "job_id": "executor.week1",
                    "result": {
                        "top_tasks": [
                            "[P2] Replace/upgrade fans and light fixtures (inventory + shortlist)",
                            "[P2] Call contractor for remodel (scope + next steps)",
                        ]
                    },
                }
            ]
        ),
        _load_week1_progress_state=lambda: {
            "version": 1,
            "stages": {
                "fan_shortlist": {"done": True},
                "contractor_brief": {"done": True},
                "pressure_wash_plan": {"done": False},
                "contractor_outreach": {"done": False},
                "procurement_packet": {"done": False},
            },
        },
        _week1_stage_order=lambda: [
            "fan_shortlist",
            "contractor_brief",
            "pressure_wash_plan",
            "contractor_outreach",
            "procurement_packet",
        ],
    )
    engine._vera_instance = SimpleNamespace(proactive_manager=proactive_stub)

    summary = engine._get_operational_surface_summary()

    assert "### Week1 External Tasks" in summary
    assert "Replace/upgrade fans and light fixtures" in summary
    assert "Call contractor for remodel" in summary
    assert "### Week1 Progress" in summary
    assert "completed: fan_shortlist, contractor_brief" in summary
    assert "next_stage: pressure_wash_plan" in summary
