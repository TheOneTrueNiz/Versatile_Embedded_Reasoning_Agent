import time
from pathlib import Path

from context.preferences import PreferenceCategory, PreferenceManager


def test_set_preference_noop_does_not_rewrite_storage(tmp_path: Path) -> None:
    storage = tmp_path / "preferences.json"
    manager = PreferenceManager(storage_path=storage)

    pref = manager.set_preference(
        category=PreferenceCategory.COMMUNICATION,
        key="response_length",
        value="concise",
        reason="keep it short",
    )
    initial_occurrences = pref.occurrences
    initial_updated_at = pref.updated_at
    initial_mtime = storage.stat().st_mtime

    same_pref = manager.set_preference(
        category=PreferenceCategory.COMMUNICATION,
        key="response_length",
        value="concise",
        reason="keep it short",
    )

    assert same_pref is pref
    assert same_pref.occurrences == initial_occurrences
    assert same_pref.updated_at == initial_updated_at
    assert storage.stat().st_mtime == initial_mtime


def test_set_preference_changed_reason_updates_storage(tmp_path: Path) -> None:
    storage = tmp_path / "preferences.json"
    manager = PreferenceManager(storage_path=storage)

    pref = manager.set_preference(
        category=PreferenceCategory.COMMUNICATION,
        key="response_length",
        value="concise",
        reason="keep it short",
    )
    initial_occurrences = pref.occurrences
    initial_updated_at = pref.updated_at

    updated = manager.set_preference(
        category=PreferenceCategory.COMMUNICATION,
        key="response_length",
        value="concise",
        reason="still keep it short",
    )

    assert updated.occurrences == initial_occurrences + 1
    assert updated.updated_at != initial_updated_at
    assert updated.notes == "still keep it short"


def test_refresh_core_identity_promotions_is_stable_after_initial_trim(tmp_path: Path) -> None:
    storage = tmp_path / "preferences.json"
    manager = PreferenceManager(storage_path=storage)
    values = [
        "I keep in mind that my partner prefers: autumn coding sessions.",
        "I keep in mind that my partner prefers: forest-green interface accents.",
        "I keep in mind that my partner prefers: concise status reports.",
        "I keep in mind that my partner prefers: explicit rollback plans.",
        "I keep in mind that my partner prefers: calendar-first reminders.",
        "I keep in mind that my partner prefers: voice memos for urgent updates.",
        "I keep in mind that my partner prefers: test evidence before claims.",
        "I keep in mind that my partner prefers: Minecraft metaphors in moderation.",
    ]

    for idx, value in enumerate(values):
        manager.set_preference(
            category=PreferenceCategory.PARTNER_MODEL,
            key=f"pref_{idx}",
            value=value,
            reason=f"reason {idx}",
        )

    first = manager.refresh_core_identity_promotions(threshold=0.9, max_items=3)
    first_mtime = storage.stat().st_mtime
    time.sleep(1.1)
    second = manager.refresh_core_identity_promotions(threshold=0.9, max_items=3)
    second_mtime = storage.stat().st_mtime

    assert first["changed"] is True
    assert first["active_count"] == 3
    assert second["changed"] is False
    assert second["promoted_now"] == 0
    assert second["active_count"] == 3
    assert second_mtime == first_mtime


def test_partner_model_similar_commitment_reuses_existing_preference(tmp_path: Path) -> None:
    storage = tmp_path / "preferences.json"
    manager = PreferenceManager(storage_path=storage)

    first = manager.set_preference(
        category=PreferenceCategory.PARTNER_MODEL,
        key="preferences_alpha",
        value="I keep in mind that my partner prefers: prefers non-repetitive phrasing.",
        reason="Auto-promoted from partner model (preferences, confidence 1.00)",
    )
    first_mtime = storage.stat().st_mtime

    second = manager.set_preference(
        category=PreferenceCategory.PARTNER_MODEL,
        key="preferences_beta",
        value="I keep in mind that my partner prefers: values non-repetitive phrasing.",
        reason="Auto-promoted from partner model (preferences, confidence 0.95)",
    )

    assert second is first
    assert len(manager.get_category("partner_model")) == 1
    assert storage.stat().st_mtime == first_mtime


def test_partner_model_distinct_commitment_still_saves(tmp_path: Path) -> None:
    storage = tmp_path / "preferences.json"
    manager = PreferenceManager(storage_path=storage)

    manager.set_preference(
        category=PreferenceCategory.PARTNER_MODEL,
        key="preferences_alpha",
        value="I keep in mind that my partner prefers: prefers non-repetitive phrasing.",
        reason="Auto-promoted from partner model (preferences, confidence 1.00)",
    )
    first_mtime = storage.stat().st_mtime
    time.sleep(1.1)

    second = manager.set_preference(
        category=PreferenceCategory.PARTNER_MODEL,
        key="preferences_gamma",
        value="I keep in mind that my partner prefers: values creative methodical evaluations.",
        reason="Auto-promoted from partner model (preferences, confidence 1.00)",
    )

    assert second.key == "preferences_gamma"
    assert len(manager.get_category("partner_model")) == 2
    assert storage.stat().st_mtime > first_mtime
