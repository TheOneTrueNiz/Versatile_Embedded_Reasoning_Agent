"""Tests for VERA Speaker Memory — persistent people recognition with decay."""

import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from core.runtime.speaker_memory import (
    RecognitionTier,
    SpeakerEntry,
    SpeakerMemory,
)


@pytest.fixture
def tmp_memory_dir(tmp_path):
    """Provide a temp directory for speaker memory storage."""
    return tmp_path


@pytest.fixture
def memory(tmp_memory_dir):
    """Provide a fresh SpeakerMemory instance."""
    return SpeakerMemory(memory_dir=tmp_memory_dir)


# ------------------------------------------------------------------
# Detection tests
# ------------------------------------------------------------------


class TestDetectSelfIdentification:
    """Test the regex-based self-identification detection."""

    def test_im_name(self):
        assert SpeakerMemory.detect_self_identification("I'm Niz") == "Niz"

    def test_i_am_name(self):
        assert SpeakerMemory.detect_self_identification("I am Carol") == "Carol"

    def test_my_name_is(self):
        assert SpeakerMemory.detect_self_identification("My name is Alice") == "Alice"

    def test_this_is(self):
        assert SpeakerMemory.detect_self_identification("This is Bob") == "Bob"

    def test_call_me(self):
        assert SpeakerMemory.detect_self_identification("Call me Vera") == "Vera"

    def test_i_go_by(self):
        assert SpeakerMemory.detect_self_identification("I go by Alex") == "Alex"

    def test_curly_apostrophe(self):
        assert SpeakerMemory.detect_self_identification("I\u2019m Niz") == "Niz"

    def test_case_insensitive(self):
        assert SpeakerMemory.detect_self_identification("i'm niz") == "Niz"

    def test_embedded_in_sentence(self):
        result = SpeakerMemory.detect_self_identification(
            "Hey Vera, I'm Niz. Can you check the weather?"
        )
        assert result == "Niz"

    def test_name_with_period(self):
        result = SpeakerMemory.detect_self_identification("I'm Niz.")
        assert result == "Niz"

    def test_my_names(self):
        result = SpeakerMemory.detect_self_identification("my name's Carol")
        assert result == "Carol"


class TestDetectRejectsStopwords:
    """Ensure common phrases don't trigger false identification."""

    def test_im_fine(self):
        assert SpeakerMemory.detect_self_identification("I'm fine") is None

    def test_im_good(self):
        assert SpeakerMemory.detect_self_identification("I'm good") is None

    def test_im_tired(self):
        assert SpeakerMemory.detect_self_identification("I'm tired") is None

    def test_im_not_sure(self):
        assert SpeakerMemory.detect_self_identification("I'm not sure about that") is None

    def test_im_a_developer(self):
        assert SpeakerMemory.detect_self_identification("I'm a developer") is None

    def test_im_the_admin(self):
        assert SpeakerMemory.detect_self_identification("I'm the admin of this system") is None

    def test_im_just_testing(self):
        assert SpeakerMemory.detect_self_identification("I'm just testing") is None

    def test_im_very_busy(self):
        assert SpeakerMemory.detect_self_identification("I'm very busy today") is None

    def test_im_really_excited(self):
        assert SpeakerMemory.detect_self_identification("I'm really excited") is None

    def test_im_so_confused(self):
        assert SpeakerMemory.detect_self_identification("I'm so confused") is None

    def test_empty_string(self):
        assert SpeakerMemory.detect_self_identification("") is None

    def test_none_string(self):
        assert SpeakerMemory.detect_self_identification("Hello there") is None

    def test_very_long_string(self):
        assert SpeakerMemory.detect_self_identification("x" * 600) is None

    def test_im_happy(self):
        assert SpeakerMemory.detect_self_identification("I'm happy to help") is None

    def test_im_wondering(self):
        assert SpeakerMemory.detect_self_identification("I'm wondering about") is None

    def test_im_looking(self):
        assert SpeakerMemory.detect_self_identification("I'm looking for info") is None


# ------------------------------------------------------------------
# Identification & recall
# ------------------------------------------------------------------


