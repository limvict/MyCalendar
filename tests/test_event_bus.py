# coding: utf-8
"""EventBus：订阅幂等、发布、异常隔离、_same_callable、多槽顺序。"""
import pytest

from desktop_calendar.contracts.event_bus import EventBus, EventType, _same_callable


class _Slot:
    def __init__(self):
        self.calls = []

    def on_event(self, data):
        self.calls.append(data)


class _Recorder:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def on(self, data):
        self.calls.append((self.name, data))


# ---------------- 基础订阅 / 发布 ----------------
def test_subscribe_publish_unsubscribe(qapp):
    bus = EventBus()
    slot = _Slot()
    bus.subscribe("evt", slot.on_event)
    bus.publish("evt", x=1)
    assert slot.calls == [{"x": 1}]

    bus.unsubscribe("evt", slot.on_event)
    bus.publish("evt", x=2)
    assert slot.calls == [{"x": 1}]


def test_subscribe_idempotent(qapp):
    """同一 event_type 下同一 slot 重复订阅只触发一次。"""
    bus = EventBus()
    slot = _Slot()
    bus.subscribe("evt", slot.on_event)
    bus.subscribe("evt", slot.on_event)
    bus.publish("evt", x=1)
    assert slot.calls == [{"x": 1}]


def test_unsubscribe_idempotent(qapp):
    bus = EventBus()
    slot = _Slot()
    bus.unsubscribe("evt", slot.on_event)   # 未订阅不抛


def test_publish_non_str_ignored(qapp):
    """event_type 非 str 时静默丢弃，不抛 TypeError。"""
    bus = EventBus()
    slot = _Slot()
    bus.subscribe("evt", slot.on_event)
    bus.publish(123, x=1)
    bus.publish(None, x=2)
    assert slot.calls == []


def test_slot_exception_isolated(qapp):
    """一个槽抛异常不影响同事件的其他槽。"""
    bus = EventBus()
    good = _Slot()

    def bad(_data):
        raise ValueError("boom")

    bus.subscribe("evt", bad)
    bus.subscribe("evt", good.on_event)
    bus.publish("evt", x=1)
    assert good.calls == [{"x": 1}]


def test_clear_all(qapp):
    bus = EventBus()
    slot = _Slot()
    bus.subscribe("evt", slot.on_event)
    bus.clear_all()
    bus.publish("evt", x=1)
    assert slot.calls == []


def test_different_event_types_isolated(qapp):
    bus = EventBus()
    slot = _Slot()
    bus.subscribe("a", slot.on_event)
    bus.publish("b", x=1)
    assert slot.calls == []


# ---------------- 多槽 / 顺序 / 隔离 ----------------
def test_multiple_slots_all_called(qapp):
    bus = EventBus()
    a, b, c = _Recorder("a"), _Recorder("b"), _Recorder("c")
    bus.subscribe("evt", a.on)
    bus.subscribe("evt", b.on)
    bus.subscribe("evt", c.on)
    bus.publish("evt", x=1)
    assert a.calls == [("a", {"x": 1})]
    assert b.calls == [("b", {"x": 1})]
    assert c.calls == [("c", {"x": 1})]


def test_bad_slot_first_good_still_runs(qapp):
    """首个槽抛异常，后续槽照常调用。"""
    bus = EventBus()
    good = _Recorder("good")

    def bad(_):
        raise RuntimeError("x")

    bus.subscribe("evt", bad)
    bus.subscribe("evt", good.on)
    bus.publish("evt", y=2)
    assert good.calls == [("good", {"y": 2})]


def test_publish_no_subscribers_noop(qapp):
    bus = EventBus()
    bus.publish("nobody", x=1)   # 不抛


def test_unsubscribe_leaves_other_slots(qapp):
    bus = EventBus()
    a, b = _Recorder("a"), _Recorder("b")
    bus.subscribe("evt", a.on)
    bus.subscribe("evt", b.on)
    bus.unsubscribe("evt", a.on)
    bus.publish("evt", x=1)
    assert a.calls == []
    assert b.calls == [("b", {"x": 1})]


def test_clear_all_clears_every_event(qapp):
    bus = EventBus()
    a, b = _Recorder("a"), _Recorder("b")
    bus.subscribe("evt1", a.on)
    bus.subscribe("evt2", b.on)
    bus.clear_all()
    bus.publish("evt1", x=1)
    bus.publish("evt2", x=2)
    assert a.calls == [] and b.calls == []


