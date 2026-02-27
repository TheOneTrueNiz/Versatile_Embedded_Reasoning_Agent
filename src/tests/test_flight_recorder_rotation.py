from __future__ import annotations

from pathlib import Path

from core.services.flight_recorder import AIRResult, FlightRecorder


def _write_large_transition(recorder: FlightRecorder, payload_size: int = 700_000) -> None:
    blob = "x" * payload_size
    recorder.log_transition(
        state_snapshot=blob,
        action={"kind": "tool_call", "payload": blob},
        result={"ok": True, "payload": blob},
        air=AIRResult(score=0.1, reason="test"),
    )


def test_rotation_compresses_and_limits_backup_slots(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VERA_FLIGHT_RECORDER_MAX_MB", "1")
    monkeypatch.setenv("VERA_FLIGHT_RECORDER_MAX_BACKUPS", "2")
    monkeypatch.setenv("VERA_FLIGHT_RECORDER_COMPRESS_BACKUPS", "1")

    recorder = FlightRecorder(
        base_dir=tmp_path / "flight_recorder",
        enabled=True,
        max_snapshot_chars=2_000_000,
        max_action_chars=2_000_000,
        max_result_chars=2_000_000,
    )

    # Multiple oversized writes to force repeated rotations.
    for _ in range(4):
        _write_large_transition(recorder)

    backup_1_gz = recorder.transitions_path.with_suffix(".ndjson.1.gz")
    backup_2_gz = recorder.transitions_path.with_suffix(".ndjson.2.gz")
    backup_3_gz = recorder.transitions_path.with_suffix(".ndjson.3.gz")

    assert backup_1_gz.exists()
    assert backup_2_gz.exists()
    assert not backup_3_gz.exists()


def test_stats_expose_backup_and_limit_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VERA_FLIGHT_RECORDER_MAX_MB", "1")
    monkeypatch.setenv("VERA_FLIGHT_RECORDER_MAX_BACKUPS", "2")
    monkeypatch.setenv("VERA_FLIGHT_RECORDER_COMPRESS_BACKUPS", "1")

    recorder = FlightRecorder(
        base_dir=tmp_path / "flight_recorder",
        enabled=True,
        max_snapshot_chars=2_000_000,
        max_action_chars=2_000_000,
        max_result_chars=2_000_000,
    )

    for _ in range(3):
        _write_large_transition(recorder)

    stats = recorder.get_stats()
    assert stats["enabled"] is True
    assert stats["max_mb"] == 1.0
    assert stats["max_backups"] == 2
    assert stats["compress_backups"] is True
    assert isinstance(stats.get("current_size_bytes"), int)
    assert isinstance(stats.get("backup_files"), list)
    assert stats["backup_files"], "expected at least one backup file entry"
