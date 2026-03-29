from __future__ import annotations

from types import SimpleNamespace

from core.runtime.vera import VERA


def test_extract_inbound_tool_choice_from_raw_string() -> None:
    message = SimpleNamespace(raw={"tool_choice": "none"})
    assert VERA._extract_inbound_tool_choice(message) == "none"


def test_extract_inbound_tool_choice_from_nested_context() -> None:
    forced = {"type": "function", "function": {"name": "time"}}
    message = SimpleNamespace(raw={"context": {"tool_choice": forced}})
    assert VERA._extract_inbound_tool_choice(message) == forced


def test_extract_inbound_tool_choice_ignores_invalid_payload() -> None:
    message = SimpleNamespace(raw={"tool_choice": ["none"]})
    assert VERA._extract_inbound_tool_choice(message) is None
