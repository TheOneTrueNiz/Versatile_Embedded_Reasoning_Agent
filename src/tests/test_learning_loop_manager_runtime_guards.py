"""Runtime guard regressions for LearningLoopManager manual cycle execution."""

import asyncio
from datetime import datetime, timedelta

from learning.learning_loop_manager import LearningLoopManager


def _build_stub_manager() -> LearningLoopManager:
    mgr = object.__new__(LearningLoopManager)
    mgr._diag = {
        "manual_cycle_requests": 0,
        "manual_cycles_started": 0,
        "manual_cycles_completed": 0,
        "last_manual_cycle_started_at": "",
        "last_manual_cycle_completed_at": "",
        "last_manual_cycle_error": "",
        "last_manual_cycle_result": {},
    }
    mgr._state = {"last_trace_date": "2026-02-18"}
    mgr._cycle_running = False
    mgr._trace_learning = lambda *args, **kwargs: None
    mgr._short_text = lambda value, limit=240: str(value or "")[:limit]
    mgr._daily_due_details = lambda now=None: {
        "due_now": True,
        "reason": "scheduled_time_reached",
        "last_trace_date": "2026-02-18",
        "next_due_at": "2026-02-19T02:00:00",
    }
    mgr._next_due_datetime = lambda now=None: datetime.now() + timedelta(hours=12)
    return mgr


def test_run_cycle_if_due_returns_already_running_guard() -> None:
    mgr = _build_stub_manager()
    mgr._cycle_running = True

    async def _unexpected_run():
        raise AssertionError("run_daily_learning_cycle should not be called when already running")

    mgr.run_daily_learning_cycle = _unexpected_run  # type: ignore[assignment]

    result = asyncio.run(mgr.run_daily_learning_cycle_if_due(force=True))

    assert result["ran"] is False
    assert result["reason"] == "already_running"
    assert mgr._diag["manual_cycle_requests"] == 1
    assert mgr._diag["manual_cycles_started"] == 0
    assert mgr._diag["manual_cycles_completed"] == 0


def test_run_cycle_if_due_sets_and_clears_running_flag() -> None:
    mgr = _build_stub_manager()

    async def _run_daily():
        assert mgr._cycle_running is True
        return {
            "trajectories_extracted": 1,
            "examples_from_trajectories": 2,
            "flight_ingest": {"examples_created": 3},
            "reward_training": {"trained": True},
            "lora_training": {"trained": False},
            "total_examples": 6,
        }

    mgr.run_daily_learning_cycle = _run_daily  # type: ignore[assignment]

    result = asyncio.run(mgr.run_daily_learning_cycle_if_due(force=True))

    assert result["ran"] is True
    assert mgr._cycle_running is False
    assert mgr._diag["manual_cycle_requests"] == 1
    assert mgr._diag["manual_cycles_started"] == 1
    assert mgr._diag["manual_cycles_completed"] == 1
    assert mgr._diag["last_manual_cycle_error"] == ""
    assert mgr._diag["last_manual_cycle_result"]["reward_trained"] is True


def _build_workflow_stub_manager() -> LearningLoopManager:
    mgr = object.__new__(LearningLoopManager)
    mgr._diag = {
        "workflow_replay_calls": 0,
        "workflow_replay_saved": 0,
        "workflow_replay_skip_short_chain": 0,
        "workflow_replay_last": {},
    }
    mgr._workflows = {"templates": {}}
    mgr.workflow_replay_disable_failures = 2
    mgr.workflow_disable_minutes = 180
    mgr.workflow_quarantine_minutes = 180
    mgr.workflow_quarantine_tags = [
        "tool_call_limit_reached",
        "confirmation_required",
        "cached_chain_not_completed",
        "chain_mismatch",
    ]
    mgr.workflow_min_success = 1
    mgr.workflow_min_reliability = 0.5
    mgr.workflow_reward_weight = 0.15
    mgr._trace_workflow = lambda *args, **kwargs: None
    mgr._score_workflow_transition = lambda **kwargs: 0.0
    mgr._apply_workflow_reward_score = lambda entry, score, now_iso: entry.update(
        {"reward_last_score": score, "reward_last_scored_at": now_iso}
    )
    mgr._save_workflows = lambda: None
    mgr._short_text = lambda value, limit=240: str(value or "")[:limit]
    mgr._short_task = lambda value, limit=180: str(value or "")[:limit]
    return mgr


def test_workflow_failure_tag_classification_is_strict_for_tool_limit_patterns() -> None:
    mgr = _build_workflow_stub_manager()
    assert mgr._classify_workflow_failure_tag("Tool call limit reached; unable to complete.") == "tool_call_limit_reached"
    assert mgr._classify_workflow_failure_tag("tool_call_limit_reached") == "tool_call_limit_reached"
    assert mgr._classify_workflow_failure_tag("no_progress_tool_loop:repeat_rounds=3") == "tool_call_limit_reached"
    assert mgr._classify_workflow_failure_tag("tool_timeout:search_web") == "tool_timeout"
    assert mgr._classify_workflow_failure_tag("Tool execution error: auth denied") == "tool_execution_error"
    assert mgr._classify_workflow_failure_tag("LLM request timed out after 60s") == "llm_timeout"
    assert mgr._classify_workflow_failure_tag("cached chain not completed") == "cached_chain_not_completed"


