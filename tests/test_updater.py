# coding: utf-8
"""updater 单元测试。

不启动真实线程、不触网、不写注册表：
  - 纯函数：版本解析 / 比较、占位符 URL 检测、SHA-256 分块哈希、
    临时文件名、bat 替换脚本生成；
  - UpdateManager 状态机：check_async / _on_checked /
    download_and_apply_async / _on_downloaded 的早退与成功分支。

UpdateChecker.run / UpdateDownloader.run 涉及真实网络与子进程，
归入 integration 测试，不在本文件内。
"""
import hashlib
import sys
from unittest.mock import MagicMock

import pytest

import updater
from updater import (
    UpdateDownloader,
    UpdateManager,
    _is_newer,
    _is_packaged,
    _is_placeholder_url,
    _parse_version,
    _sha256_of_file,
    _tmp_bat_name,
    _tmp_exe_name,
    _WAIT_EXIT_MAX_SEC,
)
from event_bus import EventType


# ===================== 纯函数：_parse_version =====================

@pytest.mark.parametrize("raw,expected", [
    ("3.1.2",      (3, 1, 2)),
    ("3.1",        (3, 1)),
    ("3",          (3,)),
    ("3.1.2.4",    (3, 1, 2, 4)),
    ("3.1.2-beta", (3, 1, 0)),   # "2-beta" 非数字 → 0，段数不变
    ("v3.1.2",     (0, 1, 2)),   # "v3" 非数字 → 0（记录现状，非推荐输入）
    ("",           (0,)),        # 空串 → [''] → 0
    ("abc",        (0,)),
])
def test_parse_version(raw, expected):
    """任何段解析失败都归 0，而不是抛异常 —— 清单里写脏了不应让
    整个检查流程崩掉。"""
    assert _parse_version(raw) == expected


# ===================== 纯函数：_is_newer =====================

@pytest.mark.parametrize("remote,local,expected", [
    ("3.1.0", "3.0.0", True),
    ("3.0.0", "3.1.0", False),
    ("3.0.0", "3.0.0", False),   # 相同 → 不算更新
    ("3.0.1", "3.0",   True),    # (3,0,1) > (3,0)
    ("3.0",   "3.0.0", False),   # (3,0) < (3,0,0)，短前缀不算更新
    ("4.0.0", "3.9.9", True),
])
def test_is_newer(remote, local, expected):
    """参数顺序是 (remote, local)，与 _on_checked 里的调用一致。"""
    assert _is_newer(remote, local) is expected


# ===================== 纯函数：_is_placeholder_url =====================

@pytest.mark.parametrize("url,expected", [
    ("", True),
    (None, True),
    ("https://raw.githubusercontent.com/yourname/yourrepo/main/version.json",
     True),
    ("https://example.com/YOURNAME/version.json", True),    # 大小写不敏感
    ("https://example.com/YOURREPO/version.json", True),
    ("https://example.com/real/repo/version.json", False),
])
def test_is_placeholder_url(url, expected):
    """占位符 URL 必须拦住：发版前忘改会把别人的版本清单拉下来。"""
    assert _is_placeholder_url(url) is expected


# ===================== 纯函数：_is_packaged =====================

