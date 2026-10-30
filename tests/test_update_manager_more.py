# coding: utf-8
"""update_manager 补充：safe_url 无主机、version_re 边界、is_newer 混合长度。"""
import pytest

from desktop_calendar.infrastructure.network import update_manager as um


class TestSafeDownloadUrlMore:
    def test_no_host(self):
        # "https:///path" urlparse 后 hostname 为空
        assert um._is_safe_download_url("https:///path") is False

    def test_userinfo_https_ok(self):
        # https 协议 + 非空主机即通过；userinfo 不影响判定
        assert um._is_safe_download_url(
            "https://user:pass@example.com/x") is True


class TestSafeVersionReMore:
    def test_newline_rejected(self):
        assert um._SAFE_VERSION_RE.fullmatch("1.0\n") is None

    def test_space_rejected(self):
        assert um._SAFE_VERSION_RE.fullmatch("1.0 0") is None

    def test_long_dotted_allowed(self):
        assert um._SAFE_VERSION_RE.fullmatch("1.2.3.4.5") is not None


class TestIsNewerMore:
    def test_mixed_lengths_reverse(self):
        assert um._is_newer("1.0.1", "1.0") is True
        assert um._is_newer("1.0", "1.0.1") is False

    def test_leading_zero_parsed_as_int(self):
        # "01" 解析为 1，与 "1" 相等
        assert um._is_newer("1.01.0", "1.1.0") is False

    def test_negative_segment_compares_lower(self):
        # _parse_version 保留负号，-1 < 0
        assert um._is_newer("1.-1.0", "1.0.0") is False


class TestPlaceholderUrlMore:
    def test_angle_bracket_host_is_placeholder(self):
        assert um._is_placeholder_url("https://<your-domain>/x.json") is True

    def test_yourname_is_placeholder(self):
        assert um._is_placeholder_url(
            "https://yourname.github.io/x") is True

    def test_real_url_not_placeholder(self):
        assert um._is_placeholder_url(
            "https://github.com/real/repo/x.json") is False