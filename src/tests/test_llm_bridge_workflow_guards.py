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


def test_should_accept_workflow_chain_rejects_avoid_tools_overlap() -> None:
    bridge = _make_bridge(max_tool_rounds=6)

    accepted, reason = bridge._should_accept_workflow_chain(
        context="execute the task",
        workflow_plan={"source": "direct"},
        workflow_chain=["search_web", "create_event", "send_mobile_push"],
        explicit_tools=[],
        forced_tool=None,
        avoid_tools=["create_event"],
    )

    assert accepted is False
    assert reason.startswith("avoid_tools_overlap:")


def test_should_accept_workflow_chain_rejects_high_failure_penalty() -> None:
    bridge = _make_bridge(max_tool_rounds=6)

    accepted, reason = bridge._should_accept_workflow_chain(
        context="execute the task",
        workflow_plan={"source": "direct", "failure_penalty": 0.95},
        workflow_chain=["search_web", "summarize"],
        explicit_tools=[],
        forced_tool=None,
    )

    assert accepted is False
    assert reason.startswith("failure_penalty:")


def test_apply_failure_recovery_override_replaces_risky_chain() -> None:
    override = LLMBridge._apply_failure_recovery_override(
        workflow_plan={"source": "fuzzy", "failure_penalty": 0.9},
        workflow_chain=["search_web", "summarize"],
        failure_plan={
            "avoid_tools": ["search_web"],
            "suggested_recovery_chain": ["brave_ai_grounding", "summarize"],
        },
        allowed_names=["search_web", "summarize", "brave_ai_grounding"],
    )

    assert override["applied"] is True
    assert override["reason"] in {"avoid_overlap", "high_failure_penalty"}
    assert override["tool_chain"] == ["brave_ai_grounding", "summarize"]


def test_apply_failure_recovery_override_rejects_avoid_overlapping_recovery_chain() -> None:
    override = LLMBridge._apply_failure_recovery_override(
        workflow_plan={"source": "fuzzy", "failure_penalty": 0.95},
        workflow_chain=["time", "read_file", "calculate"],
        failure_plan={
            "avoid_tools": ["time", "read_file", "calculate"],
            "suggested_recovery_chain": ["read_file", "write_file"],
        },
        allowed_names=["time", "read_file", "calculate", "write_file"],
    )

    assert override["applied"] is False
    assert override["reason"] == "recovery_chain_avoid_overlap"


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


def test_select_mcp_tool_shortlist_prefers_context_relevant_tools() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Please check my calendar event and create a reminder",
        candidates={
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "create_event": {
                "description": "Create a calendar reminder or appointment.",
                "server": "google-workspace",
                "raw_name": "create_event",
            },
            "github_search_repos": {
                "description": "Search GitHub repositories and code.",
                "server": "github",
                "raw_name": "github_search_repos",
            },
        },
        limit=2,
    )

    assert "get_events" in selected
    assert "create_event" in selected
    assert "github_search_repos" not in selected


def test_select_mcp_tool_shortlist_preserves_forced_tools() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Summarize the latest benchmarks",
        candidates={
            "brave_ai_grounding": {
                "description": "Ground web results with citations.",
                "server": "brave-search",
                "raw_name": "brave_ai_grounding",
            },
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "send_native_push": {
                "description": "Send a native push notification.",
                "server": "call-me",
                "raw_name": "send_native_push",
            },
        },
        limit=1,
        preserve=["send_native_push"],
    )

    assert "send_native_push" in selected


def test_select_mcp_tool_shortlist_biases_calendar_workspace_tools() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar events and reminders for today",
        candidates={
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "brave_spellcheck": {
                "description": "Check spelling in a text input.",
                "server": "brave-search",
                "raw_name": "brave_spellcheck",
            },
            "clone_element_complete": {
                "description": "Clone an extracted browser element to a new artifact.",
                "server": "browserbase",
                "raw_name": "clone_element_complete",
            },
        },
        limit=2,
    )

    assert selected == ["get_events", "list_calendars"]


