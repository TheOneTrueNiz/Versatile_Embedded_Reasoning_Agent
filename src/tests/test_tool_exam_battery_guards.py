import importlib.util
from pathlib import Path


def _load_battery_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "vera_tool_exam_battery.py"
    spec = importlib.util.spec_from_file_location("vera_tool_exam_battery", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detect_tool_runtime_failure_reason_flags_failures():
    mod = _load_battery_module()
    assert mod._detect_tool_runtime_failure_reason(
        "Tool Failure Report: desktop_screenshot failed due to missing dependencies."
    ) == "tool_runtime_failure"
    assert mod._detect_tool_runtime_failure_reason(
        "edit_file failed: ENOENT (no such file or directory)"
    ) == "tool_runtime_failure"


def test_detect_tool_runtime_failure_reason_ignores_success_text():
    mod = _load_battery_module()
    assert mod._detect_tool_runtime_failure_reason("EXAM_COMPLETE.") == ""
    assert mod._detect_tool_runtime_failure_reason(
        "Action completed successfully. EXAM_COMPLETE."
    ) == ""


def test_tier1_prompt_for_edit_file_prepares_probe_file():
    mod = _load_battery_module()
    prompt = mod._tier1_prompt_for_tool("edit_file")
    probe_path = Path("/tmp/vera_exam_edit_file.txt")
    assert probe_path.exists()
    assert "Use this existing file path only" in prompt
    assert str(probe_path) in prompt
