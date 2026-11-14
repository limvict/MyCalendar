# coding: utf-8
"""utils.paths 平台路径测试。"""
import os
import sys

import pytest

from desktop_calendar.utils import paths


class TestGetBaseDir:
    def test_windows_uses_appdata(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", "C:/Users/test/AppData/Roaming")
        assert paths.get_base_dir() == "C:/Users/test/AppData/Roaming"

    def test_windows_missing_appdata(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setenv("HOME", "/home/user")
        result = paths.get_base_dir()
        assert "home" in result.lower() or "user" in result.lower()

    def test_linux_xdg(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
        assert paths.get_base_dir() == "/custom/data"

    def test_linux_fallback(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        result = paths.get_base_dir()
        assert "local/share" in result or result.endswith(".local/share")


class TestGetLogDir:
    def test_override(self, monkeypatch):
        monkeypatch.setenv("MYCALENDAR_LOG_DIR", "/custom/logs")
        assert paths.get_log_dir() == "/custom/logs"

    def test_default(self, monkeypatch):
        monkeypatch.delenv("MYCALENDAR_LOG_DIR", raising=False)
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", "/data")
        assert paths.get_log_dir() == os.path.join("/data", "MyCalendarApp")


class TestGetResourcePath:
    def test_normal(self, monkeypatch):
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        result = paths.get_resource_path("assets/app.ico")
        assert result.endswith("assets/app.ico")

    def test_meipass(self, monkeypatch):
        monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI123", raising=False)
        result = paths.get_resource_path("assets/app.ico")
        assert result == os.path.join("/tmp/_MEI123", "assets/app.ico")


class TestGetAppDataDir:
    def test_creates_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        result = paths.get_app_data_dir()
        assert os.path.isdir(result)
        assert result.endswith("MyCalendarApp")

    def test_fallback_on_permission(self, monkeypatch, tmp_path, tmp_tmpdir):
        monkeypatch.setattr(sys, "platform", "linux")
        real_makedirs = os.makedirs

        def _fail_makedirs(path, *args, **kwargs):
            if path.startswith("/nonexistent"):
                raise OSError("permission denied")
            return real_makedirs(path, *args, **kwargs)

        monkeypatch.setenv("XDG_DATA_HOME", "/nonexistent")
        monkeypatch.setattr(os, "makedirs", _fail_makedirs)
        result = paths.get_app_data_dir()
        assert "MyCalendarApp" in result
