# coding: utf-8
import hashlib

import pytest

from desktop_calendar.infrastructure.network import update_manager as um


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


class TestStateFile:
    def test_consume_empty(self, isolated_paths):
        assert um.consume_state_file() is None

    def test_roundtrip_then_deleted(self, isolated_paths):
        state_path = um._state_file_path()
        with open(state_path, "w", encoding="utf-8") as f:
            f.write('version=1.0.1\nreason=backup_failed\n')
        result = um.consume_state_file()
        assert result == {"version": "1.0.1", "reason": "backup_failed"}
        # 已删除
        assert um.consume_state_file() is None