# coding: utf-8
"""updater 单元测试。

不启动真实线程、不触网、不写注册表：
  - 纯函数：版本解析 / 比较、占位符 URL 检测、安全 URL 检测、
    SHA-256 分块哈希、临时文件名、bat 替换脚本生成；
  - UpdateManager 状态机：check_async / _on_checked /
    download_and_apply_async / _on_downloaded 的早退与成功分支。

UpdateChecker.run / UpdateDownloader.run 涉及真实网络与子进程，
归入 integration 测试，不在本文件内。

【平台前提】
UpdateManager.download_and_apply_async 有 sys.platform == "win32"
的显式门。本文件必须能在任意 CI 平台跑，故 packaged fixture 会同时
伪装 _is_packaged 与 sys.platform。详见该 fixture 的 docstring。
"""
import hashlib
import re
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
    _is_safe_download_url,
    _parse_version,
    _sha256_of_file,
    _tmp_bat_name,
    _tmp_exe_name,
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


# ===================== 纯函数：_is_safe_download_url =====================

@pytest.mark.parametrize("url,expected", [
    # 合法
    ("https://example.com/app.exe",          True),
    ("http://example.com/app.exe",           True),
    ("https://cdn.example.com:8443/x",       True),
    # 非法：空 / 非 str
    ("",                                     False),
    (None,                                   False),
    # 非法：无 scheme
    ("x",                                    False),
    ("//example.com/app.exe",                False),   # 协议相对
    ("example.com/app.exe",                  False),
    # 非法：危险 scheme
    ("file:///tmp/evil.exe",                 False),
    ("ftp://example.com/app.exe",            False),
    ("javascript:alert(1)",                  False),
    ("data:application/x-msdownload;base64,AAAA", False),
    # 非法：scheme 合法但无 host
    ("https://",                             False),
    ("http:///path",                         False),
])
def test_is_safe_download_url(url, expected):
    """download_url 必须是 http(s) 且带 host。

    这条检查挡住的是「version.json 被劫持后指向本地文件」的场景，
    不是「URL 是否可达」——可达性由下载阶段验证。
    """
    assert _is_safe_download_url(url) is expected


# ===================== 纯函数：_is_packaged =====================