def test_select_mcp_tool_shortlist_penalizes_drive_tools_for_calendar_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar events and reminders for today",
        candidates={
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "modify_event": {
                "description": "Update an existing calendar event or reminder.",
                "server": "google-workspace",
                "raw_name": "modify_event",
            },
            "get_drive_file_content": {
                "description": "Read the content of a Google Drive file.",
                "server": "google-workspace",
                "raw_name": "get_drive_file_content",
            },
            "check_drive_file_public_access": {
                "description": "Check whether a Google Drive file is publicly accessible.",
                "server": "google-workspace",
                "raw_name": "check_drive_file_public_access",
            },
        },
        limit=3,
    )

    assert set(selected) == {"get_events", "list_calendars", "modify_event"}


def test_select_mcp_tool_shortlist_penalizes_web_and_browser_tools_for_calendar_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar events and reminders for today",
        candidates={
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "modify_event": {
                "description": "Update an existing calendar event or reminder.",
                "server": "google-workspace",
                "raw_name": "modify_event",
            },
            "brave_web_search": {
                "description": "Search the web for public information.",
                "server": "brave-search",
                "raw_name": "brave_web_search",
            },
            "extract_element_events": {
                "description": "Extract browser events from page elements.",
                "server": "browserbase",
                "raw_name": "extract_element_events",
            },
        },
        limit=3,
    )

    assert set(selected) == {"get_events", "list_calendars", "modify_event"}


def test_select_mcp_tool_shortlist_penalizes_gmail_tools_for_calendar_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar events and reminders for today",
        candidates={
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "modify_event": {
                "description": "Update an existing calendar event or reminder.",
                "server": "google-workspace",
                "raw_name": "modify_event",
            },
            "search_gmail_messages": {
                "description": "Search Gmail messages and inbox threads.",
                "server": "google-workspace",
                "raw_name": "search_gmail_messages",
            },
            "draft_gmail_message": {
                "description": "Create a Gmail draft message.",
                "server": "google-workspace",
                "raw_name": "draft_gmail_message",
            },
        },
        limit=3,
    )

    assert set(selected) == {"get_events", "list_calendars", "modify_event"}


def test_select_mcp_tool_shortlist_penalizes_support_tools_for_calendar_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar events and reminders for today",
        candidates={
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "modify_event": {
                "description": "Update an existing calendar event or reminder.",
                "server": "google-workspace",
                "raw_name": "modify_event",
            },
            "sequentialthinking": {
                "description": "Step-by-step reasoning tool.",
                "server": "sequential-thinking",
                "raw_name": "sequentialthinking",
            },
            "marm_notebook_status": {
                "description": "Inspect Marm notebook state.",
                "server": "marm-memory",
                "raw_name": "marm_notebook_status",
            },
        },
        limit=3,
    )

    assert set(selected) == {"get_events", "list_calendars", "modify_event"}


def test_select_mcp_tool_shortlist_penalizes_filesystem_tools_for_calendar_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar events and reminders for today",
        candidates={
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "modify_event": {
                "description": "Update an existing calendar event or reminder.",
                "server": "google-workspace",
                "raw_name": "modify_event",
            },
            "list_allowed_directories": {
                "description": "List allowed directories for filesystem access.",
                "server": "filesystem",
                "raw_name": "list_allowed_directories",
            },
            "search_files": {
                "description": "Search files by name or content.",
                "server": "filesystem",
                "raw_name": "search_files",
            },
        },
        limit=3,
    )

    assert set(selected) == {"get_events", "list_calendars", "modify_event"}


