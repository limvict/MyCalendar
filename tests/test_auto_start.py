# coding: utf-8
"""auto_start：mock winreg 测 is_enabled/set_enabled/旧键迁移。"""
import sys

import pytest

from desktop_calendar.infrastructure.platform import auto_start


class _FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1
    KEY_QUERY_VALUE = 2
    KEY_SET_VALUE = 4

    def __init__(self):
        self.values: dict = {}
        self.raise_permission = False

    def OpenKey(self, root, path, *a, **k):
        return _FakeKey(self, path)

    def CreateKeyEx(self, root, path, *a, **k):
        if self.raise_permission:
            raise PermissionError("denied")
        return _FakeKey(self, path)

    def QueryValueEx(self, key, name):
        k = (key.path, name)
        if k not in self.values:
            raise FileNotFoundError(name)
        return self.values[k], self.REG_SZ

    def SetValueEx(self, key, name, reserved, typ, val):
        self.values[(key.path, name)] = val

    def DeleteValue(self, key, name):
        k = (key.path, name)
        if k not in self.values:
            raise FileNotFoundError(name)
        del self.values[k]


class _FakeKey:
    def __init__(self, reg, path):
        self._reg = reg
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


@pytest.fixture
def fake_winreg(monkeypatch):
    fake = _FakeWinreg()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(auto_start, "winreg", fake)
    monkeypatch.setattr(auto_start, "HAS_WINREG", True)
    return fake


class TestIsSupported:
    def test_non_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert auto_start.is_supported() is False

    def test_windows_with_winreg(self, fake_winreg):
        assert auto_start.is_supported() is True


class TestBuildCmd:
    def test_frozen(self, monkeypatch):
        monkeypatch.setattr(sys, "_MEIPASS", "/tmp/mei", raising=False)
        monkeypatch.setattr(sys, "executable", "/path/app.exe")
        assert auto_start._build_cmd() == '"/path/app.exe"'

    def test_script(self, monkeypatch):
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", "/path/python.exe")
        monkeypatch.setattr(sys, "argv", ["/path/main.py"])
        assert "main.py" in auto_start._build_cmd()


class TestIsEnabled:
    def test_no_key(self, fake_winreg):
        assert auto_start.is_enabled() is False

    def test_present(self, fake_winreg):
        fake_winreg.values[
            (auto_start._REG_PATH, auto_start._REG_KEY)] = "cmd"
        assert auto_start.is_enabled() is True

    def test_legacy_only_triggers_migration(self, fake_winreg):
        fake_winreg.values[
            (auto_start._REG_PATH, auto_start._LEGACY_REG_KEY)] = "old"
        assert auto_start.is_enabled() is True
        # 迁移：新键写入、旧键删除
        assert (auto_start._REG_PATH, auto_start._REG_KEY) in fake_winreg.values
        assert (auto_start._REG_PATH,
                auto_start._LEGACY_REG_KEY) not in fake_winreg.values


class TestSetEnabled:
    def test_enable_writes(self, fake_winreg, monkeypatch):
        monkeypatch.setattr(auto_start, "_build_cmd", lambda: '"x"')
        auto_start.set_enabled(True)
        assert fake_winreg.values[
            (auto_start._REG_PATH, auto_start._REG_KEY)] == '"x"'

    def test_disable_removes_both_keys(self, fake_winreg):
        fake_winreg.values[(auto_start._REG_PATH, auto_start._REG_KEY)] = "x"
        fake_winreg.values[
            (auto_start._REG_PATH, auto_start._LEGACY_REG_KEY)] = "old"
        auto_start.set_enabled(False)
        assert (auto_start._REG_PATH,
                auto_start._REG_KEY) not in fake_winreg.values
        assert (auto_start._REG_PATH,
                auto_start._LEGACY_REG_KEY) not in fake_winreg.values

    def test_permission_error_maps_reason(self, fake_winreg):
        fake_winreg.raise_permission = True
        with pytest.raises(auto_start.AutoStartError) as ei:
            auto_start.set_enabled(True)
        assert ei.value.reason == "permission"

    def test_unsupported_raises(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(auto_start, "HAS_WINREG", False)
        with pytest.raises(auto_start.AutoStartError) as ei:
            auto_start.set_enabled(True)
        assert ei.value.reason == "unsupported"