class TestIdentifyAndRecall:
    """Test storing and retrieving speaker identities."""

    def test_identify_new_speaker(self, memory):
        entry = memory.identify_speaker("Niz", "sender_123", "api")
        assert entry.name == "Niz"
        assert entry.interaction_count == 1
        assert "api" in entry.channel_ids

    def test_recall_by_sender_id(self, memory):
        memory.identify_speaker("Niz", "sender_123", "api")
        tier, entry, fam = memory.get_recognition("sender_123")
        assert tier == RecognitionTier.KNOWN
        assert entry is not None
        assert entry.name == "Niz"
        assert fam > 0.9

    def test_recall_by_name(self, memory):
        memory.identify_speaker("Niz", "sender_123", "api")
        entry = memory.find_by_name("Niz")
        assert entry is not None
        assert entry.name == "Niz"

    def test_recall_by_name_case_insensitive(self, memory):
        memory.identify_speaker("Niz", "sender_123", "api")
        entry = memory.find_by_name("niz")
        assert entry is not None

    def test_unknown_speaker_is_stranger(self, memory):
        tier, entry, fam = memory.get_recognition("unknown_sender")
        assert tier == RecognitionTier.STRANGER
        assert entry is None
        assert fam == 0.0

    def test_empty_sender_is_stranger(self, memory):
        tier, entry, fam = memory.get_recognition("")
        assert tier == RecognitionTier.STRANGER
        assert entry is None

    def test_reidentify_updates_name(self, memory):
        memory.identify_speaker("Niz", "sender_123", "api")
        memory.identify_speaker("Nizbot", "sender_123", "api")
        _, entry, _ = memory.get_recognition("sender_123")
        assert entry.name == "Nizbot"
        assert entry.interaction_count == 2

    def test_record_interaction_increments(self, memory):
        memory.identify_speaker("Niz", "sender_123", "api")
        memory.record_interaction("sender_123", "api")
        memory.record_interaction("sender_123", "api")
        _, entry, _ = memory.get_recognition("sender_123")
        assert entry.interaction_count == 3  # 1 from identify + 2 from record

    def test_record_interaction_unknown_is_noop(self, memory):
        # Should not crash or create entry
        memory.record_interaction("nobody", "api")
        tier, entry, _ = memory.get_recognition("nobody")
        assert tier == RecognitionTier.STRANGER

    def test_multiple_channels(self, memory):
        memory.identify_speaker("Niz", "sender_123", "api")
        memory.record_interaction("sender_123", "telegram")
        _, entry, _ = memory.get_recognition("sender_123")
        assert "api" in entry.channel_ids
        assert "telegram" in entry.channel_ids


# ------------------------------------------------------------------
# Familiarity decay
# ------------------------------------------------------------------


class TestFamiliarityDecay:
    """Test that familiarity decays over time."""

    def test_fresh_speaker_is_known(self, memory):
        memory.identify_speaker("Niz", "sender_123", "api")
        _, _, fam = memory.get_recognition("sender_123")
        assert fam > 0.9

    def test_decay_after_one_half_life(self, memory):
        entry = memory.identify_speaker("Niz", "sender_123", "api")
        # Simulate 1 week ago (168 hours = default half-life)
        past = (datetime.now() - timedelta(hours=168)).isoformat()
        entry.last_seen = past
        fam = memory.compute_familiarity(entry)
        # Should be ~0.5 from time decay + 0.015 interaction bonus
        assert 0.45 < fam < 0.60

    def test_decay_after_two_half_lives(self, memory):
        entry = memory.identify_speaker("Niz", "sender_123", "api")
        past = (datetime.now() - timedelta(hours=336)).isoformat()
        entry.last_seen = past
        fam = memory.compute_familiarity(entry)
        # Should be ~0.25 from time + 0.015 interaction bonus
        assert 0.20 < fam < 0.35

    def test_decay_after_one_month(self, memory):
        entry = memory.identify_speaker("Niz", "sender_123", "api")
        past = (datetime.now() - timedelta(days=30)).isoformat()
        entry.last_seen = past
        fam = memory.compute_familiarity(entry)
        # Should be very low
        assert fam < 0.15


