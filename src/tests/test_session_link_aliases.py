"""Regression tests for cross-channel session linking primitives."""

from __future__ import annotations

from sessions.keys import derive_link_session_key
from sessions.store import SessionStore


def test_derive_link_session_key_normalizes_input() -> None:
    a = derive_link_session_key("  Niz@Example.Com  ")
    b = derive_link_session_key("niz@example.com")
    assert a == b
    assert a.startswith("link:")


def test_linked_aliases_share_same_session_entry(tmp_path) -> None:
    store = SessionStore(storage_dir=tmp_path / "transcripts")
    api_session = store.get_or_create("api:niz", channel_id="api", sender_id="niz")

    canonical = store.link_session_keys("link:niz", "api:niz", "discord:1234")

    assert canonical == "api:niz"
    assert store.resolve_session_key("link:niz") == canonical
    assert store.resolve_session_key("discord:1234") == canonical
    assert "discord:1234" in store.aliases_for(canonical)

    discord_session = store.get_or_create("discord:1234", channel_id="discord", sender_id="1234")
    assert discord_session.session_id == api_session.session_id


def test_session_link_aliases_persist_across_store_reload(tmp_path) -> None:
    storage_dir = tmp_path / "transcripts"
    store1 = SessionStore(storage_dir=storage_dir)
    store1.get_or_create("api:niz", channel_id="api", sender_id="niz")
    store1.link_session_keys("link:niz", "api:niz", "discord:1234")

    store2 = SessionStore(storage_dir=storage_dir)
    assert store2.resolve_session_key("link:niz") == "api:niz"
    assert store2.resolve_session_key("discord:1234") == "api:niz"
