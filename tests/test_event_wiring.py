# coding: utf-8
"""event_wiring 订阅声明表测试。"""
from unittest.mock import MagicMock

from app import event_wiring
from event_bus import EventType


class FakeWindow:
    """用 MagicMock 承载 11 个回调。

    不用字符串桩：字符串在这里"碰巧能过"，只是因为 _subscriptions
    目前只做了取值、没调用回调。一旦将来 _subscriptions 里加入
    cb() / cb.__self__ 之类的访问，字符串桩会以 TypeError 在距离
    病根很远的地方崩溃。MagicMock 既可通过 is 做身份断言，
    也能被 callable 检查。
    """
    def __init__(self):
        self._on_holiday_updated  = MagicMock(name="_on_holiday_updated")
        self._on_memorial_changed = MagicMock(name="_on_memorial_changed")
        self._on_window_show      = MagicMock(name="_on_window_show")
        self._on_window_quit      = MagicMock(name="_on_window_quit")
        self._on_toggle_topmost   = MagicMock(name="_on_toggle_topmost")
        self._on_open_settings    = MagicMock(name="_on_open_settings")
        self._on_backup_memorial  = MagicMock(name="_on_backup_memorial")
        self._on_restore_memorial = MagicMock(name="_on_restore_memorial")
        self._on_update_available = MagicMock(name="_on_update_available")
        self._on_update_failed    = MagicMock(name="_on_update_failed")
        self._on_update_ready     = MagicMock(name="_on_update_ready")


# 说明：不能 monkeypatch event_bus.subscribe —— 它是个只读代理
# (_EventBusProxy)，方法属性不可写。要换就换整个名字。
class FakeBus:
    def __init__(self, calls):
        self.calls = calls

    def subscribe(self, evt, cb):
        self.calls.append(("sub", evt, cb))

    def unsubscribe(self, evt, cb):
        self.calls.append(("unsub", evt, cb))


def test_subscriptions_has_all_eleven():
    subs = event_wiring._subscriptions(FakeWindow())
    assert len(subs) == 11


def test_subscriptions_bind_correct_callbacks():
    """断言"绑的是哪个回调方法"，而不是"字符串叫什么"。"""
    w = FakeWindow()
    subs = dict(event_wiring._subscriptions(w))
    assert subs[EventType.HOLIDAY_UPDATED]       is w._on_holiday_updated
    assert subs[EventType.MEMORIAL_CHANGED]      is w._on_memorial_changed
    assert subs[EventType.WINDOW_SHOW]           is w._on_window_show
    assert subs[EventType.WINDOW_QUIT]           is w._on_window_quit
    assert subs[EventType.WINDOW_TOGGLE_TOPMOST] is w._on_toggle_topmost
    assert subs[EventType.OPEN_SETTINGS]         is w._on_open_settings
    assert subs[EventType.BACKUP_MEMORIAL]       is w._on_backup_memorial
    assert subs[EventType.RESTORE_MEMORIAL]      is w._on_restore_memorial
    assert subs[EventType.UPDATE_AVAILABLE]      is w._on_update_available
    assert subs[EventType.UPDATE_FAILED]         is w._on_update_failed
    assert subs[EventType.UPDATE_READY]          is w._on_update_ready


def test_connect_disconnect_are_symmetric(monkeypatch):
    """connect / disconnect 必须遍历同一份声明表。"""
    calls = []
    monkeypatch.setattr(event_wiring, "event_bus", FakeBus(calls))

    w = FakeWindow()
    event_wiring.connect(w)
    event_wiring.disconnect(w)

    subs   = [(e, c) for tag, e, c in calls if tag == "sub"]
    unsubs = [(e, c) for tag, e, c in calls if tag == "unsub"]
    assert len(subs) == len(unsubs) == 11
    for (e1, c1), (e2, c2) in zip(subs, unsubs):
        assert e1 == e2, f"事件类型不一致: {e1!r} vs {e2!r}"
        assert c1 is c2, f"回调不是同一对象: {c1!r} vs {c2!r}"


def test_connect_continues_after_individual_failure(monkeypatch):
    calls = []

    class BadBus(FakeBus):
        def subscribe(self, evt, cb):
            calls.append(("sub", evt, cb))
            if len(calls) == 1:
                raise RuntimeError("boom")

    monkeypatch.setattr(event_wiring, "event_bus", BadBus(calls))
    event_wiring.connect(FakeWindow())
    assert len(calls) == 11  # 若实现是整体 try，只会有 1 条


def test_disconnect_swallows_individual_failures(monkeypatch):
    """某条 unsubscribe 抛异常时，后续条目仍需继续清理。"""
    calls = []

    class BadBus(FakeBus):
        def unsubscribe(self, evt, cb):
            calls.append((evt, cb))
            if len(calls) == 1:
                raise RuntimeError("模拟 event_bus 内部错误")

    monkeypatch.setattr(event_wiring, "event_bus", BadBus(calls))
    w = FakeWindow()
    event_wiring.disconnect(w)

    assert len(calls) == 11   # 数量对账
    # 身份对账：11 条恰好是 w 上的 11 个回调，不重不漏。
    assert {cb for _, cb in calls} == {
        w._on_holiday_updated, w._on_memorial_changed,
        w._on_window_show, w._on_window_quit, w._on_toggle_topmost,
        w._on_open_settings, w._on_backup_memorial, w._on_restore_memorial,
        w._on_update_available, w._on_update_failed, w._on_update_ready,
    }