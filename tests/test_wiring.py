# coding: utf-8
"""MainWindow._event_subscriptions 订阅表契约检查。

订阅表已合并回 MainWindow（原独立 wiring.py 已移除）。本测试仍保持
"订阅表变更必须显式改测试"的约束：len / 事件集合变化会失败，提示
PR 作者确认是刻意修改而非误操作。
"""
from unittest.mock import MagicMock

from desktop_calendar.contracts.event_bus import EventType
from desktop_calendar.ui.main_window import MainWindow


def test_subscriptions_len():
    """订阅表覆盖所有事件，数量变化需同步更新本测试。

    `== 13` 是有意的精确断言：新增 / 删除事件时必须显式改本测试，
    让 PR 作者确认"订阅数量变化"是刻意的而非误操作。
    """
    entries = MainWindow._event_subscriptions(MagicMock())
    assert len(entries) == 13


def test_subscriptions_all_callable():
    """每条订阅的 callback 必须 callable。

    用 MagicMock 作为 self，`self._on_xxx` 返回的 MagicMock 子对象
    恒为 callable——本测试只验证返回结构正确，测不到真实 MainWindow
    上的方法存在性；后者由 test_wiring_methods_exist_on_main_window
    覆盖。
    """
    for evt, cb in MainWindow._event_subscriptions(MagicMock()):
        assert isinstance(evt, str) and evt
        assert callable(cb)


class _AttrRecorder:
    """记录属性访问的轻量替身。

    MagicMock 的公开接口只记录"调用"，纯属性访问（self._on_xxx）
    落在私有的 _mock_children 里。本测试需要"订阅表看过哪些属性名"，
    用 __getattr__ 精确记录，不依赖私有 API。
    """

    def __init__(self):
        self.accessed: set = set()

    def __getattr__(self, name):
        self.accessed.add(name)
        return MagicMock()


def test_wiring_methods_exist_on_main_window():
    """MainWindow 上确实存在订阅表引用的 _on_xxx 方法。

    用 _AttrRecorder 记录 _event_subscriptions 访问了哪些属性，再对照
    MainWindow 类上是否有这些方法。不硬编码方法名——订阅表新增事件时
    本测试自动跟进，避免清单与实现漂移。

    用 dir(MainWindow) 而非实例化：避免 QApplication / 依赖检查 /
    主题构建等副作用。

    这是 Bug 1（_on_attendance_remind_triggered 不存在）的守门人：
    订阅表引用错误名称时本测试报 `MainWindow 缺少订阅表依赖的方法`。
    """
    probes = _AttrRecorder()
    MainWindow._event_subscriptions(probes)

    accessed = {n for n in probes.accessed if n.startswith("_on_")}
    assert accessed, (
        "未能从 MainWindow._event_subscriptions 提取任何 _on_xxx 方法访问，"
        "订阅表的实现可能变了（如改成 getattr(self, name)），"
        "需同步更新本测试"
    )

    names = set(dir(MainWindow))
    missing = accessed - names
    assert not missing, (
        f"MainWindow 缺少订阅表依赖的方法: {sorted(missing)}"
    )


def test_subscriptions_cover_expected_events():
    actual = {evt for evt, _ in MainWindow._event_subscriptions(MagicMock())}
    expected = {
        EventType.HOLIDAY_UPDATED,
        EventType.MEMORIAL_CHANGED,
        EventType.MEMORIAL_REMIND_TRIGGERED,
        EventType.WINDOW_SHOW,
        EventType.WINDOW_QUIT,
        EventType.OPEN_SETTINGS,
        EventType.BACKUP_MEMORIAL,
        EventType.RESTORE_MEMORIAL,
        EventType.UPDATE_AVAILABLE,
        EventType.UPDATE_FAILED,
        EventType.UPDATE_READY,
        EventType.UPDATE_PROGRESS,
        EventType.ATTENDANCE_REMIND_TRIGGERED,
    }
    assert actual == expected
    # SETTINGS_CHANGED 当前未订阅（注释说明保留备未来）
    assert EventType.SETTINGS_CHANGED not in actual