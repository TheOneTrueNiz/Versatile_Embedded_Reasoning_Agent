"""Regression guard for cache-hit tool execution telemetry."""

import asyncio
from types import SimpleNamespace

from core.runtime.tool_orchestrator import ToolOrchestrator


class _FakeCache:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self, tool_name, params):  # noqa: ANN001
        return self.value


class _FakeToolSelection:
    def __init__(self) -> None:
        self.calls = []

    def record_result(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)


class _FakeObservability:
    def __init__(self) -> None:
        self.events = []

    def record_event(self, event_name, **kwargs):  # noqa: ANN001, ANN003
        self.events.append((event_name, kwargs))


class _FakeFlightRecorder:
    def __init__(self) -> None:
        self.calls = []

    def record_tool_call(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)


class _FakeOwner:
    def __init__(self) -> None:
        self.cache = _FakeCache("cached-result")
        self.config = SimpleNamespace(observability=True)
        self.observability = _FakeObservability()
        self.tool_selection = _FakeToolSelection()
        self.flight_recorder = _FakeFlightRecorder()
        self.published = []

    @staticmethod
    def _normalize_conversation_id(raw):  # noqa: ANN001
        text = str(raw or "").strip()
        return text or "default"

    def _publish_tool_event(self, event_name, payload):  # noqa: ANN001
        self.published.append((event_name, payload))


def test_cache_hit_records_flight_recorder_tool_call() -> None:
    owner = _FakeOwner()
    orchestrator = ToolOrchestrator(owner)

    result = asyncio.run(
        orchestrator.execute_tool(
            "discover_global_functions",
            {"instance_id": "default"},
            context={"conversation_id": "cid-cache-1"},
        )
    )

    assert result == "cached-result"
    assert len(owner.flight_recorder.calls) == 1
    call = owner.flight_recorder.calls[0]
    assert call["tool_name"] == "discover_global_functions"
    assert call["conversation_id"] == "cid-cache-1"
    assert call["success"] is True
    assert call["source_type"] == "cache"
    assert call["result"]["cached"] is True


# ------------------------------------------------------------------
# Quorum auto-trigger tests
# ------------------------------------------------------------------


class _FakeSafetyValidator:
    """Return a configurable severity on every validate() call."""

    def __init__(self, severity: int = 0, result_name: str = "ALLOWED") -> None:
        from safety.safety_validator import ValidationResult, ValidationDecision
        self._decision = ValidationDecision(
            result=ValidationResult[result_name],
            message="test",
            matched_pattern="test_pattern",
            severity=severity,
        )

    def validate(self, _command: str):  # noqa: ANN001
        return self._decision


class _QuorumOwner(_FakeOwner):
    """FakeOwner extended with quorum plumbing."""

    def __init__(self, severity: int = 4) -> None:
        super().__init__()
        self.safety_validator = _FakeSafetyValidator(severity=severity)
        self.quorum_calls = []
        self.cache = _FakeCache(None)  # no cache hits

    async def _run_quorum_tool(self, mode, params, *, manual=False, trigger="auto"):  # noqa: ANN001
        self.quorum_calls.append({"mode": mode, "params": params, "trigger": trigger})
        return "Quorum advisory: proceed with caution."

    def log_decision(self, **kwargs):  # noqa: ANN003
        pass


def test_quorum_auto_trigger_fires_on_high_severity(monkeypatch) -> None:
    monkeypatch.setenv("VERA_QUORUM_AUTO_TRIGGER", "1")
    owner = _QuorumOwner(severity=4)
    orchestrator = ToolOrchestrator(owner)

    # The tool execution will fail (no real tool source), but the quorum
    # trigger should fire before that. We catch the downstream error.
    try:
        asyncio.run(
            orchestrator.execute_tool(
                "dangerous_tool",
                {"action": "delete_everything"},
                context={"conversation_id": "cid-auto-q"},
            )
        )
    except Exception:
        pass  # expected — no real tool runner

    assert len(owner.quorum_calls) == 1
    assert owner.quorum_calls[0]["trigger"] == "auto_safety"
    assert owner.quorum_calls[0]["mode"] == "quorum"


def test_quorum_auto_trigger_skipped_when_env_off(monkeypatch) -> None:
    monkeypatch.setenv("VERA_QUORUM_AUTO_TRIGGER", "0")
    owner = _QuorumOwner(severity=4)
    orchestrator = ToolOrchestrator(owner)

    try:
        asyncio.run(
            orchestrator.execute_tool(
                "dangerous_tool",
                {"action": "delete_everything"},
                context={"conversation_id": "cid-auto-q"},
            )
        )
    except Exception:
        pass

    assert len(owner.quorum_calls) == 0


def test_quorum_auto_trigger_fires_only_once_per_conversation(monkeypatch) -> None:
    monkeypatch.setenv("VERA_QUORUM_AUTO_TRIGGER", "1")
    owner = _QuorumOwner(severity=4)
    orchestrator = ToolOrchestrator(owner)

    for _ in range(3):
        try:
            asyncio.run(
                orchestrator.execute_tool(
                    "dangerous_tool",
                    {"action": "delete_everything"},
                    context={"conversation_id": "cid-rate-limit"},
                )
            )
        except Exception:
            pass

    # Only one quorum call despite 3 tool executions
    assert len(owner.quorum_calls) == 1