def test_select_mcp_tool_shortlist_penalizes_obsidian_alias_tools_for_calendar_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar for upcoming events and reminders. If there are any today, summarize them briefly.",
        candidates={
            "create_event": {
                "description": "Create a calendar reminder or appointment.",
                "server": "google-workspace",
                "raw_name": "create_event",
            },
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "modify_event": {
                "description": "Update an existing calendar event or reminder.",
                "server": "google-workspace",
                "raw_name": "modify_event",
            },
            "obsidian_vault__list_allowed_directories": {
                "description": "List directories that the Obsidian vault bridge can access.",
                "server": "obsidian-vault",
                "raw_name": "list_allowed_directories",
            },
        },
        limit=4,
    )

    assert set(selected) == {"create_event", "get_events", "list_calendars", "modify_event"}


def test_select_mcp_tool_shortlist_penalizes_live_gmail_batch_tools_for_calendar_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar for upcoming events and reminders. If there are any today, summarize them briefly.",
        candidates={
            "create_event": {
                "description": "Create a calendar reminder or appointment.",
                "server": "google-workspace",
                "raw_name": "create_event",
            },
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "modify_event": {
                "description": "Update an existing calendar event or reminder.",
                "server": "google-workspace",
                "raw_name": "modify_event",
            },
            "get_gmail_messages_content_batch": {
                "description": "Fetch Gmail message content in batch.",
                "server": "google-workspace",
                "raw_name": "get_gmail_messages_content_batch",
            },
            "get_gmail_threads_content_batch": {
                "description": "Fetch Gmail thread content in batch.",
                "server": "google-workspace",
                "raw_name": "get_gmail_threads_content_batch",
            },
        },
        limit=4,
    )

    assert set(selected) == {"create_event", "get_events", "list_calendars", "modify_event"}


def test_select_mcp_tool_shortlist_penalizes_auth_tools_for_calendar_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar for upcoming events and reminders. If there are any today, summarize them briefly.",
        candidates={
            "create_event": {
                "description": "Create a calendar reminder or appointment.",
                "server": "google-workspace",
                "raw_name": "create_event",
            },
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "modify_event": {
                "description": "Update an existing calendar event or reminder.",
                "server": "google-workspace",
                "raw_name": "modify_event",
            },
            "start_google_auth": {
                "description": "Start Google authentication flow.",
                "server": "google-workspace",
                "raw_name": "start_google_auth",
            },
        },
        limit=4,
    )

    assert set(selected) == {"create_event", "get_events", "list_calendars", "modify_event"}


def test_select_mcp_tool_shortlist_penalizes_document_tools_for_calendar_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar for upcoming events and reminders. If there are any today, summarize them briefly.",
        candidates={
            "create_event": {
                "description": "Create a calendar reminder or appointment.",
                "server": "google-workspace",
                "raw_name": "create_event",
            },
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "modify_event": {
                "description": "Update an existing calendar event or reminder.",
                "server": "google-workspace",
                "raw_name": "modify_event",
            },
            "create_document_comment": {
                "description": "Create a comment in a Google document.",
                "server": "google-workspace",
                "raw_name": "create_document_comment",
            },
        },
        limit=4,
    )

    assert set(selected) == {"create_event", "get_events", "list_calendars", "modify_event"}


def test_is_pure_calendar_intent_only_for_calendar_without_other_intents() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    assert bridge._is_pure_calendar_intent({"calendar"}) is True
    assert bridge._is_pure_calendar_intent({"calendar", "workspace"}) is True
    assert bridge._is_pure_calendar_intent({"calendar", "web"}) is False
    assert bridge._is_pure_calendar_intent({"calendar", "auth"}) is False
    assert bridge._is_pure_calendar_intent({"calendar", "messaging"}) is False


def test_is_pure_local_memory_intent_only_for_local_memory_without_other_intents() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    assert bridge._is_pure_local_memory_intent({"local"}) is True
    assert bridge._is_pure_local_memory_intent({"memory"}) is True
    assert bridge._is_pure_local_memory_intent({"local", "memory"}) is True
    assert bridge._is_pure_local_memory_intent({"local", "web"}) is False
    assert bridge._is_pure_local_memory_intent({"memory", "workspace"}) is False
    assert bridge._is_pure_local_memory_intent({"local", "calendar"}) is False


