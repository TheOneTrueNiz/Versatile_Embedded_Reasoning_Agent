"""Regression tests for llm_bridge workflow and media-intent guardrails."""

from orchestration.llm_bridge import LLMBridge


def _make_bridge(max_tool_rounds: int = 5) -> LLMBridge:
    bridge = object.__new__(LLMBridge)
    bridge.max_tool_rounds = max_tool_rounds
    bridge.last_tool_payload = {}
    bridge._trace_workflow = lambda *args, **kwargs: None
    return bridge


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
