import builtins

import pytest

from desktop_control import drivers


def test_pyautogui_systemexit_is_converted_to_importerror(monkeypatch):
    monkeypatch.setattr(drivers, "_pyautogui", None)
    monkeypatch.setattr(drivers, "_pyautogui_error", None)

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pyautogui":
            raise SystemExit("simulated fatal import")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError) as exc:
        drivers._get_pyautogui()

    text = str(exc.value).lower()
    assert "desktop control unavailable" in text
    assert "simulated fatal import" in text


def test_pyautogui_tkinter_systemexit_recovers_with_mouseinfo_stub(monkeypatch):
    monkeypatch.setattr(drivers, "_pyautogui", None)
    monkeypatch.setattr(drivers, "_pyautogui_error", None)

    class FakePyAuto:
        FAILSAFE = True

    fake = FakePyAuto()
    calls = {"pyautogui": 0}
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pyautogui":
            calls["pyautogui"] += 1
            if calls["pyautogui"] == 1:
                raise SystemExit(
                    "NOTE: You must install tkinter on Linux to use MouseInfo."
                )
            return fake
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    loaded = drivers._get_pyautogui()
    assert loaded is fake
    assert loaded.FAILSAFE is False
    assert calls["pyautogui"] == 2


def test_pyautogui_error_is_cached_after_failed_import(monkeypatch):
    monkeypatch.setattr(drivers, "_pyautogui", None)
    monkeypatch.setattr(drivers, "_pyautogui_error", "cached failure")

    with pytest.raises(ImportError) as exc:
        drivers._get_pyautogui()

    assert "cached failure" in str(exc.value)


def test_linuxscreen_screenshot_falls_back_to_scrot(monkeypatch):
    class FakePyAuto:
        def screenshot(self, *args, **kwargs):
            raise RuntimeError("pyautogui screenshot unavailable")

    sentinel = object()
    captured = {}

    def fake_scrot(self, region=None):
        captured["region"] = region
        return sentinel

    monkeypatch.setattr(drivers, "_pyautogui", FakePyAuto())
    monkeypatch.setattr(drivers, "_pyautogui_error", None)
    monkeypatch.setattr(drivers.LinuxScreen, "_screenshot_via_scrot", fake_scrot)

    result = drivers.LinuxScreen().screenshot(region=(1, 2, 3, 4))
    assert result is sentinel
    assert captured.get("region") == (1, 2, 3, 4)


def test_linuxscreen_screenshot_raises_when_both_paths_fail(monkeypatch):
    class FakePyAuto:
        def screenshot(self, *args, **kwargs):
            raise RuntimeError("pyautogui screenshot unavailable")

    def fake_scrot(self, region=None):
        raise RuntimeError("scrot fallback failed")

    monkeypatch.setattr(drivers, "_pyautogui", FakePyAuto())
    monkeypatch.setattr(drivers, "_pyautogui_error", None)
    monkeypatch.setattr(drivers.LinuxScreen, "_screenshot_via_scrot", fake_scrot)

    with pytest.raises(RuntimeError) as exc:
        drivers.LinuxScreen().screenshot()

    assert "pyautogui and scrot fallback" in str(exc.value).lower()


def test_linuxscreen_screenshot_scrot_backend_short_circuits_pyautogui(monkeypatch):
    sentinel = object()
    called = {}

    def fake_scrot(self, region=None):
        called["region"] = region
        return sentinel

    monkeypatch.setenv("VERA_DESKTOP_SCREENSHOT_BACKEND", "scrot")
    monkeypatch.setattr(drivers, "_pyautogui", None)
    monkeypatch.setattr(drivers, "_pyautogui_error", "pyautogui should not be used")
    monkeypatch.setattr(drivers.LinuxScreen, "_screenshot_via_scrot", fake_scrot)

    result = drivers.LinuxScreen().screenshot(region=(10, 20, 30, 40))
    assert result is sentinel
    assert called.get("region") == (10, 20, 30, 40)
