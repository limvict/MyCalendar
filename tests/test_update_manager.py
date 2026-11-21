# coding: utf-8
"""update_manager：版本解析、URL 安全、sha256、可重试错误、孤儿线程回收。

预发布（-beta / -rc 等后缀）已从产品语义移除：构建链
（scripts/_version.validate_ver）、release.yml 的 tag 校验、运行时
_SAFE_VERSION_RE 三处统一只认严格 X.Y.Z。
"""

import hashlib
import http.client
from unittest.mock import MagicMock

import pytest

from desktop_calendar.infrastructure.network import update_manager as um
from desktop_calendar.infrastructure.network.update_checker import _is_newer
from desktop_calendar.infrastructure.network.update_downloader import (
    _is_retryable_network_error,
    _sha256_of_file,
)


class TestParseVersion:
    @pytest.mark.parametrize(
        "v,expected",
        [
            ("1.2.3", (1, 2, 3)),
            ("1.0", (1, 0)),
            ("0.0.0", (0, 0, 0)),
            ("1.2.3.4", (1, 2, 3, 4)),
        ],
    )
    def test_valid(self, v, expected):
        assert um._parse_version(v) == expected

    def test_invalid_segment_becomes_zero(self):
        assert um._parse_version("1.x.3") == (1, 0, 3)

    def test_empty(self):
        assert um._parse_version("") == (0,)

    def test_negative_and_empty_segment(self):
        assert um._parse_version("1.-2.3") == (1, -2, 3)
        assert um._parse_version("1..3") == (1, 0, 3)

    def test_non_numeric_segment_falls_back_to_zero(self):
        """防御性回退：非数字段（含预发布后缀）解析为 0。

        正常路径不会走到：version 已被 _SAFE_VERSION_RE 校验为纯
        X.Y.Z。此处仅锁定 manifest 被外部篡改时 _parse_version 不
        抛异常、_is_newer 得出安全结论。
        """
        assert um._parse_version("3.1.0-beta") == (3, 1, 0)
        assert um._parse_version("3.1.0") == (3, 1, 0)


class TestIsNewer:
    def test_newer(self):
        assert _is_newer("1.0.1", "1.0.0") is True
        assert _is_newer("2.0.0", "1.9.9") is True

    def test_same(self):
        assert _is_newer("1.0.0", "1.0.0") is False

    def test_older(self):
        assert _is_newer("1.0.0", "1.0.1") is False

    def test_different_lengths(self):
        assert _is_newer("1.0.0", "1.0") is True

    def test_mixed_lengths_reverse(self):
        assert _is_newer("1.0.1", "1.0") is True
        assert _is_newer("1.0", "1.0.1") is False

    def test_leading_zero_parsed_as_int(self):
        assert _is_newer("1.01.0", "1.1.0") is False

    def test_negative_segment_compares_lower(self):
        assert _is_newer("1.-1.0", "1.0.0") is False


class TestPlaceholderUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "",
            "https://yourname.github.io/x",
            "https://github.com/<org>/<repo>",
            "https://<your-domain>/x.json",
        ],
    )
    def test_is_placeholder(self, url):
        assert um._is_placeholder_url(url) is True

    def test_not_placeholder(self):
        assert um._is_placeholder_url("https://github.com/real/repo/x.json") is False

    def test_angle_bracket_host_is_placeholder(self):
        assert um._is_placeholder_url("https://<your-domain>/x.json") is True

    def test_real_url_not_placeholder(self):
        assert um._is_placeholder_url("https://github.com/real/repo/x.json") is False


class TestSafeDownloadUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/file.zip",
            "https://sub.example.com:8080/x",
        ],
    )
    def test_valid_https(self, url):
        assert um._is_safe_download_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/x",
            "ftp://example.com/x",
            "",
            "https://",
            "not a url",
        ],
    )
    def test_invalid(self, url):
        assert um._is_safe_download_url(url) is False

    def test_no_host(self):
        assert um._is_safe_download_url("https:///path") is False

    def test_userinfo_https_ok(self):
        assert um._is_safe_download_url("https://user:pass@example.com/x") is True