def test_is_packaged_false_in_source(monkeypatch):
    """源码环境 sys.frozen 不存在 → False，拒绝自动替换。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert _is_packaged() is False


def test_is_packaged_true_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert _is_packaged() is True


# ===================== 纯函数：_sha256_of_file =====================

def test_sha256_of_file_matches_hashlib(tmp_path):
    p = tmp_path / "payload.bin"
    p.write_bytes(b"hello world")
    assert _sha256_of_file(str(p)) == hashlib.sha256(b"hello world").hexdigest()


def test_sha256_of_file_empty(tmp_path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    assert _sha256_of_file(str(p)) == hashlib.sha256(b"").hexdigest()


def test_sha256_of_file_large_spans_chunks(tmp_path):
    """文件大于分块大小（1 MiB）时应逐块累加，而非只算首块。"""
    data = b"a" * (3 * (1 << 20) + 123)
    p = tmp_path / "large.bin"
    p.write_bytes(data)
    assert _sha256_of_file(str(p)) == hashlib.sha256(data).hexdigest()


# ===================== 纯函数：临时文件名 =====================

def test_tmp_names_include_pid_and_differ_per_pid():
    """bat 靠 PID 避免多实例互相覆盖，也让 bat 的同名自删能命中自己。"""
    assert "12345" in _tmp_exe_name(12345)
    assert "12345" in _tmp_bat_name(12345)
    assert _tmp_exe_name(1) != _tmp_exe_name(2)
    assert _tmp_bat_name(1) != _tmp_bat_name(2)


# ===================== UpdateDownloader._build_bat =====================

def test_build_bat_polls_pid_then_moves(qapp):
    """bat 必须先等主程序退出再 move，且 move 顺序为
    old ← exe、exe ← new，最后 start 新 exe。"""
    dl = UpdateDownloader("http://x/y.exe", "abc", target_pid=12345)
    bat = dl._build_bat(
        exe_path=r"C:\app\main.exe",
        new_exe=r"C:\Temp\new.exe",
        old_exe=r"C:\app\main.exe.old",
        bat_path=r"C:\Temp\a.bat",
    )

    # 轮询段的 PID 与上限
    assert "TARGET_PID=12345" in bat
    assert "tasklist /FI" in bat
    assert f"GEQ {_WAIT_EXIT_MAX_SEC}" in bat

    # move 顺序：先备份旧 exe，再把新 exe 顶上，最后启动
    i_backup = bat.index(r'move /y "C:\app\main.exe" "C:\app\main.exe.old"')
    i_move   = bat.index(r'move /y "C:\Temp\new.exe" "C:\app\main.exe"')
    i_start  = bat.index(r'start "" "C:\app\main.exe"')
    assert i_backup < i_move < i_start


def test_build_bat_self_deletes(qapp):
    dl = UpdateDownloader("http://x/y.exe", "abc", target_pid=1)
    bat = dl._build_bat("a.exe", "b.exe", "a.exe.old", "c.bat")
    assert "del \"%~f0\"" in bat


def test_build_bat_uses_crlf(qapp):
    """Windows cmd 对 LF-only 容忍度差，脚本必须写 CRLF。"""
    dl = UpdateDownloader("http://x/y.exe", "abc", target_pid=1)
    bat = dl._build_bat("a.exe", "b.exe", "a.exe.old", "c.bat")
    assert "\r\n" in bat
    # 不应出现孤立的 \n（每个 \n 前面都跟着 \r）
    for i, ch in enumerate(bat):
        if ch == "\n":
            assert bat[i - 1] == "\r", f"位置 {i} 处的 \\n 前没有 \\r"


# ===================== UpdateManager 测试替身 =====================

_REAL_URL = "https://real.example.com/version.json"


class _FakeBus:
    """只记录 publish；subscribe / unsubscribe 留给别处的替身。"""

    def __init__(self):
        self.calls = []

    def publish(self, evt, **kw):
        self.calls.append((evt, kw))

    def subscribe(self, *a, **k):
        pass

    def unsubscribe(self, *a, **k):
        pass


@pytest.fixture
def fake_bus(monkeypatch):
    bus = _FakeBus()
    monkeypatch.setattr(updater, "event_bus", bus)
    return bus


@pytest.fixture
def packaged(monkeypatch):
    """默认把环境伪装成"已打包"，让 check_async 越过第一道门。"""
    monkeypatch.setattr(updater, "_is_packaged", lambda: True)


def _install_fake_checker(monkeypatch):
    """把 UpdateChecker 换成 MagicMock；返回该替身。

    替换的是 updater.UpdateChecker 这个名字，check_async 里的
    `UpdateChecker(...)` 会命中 patched 版本。替身不需要真的
    QThread：check_async 只依赖 .finished / .checked / .start()。
    """
    fake = MagicMock(name="FakeChecker")
    monkeypatch.setattr(updater, "UpdateChecker", lambda *a, **k: fake)
    return fake


def _install_fake_downloader(monkeypatch):
    fake = MagicMock(name="FakeDownloader")
    monkeypatch.setattr(updater, "UpdateDownloader", lambda *a, **k: fake)
    return fake


# ===================== UpdateManager.check_async =====================

def test_check_async_skips_when_not_packaged(qapp, monkeypatch):
    """非打包环境（源码运行）必须返回 False —— 替换 python.exe
    会毁掉开发环境。"""
    monkeypatch.setattr(updater, "_is_packaged", lambda: False)
    mgr = UpdateManager(manifest_url=_REAL_URL)
    assert mgr.check_async() is False
    assert mgr._checker is None


def test_check_async_skips_placeholder_url(qapp, packaged):
    """占位符 URL（含 yourname / yourrepo）跳过，避免发版前误拉
    别人的 version.json。"""
    mgr = UpdateManager(
        manifest_url="https://raw.githubusercontent.com/yourname/yourrepo/main/version.json")
    assert mgr.check_async() is False
    assert mgr._checker is None


def test_check_async_skips_when_already_running(qapp, packaged):
    """已有在跑的 checker → 返回 False，不覆盖引用。"""
    mgr = UpdateManager(manifest_url=_REAL_URL)
    existing = MagicMock(name="ExistingChecker")
    existing.isRunning.return_value = True
    mgr._checker = existing

    assert mgr.check_async() is False
    assert mgr._checker is existing       # 未被覆盖
    existing.start.assert_not_called()


def test_check_async_starts_checker(qapp, packaged, monkeypatch):
    fake = _install_fake_checker(monkeypatch)
    mgr = UpdateManager(manifest_url=_REAL_URL)

    assert mgr.check_async() is True
    assert mgr._checker is fake
    fake.start.assert_called_once()
    # 两条信号都接到（具体槽用 is 断言留到 _on_checked 的测试）：
    # 检查信号对象被 connect 调用过即可，不深究连接的是谁。
    fake.finished.connect.assert_called_once()
    fake.checked.connect.assert_called_once()


# ===================== UpdateManager._on_checked =====================

def test_on_checked_clears_checker_even_on_error(qapp, fake_bus):
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._checker = MagicMock(name="Stale")
    mgr._pending_info = {"version": "9.9.9"}

    mgr._on_checked({"has_update": False, "info": {}, "error": "boom"})

    assert mgr._checker is None
    assert fake_bus.calls == []       # 不广播
    # _pending_info 不被脏结果污染
    assert mgr._pending_info == {"version": "9.9.9"}


def test_on_checked_no_update_publishes_nothing(qapp, fake_bus):
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._on_checked({"has_update": False, "info": {}, "error": None})
    assert fake_bus.calls == []


@pytest.mark.parametrize("info", [
    "not-a-dict",
    None,
    [],
])
def test_on_checked_rejects_non_dict_info(qapp, fake_bus, info):
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._on_checked({"has_update": True, "info": info, "error": None})
    assert fake_bus.calls == []
    assert mgr._pending_info == {}


@pytest.mark.parametrize("info", [
    {},                                               # 全缺
    {"version": "3.1.0"},                             # 缺 url/sha
    {"version": "3.1.0", "download_url": "x"},        # 缺 sha
    {"version": "3.1.0", "sha256": "a"},              # 缺 url
    {"download_url": "x", "sha256": "a"},             # 缺 version
    {"version": "", "download_url": "x", "sha256": "a"},  # 空串算缺
])
def test_on_checked_rejects_missing_required_fields(qapp, fake_bus, info):
    """required 是 (version, download_url, sha256)，任一缺失或为空
    都拒绝更新并跳过广播。"""
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._on_checked({"has_update": True, "info": info, "error": None})
    assert fake_bus.calls == []
    assert mgr._pending_info == {}


def test_on_checked_publishes_update_available(qapp, fake_bus):
    mgr = UpdateManager(manifest_url=_REAL_URL)
    info = {
        "version": "3.1.0",
        "download_url": "https://real.example.com/app.exe",
        "sha256": "a" * 64,
    }
    mgr._on_checked({"has_update": True, "info": info, "error": None})

    assert mgr._pending_info == info
    assert len(fake_bus.calls) == 1
    evt, kw = fake_bus.calls[0]
    assert evt == EventType.UPDATE_AVAILABLE
    assert kw == {"info": info}


# ===================== UpdateManager.download_and_apply_async =====================

def test_download_and_apply_skips_when_not_packaged(qapp, monkeypatch):
    monkeypatch.setattr(updater, "_is_packaged", lambda: False)
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._pending_info = {
        "version": "3.1.0", "download_url": "u", "sha256": "s"}
    assert mgr.download_and_apply_async() is False
    assert mgr._downloader is None


def test_download_and_apply_skips_without_pending(qapp, packaged):
    mgr = UpdateManager(manifest_url=_REAL_URL)
    assert mgr.download_and_apply_async() is False
    assert mgr._downloader is None


def test_download_and_apply_skips_when_already_running(qapp, packaged):
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._pending_info = {
        "version": "3.1.0", "download_url": "u", "sha256": "s"}
    existing = MagicMock(name="StaleDownloader")
    existing.isRunning.return_value = True
    mgr._downloader = existing

    assert mgr.download_and_apply_async() is False
    assert mgr._downloader is existing
    existing.start.assert_not_called()


@pytest.mark.parametrize("pending", [
    {"version": "3.1.0", "sha256": "s"},              # 缺 download_url
    {"version": "3.1.0", "download_url": "",  "sha256": "s"},  # 空 url
    {"version": "3.1.0", "download_url": "u", "sha256": ""},   # 空 sha
])
def test_download_and_apply_rejects_incomplete_pending(
        qapp, packaged, pending):
    """_on_checked 已经拦过一次，这两条是内部误调时的兜底。"""
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._pending_info = pending
    assert mgr.download_and_apply_async() is False
    assert mgr._downloader is None


def test_download_and_apply_starts_downloader(
        qapp, packaged, monkeypatch):
    fake = _install_fake_downloader(monkeypatch)
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._pending_info = {
        "version": "3.1.0",
        "download_url": "https://real.example.com/app.exe",
        "sha256": "a" * 64,
    }

    assert mgr.download_and_apply_async() is True
    assert mgr._downloader is fake
    fake.start.assert_called_once()
    # 两条信号（生命周期 + 结果）都接上
    assert fake.finished.connect.call_count == 1
    assert fake.finished_download.connect.call_count == 1


# ===================== UpdateManager._on_downloaded =====================

def test_on_downloaded_failure_publishes_update_failed(qapp, fake_bus):
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._downloader = MagicMock(name="Stale")

    mgr._on_downloaded({"ok": False, "error": "网络断了"})

    assert mgr._downloader is None
    assert len(fake_bus.calls) == 1
    evt, kw = fake_bus.calls[0]
    assert evt == EventType.UPDATE_FAILED
    assert kw["stage"] == "download"
    assert kw["error"] == "网络断了"


def test_on_downloaded_failure_defaults_error_when_missing(
        qapp, fake_bus):
    """缺 error 字段时落回 "unknown"，不会让 payload 缺键。"""
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._on_downloaded({"ok": False})
    assert fake_bus.calls[0][1]["error"] == "unknown"


def test_on_downloaded_success_publishes_update_ready(qapp, fake_bus):
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._downloader = MagicMock(name="Stale")

    mgr._on_downloaded({"ok": True, "error": None})

    assert mgr._downloader is None
    assert len(fake_bus.calls) == 1
    evt, kw = fake_bus.calls[0]
    assert evt == EventType.UPDATE_READY
    # UPDATE_READY 无 payload
    assert kw == {}