class TestRecognitionTiers:
    """Test tier assignment based on familiarity."""

    def test_known_tier(self, memory):
        memory.identify_speaker("Niz", "s1", "api")
        tier, _, _ = memory.get_recognition("s1")
        assert tier == RecognitionTier.KNOWN

    def test_recognized_tier(self, memory):
        entry = memory.identify_speaker("Niz", "s1", "api")
        # ~1 week old, 1 interaction → familiarity ~0.52
        entry.last_seen = (datetime.now() - timedelta(hours=168)).isoformat()
        tier, _, fam = memory.get_recognition("s1")
        assert tier == RecognitionTier.RECOGNIZED

    def test_vague_tier(self, memory):
        entry = memory.identify_speaker("Niz", "s1", "api")
        # ~2 weeks old, 1 interaction → familiarity ~0.27
        entry.last_seen = (datetime.now() - timedelta(hours=336)).isoformat()
        tier, _, fam = memory.get_recognition("s1")
        assert tier == RecognitionTier.VAGUE

    def test_stranger_tier_from_decay(self, memory):
        entry = memory.identify_speaker("Niz", "s1", "api")
        # ~1 month old, 1 interaction → very low
        entry.last_seen = (datetime.now() - timedelta(days=35)).isoformat()
        tier, _, fam = memory.get_recognition("s1")
        assert tier == RecognitionTier.STRANGER


class TestInteractionBonus:
    """Test that frequent interactions create lasting memory."""

    def test_many_interactions_resist_decay(self, memory):
        entry = memory.identify_speaker("Niz", "s1", "api")
        # Simulate 20 interactions
        entry.interaction_count = 20
        # 1 week old
        entry.last_seen = (datetime.now() - timedelta(hours=168)).isoformat()
        fam = memory.compute_familiarity(entry)
        # time_factor ~0.5, interaction_bonus = min(0.3, 20*0.015) = 0.3
        # total ~0.8
        assert fam > 0.7
        tier, _, _ = memory.get_recognition("s1")
        assert tier == RecognitionTier.KNOWN

    def test_interaction_bonus_caps_at_03(self, memory):
        entry = memory.identify_speaker("Niz", "s1", "api")
        entry.interaction_count = 100
        entry.last_seen = datetime.now().isoformat()
        fam = memory.compute_familiarity(entry)
        # 1.0 * 1.0 + 0.3 = 1.3 → capped at 1.0
        assert fam == 1.0


# ------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------


class TestPersistenceRoundtrip:
    """Test save/load cycle across instances."""

    def test_save_and_load(self, tmp_memory_dir):
        mem1 = SpeakerMemory(memory_dir=tmp_memory_dir)
        mem1.identify_speaker("Niz", "sender_123", "api")
        mem1.identify_speaker("Carol", "sender_456", "telegram")

        # Create new instance — should load from disk
        mem2 = SpeakerMemory(memory_dir=tmp_memory_dir)
        tier, entry, _ = mem2.get_recognition("sender_123")
        assert entry is not None
        assert entry.name == "Niz"

        tier2, entry2, _ = mem2.get_recognition("sender_456")
        assert entry2 is not None
        assert entry2.name == "Carol"

    def test_storage_file_is_valid_json(self, tmp_memory_dir):
        mem = SpeakerMemory(memory_dir=tmp_memory_dir)
        mem.identify_speaker("Niz", "sender_123", "api")
        storage_path = tmp_memory_dir / "speakers.json"
        assert storage_path.exists()
        data = json.loads(storage_path.read_text())
        assert data["version"] == 1
        assert "sender_123" in str(data["speakers"])

    def test_journal_file_created(self, tmp_memory_dir):
        mem = SpeakerMemory(memory_dir=tmp_memory_dir)
        mem.identify_speaker("Niz", "sender_123", "api")
        journal_path = tmp_memory_dir / "speaker_journal.ndjson"
        assert journal_path.exists()
        lines = journal_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["event"] == "first_identify"
        assert entry["name"] == "Niz"


# ------------------------------------------------------------------
# SpeakerEntry serialization
# ------------------------------------------------------------------


class TestSpeakerEntry:
    """Test SpeakerEntry data class."""

    def test_roundtrip(self):
        entry = SpeakerEntry(
            name="Niz",
            aliases=["nizbot"],
            first_seen="2026-02-18T10:00:00",
            last_seen="2026-02-18T15:00:00",
            interaction_count=5,
            peak_familiarity=1.0,
            notes=["primary user"],
            channel_ids=["api", "telegram"],
        )
        d = entry.to_dict()
        restored = SpeakerEntry.from_dict(d)
        assert restored.name == "Niz"
        assert restored.aliases == ["nizbot"]
        assert restored.interaction_count == 5
        assert "telegram" in restored.channel_ids

    def test_from_empty_dict(self):
        entry = SpeakerEntry.from_dict({})
        assert entry.name == ""
        assert entry.interaction_count == 0
        assert entry.aliases == []


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