class TestSafeVersionRegex:
    """_SAFE_VERSION_RE 严格 X.Y.Z —— 与 scripts/_version.validate_ver、
    release.yml 的 tag 格式校验三处契约一致。"""

    @pytest.mark.parametrize("v", ["0.0.0", "1.0.0", "3.0.3", "10.20.30"])
    def test_valid_x_y_z(self, v):
        assert um._SAFE_VERSION_RE.fullmatch(v) is not None

    @pytest.mark.parametrize(
        "v",
        [
            # 段数不是 3
            "1",
            "1.0",
            "1.0.0.1",
            "1.2.3.4.5",
            # 预发布 / 前缀（构建链与运行时均拒绝）
            "1.0.0-beta",
            "1.0.0-rc.1",
            "v1.0.0",
            # 注入 / 空
            "1.0.0; rm -rf /",
            "1.0%0a",
            "1.0|dir",
            "1.0&x",
            "1.0 > x",
            "1.0^",
            "",
            # 换行 / 空格
            "1.0\n",
            "1.0 0",
        ],
    )
    def test_invalid(self, v):
        assert um._SAFE_VERSION_RE.fullmatch(v) is None


class TestSha256:
    def test_basic(self, tmp_path):
        path = tmp_path / "f.bin"
        data = b"hello world"
        path.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert _sha256_of_file(str(path)) == expected

    def test_empty(self, tmp_path):
        path = tmp_path / "f.bin"
        path.write_bytes(b"")
        assert _sha256_of_file(str(path)) == hashlib.sha256(b"").hexdigest()


def test_is_retryable_network_error():
    assert _is_retryable_network_error(ConnectionResetError("x"))
    assert _is_retryable_network_error(ConnectionAbortedError("x"))
    assert _is_retryable_network_error(TimeoutError())
    assert _is_retryable_network_error(http.client.IncompleteRead(b"x", 10))
    assert not _is_retryable_network_error(ValueError("x"))


class _FakeThread:
    def __init__(self, finished: bool):
        self._finished = finished
        self.deleted = False

    def isFinished(self):
        return self._finished

    def deleteLater(self):
        self.deleted = True


class _DeadThread:
    """模拟底层 C++ 对象已销毁的 QThread。"""

    def isFinished(self):
        raise RuntimeError("wrapped C/C++ object deleted")

    def deleteLater(self):
        raise RuntimeError("wrapped C/C++ object deleted")


class TestPruneOrphanThreads:
    def test_removes_finished_keeps_running(self, qapp):
        mgr = um.UpdateManager()
        done, running = _FakeThread(True), _FakeThread(False)
        mgr._orphan_threads = [done, running]

        mgr._prune_orphan_threads()

        assert done.deleted is True
        assert running.deleted is False
        assert mgr._orphan_threads == [running]

    def test_dead_qt_objects_tolerated(self, qapp):
        mgr = um.UpdateManager()
        mgr._orphan_threads = [_DeadThread()]
        mgr._prune_orphan_threads()
        assert mgr._orphan_threads == []

    def test_noop_when_empty(self, qapp):
        mgr = um.UpdateManager()
        mgr._orphan_threads = []
        mgr._prune_orphan_threads()
        assert mgr._orphan_threads == []

    def test_called_on_check_async_entry(self, qapp, monkeypatch):
        mgr = um.UpdateManager()
        spy = MagicMock()
        mgr._orphan_threads = [_FakeThread(True)]
        monkeypatch.setattr(mgr, "_prune_orphan_threads", spy)
        monkeypatch.setattr(um, "_is_packaged", lambda: False)

        assert mgr.check_async() is False
        spy.assert_called_once()

    def test_called_on_download_and_apply_entry(self, qapp, monkeypatch):
        mgr = um.UpdateManager()
        spy = MagicMock()
        mgr._orphan_threads = [_FakeThread(True)]
        monkeypatch.setattr(mgr, "_prune_orphan_threads", spy)
        monkeypatch.setattr(um, "_is_packaged", lambda: False)

        assert mgr.download_and_apply_async() is False
        spy.assert_called_once()


