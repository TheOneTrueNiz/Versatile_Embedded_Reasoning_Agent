"""Regression tests for llm_bridge workflow and media-intent guardrails."""

import asyncio

from orchestration.llm_bridge import LLMBridge


def _make_bridge(max_tool_rounds: int = 5) -> LLMBridge:
    bridge = object.__new__(LLMBridge)
    bridge.max_tool_rounds = max_tool_rounds
    bridge.last_tool_payload = {}
    bridge.last_tools_used = []
    bridge._trace_workflow = lambda *args, **kwargs: None
    bridge._workflow_record_trace_debug = False
    bridge._workflow_record_diag = {"events_total": 0, "counts": {}, "last_event": {}}
    return bridge


# ------------------------------------------------------------------
# History trim tests
# ------------------------------------------------------------------


def test_trim_history_returns_unchanged_when_under_budget() -> None:
    history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
    result = LLMBridge._make_bridge_stub()._trim_history(history)
    assert result is history  # same object, no copy


def test_trim_history_compresses_old_messages() -> None:
    """Build a long history and verify trimming produces an episodic summary."""
    history = []
    for i in range(40):
        history.append({"role": "user", "content": f"Question {i} " + "x" * 200})
        history.append({"role": "assistant", "content": f"Answer {i} " + "y" * 200})
    bridge = LLMBridge._make_bridge_stub()
    result = bridge._trim_history(history)
    # Should be shorter than original
    assert len(result) < len(history)
    # First message should be the episodic summary
    assert "[Earlier conversation summary" in result[0]["content"]
    # Last messages should be verbatim from the working window
    assert result[-1] == history[-1]
    assert result[-2] == history[-2]


def test_trim_history_preserves_tool_call_pairs() -> None:
    """Tool results must never be orphaned from their tool call."""
    history = []
    # Old messages
    for i in range(20):
        history.append({"role": "user", "content": f"Q{i}"})
        history.append({"role": "assistant", "content": f"A{i}"})
    # Tool call pair right at the boundary
    history.append({"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "time", "arguments": "{}"}}
    ]})
    history.append({"role": "tool", "name": "time", "content": "2026-02-20T12:00:00Z"})
    # Recent messages
    for i in range(8):
        history.append({"role": "user", "content": f"Recent Q{i}"})
        history.append({"role": "assistant", "content": f"Recent A{i}"})

    bridge = LLMBridge._make_bridge_stub()
    result = bridge._trim_history(history)
    # No tool result should appear without its preceding assistant message
    for idx, msg in enumerate(result):
        if msg.get("role") == "tool":
            assert idx > 0, "tool result at index 0 is orphaned"
            prev = result[idx - 1]
            assert prev.get("role") == "assistant" or prev.get("tool_calls"), \
                f"tool result at index {idx} is orphaned"


def _make_bridge_stub():
    """Create a minimal LLMBridge for trim testing."""
    bridge = object.__new__(LLMBridge)
    bridge.max_tool_rounds = 5
    return bridge

LLMBridge._make_bridge_stub = staticmethod(_make_bridge_stub)


def test_detect_media_intent_video_generation_phrase() -> None:
    assert LLMBridge._detect_media_generation_intent("Lets do some video generation tonight") == "video"


def test_detect_media_intent_generate_another_video() -> None:
    prompt = "Can you generate another video? Anything you want."
    assert LLMBridge._detect_media_generation_intent(prompt) == "video"


def test_detect_media_intent_generate_another_image() -> None:
    prompt = "Please generate another image in watercolor style"
    assert LLMBridge._detect_media_generation_intent(prompt) == "image"


def test_should_accept_workflow_chain_rejects_budget_overflow() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    accepted, reason = bridge._should_accept_workflow_chain(
        context="execute the task",
        workflow_plan={"source": "direct"},
        workflow_chain=["a", "b", "c", "d", "e"],
        explicit_tools=[],
        forced_tool=None,
    )

    assert accepted is False
    assert reason == "chain_exceeds_budget:5>4"


def test_resolve_runtime_plan_skips_over_budget_chain() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    bridge.last_tool_payload = {
        "workflow_plan": {
            "signature": "sig1",
            "tool_chain": ["a", "b", "c", "d", "e"],
            "source": "direct",
        },
        "workflow_suggested_chain": ["a", "b", "c", "d", "e"],
    }

    plan = bridge._resolve_workflow_runtime_plan(
        task_text="execute the task",
        available_tools=["a", "b", "c", "d", "e"],
        existing_tool_choice=None,
    )

    assert plan == {}