def test_tool_shortlist_intents_does_not_treat_local_llm_phrase_as_local_files_intent() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    intents = bridge._tool_shortlist_intents(
        "Research the latest public information about local LLM inference acceleration and summarize the top findings with sources."
    )

    assert "web" in intents
    assert "local" not in intents


def test_is_pure_web_research_intent_only_for_web_without_other_intents() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    assert bridge._is_pure_web_research_intent({"web"}) is True
    assert bridge._is_pure_web_research_intent({"web", "calendar"}) is False
    assert bridge._is_pure_web_research_intent({"web", "workspace"}) is False
    assert bridge._is_pure_web_research_intent({"web", "local"}) is False
    assert bridge._is_pure_web_research_intent({"web", "memory"}) is False


def test_select_mcp_tool_shortlist_penalizes_memvid_for_calendar_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Check my calendar for upcoming events and reminders. If there are any today, summarize them briefly.",
        candidates={
            "create_event": {
                "description": "Create a calendar reminder or appointment.",
                "server": "google-workspace",
                "raw_name": "create_event",
            },
            "get_events": {
                "description": "List calendar events and upcoming appointments.",
                "server": "google-workspace",
                "raw_name": "get_events",
            },
            "list_calendars": {
                "description": "List the user's calendars and reminder sources.",
                "server": "google-workspace",
                "raw_name": "list_calendars",
            },
            "modify_event": {
                "description": "Update an existing calendar event or reminder.",
                "server": "google-workspace",
                "raw_name": "modify_event",
            },
            "memvid_encode_text": {
                "description": "Archive text into QR-code video plus semantic index.",
                "server": "memvid",
                "raw_name": "memvid_encode_text",
            },
        },
        limit=4,
    )

    assert set(selected) == {"create_event", "get_events", "list_calendars", "modify_event"}


def test_select_mcp_tool_shortlist_penalizes_web_and_memvid_for_local_memory_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Inspect the local Vera project files and memory notes to find the latest diary checkpoint about autonomy work.",
        candidates={
            "editor_read": {
                "description": "Read local project files from the workspace.",
                "server": "filesystem",
                "raw_name": "editor_read",
            },
            "search_files": {
                "description": "Search local files and notes by keyword.",
                "server": "filesystem",
                "raw_name": "search_files",
            },
            "retrieve_memory": {
                "description": "Retrieve relevant memory entries and diary notes.",
                "server": "memory",
                "raw_name": "retrieve_memory",
            },
            "read_multiple_files": {
                "description": "Read multiple local files from the project or vault.",
                "server": "obsidian-vault",
                "raw_name": "read_multiple_files",
            },
            "brave_local_search": {
                "description": "Search the web for public information.",
                "server": "brave-search",
                "raw_name": "brave_local_search",
            },
            "memvid_encode_text": {
                "description": "Archive text into QR-code video plus semantic index.",
                "server": "memvid",
                "raw_name": "memvid_encode_text",
            },
        },
        limit=4,
    )

    assert set(selected) == {"editor_read", "search_files", "retrieve_memory", "read_multiple_files"}


