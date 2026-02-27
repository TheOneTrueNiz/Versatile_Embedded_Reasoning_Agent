from __future__ import annotations

from types import SimpleNamespace

from api.server import _parse_utc_timestamp, create_app
from core.services.event_bus import EventBus


def test_reachout_state_tracker_active_without_web_push_enabled() -> None:
    event_bus = EventBus()
    vera = SimpleNamespace(event_bus=event_bus)
    app = create_app(vera, ui_dist=None)

    assert app["last_reachout_event"] == {}

    event_bus.publish(
        "innerlife.reached_out",
        {"run_id": "abc12345"},
        source="test",
        sync=True,
    )

    assert app["last_reachout_event"]["run_id"] == "abc12345"
    assert "timestamp" in app["last_reachout_event"]


def test_parse_utc_timestamp_accepts_unix_epoch_values() -> None:
    parsed_from_number = _parse_utc_timestamp(1772149953.25)
    parsed_from_text = _parse_utc_timestamp("1772149953.25")

    assert parsed_from_number is not None
    assert parsed_from_text is not None
    assert parsed_from_number.tzinfo is not None
    assert parsed_from_text.tzinfo is not None
