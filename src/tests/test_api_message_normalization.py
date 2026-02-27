"""Regression tests for chat message normalization compatibility paths."""

from api.server import _normalize_messages


def test_normalize_messages_accepts_string_entries() -> None:
    messages, system = _normalize_messages(
        [
            "hello from legacy client",
            {"role": "assistant", "content": "ack"},
        ]
    )
    assert system == ""
    assert messages == [
        {"role": "user", "content": "hello from legacy client"},
        {"role": "assistant", "content": "ack"},
    ]


def test_normalize_messages_tolerates_invalid_entries() -> None:
    messages, system = _normalize_messages(
        [
            None,
            123,
            {"role": "system", "content": "System A"},
            {"content": "content-only legacy entry"},
            {"role": "bogus", "note": "ignore me"},
        ]
    )
    assert system == "System A"
    assert messages == [{"role": "user", "content": "content-only legacy entry"}]