def test_select_mcp_tool_shortlist_penalizes_browserbase_files_and_memvid_for_web_research_queries() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Research the latest public information about local LLM inference acceleration and summarize the top findings with sources.",
        candidates={
            "brave_ai_grounding": {
                "description": "Ground public web results with citations.",
                "server": "brave-search",
                "raw_name": "brave_ai_grounding",
            },
            "brave_summarize": {
                "description": "Summarize search results and sources from the web.",
                "server": "brave-search",
                "raw_name": "brave_summarize",
            },
            "clone_element_to_file": {
                "description": "Clone a browser element and save it to a file.",
                "server": "stealth-browser",
                "raw_name": "clone_element_to_file",
            },
            "get_active_tab": {
                "description": "Inspect the active browser tab.",
                "server": "stealth-browser",
                "raw_name": "get_active_tab",
            },
            "get_file_info": {
                "description": "Retrieve detailed metadata about a local file or directory.",
                "server": "filesystem",
                "raw_name": "get_file_info",
            },
            "memvid_encode_text": {
                "description": "Archive text into QR-code video plus semantic index.",
                "server": "memvid",
                "raw_name": "memvid_encode_text",
            },
            "github_search_repos": {
                "description": "Search GitHub repositories and code.",
                "server": "github",
                "raw_name": "github_search_repos",
            },
        },
        limit=2,
    )

    assert set(selected) == {"brave_ai_grounding", "brave_summarize"}


def test_select_mcp_tool_shortlist_penalizes_local_and_video_search_for_generic_web_research() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    selected = bridge._select_mcp_tool_shortlist(
        context="Research the latest public information about local LLM inference acceleration and summarize the top findings with sources.",
        candidates={
            "brave_ai_grounding": {
                "description": "Ground public web results with citations.",
                "server": "brave-search",
                "raw_name": "brave_ai_grounding",
            },
            "brave_summarize": {
                "description": "Summarize search results and sources from the web.",
                "server": "brave-search",
                "raw_name": "brave_summarize",
            },
            "brave_news_search": {
                "description": "Search recent news and latest public developments.",
                "server": "brave-search",
                "raw_name": "brave_news_search",
            },
            "get_page_citations": {
                "description": "Retrieve citations and source references for an article.",
                "server": "grokipedia",
                "raw_name": "get_page_citations",
            },
            "brave_local_search": {
                "description": "Search for local places, businesses, addresses, and nearby results.",
                "server": "brave-search",
                "raw_name": "brave_local_search",
            },
            "brave_video_search": {
                "description": "Search for videos and lectures on a topic.",
                "server": "brave-search",
                "raw_name": "brave_video_search",
            },
        },
        limit=4,
    )

    assert "brave_local_search" not in selected
    assert "brave_video_search" not in selected
    assert set(selected) == {"brave_ai_grounding", "brave_summarize", "brave_news_search", "get_page_citations"}


def test_tool_shortlist_blocked_does_not_treat_prevent_as_calendar_event() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    blocked = bridge._tool_shortlist_blocked(
        context_intents={"calendar"},
        context_text="check my calendar for events",
        server_name="google-workspace",
        exposed_name="get_gmail_messages_content_batch",
        raw_name="get_gmail_messages_content_batch",
        haystack=(
            "get_gmail_messages_content_batch get_gmail_messages_content_batch google-workspace "
            "Retrieves the content of multiple Gmail messages in a single batch request. "
            "Supports up to 25 messages per batch to prevent SSL connection exhaustion."
        ).lower(),
    )

    assert blocked is True


def test_tool_shortlist_blocked_does_not_treat_connection_as_auth_connect() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    blocked = bridge._tool_shortlist_blocked(
        context_intents={"calendar"},
        context_text="check my calendar for events",
        server_name="google-workspace",
        exposed_name="get_gmail_threads_content_batch",
        raw_name="get_gmail_threads_content_batch",
        haystack=(
            "get_gmail_threads_content_batch get_gmail_threads_content_batch google-workspace "
            "Retrieves the content of multiple Gmail threads in a single batch request to prevent "
            "SSL connection exhaustion."
        ).lower(),
    )

    assert blocked is True


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
    assert LLMBridge._final_failure_response("tool_auth_required:create_event") == (
        "Tool authorization is required before continuing. Re-authorize and retry."
    )
    assert LLMBridge._final_failure_response("tool_rate_limited:send_mobile_push") == (
        "Tool calls were rate-limited; please retry in a moment."
    )
    assert LLMBridge._final_failure_response("tool_quota_exceeded:generate_video") == (
        "Tool quota was exceeded; retry later or adjust limits."
    )
    assert LLMBridge._final_failure_response("tool_execution_error:list_tasks") == (
        "Tool execution failed; recovered safely. Please retry or narrow the request."
    )


