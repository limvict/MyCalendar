# coding: utf-8
"""update_downloader：预检、URL 去重、cleanup_partial、安装目录探测。"""
import os
import sys

import pytest

from desktop_calendar.infrastructure.network import update_downloader as ud


class TestIsInstallDirWritable:
    def test_writable(self, tmp_path):
        assert ud._is_install_dir_writable(str(tmp_path)) is True

    def test_not_writable(self, tmp_path, monkeypatch):
        def fail_open(*a, **k):
            raise OSError(13, "permission denied")

        import builtins
        monkeypatch.setattr(builtins, "open", fail_open)
        assert ud._is_install_dir_writable(str(tmp_path)) is False


class TestInProgramFiles:
    def test_non_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert ud._in_program_files("/any/path") is False

    def test_inside(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        pf = tmp_path / "Program Files"
        pf.mkdir()
        monkeypatch.setenv("ProgramFiles", str(pf))
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        monkeypatch.delenv("ProgramW6432", raising=False)
        assert ud._in_program_files(str(pf / "app" / "x.exe")) is True

    def test_outside(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        pf = tmp_path / "Program Files"
        pf.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.setenv("ProgramFiles", str(pf))
        monkeypatch.delenv("ProgramFiles(x86)", raising=False)
        monkeypatch.delenv("ProgramW6432", raising=False)
        assert ud._in_program_files(str(other / "x.exe")) is False


class TestPrecheck:
    def test_writable_passes(self, tmp_path):
        exe = tmp_path / "app.exe"
        exe.write_text("x")
        assert ud.precheck_install_target(str(exe)) is None

    def test_unwritable_returns_reason(self, tmp_path, monkeypatch):
        exe = tmp_path / "app.exe"
        exe.write_text("x")
        monkeypatch.setattr(ud, "_is_install_dir_writable", lambda d: False)
        monkeypatch.setattr(ud, "_in_program_files", lambda e: False)
        result = ud.precheck_install_target(str(exe))
        assert result is not None and "不可写" in result

    def test_program_files_hint(self, tmp_path, monkeypatch):
        exe = tmp_path / "app.exe"
        exe.write_text("x")
        monkeypatch.setattr(ud, "_is_install_dir_writable", lambda d: False)
        monkeypatch.setattr(ud, "_in_program_files", lambda e: True)
        result = ud.precheck_install_target(str(exe))
        assert "管理员" in result


class TestInit:
    def test_dedupe_urls(self):
        d = ud.UpdateDownloader(
            ["https://a", "https://a", "https://b"], "sha", 1)
        assert d._urls == ["https://a", "https://b"]

    def test_single_str_url(self):
        d = ud.UpdateDownloader("https://a", "sha", 1)
        assert d._urls == ["https://a"]

    def test_sha_lowercased_stripped(self):
        d = ud.UpdateDownloader(["https://a"], "  ABC  ", 1)
        assert d._expected_sha == "abc"

    def test_falsy_urls_skipped(self):
        d = ud.UpdateDownloader(["", None, "https://a"], "", 1)
        assert d._urls == ["https://a"]


class TestCleanupPartial:
    def test_noop_when_none(self):
        d = ud.UpdateDownloader(["https://a"], "", 1)
        d.cleanup_partial()  # 不抛

    def test_removes_file(self, tmp_path):
        d = ud.UpdateDownloader(["https://a"], "", 1)
        f = tmp_path / "x.exe"
        f.write_text("x")
        d._partial_path = str(f)
        d.cleanup_partial()
        assert not f.exists()
        assert d._partial_path is None

    def test_missing_file_ok(self, tmp_path):
        d = ud.UpdateDownloader(["https://a"], "", 1)
        d._partial_path = str(tmp_path / "missing.exe")
        d.cleanup_partial()  # 不抛

    def test_idempotent(self, tmp_path):
        d = ud.UpdateDownloader(["https://a"], "", 1)
        f = tmp_path / "x.exe"
        f.write_text("x")
        d._partial_path = str(f)
        d.cleanup_partial()
        d.cleanup_partial()  # 二次不抛
