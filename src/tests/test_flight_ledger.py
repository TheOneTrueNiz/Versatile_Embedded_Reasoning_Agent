from __future__ import annotations

import json
from pathlib import Path

from core.services.flight_recorder import AIRResult, FlightRecorder, verify_flight_ledger


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _log_small_transition(recorder: FlightRecorder, idx: int = 1) -> None:
    recorder.log_transition(
        state_snapshot=f"state-{idx}",
        action={"type": "tool_call", "tool_name": f"tool_{idx}", "params": {"i": idx}},
        result={"success": True, "output": {"i": idx}},
        air=AIRResult(score=0.5, reason="tool_success"),
    )


def test_flight_ledger_creates_genesis_and_verifies(tmp_path: Path) -> None:
    recorder = FlightRecorder(base_dir=tmp_path / "flight_recorder", enabled=True)

    _log_small_transition(recorder, 1)
    _log_small_transition(recorder, 2)

    ledger_rows = _read_jsonl(recorder.ledger_path)
    assert [row["record_type"] for row in ledger_rows] == ["GENESIS", "transition", "transition"]

    result = verify_flight_ledger(recorder.ledger_path, cross_check_source=True)
    assert result["ok"] is True
    assert result["records"] == 3
    assert result["warnings"] == []
    assert result["errors"] == []


def test_flight_ledger_detects_tampering(tmp_path: Path) -> None:
    recorder = FlightRecorder(base_dir=tmp_path / "flight_recorder", enabled=True)
    _log_small_transition(recorder, 1)
    _log_small_transition(recorder, 2)

    rows = _read_jsonl(recorder.ledger_path)
    rows[2]["hash_prev"] = "0" * 64
    with recorder.ledger_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    result = verify_flight_ledger(recorder.ledger_path)
    assert result["ok"] is False
    assert result["exit_code"] == 30
    assert any("hash_prev_mismatch" in err for err in result["errors"])


def test_flight_ledger_failure_does_not_break_transition_write(tmp_path: Path, monkeypatch) -> None:
    recorder = FlightRecorder(base_dir=tmp_path / "flight_recorder", enabled=True)

    def _boom(payload: dict) -> None:
        raise RuntimeError("simulated ledger failure")

    monkeypatch.setattr(recorder, "_append_ledger_record_locked", _boom)

    _log_small_transition(recorder, 1)

    transition_rows = _read_jsonl(recorder.transitions_path)
    assert len(transition_rows) == 1
    assert transition_rows[0]["type"] == "transition"
    assert not recorder.ledger_path.exists()


def test_flight_ledger_stays_valid_across_multiple_recorder_instances(tmp_path: Path) -> None:
    base = tmp_path / "flight_recorder"
    recorder_a = FlightRecorder(base_dir=base, enabled=True)
    recorder_b = FlightRecorder(base_dir=base, enabled=True)

    _log_small_transition(recorder_a, 1)
    _log_small_transition(recorder_b, 2)
    _log_small_transition(recorder_a, 3)

    result = verify_flight_ledger(base / "ledger.jsonl", cross_check_source=True)
    assert result["ok"] is True
    assert result["warnings"] == []
    assert result["errors"] == []