# ===================== 手动检查 / 镜像地址 =====================
class _StubChecker:
    """替身：不真跑线程，只记录构造参数，信号用 MagicMock。"""

    last = None

    def __init__(self, urls, parent=None):
        self.urls = urls
        self.finished = MagicMock()
        self.checked = MagicMock()
        self.started = False
        _StubChecker.last = self

    def isRunning(self):
        return False

    def start(self):
        self.started = True

    def deleteLater(self):
        pass


def test_manual_check_allowed_when_not_packaged(qapp, monkeypatch):
    monkeypatch.setattr(um, "_is_packaged", lambda: False)
    monkeypatch.setattr(um, "UpdateChecker", _StubChecker)
    mgr = um.UpdateManager(manifest_url="https://example.com/version.json")

    assert mgr.check_async(manual=True) is True
    assert _StubChecker.last.urls == ("https://example.com/version.json",)
    assert _StubChecker.last.started is True


def test_auto_check_skipped_when_not_packaged(qapp, monkeypatch):
    monkeypatch.setattr(um, "_is_packaged", lambda: False)
    mgr = um.UpdateManager(manifest_url="https://example.com/version.json")
    assert mgr.check_async() is False


def test_default_manifest_carries_mirrors(qapp):
    from desktop_calendar.infrastructure.network.update_checker import manifest_urls

    mgr = um.UpdateManager()
    assert mgr._manifest_urls == manifest_urls()
    assert len(mgr._manifest_urls) > 1


def test_manual_result_callback_receives_error(qapp, monkeypatch):
    monkeypatch.setattr(um, "_is_packaged", lambda: False)
    monkeypatch.setattr(um, "UpdateChecker", _StubChecker)
    mgr = um.UpdateManager(manifest_url="https://example.com/version.json")
    seen = []

    assert mgr.check_async(manual=True, on_result=seen.append) is True
    mgr._on_checked({"has_update": False, "info": {}, "error": "boom"})

    assert len(seen) == 1
    assert seen[0]["error"] == "boom"


def test_checking_property_tracks_thread(qapp):
    class _Running:
        def isRunning(self):
            return True

    mgr = um.UpdateManager()
    assert mgr.checking is False
    mgr._checker = _Running()
    assert mgr.checking is True


# ===================== 清单正则校验在调度层的效果 =====================
def _capture_published(monkeypatch):
    """替换模块级 event_bus（_EventBusProxy 的 publish 是类属性，不能在实例上打桩）。"""
    published = []

    class _RecordingBus:
        def publish(self, event, **kw):
            published.append((event, kw))

    monkeypatch.setattr(um, "event_bus", _RecordingBus())
    return published


def test_invalid_manifest_rejected(qapp, monkeypatch):
    published = _capture_published(monkeypatch)
    mgr = um.UpdateManager(manifest_url="https://example.com/version.json")
    mgr._on_checked(
        {
            "has_update": True,
            "info": {
                "version": "9.9.9",
                "download_url": "https://example.com/setup.exe",
                "sha256": "abc",
            },
        }
    )
    assert published == []
    assert mgr._pending_info == {}


def test_valid_manifest_published(qapp, monkeypatch):
    published = _capture_published(monkeypatch)
    mgr = um.UpdateManager(manifest_url="https://example.com/version.json")
    info = {
        "version": "9.9.9",
        "download_url": "https://example.com/setup.exe",
        "sha256": "b" * 64,
    }
    mgr._on_checked({"has_update": True, "info": info})
    assert [event for event, _ in published] == [um.EventType.UPDATE_AVAILABLE]
    assert mgr._pending_info["version"] == "9.9.9"
