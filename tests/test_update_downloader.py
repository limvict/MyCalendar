# coding: utf-8
"""update_downloader：URL 去重、cleanup_partial、超长/不完整残文件处理。"""
import pytest
from unittest.mock import patch

from desktop_calendar.infrastructure.network import update_downloader as ud


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
    """残文件比预期大时先删除再抛，避免后续 URL 带错误 Range 撞 416。"""

    def _make(self, urls=None):
        return ud.UpdateDownloader(
            urls or ["https://a"], expected_sha256="",
            target_version="1.0.0")

    def test_oversized_dest_removed_before_raise(self, tmp_path):
        dest = tmp_path / "new.exe"
        dest.write_bytes(b"x" * 200)
        d = self._make(["https://a"])

        # 服务端报告 total=100 < 本地 actual=200 → 触发超长分支
        with patch.object(d, "_download_once", return_value=(100, 0)):
            with pytest.raises(IOError, match="长度异常"):
                d._download_and_verify(str(dest))

        assert not dest.exists(), "超长残文件必须删除，否则下一地址会撞 416"

    def test_next_url_resumes_from_zero(self, tmp_path):
        dest = tmp_path / "new.exe"
        dest.write_bytes(b"x" * 200)
        d = self._make(["https://a", "https://b"])
        calls = []

        def fake(url, _dest, resume_from, **_kw):
            calls.append((url, resume_from))
            if url.endswith("a"):
                return (100, 0)   # 触发超长分支并删残文件
            return None           # 第二个地址无 Content-Length，成功

        with patch.object(d, "_download_once", side_effect=fake):
            d._download_and_verify(str(dest))

        assert calls[0] == ("https://a", 200)
        assert calls[1] == ("https://b", 0), (
            "残文件删除后，下一个地址必须从头下载")

    def test_incomplete_dest_kept_for_resume(self, tmp_path, monkeypatch):
        """字节数不足的残文件应保留（走续传），不能误删。"""
        monkeypatch.setattr(ud, "_RETRY_BACKOFF_SEC", (0, 0, 0))
        dest = tmp_path / "new.exe"
        dest.write_bytes(b"x" * 100)
        d = self._make(["https://a"])

        with patch.object(d, "_download_once", return_value=(200, 0)):
            with pytest.raises(IOError):
                d._download_and_verify(str(dest))

        assert dest.exists(), "不完整残文件必须保留供续传"