def test_record_workflow_replay_failure_propagates_quarantine_to_matching_chain() -> None:
    mgr = _build_workflow_stub_manager()
    chain = ["search_web", "summarize"]
    other_chain = ["time", "read_graph"]

    mgr._workflows["templates"] = {
        "sig_primary": mgr._normalize_workflow_entry(
            {"tool_chain": list(chain), "success_count": 2},
            signature="sig_primary",
            task_text="find latest update",
            chain=chain,
        ),
        "sig_same_chain": mgr._normalize_workflow_entry(
            {"tool_chain": list(chain), "success_count": 1},
            signature="sig_same_chain",
            task_text="lookup latest update",
            chain=chain,
        ),
        "sig_other_chain": mgr._normalize_workflow_entry(
            {"tool_chain": list(other_chain), "success_count": 4},
            signature="sig_other_chain",
            task_text="check current time",
            chain=other_chain,
        ),
    }

    mgr.record_workflow_replay_result(
        task_text="find latest update",
        tool_chain=chain,
        success=False,
        conversation_id="cid-1",
        error="Tool call limit reached; unable to complete the request.",
        signature="sig_primary",
    )

    templates = mgr._workflows["templates"]
    primary = templates["sig_primary"]
    same_chain = templates["sig_same_chain"]
    other = templates["sig_other_chain"]

    assert primary["quarantine_reason"] == "replay_failure:tool_call_limit_reached"
    assert bool(primary["quarantine_requires_fresh_success"]) is True
    assert int(primary["quarantine_propagated_count"]) >= 1

    assert same_chain["quarantine_reason"] == "propagated_replay_failure:tool_call_limit_reached"
    assert bool(same_chain["quarantine_requires_fresh_success"]) is True
    assert same_chain["quarantine_until"] != ""
    assert int(same_chain["quarantine_count"]) >= 1

    assert other["quarantine_reason"] == ""
    assert other["quarantine_until"] == ""
    assert mgr._diag["workflow_replay_saved"] == 1


def test_record_workflow_replay_failure_quarantines_tool_execution_error() -> None:
    mgr = _build_workflow_stub_manager()
    if "tool_execution_error" not in mgr.workflow_quarantine_tags:
        mgr.workflow_quarantine_tags.append("tool_execution_error")

    chain = ["create_calendar_event", "send_mobile_push"]
    mgr._workflows["templates"] = {
        "sig_tool_error": mgr._normalize_workflow_entry(
            {"tool_chain": list(chain), "success_count": 2},
            signature="sig_tool_error",
            task_text="schedule reminder",
            chain=chain,
        )
    }

    mgr.record_workflow_replay_result(
        task_text="schedule reminder",
        tool_chain=chain,
        success=False,
        conversation_id="cid-err",
        error="Tool execution error: auth denied",
        signature="sig_tool_error",
    )

    entry = mgr._workflows["templates"]["sig_tool_error"]
    assert entry["last_failure_tag"] == "tool_execution_error"
    assert entry["quarantine_reason"] == "replay_failure:tool_execution_error"
    assert bool(entry["quarantine_requires_fresh_success"]) is True


def test_get_failure_recovery_plan_returns_avoid_and_recovery_chain() -> None:
    mgr = _build_workflow_stub_manager()
    bad_chain = ["search_web", "summarize"]
    good_chain = ["brave_ai_grounding", "summarize"]

    mgr._workflows["templates"] = {
        "sig_bad": mgr._normalize_workflow_entry(
            {
                "tool_chain": list(bad_chain),
                "tokens": ["latest", "news", "summary"],
                "failure_count": 2,
                "replay_failure_count": 1,
                "last_error": "Tool call limit reached; unable to complete the request.",
                "last_failure_tag": "tool_call_limit_reached",
                "last_failure_at": datetime.now().isoformat(),
            },
            signature="sig_bad",
            task_text="find latest news summary",
            chain=bad_chain,
        ),
        "sig_good": mgr._normalize_workflow_entry(
            {
                "tool_chain": list(good_chain),
                "tokens": ["latest", "news", "summary"],
                "success_count": 4,
                "replay_success_count": 1,
                "reward_score_ema": 0.2,
                "reward_samples": 3,
            },
            signature="sig_good",
            task_text="find latest news summary",
            chain=good_chain,
        ),
    }

    plan = mgr.get_failure_recovery_plan("Please find the latest news and summarize it")

    assert plan["source_signature"] == "sig_bad"
    assert plan["source_failure_tag"] == "tool_call_limit_reached"
    assert plan["avoid_chain"] == bad_chain
    assert plan["avoid_tools"] == bad_chain
    assert plan["suggested_recovery_chain"] == good_chain
    assert plan["recovery_signature"] == "sig_good"


def test_on_daily_loop_done_restarts_loop_when_unexpectedly_cancelled() -> None:
    async def _run() -> None:
        mgr = _build_stub_manager()
        mgr._running = True
        mgr._task = None

        event = asyncio.Event()

        async def _daily_loop_wait() -> None:
            await event.wait()

        mgr._daily_loop = _daily_loop_wait  # type: ignore[assignment]

        loop = asyncio.get_running_loop()
        done_task = loop.create_task(asyncio.sleep(0))
        await done_task
        mgr._task = done_task

        mgr._on_daily_loop_done(done_task)

        assert mgr._task is not done_task
        assert mgr._task is not None
        assert not mgr._task.done()
        assert mgr._diag.get("last_start_error") in {
            "daily_loop_exited_unexpectedly",
            "daily_loop_cancelled_unexpectedly",
        }

        mgr._running = False
        event.set()
        mgr._task.cancel()
        try:
            await mgr._task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
