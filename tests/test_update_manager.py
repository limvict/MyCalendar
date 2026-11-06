# coding: utf-8
"""update_manager：版本解析、URL 安全、sha256、state 文件、残留清理、可重试错误。"""
import hashlib
import http.client
import os
import socket
from pathlib import Path

import pytest

# 全部被测符号都 re-export 到了 update_manager 命名空间（见该模块
# 顶部 "兼容性 re-export" 段的 import 清单）：
#   - _parse_version / _is_newer / _is_placeholder_url /
#     _is_safe_download_url / _SAFE_VERSION_RE   ← update_checker
#   - consume_state_file / _state_file_path /
#     _cleanup_leftover_new_exe                  ← update_bat
#   - _sha256_of_file / _is_retryable_network_error ← update_downloader
from desktop_calendar.infrastructure.network import update_manager as um


# ---------------- _parse_version / _is_newer ----------------
class TestParseVersion:
    @pytest.mark.parametrize("v,expected", [
        ("1.2.3", (1, 2, 3)),
        ("1.0", (1, 0)),
        ("0.0.0", (0, 0, 0)),
        ("1.2.3.4", (1, 2, 3, 4)),
    ])
    def test_valid(self, v, expected):
        assert um._parse_version(v) == expected

    def test_invalid_segment_becomes_zero(self):
        assert um._parse_version("1.x.3") == (1, 0, 3)

    def test_empty(self):
        assert um._parse_version("") == (0,)

    def test_negative_and_empty_segment(self):
        assert um._parse_version("1.-2.3") == (1, -2, 3)
        assert um._parse_version("1..3") == (1, 0, 3)


class TestIsNewer:
    def test_newer(self):
        assert um._is_newer("1.0.1", "1.0.0") is True
        assert um._is_newer("2.0.0", "1.9.9") is True

    def test_same(self):
        assert um._is_newer("1.0.0", "1.0.0") is False

    def test_older(self):
        assert um._is_newer("1.0.0", "1.0.1") is False

    def test_different_lengths(self):
        assert um._is_newer("1.0.0", "1.0") is True

    def test_mixed_lengths_reverse(self):
        assert um._is_newer("1.0.1", "1.0") is True
        assert um._is_newer("1.0", "1.0.1") is False

    def test_leading_zero_parsed_as_int(self):
        assert um._is_newer("1.01.0", "1.1.0") is False

    def test_negative_segment_compares_lower(self):
        assert um._is_newer("1.-1.0", "1.0.0") is False


# ---------------- URL / 版本正则 ----------------
class TestPlaceholderUrl:
    @pytest.mark.parametrize("url", [
        "", "https://yourname.github.io/x",
        "https://github.com/<org>/<repo>",
        "https://<your-domain>/x.json",
    ])
    def test_is_placeholder(self, url):
        assert um._is_placeholder_url(url) is True

    def test_not_placeholder(self):
        assert um._is_placeholder_url(
            "https://github.com/real/repo/x.json") is False

    def test_angle_bracket_host_is_placeholder(self):
        assert um._is_placeholder_url("https://<your-domain>/x.json") is True

    def test_real_url_not_placeholder(self):
        assert um._is_placeholder_url(
            "https://github.com/real/repo/x.json") is False


class TestSafeDownloadUrl:
    @pytest.mark.parametrize("url", [
        "https://example.com/file.zip",
        "https://sub.example.com:8080/x",
    ])
    def test_valid_https(self, url):
        assert um._is_safe_download_url(url) is True

    @pytest.mark.parametrize("url", [
        "http://example.com/x",
        "ftp://example.com/x",
        "",
        "https://",
        "not a url",
    ])
    def test_invalid(self, url):
        assert um._is_safe_download_url(url) is False

    def test_no_host(self):
        # "https:///path" urlparse 后 hostname 为空
        assert um._is_safe_download_url("https:///path") is False

    def test_userinfo_https_ok(self):
        # https 协议 + 非空主机即通过；userinfo 不影响判定
        assert um._is_safe_download_url(
            "https://user:pass@example.com/x") is True


class TestSafeVersionRegex:
    @pytest.mark.parametrize("v", ["1.0.0", "1.0.0-beta", "1.0.0.1", "v1"])
    def test_valid(self, v):
        assert um._SAFE_VERSION_RE.fullmatch(v) is not None

    @pytest.mark.parametrize("v", [
        "1.0.0; rm -rf /", "1.0%0a", "1.0|dir", "1.0&x",
        "1.0 > x", "1.0^", "",
    ])
    def test_invalid(self, v):
        assert um._SAFE_VERSION_RE.fullmatch(v) is None

    def test_newline_rejected(self):
        assert um._SAFE_VERSION_RE.fullmatch("1.0\n") is None

    def test_space_rejected(self):
        assert um._SAFE_VERSION_RE.fullmatch("1.0 0") is None

    def test_long_dotted_allowed(self):
        assert um._SAFE_VERSION_RE.fullmatch("1.2.3.4.5") is not None


# ---------------- sha256 / state ----------------
class TestSha256:
    def test_basic(self, tmp_path):
        path = tmp_path / "f.bin"
        data = b"hello world"
        path.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert um._sha256_of_file(str(path)) == expected

    def test_empty(self, tmp_path):
        path = tmp_path / "f.bin"
        path.write_bytes(b"")
        assert um._sha256_of_file(str(path)) == hashlib.sha256(b"").hexdigest()


class TestStateFile:
    def test_consume_empty(self, isolated_paths):
        assert um.consume_state_file() is None

    def test_roundtrip_then_deleted(self, isolated_paths):
        # 用 consume_state_file 内部同一路径，确保读写一致
        state_path = um._state_file_path()
        with open(state_path, "w", encoding="utf-8") as f:
            f.write('version=1.0.1\nreason=backup_failed\n')
        result = um.consume_state_file()
        assert result == {"version": "1.0.1", "reason": "backup_failed"}
        # 已删除
        assert um.consume_state_file() is None


# ---------------- 残留清理 / 可重试错误 ----------------
def test_cleanup_leftover_rejects_bad_path(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("x", encoding="utf-8")
    um._cleanup_leftover_new_exe(str(victim))
    assert victim.exists()      # 非 %TEMP%/DLC_update_new_*.exe，拒绝删


def test_cleanup_leftover_removes_tmp_files(tmp_tmpdir):
    tmp = str(tmp_tmpdir)
    pid = 999999
    new_exe = os.path.join(tmp, f"DLC_update_new_{pid}.exe")
    bat = os.path.join(tmp, f"DLC_update_apply_{pid}.bat")
    Path(new_exe).write_bytes(b"x")
    Path(bat).write_bytes(b"x")
    um._cleanup_leftover_new_exe(new_exe)
    assert not os.path.exists(new_exe)
    assert not os.path.exists(bat)


def test_is_retryable_network_error():
    assert um._is_retryable_network_error(ConnectionResetError("x"))
    assert um._is_retryable_network_error(ConnectionAbortedError("x"))
    assert um._is_retryable_network_error(socket.timeout())
    assert um._is_retryable_network_error(
        http.client.IncompleteRead(b"x", 10))
    assert not um._is_retryable_network_error(ValueError("x"))