def test_is_packaged_false_in_source(monkeypatch):
    """源码环境 sys.frozen 不存在 → False，拒绝自动替换。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.delattr(sys, "nuitka_version", raising=False)
    assert _is_packaged() is False


def test_is_packaged_true_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert _is_packaged() is True


def test_is_packaged_true_when_meipass(monkeypatch):
    """部分打包器只设 _MEIPASS。"""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/fake", raising=False)
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


# ===================== UpdateDownloader._build_bat_script =====================

def test_build_bat_polls_pid_then_moves(qapp):
    """bat 必须先等主程序退出再 move，且 move 顺序为
    old ← exe、exe ← new，最后 start 新 exe。

    路径 / PID 走环境变量（DLC_PID / DLC_EXE / DLC_NEW / DLC_OLD /
    DLC_WAIT），脚本里是 %DLC_*% 占位符，避免在 Python 侧做 cmd
    转义；具体值由 run() 在 Popen(env=...) 时注入。
    """
    bat = UpdateDownloader._build_bat_script()

    # 轮询段：从环境变量取 PID，tasklist 查询，计数上限从 WAIT_MAX 取
    assert 'TARGET_PID=%DLC_PID%' in bat
    assert "tasklist /FI" in bat
    assert "GEQ %WAIT_MAX%" in bat

    # move 顺序：先备份旧 exe，再把新 exe 顶上，最后启动
    i_backup = bat.index('move /y "%EXE%" "%OLD%"')
    i_move   = bat.index('move /y "%NEW%" "%EXE%"')
    i_start  = bat.index('start "" "%EXE%"')
    assert i_backup < i_move < i_start


def test_build_bat_env_keys_consistent():
    """Python 侧写入的每个 env key 都必须在 bat 里被消费。

    与 run() 里 env.update({...}) 的键集保持同步：新增键时如果忘了
    在 bat 里用，此测试会失败。DLC_PROBE 是已废弃的死变量。
    """
    bat = UpdateDownloader._build_bat_script()
    for key in ("DLC_PID", "DLC_EXE", "DLC_NEW", "DLC_OLD",
                "DLC_LOG", "DLC_WAIT"):
        assert f"%{key}%" in bat, f"{key} 在 bat 脚本中未被使用"
    assert "%DLC_PROBE%" not in bat, "DLC_PROBE 已废弃，不应再出现"


def test_build_bat_self_deletes(qapp):
    bat = UpdateDownloader._build_bat_script()
    assert 'del "%~f0"' in bat


def test_build_bat_self_delete_silences_errors(qapp):
    """del 自身失败时不应向无归宿的 stderr 输出。

    DETACHED 进程没有控制台，未重定向的错误会留下悬挂的
    「cmd 无法找到文件」轨迹，或触发系统弹框。
    """
    bat = UpdateDownloader._build_bat_script()
    assert 'del "%~f0" >nul 2>&1' in bat
    # 旧写法（无重定向）不应残留
    assert not re.search(r'del "%~f0"\r\n', bat)


def test_build_bat_uses_crlf(qapp):
    """Windows cmd 对 LF-only 容忍度差，脚本必须写 CRLF。"""
    bat = UpdateDownloader._build_bat_script()
    assert "\r\n" in bat
    # 不应出现孤立的 \n（每个 \n 前面都跟着 \r）
    for i, ch in enumerate(bat):
        if ch == "\n":
            assert bat[i - 1] == "\r", f"位置 {i} 处的 \\n 前没有 \\r"


def _rollback_block(bat: str) -> str:
    """切出 :rollback ... :cleanup 之间的文本。"""
    start = bat.index(":rollback")
    end = bat.index(":cleanup", start)
    return bat[start:end]


def test_build_bat_rollback_checks_move_errorlevel(qapp):
    """回滚 move 失败时不能 start 一个不存在/损坏的 exe。

    这是 bat 里的关键错误路径：安装失败 → 尝试用旧版本覆盖回去 →
    如果这次 move 也失败，唯一能做的就是把错误记进日志后退出，
    而不是 start 一个未验证的路径。
    """
    bat = UpdateDownloader._build_bat_script()
    block = _rollback_block(bat)
    assert re.search(
    r'move /y "%OLD%" "%EXE%".*?\r\n\s*if errorlevel 1 \(',
    block,
    flags=re.DOTALL,
), "rollback 的 move 后缺少 errorlevel 检查"


def test_build_bat_rollback_failure_body_has_cleanup(qapp):
    """errorlevel 命中时，分支体内必须 goto cleanup，而不是 start。"""
    bat = UpdateDownloader._build_bat_script()
    block = _rollback_block(bat)
    m = re.search(r"if errorlevel 1 \(\s*(.*?)\s*\)", block, flags=re.DOTALL)
    assert m, "rollback 的 errorlevel 分支体为空"
    assert "goto cleanup" in m.group(1)


def test_build_bat_start_appears_exactly_twice(qapp):
    """start 只应出现在「安装成功」与「回滚成功」两条互斥路径上。

    如果引入第三条路径，必须先更新本测试说明新场景，防止无意间
    多出一个 start（那意味着某条错误路径上也可能启动程序）。
    """
    bat = UpdateDownloader._build_bat_script()
    assert bat.count('start "" "%EXE%"') == 2


def test_build_bat_no_start_inside_errorlevel_body(qapp):
    """任何 errorlevel 分支体内都不能 start——那是未验证的路径。"""
    bat = UpdateDownloader._build_bat_script()
    for m in re.finditer(
        r"if errorlevel 1 \(\s*(.*?)\s*\)", bat, flags=re.DOTALL
    ):
        assert "start " not in m.group(1), \
            f"errorlevel 分支体内出现 start: {m.group(1)!r}"


# ===================== UpdateManager 测试替身 =====================

_REAL_URL = "https://real.example.com/version.json"


class _FakeBus:
    """只记录 publish；subscribe / unsubscribe 是 no-op。

    UpdateManager 目前只 publish，不 subscribe，故后两者是空实现。
    若将来 UpdateManager 增加了订阅行为，应改用 MagicMock 让未预期
    的调用浮出水面，而不是静默吞掉。
    """

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
    """把环境伪装成「Windows 上已打包」。

    同时 patch 两处：
      - _is_packaged：决定是否允许自动更新；
      - sys.platform：download_and_apply_async 的平台门。

    只在 Windows 上真实运行时，"已打包"与"是 Windows"才是同一条
    前提；测试要在任意 CI 平台跑，必须把两者一起伪装。不这样做的话，
    test_download_and_apply_* 会在 Linux/macOS 上因平台门提前返回，
    既掩盖真实意图又导致断言失败。
    """
    monkeypatch.setattr(updater, "_is_packaged", lambda: True)
    monkeypatch.setattr(updater.sys, "platform", "win32")


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

    # 槽身份断言：finished → deleteLater，checked → mgr._on_checked。
    # 只断言「被连接一次」太弱：若代码误改成把 _on_checked 连到
    # finished，测试仍然绿。
    assert fake.finished.connect.call_args.args[0] is fake.deleteLater
    assert fake.checked.connect.call_args.args[0] == mgr._on_checked


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
    {},                                                      # 全缺
    {"version": "3.1.0"},                                    # 缺 url/sha
    {"version": "3.1.0", "download_url": "https://x/y"},     # 缺 sha
    {"version": "3.1.0", "sha256": "a" * 64},                # 缺 url
    {"download_url": "https://x/y", "sha256": "a" * 64},     # 缺 version
    # 空串同样算缺
    {"version": "", "download_url": "https://x/y", "sha256": "a" * 64},
    {"version": "3.1.0", "download_url": "", "sha256": "a" * 64},
    {"version": "3.1.0", "download_url": "https://x/y", "sha256": ""},
])
def test_on_checked_rejects_missing_required_fields(qapp, fake_bus, info):
    """required 是 (version, download_url, sha256)，任一缺失或为空
    都拒绝更新并跳过广播。"""
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._on_checked({"has_update": True, "info": info, "error": None})
    assert fake_bus.calls == []
    assert mgr._pending_info == {}


@pytest.mark.parametrize("url", [
    "x",                              # 无 scheme
    "file:///tmp/evil.exe",           # file: 协议
    "ftp://example.com/app.exe",      # ftp: 协议
    "javascript:alert(1)",            # 明显恶意
    "https://",                       # 有 scheme 无 host
    "//example.com/app.exe",          # 协议相对
])
def test_on_checked_rejects_unsafe_download_url(qapp, fake_bus, url):
    """required 字段齐全但 url 协议非法：必须拒绝，不广播。

    这里检查的是 _is_safe_download_url 的第二道门（第一道门只查
    字段非空，不校验协议）。避免被劫持的 version.json 把
    download_url 指向 file:// 等本地资源。
    """
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._on_checked({
        "has_update": True, "error": None,
        "info": {
            "version": "3.1.0",
            "download_url": url,
            "sha256": "a" * 64,
        },
    })
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


def test_download_and_apply_skips_on_non_windows(qapp, monkeypatch):
    """非 Windows 平台必须早退：DETACHED_PROCESS 等常量是 Windows
    专属，走到 Popen 会 AttributeError。

    只 patch 平台，不 patch _is_packaged——验证平台门在打包门之后
    独立生效。
    """
    monkeypatch.setattr(updater, "_is_packaged", lambda: True)
    monkeypatch.setattr(updater.sys, "platform", "linux")
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._pending_info = {
        "version": "3.1.0",
        "download_url": "https://x/y",
        "sha256": "a" * 64,
    }
    assert mgr.download_and_apply_async() is False
    assert mgr._downloader is None


def test_download_and_apply_skips_without_pending(qapp, packaged):
    mgr = UpdateManager(manifest_url=_REAL_URL)
    assert mgr.download_and_apply_async() is False
    assert mgr._downloader is None


def test_download_and_apply_skips_when_already_running(qapp, packaged):
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._pending_info = {
        "version": "3.1.0",
        "download_url": "https://x/y",
        "sha256": "a" * 64,
    }
    existing = MagicMock(name="StaleDownloader")
    existing.isRunning.return_value = True
    mgr._downloader = existing

    assert mgr.download_and_apply_async() is False
    assert mgr._downloader is existing
    existing.start.assert_not_called()


@pytest.mark.parametrize("pending", [
    {"version": "3.1.0", "sha256": "a" * 64},                      # 缺 url
    {"version": "3.1.0", "download_url": "",  "sha256": "a" * 64}, # 空 url
    {"version": "3.1.0", "download_url": "https://x/y", "sha256": ""},  # 空 sha
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

    # 生命周期槽是 deleteLater（MagicMock 每次属性访问返回同一
    # 子 mock，is 比较成立）；结果槽是 _on_downloaded。
    assert fake.finished.connect.call_args.args[0] is fake.deleteLater
    assert fake.finished_download.connect.call_args.args[0] == mgr._on_downloaded


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


def test_on_downloaded_cancelled_publishes_nothing(qapp, fake_bus):
    """取消不是失败：不发 UPDATE_FAILED，也不发 UPDATE_READY。"""
    mgr = UpdateManager(manifest_url=_REAL_URL)
    mgr._downloader = MagicMock(name="Stale")
    mgr._on_downloaded({"ok": False, "cancelled": True, "error": "下载已取消"})

    assert mgr._downloader is None
    assert fake_bus.calls == []


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