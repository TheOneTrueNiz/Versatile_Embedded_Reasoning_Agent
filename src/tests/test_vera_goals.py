"""Unit tests for Vera's goal persistence system."""

import json
from pathlib import Path
from planning.inner_life_engine import InnerLifeEngine, InnerLifeConfig


def _make_engine(tmp_path: Path) -> InnerLifeEngine:
    """Create a minimal InnerLifeEngine wired to tmp_path."""
    config = InnerLifeConfig(enabled=True)
    engine = InnerLifeEngine(config=config, storage_dir=tmp_path)
    return engine


def test_add_goal_persists(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    goal = engine.add_goal("Learn about timeout patterns", category="self_improvement", priority=4)
    assert goal is not None
    assert goal["id"].startswith("g_")
    assert goal["status"] == "active"
    assert goal["priority"] == 4

    # Reload from disk and verify
    engine2 = _make_engine(tmp_path)
    active = engine2.list_active_goals()
    assert len(active) == 1
    assert active[0]["id"] == goal["id"]
    assert active[0]["description"] == "Learn about timeout patterns"


def test_max_10_active_goals(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    for i in range(10):
        result = engine.add_goal(f"Goal {i}", priority=3)
        assert result is not None

    # 11th should be rejected
    rejected = engine.add_goal("Goal 10 — too many", priority=3)
    assert rejected is None
    assert len(engine.list_active_goals()) == 10


def test_update_goal_status(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    goal = engine.add_goal("Finish task X")
    assert goal is not None

    ok = engine.update_goal(goal["id"], status="completed")
    assert ok is True

    # Verify it's no longer active
    assert len(engine.list_active_goals()) == 0

    # Verify completed_at is set
    data = engine._load_goals()
    completed = [g for g in data["goals"] if g["id"] == goal["id"]][0]
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None


def test_update_goal_progress_note(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    goal = engine.add_goal("Track progress")
    assert goal is not None

    engine.update_goal(goal["id"], note="Made some headway")
    data = engine._load_goals()
    g = [x for x in data["goals"] if x["id"] == goal["id"]][0]
    assert len(g["progress_notes"]) == 1
    assert g["progress_notes"][0]["note"] == "Made some headway"


def test_update_nonexistent_goal(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    ok = engine.update_goal("g_nonexistent", status="completed")
    assert ok is False


def test_format_goals_for_reflection(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    engine.add_goal("High priority goal", category="skill", priority=5)
    engine.add_goal("Low priority goal", category="exploration", priority=1)

    output = engine._format_goals_for_reflection()
    assert "High priority goal" in output
    assert "Low priority goal" in output
    # High priority should come first (sorted desc)
    high_idx = output.index("High priority goal")
    low_idx = output.index("Low priority goal")
    assert high_idx < low_idx


def test_format_goals_empty(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    assert engine._format_goals_for_reflection() == ""


def test_parse_goal_complete_tag(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    goal = engine.add_goal("Temporary goal")
    assert goal is not None

    content = f"I've finished this. [GOAL_COMPLETE:{goal['id']}] Moving on."
    engine._parse_goal_tags_from_content(content)

    assert len(engine.list_active_goals()) == 0


def test_parse_goal_new_tag(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)

    content = "I want to learn something. [GOAL_NEW:skill:4:Master the browser tool] Let's go."
    engine._parse_goal_tags_from_content(content)

    active = engine.list_active_goals()
    assert len(active) == 1
    assert active[0]["description"] == "Master the browser tool"
    assert active[0]["category"] == "skill"
    assert active[0]["priority"] == 4


def test_parse_goal_note_tag(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    goal = engine.add_goal("Ongoing goal")
    assert goal is not None

    content = f"Progress update. [GOAL_NOTE:{goal['id']}:Found a workaround] Nice."
    engine._parse_goal_tags_from_content(content)

    data = engine._load_goals()
    g = [x for x in data["goals"] if x["id"] == goal["id"]][0]
    assert len(g["progress_notes"]) == 1
    assert "workaround" in g["progress_notes"][0]["note"]


def test_goal_category_validation(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    goal = engine.add_goal("Test", category="invalid_cat", priority=3)
    assert goal is not None
    assert goal["category"] == "self_improvement"  # Falls back to default


def test_goal_priority_clamping(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    goal_high = engine.add_goal("Too high", priority=99)
    goal_low = engine.add_goal("Too low", priority=-5)
    assert goal_high is not None
    assert goal_low is not None
    assert goal_high["priority"] == 5
    assert goal_low["priority"] == 1


def test_completed_goal_allows_new(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    for i in range(10):
        engine.add_goal(f"Goal {i}")
    # Complete one
    goals = engine.list_active_goals()
    engine.update_goal(goals[0]["id"], status="completed")
    # Now should be able to add one more
    new_goal = engine.add_goal("Replacement goal")
    assert new_goal is not None
