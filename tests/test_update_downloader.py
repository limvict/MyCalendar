# coding: utf-8
"""update_downloader：预检、URL 去重、cleanup_partial、安装目录探测。"""
import os
import sys
from unittest.mock import patch

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


class TestOversizedResidual:
    """修复点：残文件比预期大时先删除再抛，避免后续 URL 带错误 Range 撞 416。

    mock 说明：_download_once 被替换后不会真的写 dest 文件，
    因此「单 URL 超长分支」测试依赖循环结束后 raise last_exc 抛出
    原 IOError；双 URL 测试用 side_effect 区分两个地址的返回值。
    """

    def _make(self, urls=None):
        return ud.UpdateDownloader(
            urls or ["https://a"], expected_sha256="", target_pid=12345)

    def test_oversized_dest_removed_before_raise(self, tmp_path):
        """单 URL：超长残文件应删除，最终抛「长度异常」而不是 FileNotFoundError。"""
        dest = tmp_path / "new.exe"
        dest.write_bytes(b"x" * 200)
        d = self._make(["https://a"])

        # 服务端报告 total=100 < 本地 actual=200 → 触发超长分支
        with patch.object(d, "_download_once", return_value=(100, 0)):
            with pytest.raises(IOError, match="长度异常"):
                d._download_and_verify(str(dest))

        assert not dest.exists(), "超长残文件必须删除，否则下一地址会撞 416"

    def test_next_url_resumes_from_zero(self, tmp_path):
        """双 URL：残文件删除后，第二个 URL 的 resume_from 必须是 0。"""
        dest = tmp_path / "new.exe"
        dest.write_bytes(b"x" * 200)
        d = self._make(["https://a", "https://b"])
        calls = []

        def fake(url, _dest, resume_from, **_kw):
            calls.append((url, resume_from))
            if url.endswith("a"):
                return (100, 0)   # 触发超长分支并删残文件
            return None           # 第二个地址无 Content-Length，走 sha 空 → 成功

        with patch.object(d, "_download_once", side_effect=fake):
            d._download_and_verify(str(dest))

        assert calls[0] == ("https://a", 200)
        assert calls[1] == ("https://b", 0), (
            "残文件删除后，下一个地址必须从头下载")

    def test_incomplete_dest_kept_for_resume(self, tmp_path, monkeypatch):
        """对照：字节数不足的残文件应保留（走续传），不能误删。

        单 URL 下 _IncompleteDownload 是可重试异常，会重试 3 次。把
        退避时长置 0 避免测试耗时 ~7s。
        """
        monkeypatch.setattr(ud, "_RETRY_BACKOFF_SEC", (0, 0, 0))
        dest = tmp_path / "new.exe"
        dest.write_bytes(b"x" * 100)
        d = self._make(["https://a"])

        with patch.object(d, "_download_once", return_value=(200, 0)):
            with pytest.raises(IOError):
                d._download_and_verify(str(dest))

        assert dest.exists(), "不完整残文件必须保留供续传"