def test_non_retryable_tool_failure_classifier() -> None:
    assert LLMBridge._is_non_retryable_tool_failure("confirmation_required:send_gmail_message")
    assert LLMBridge._is_non_retryable_tool_failure("tool_auth_required:create_event")
    assert LLMBridge._is_non_retryable_tool_failure("tool_rate_limited:send_mobile_push")
    assert LLMBridge._is_non_retryable_tool_failure("tool_quota_exceeded:generate_video")
    assert LLMBridge._is_non_retryable_tool_failure("tool_execution_error:list_tasks")
    assert LLMBridge._is_non_retryable_tool_failure("Tool execution unavailable for: create_event")
    assert not LLMBridge._is_non_retryable_tool_failure("tool_timeout:create_event")
    assert not LLMBridge._is_non_retryable_tool_failure("no_progress_tool_loop:repeat_rounds=3")


def test_mark_tool_round_budget_exhausted_sets_classified_error_and_abandon_reason() -> None:
    plan = {"active": True, "forced_steps": 2}
    error = LLMBridge._mark_tool_round_budget_exhausted(plan, "")
    assert error == "tool_call_limit_reached"
    assert plan["active"] is False
    assert plan["abandon_reason"] == "tool_call_limit_reached"


def test_mark_tool_round_budget_exhausted_preserves_existing_error() -> None:
    plan = {"active": True}
    error = LLMBridge._mark_tool_round_budget_exhausted(plan, "tool_timeout:search_web")
    assert error == "tool_timeout:search_web"
    assert plan["active"] is False
    assert plan["abandon_reason"] == "tool_call_limit_reached"