class TestEdgeCases:
    """Miscellaneous edge-case tests."""

    def test_find_by_name_not_found(self, memory):
        assert memory.find_by_name("nobody") is None

    def test_identify_normalizes_sender_key(self, memory):
        memory.identify_speaker("Niz", "  Sender_123  ", "api")
        tier, entry, _ = memory.get_recognition("sender_123")
        assert entry is not None
        assert entry.name == "Niz"

    def test_half_life_configurable(self, tmp_memory_dir):
        # Very short half-life (1 hour)
        mem = SpeakerMemory(memory_dir=tmp_memory_dir, half_life_hours=1.0)
        entry = mem.identify_speaker("Niz", "s1", "api")
        # 2 hours ago → should be well decayed
        entry.last_seen = (datetime.now() - timedelta(hours=2)).isoformat()
        fam = mem.compute_familiarity(entry)
        assert fam < 0.35  # ~0.25 from time + 0.015 bonus

    def test_bad_last_seen_returns_zero(self, memory):
        entry = SpeakerEntry(name="Bad", last_seen="not-a-date")
        assert memory.compute_familiarity(entry) == 0.0

    def test_empty_last_seen_returns_zero(self, memory):
        entry = SpeakerEntry(name="Empty", last_seen="")
        assert memory.compute_familiarity(entry) == 0.0


# ------------------------------------------------------------------
# Emotional context & conversation tracking
# ------------------------------------------------------------------


class TestEmotionalContext:
    """Test emotional memory across conversations."""

    def test_store_emotional_context(self, memory):
        memory.identify_speaker("Niz", "s1", "api")
        memory.update_emotional_context(
            "s1", mood="anxious", emotion="worried", sentiment_trend="declining"
        )
        _, entry, _ = memory.get_recognition("s1")
        assert entry.last_mood == "anxious"
        assert entry.last_emotion == "worried"
        assert entry.last_sentiment_trend == "declining"

    def test_emotional_context_persists(self, tmp_memory_dir):
        mem1 = SpeakerMemory(memory_dir=tmp_memory_dir)
        mem1.identify_speaker("Niz", "s1", "api")
        mem1.update_emotional_context("s1", mood="happy", emotion="grateful")

        mem2 = SpeakerMemory(memory_dir=tmp_memory_dir)
        _, entry, _ = mem2.get_recognition("s1")
        assert entry.last_mood == "happy"
        assert entry.last_emotion == "grateful"

    def test_emotional_context_unknown_speaker_noop(self, memory):
        # Should not crash
        memory.update_emotional_context("nobody", mood="happy")

    def test_emotional_context_updates_incrementally(self, memory):
        memory.identify_speaker("Niz", "s1", "api")
        memory.update_emotional_context("s1", mood="happy")
        memory.update_emotional_context("s1", emotion="excited")
        _, entry, _ = memory.get_recognition("s1")
        assert entry.last_mood == "happy"
        assert entry.last_emotion == "excited"


class TestConversationTracking:
    """Test conversation count for milestones."""

    def test_start_conversation_increments(self, memory):
        memory.identify_speaker("Niz", "s1", "api")
        assert memory._speakers["s1"].conversation_count == 0
        memory.start_conversation("s1")
        assert memory._speakers["s1"].conversation_count == 1
        memory.start_conversation("s1")
        assert memory._speakers["s1"].conversation_count == 2

    def test_start_conversation_unknown_noop(self, memory):
        memory.start_conversation("nobody")  # Should not crash

    def test_conversation_count_persists(self, tmp_memory_dir):
        mem1 = SpeakerMemory(memory_dir=tmp_memory_dir)
        mem1.identify_speaker("Niz", "s1", "api")
        mem1.start_conversation("s1")
        mem1.start_conversation("s1")
        mem1.start_conversation("s1")

        mem2 = SpeakerMemory(memory_dir=tmp_memory_dir)
        _, entry, _ = mem2.get_recognition("s1")
        assert entry.conversation_count == 3

    def test_entry_roundtrip_with_new_fields(self):
        entry = SpeakerEntry(
            name="Niz",
            conversation_count=42,
            last_mood="happy",
            last_emotion="grateful",
            last_sentiment_trend="improving",
        )
        d = entry.to_dict()
        restored = SpeakerEntry.from_dict(d)
        assert restored.conversation_count == 42
        assert restored.last_mood == "happy"
        assert restored.last_emotion == "grateful"
        assert restored.last_sentiment_trend == "improving"