# ---------------- _same_callable ----------------
class TestSameCallable:
    def test_bound_method(self):
        """bound method 每次属性访问是新对象，但语义相同。"""
        obj = _Slot()
        a, b = obj.on_event, obj.on_event
        assert a is not b
        assert _same_callable(a, b) is True

    def test_different_obj(self):
        a, b = _Slot(), _Slot()
        assert _same_callable(a.on_event, b.on_event) is False

    def test_same_func(self):
        f = lambda _: None  # noqa: E731
        assert _same_callable(f, f) is True
        assert _same_callable(lambda _: None, lambda _: None) is False

    def test_non_bool_eq_fails_closed(self):
        """__eq__ 返回非 bool 时按不相同处理。"""
        class Weird:
            def __eq__(self, other):
                return "yes"        # 非 bool

        assert _same_callable(Weird(), Weird()) is False

    def test_static_method(self):
        class C:
            @staticmethod
            def f(_):
                pass
        assert _same_callable(C.f, C.f) is True

    def test_classmethod(self):
        class C:
            @classmethod
            def f(cls, _):
                pass
        assert _same_callable(C.f, C.f) is True

    def test_bound_same_obj_different_method(self):
        class C:
            def f(self, _):
                pass

            def g(self, _):
                pass
        o = C()
        assert _same_callable(o.f, o.g) is False

    def test_lambda_different_refs(self):
        a = lambda _: None  # noqa: E731
        b = lambda _: None  # noqa: E731
        assert _same_callable(a, b) is False


class TestEventType:
    def test_strings_are_unique(self):
        values = [
            v for k, v in vars(EventType).items()
            if not k.startswith("_") and isinstance(v, str)
        ]
        assert len(values) == len(set(values))

    def test_known_events_exist(self):
        assert EventType.HOLIDAY_UPDATED == "holiday_updated"
        assert EventType.MEMORIAL_CHANGED == "memorial_changed"
        assert EventType.UPDATE_READY == "update_ready"

# ===================== 自动退订（依赖 B1 的 _safe_unsubscribe） =====================
@pytest.mark.skipif(
    not hasattr(__import__(
        "desktop_calendar.contracts.event_bus",
        fromlist=["_safe_unsubscribe"]), "_safe_unsubscribe"),
    reason="B1 自动退订修复未实施（缺 _safe_unsubscribe）")
def test_deleted_object_auto_unsubscribed(qapp):
    """订阅者所属 C++ 对象已删除时，wrapper 主动退订，不再刷 traceback。

    对应 event_bus.subscribe 里 `"has been deleted" in str(e)` 分支：
      - 捕获 RuntimeError；
      - QTimer.singleShot(0, ...) 延迟退订；
      - 后续 publish 不再进入该 slot。

    用纯 Python 对象模拟"已删除的 C++ 对象"：只要 slot 抛
    RuntimeError("... has been deleted")，wrapper 就会走退订路径。
    """
    from PyQt6.QtTest import QTest

    bus = EventBus()
    calls = []

    class _Deleted:
        def slot(self, data):
            calls.append(data)
            raise RuntimeError(
                "Internal C++ object (X) already deleted.")

    d = _Deleted()
    bus.subscribe("evt", d.slot)
    assert "evt" in bus._subscriber_map
    assert len(bus._subscriber_map["evt"]) == 1

    # 第一次 publish：slot 抛 RuntimeError → wrapper 安排 singleShot 退订
    bus.publish("evt", x=1)
    assert calls == [{"x": 1}]

    # 处理事件循环，让 QTimer.singleShot(0) 触发
    QTest.qWait(20)

    print("subscriber_map after qWait:", bus._subscriber_map)   # 调试
    
    # 退订后 entries 为空，且 _subscriber_map 里不再有 "evt"
    assert "evt" not in bus._subscriber_map

    # 二次 publish 不再调用 slot
    bus.publish("evt", x=2)
    assert calls == [{"x": 1}]


# ===================== _EventBusProxy.init 显式构造（A3 建议回归） =====================
@pytest.mark.skipif(
    not hasattr(
        __import__("desktop_calendar.contracts.event_bus",
                   fromlist=["_EventBusProxy"])._EventBusProxy,
        "init"),
    reason="A3 显式 init 未实施")
def test_proxy_init_constructs_impl(qapp):
    from desktop_calendar.contracts.event_bus import _EventBusProxy

    proxy = _EventBusProxy()
    assert proxy._impl is None

    proxy.init()
    assert proxy._impl is not None

    # 幂等：再次 init 不重建
    impl = proxy._impl
    proxy.init()
    assert proxy._impl is impl


@pytest.mark.skipif(
    not hasattr(
        __import__("desktop_calendar.contracts.event_bus",
                   fromlist=["_EventBusProxy"])._EventBusProxy,
        "init"),
    reason="A3 显式 init 未实施")
def test_proxy_init_then_subscribe_works(qapp):
    """init 后 subscribe/publish 走同一 impl，不重复构造。"""
    from desktop_calendar.contracts.event_bus import _EventBusProxy

    proxy = _EventBusProxy()
    proxy.init()
    impl = proxy._impl

    calls = []
    proxy.subscribe("evt", lambda d: calls.append(d))
    proxy.publish("evt", x=1)

    assert proxy._impl is impl
    assert calls == [{"x": 1}]