def test_tool_result_indicates_failure_and_classification() -> None:
    assert LLMBridge._tool_result_indicates_failure("Error: missing token")
    assert LLMBridge._tool_result_indicates_failure(
        "**ACTION REQUIRED: Google Authentication Needed for Google Calendar**"
    )
    assert LLMBridge._tool_result_indicates_failure("⚠️ Tool quota exceeded for google-workspace")
    assert not LLMBridge._tool_result_indicates_failure("All good. Created 3 events.")

    assert (
        LLMBridge._classify_tool_result_failure(
            "create_event",
            "**ACTION REQUIRED: Google Authentication Needed for Google Calendar**",
        )
        == "tool_auth_required:create_event"
    )
    assert (
        LLMBridge._classify_tool_result_failure(
            "send_mobile_push",
            "Rate limit exceeded. Retry in 10s.",
        )
        == "tool_rate_limited:send_mobile_push"
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


def test_trim_tool_payload_caps_debug_rows_and_aliases(monkeypatch) -> None:
    monkeypatch.setenv("VERA_TOOL_PAYLOAD_ROW_LIMIT", "2")
    monkeypatch.setenv("VERA_TOOL_PAYLOAD_ALIAS_LIMIT", "1")
    monkeypatch.setenv("VERA_TOOL_PAYLOAD_TEXT_LIMIT", "32")

    payload = LLMBridge._trim_tool_payload(
        {
            "mcp_shortlist_names": ["a", "b", "c"],
            "mcp_shortlist_preserve_names": ["x", "y", "z"],
            "mcp_shortlist_rows": {
                "a": {"server": "alpha", "raw_name": "tool_a", "description": "A" * 80},
                "b": {"server": "beta", "raw_name": "tool_b", "description": "B" * 80},
                "c": {"server": "gamma", "raw_name": "tool_c", "description": "C" * 80},
            },
            "tool_aliases": {
                "alias_a": {"server": "obsidian-vault", "tool": "read_file", "extra": "ignored"},
                "alias_b": {"server": "filesystem", "tool": "read_file"},
            },
        }
    )

    assert payload["mcp_shortlist_names"] == ["a", "b"]
    assert payload["mcp_shortlist_names_total"] == 3
    assert payload["mcp_shortlist_names_truncated"] is True
    assert payload["mcp_shortlist_preserve_names"] == ["x", "y"]
    assert payload["mcp_shortlist_preserve_names_total"] == 3
    assert payload["mcp_shortlist_preserve_names_truncated"] is True
    assert list(payload["mcp_shortlist_rows"].keys()) == ["a", "b"]
    assert payload["mcp_shortlist_rows_total"] == 3
    assert payload["mcp_shortlist_rows_truncated"] is True
    assert payload["mcp_shortlist_rows"]["a"]["description"].endswith("...")
    assert payload["tool_aliases_total"] == 2
    assert payload["tool_aliases_truncated"] is True
    assert list(payload["tool_aliases"].keys()) == ["alias_a"]
    assert payload["tool_aliases"]["alias_a"] == {"server": "obsidian-vault", "tool": "read_file"}


def test_workflow_recording_snapshot_includes_override_metrics() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    bridge._record_workflow_trace_event("failure_recovery_override_applied", reason="avoid_overlap")
    bridge._record_workflow_trace_event("replay_override_done", success=True)
    bridge._record_workflow_trace_event("replay_override_error", success=False)

    snapshot = bridge._workflow_recording_snapshot()
    override = snapshot["failure_recovery_override"]
    assert override["applied"] == 1
    assert override["replayed"] == 2
    assert override["successes"] == 1
    assert override["failures"] == 1
    assert override["success_rate_pct"] == 50.0
    assert override["replay_rate_pct"] == 200.0


def test_record_workflow_replay_result_tracks_override_success_event() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    class _LearningLoop:
        def record_workflow_replay_result(self, **kwargs):
            return None

    class _Vera:
        def __init__(self) -> None:
            self.learning_loop = _LearningLoop()

    bridge.vera = _Vera()
    bridge._trace_workflow = lambda *args, **kwargs: None
    workflow_plan = {
        "signature": "sig-override",
        "tool_chain": ["search_web", "summarize"],
        "forced_steps": 2,
        "failure_recovery_override": True,
    }

    bridge._record_workflow_replay_result(
        task_text="find latest news",
        workflow_plan=workflow_plan,
        success=True,
        conversation_id="default",
        error="",
    )

    snapshot = bridge._workflow_recording_snapshot()
    counts = snapshot["counts"]
    assert counts["replay_done"] >= 1
    assert counts["replay_override_done"] >= 1
    assert snapshot["failure_recovery_override"]["successes"] >= 1


def test_record_workflow_replay_result_tracks_override_failure_event() -> None:
    bridge = _make_bridge(max_tool_rounds=5)

    class _LearningLoop:
        def record_workflow_replay_result(self, **kwargs):
            raise RuntimeError("simulated replay write failure")

    class _Vera:
        def __init__(self) -> None:
            self.learning_loop = _LearningLoop()

    bridge.vera = _Vera()
    bridge._trace_workflow = lambda *args, **kwargs: None
    workflow_plan = {
        "signature": "sig-override",
        "tool_chain": ["search_web", "summarize"],
        "forced_steps": 2,
        "failure_recovery_override": True,
    }

    bridge._record_workflow_replay_result(
        task_text="find latest news",
        workflow_plan=workflow_plan,
        success=False,
        conversation_id="default",
        error="tool_timeout:search_web",
    )

    snapshot = bridge._workflow_recording_snapshot()
    counts = snapshot["counts"]
    assert counts["replay_error"] >= 1
    assert counts["replay_override_error"] >= 1
    assert snapshot["failure_recovery_override"]["failures"] >= 1


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
    bridge._sanitize_response_text = lambda text, **kwargs: " ".join(str(text).split())
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
            model_override="grok-4.20-experimental-beta-0304-reasoning",
            generation_config=None,
            conversation_id="cid-fallback",
        )
    )

    assert text == "Fallback complete"
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "Fallback complete"