def test_resolve_runtime_plan_accepts_within_budget_chain() -> None:
    bridge = _make_bridge(max_tool_rounds=8)
    bridge.last_tool_payload = {
        "workflow_plan": {
            "signature": "sig2",
            "tool_chain": ["a", "b", "c", "d", "e"],
            "source": "direct",
        },
        "workflow_suggested_chain": ["a", "b", "c", "d", "e"],
    }

    plan = bridge._resolve_workflow_runtime_plan(
        task_text="execute the task",
        available_tools=["a", "b", "c", "d", "e"],
        existing_tool_choice=None,
    )

    assert plan.get("active") is True
    assert plan.get("tool_chain") == ["a", "b", "c", "d", "e"]
    assert plan.get("forced_steps") == 0


def test_tool_calls_signature_is_stable_for_json_key_order() -> None:
    calls_a = [
        {
            "function": {
                "name": "search_files",
                "arguments": "{\"path\":\"src\",\"query\":\"vera\",\"limit\":5}",
            }
        }
    ]
    calls_b = [
        {
            "function": {
                "name": "search_files",
                "arguments": "{\"limit\":5,\"query\":\"vera\",\"path\":\"src\"}",
            }
        }
    ]
    assert LLMBridge._tool_calls_signature(calls_a) == LLMBridge._tool_calls_signature(calls_b)


def test_tool_calls_signature_changes_when_arguments_change() -> None:
    calls_a = [{"function": {"name": "time", "arguments": "{\"timezone\":\"UTC\"}"}}]
    calls_b = [{"function": {"name": "time", "arguments": "{\"timezone\":\"America/Chicago\"}"}}]
    assert LLMBridge._tool_calls_signature(calls_a) != LLMBridge._tool_calls_signature(calls_b)


def test_tool_loop_no_progress_limit_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("VERA_TOOL_LOOP_NO_PROGRESS_LIMIT", raising=False)
    bridge = _make_bridge(max_tool_rounds=5)
    assert bridge._tool_loop_no_progress_limit() == 3

    monkeypatch.setenv("VERA_TOOL_LOOP_NO_PROGRESS_LIMIT", "2")
    assert bridge._tool_loop_no_progress_limit() == 2


def test_tool_failure_retry_limit_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("VERA_TOOL_FAILURE_RETRY_LIMIT", raising=False)
    bridge = _make_bridge(max_tool_rounds=5)
    assert bridge._tool_failure_retry_limit() == 2

    monkeypatch.setenv("VERA_TOOL_FAILURE_RETRY_LIMIT", "4")
    assert bridge._tool_failure_retry_limit() == 4


def test_tools_for_round_filters_disabled_tools() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    tools = [
        {"type": "function", "function": {"name": "time"}},
        {"type": "function", "function": {"name": "search_files"}},
    ]
    filtered = bridge._tools_for_round(tools, {"search_files"})
    assert [tool["function"]["name"] for tool in filtered] == ["time"]


def test_forced_tool_choice_name_parses_function_tool() -> None:
    forced = {"type": "function", "function": {"name": "generate_image"}}
    assert LLMBridge._forced_tool_choice_name(forced) == "generate_image"
    assert LLMBridge._forced_tool_choice_name("none") == ""


def test_llm_request_timeout_defaults_to_bridge_timeout(monkeypatch) -> None:
    monkeypatch.delenv("VERA_LLM_REQUEST_TIMEOUT_SECONDS", raising=False)
    bridge = _make_bridge(max_tool_rounds=5)
    bridge.timeout = 42.0
    assert bridge._llm_request_timeout_seconds() == 42.0


def test_final_failure_response_maps_timeout_errors() -> None:
    assert LLMBridge._final_failure_response("tool_timeout:search_web") == (
        "Tool execution timed out; stopped safely. Please retry with a narrower request."
    )
    assert LLMBridge._final_failure_response("llm_timeout:request timed out") == (
        "Model request timed out; recovered safely. Please retry with a narrower request."
    )
    assert LLMBridge._final_failure_response("llm_call_failed:provider unavailable") == (
        "Model call failed; recovered safely. Please retry."
    )
    assert LLMBridge._final_failure_response("no_progress_tool_loop:repeat_rounds=3") == (
        "Tool loop made no progress; aborted safely. Please rephrase or narrow the request."
    )


def test_workflow_record_trace_event_updates_snapshot_and_payload() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    bridge._record_workflow_trace_event(
        "outcome_call",
        success=True,
        chain=["search_web", "summarize"],
        conversation_id="default",
    )

    snapshot = bridge._workflow_recording_snapshot()
    assert snapshot["events_total"] == 1
    assert snapshot["counts"]["outcome_call"] == 1
    assert snapshot["last_event"]["event"] == "outcome_call"
    assert "workflow_recording" in bridge.last_tool_payload


def test_get_last_tool_payload_includes_workflow_recording_snapshot() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    bridge.last_tool_payload = {"tool_count": 1}
    bridge._record_workflow_trace_event("replay_skip_empty_plan", conversation_id="default")

    payload = bridge.get_last_tool_payload()
    assert payload["workflow_recording"]["events_total"] == 1
    assert payload["workflow_recording"]["last_event"]["event"] == "replay_skip_empty_plan"