def test_tool_limit_fallback_completion_handles_call_errors() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    bridge._sanitize_response_text = lambda text, **kwargs: str(text)
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
            model_override="grok-4.20-experimental-beta-0304-reasoning",
            generation_config=None,
            conversation_id="cid-fallback",
        )
    )

    assert text == ""
    assert len(history) == 1


def test_sanitize_push_manual_fallback_uses_onboarded_workspace_identity() -> None:
    class _FakeVera:
        @staticmethod
        def _resolve_workspace_google_auth_context():
            return "owner@example.com", True

    bridge = _make_bridge(max_tool_rounds=5)
    bridge.vera = _FakeVera()
    bridge.last_tool_payload = {"tool_names": ["send_native_push"]}

    sanitized = bridge._sanitize_push_manual_fallback(
        "Manual fix: set it manually in the Clock app."
    )

    lowered = sanitized.lower()
    assert "immediate native push" in lowered
    assert "onboarded google workspace account automatically" in lowered
    assert "share your google email" not in lowered


def test_sanitize_push_manual_fallback_requests_email_only_when_unknown() -> None:
    class _FakeVera:
        @staticmethod
        def _resolve_workspace_google_auth_context():
            return "", False

    bridge = _make_bridge(max_tool_rounds=5)
    bridge.vera = _FakeVera()
    bridge.last_tool_payload = {"tool_names": ["send_native_push"]}

    sanitized = bridge._sanitize_push_manual_fallback(
        "Manual fix: copy-paste into Google Calendar app."
    )

    lowered = sanitized.lower()
    assert "share your google email and timezone" in lowered


def test_sanitize_response_blocks_unverified_wake_call_claim() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    bridge.last_tool_payload = {"tool_names": ["initiate_call"]}

    text = "Queued: Tomorrow 07:00 wake-up call is armed."
    sanitized = bridge._sanitize_response_text(text, request_tool_exec=[])

    lowered = sanitized.lower()
    assert "not armed" in lowered
    assert "haven't confirmed successful call/scheduler tool execution" in lowered


def test_sanitize_response_keeps_verified_wake_call_claim() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    bridge.last_tool_payload = {"tool_names": ["initiate_call"]}

    text = "Queued: Tomorrow 07:00 wake-up call is armed."
    sanitized = bridge._sanitize_response_text(
        text,
        request_tool_exec=[{"tool_name": "initiate_call", "status": "success"}],
    )

    assert sanitized == text


def test_sanitize_response_blocks_unverified_scheduler_claim() -> None:
    bridge = _make_bridge(max_tool_rounds=5)
    bridge.last_tool_payload = {"tool_names": ["create_event"]}

    text = "All set for tomorrow. Reminder set for 07:00."
    sanitized = bridge._sanitize_response_text(text, request_tool_exec=[])

    lowered = sanitized.lower()
    assert "not armed" in lowered
    assert "scheduler tool execution" in lowered


def test_sanitize_response_prefers_callme_default_recipient(monkeypatch) -> None:
    monkeypatch.setenv("CALLME_USER_PHONE_NUMBER", "+15551234567")
    bridge = _make_bridge(max_tool_rounds=5)
    bridge.last_tool_payload = {"tool_names": ["initiate_call"]}

    text = (
        "Queued. Reply your E.164 number (+1xxxxxxxxxx) or confirm \"Arm default\"."
    )
    sanitized = bridge._sanitize_response_text(text, request_tool_exec=[])
    lowered = sanitized.lower()
    assert "default recipient is already configured" in lowered
    assert "e.164" not in lowered