def test_emit_routing_signals_records_failed_tools_for_memory_learning() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    captured = {}

    class _ToolSelection:
        def record_routing_outcome(self, **kwargs):
            captured.update(kwargs)

    class _Vera:
        def __init__(self) -> None:
            self.flight_recorder = None
            self.tool_selection = _ToolSelection()

    bridge.vera = _Vera()
    bridge.model = "grok-test"
    bridge._last_routing_meta = {
        "tool_confidence": {},
        "pass1_confidence": 0.4,
        "used_llm_router": False,
    }
    bridge._active_workflow_plan = {"reward_score_ema": 0.25}

    bridge._emit_routing_signals(
        user_message="find latest update",
        selected_categories=["web"],
        model_override="grok-test",
        model_reason="default_reasoning",
        tools_used=["search_web", "summarize"],
        tools_failed=["summarize"],
        conversation_id="default",
    )

    assert captured["tools_used"] == ["search_web", "summarize"]
    assert captured["tools_succeeded"] == ["search_web"]
    assert captured["context"]["failed_tools"] == ["summarize"]
    assert captured["tool_reward_scores"]["summarize"] <= -0.6


def test_get_system_prompt_append_mode_preserves_base_prompt(monkeypatch) -> None:
    monkeypatch.delenv("VERA_SYSTEM_OVERRIDE_MODE", raising=False)

    class _FakeVera:
        def __init__(self) -> None:
            self.last_build_args = None

        async def get_relevant_past_corrections(self, _last_user: str):
            return ["keep responses concise"]

        def build_system_prompt(self, **kwargs):
            self.last_build_args = dict(kwargs)
            return "BASE_PROMPT"

    bridge = _make_bridge(max_tool_rounds=5)
    bridge.vera = _FakeVera()

    prompt = asyncio.run(
        bridge._get_system_prompt(
            "hello vera",
            system_override="Follow caller formatting.",
            conversation_id="cid-123",
        )
    )

    assert prompt.startswith("BASE_PROMPT")
    assert "## Caller System Addendum" in prompt
    assert "Follow caller formatting." in prompt
    assert bridge.vera.last_build_args["conversation_id"] == "cid-123"
    assert bridge.vera.last_build_args["router_context"] == "hello vera"
    assert bridge.vera.last_build_args["memory_constraints"] == ["keep responses concise"]


def test_get_system_prompt_replace_mode_returns_override(monkeypatch) -> None:
    monkeypatch.setenv("VERA_SYSTEM_OVERRIDE_MODE", "replace")

    class _FakeVera:
        async def get_relevant_past_corrections(self, _last_user: str):
            return []

        def build_system_prompt(self, **kwargs):
            return "BASE_PROMPT"

    bridge = _make_bridge(max_tool_rounds=5)
    bridge.vera = _FakeVera()

    prompt = asyncio.run(
        bridge._get_system_prompt(
            "hello vera",
            system_override="Caller-only directives.",
            conversation_id="cid-456",
        )
    )

    assert prompt == "Caller-only directives."


def test_tool_limit_fallback_completion_returns_sanitized_content() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    bridge._sanitize_response_text = lambda text: " ".join(str(text).split())
    bridge._record_workflow_trace_event = lambda *args, **kwargs: None
    bridge._trace_workflow = lambda *args, **kwargs: None

    async def _fake_call_chat(*args, **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Fallback   complete",
                    }
                }
            ]
        }

    bridge._call_chat = _fake_call_chat
    history = [{"role": "user", "content": "test"}]

    text = asyncio.run(
        bridge._attempt_tool_limit_fallback_completion(
            system_prompt="BASE",
            history_ref=history,
            model_override="grok-4-1-fast-reasoning",
            generation_config=None,
            conversation_id="cid-fallback",
        )
    )

    assert text == "Fallback complete"
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "Fallback complete"


def test_tool_limit_fallback_completion_handles_call_errors() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    bridge._sanitize_response_text = lambda text: str(text)
    bridge._record_workflow_trace_event = lambda *args, **kwargs: None
    bridge._trace_workflow = lambda *args, **kwargs: None

    async def _fake_call_chat(*args, **kwargs):
        raise RuntimeError("simulated fallback error")

    bridge._call_chat = _fake_call_chat
    history = [{"role": "user", "content": "test"}]

    text = asyncio.run(
        bridge._attempt_tool_limit_fallback_completion(
            system_prompt="BASE",
            history_ref=history,
            model_override="grok-4-1-fast-reasoning",
            generation_config=None,
            conversation_id="cid-fallback",
        )
    )

    assert text == ""
    assert len(history) == 1
