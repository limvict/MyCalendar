# coding: utf-8
"""EventBus：订阅幂等、发布、异常隔离、_same_callable。"""
import pytest

from desktop_calendar.contracts.event_bus import EventBus, _same_callable


class _Slot:
    def __init__(self):
        self.calls = []

    def on_event(self, data):
        self.calls.append(data)


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


# ---------- _same_callable ----------
def test_same_callable_bound_method():
    """bound method 每次属性访问是新对象，但语义相同。"""
    obj = _Slot()
    a, b = obj.on_event, obj.on_event
    assert a is not b
    assert _same_callable(a, b) is True


def test_same_callable_different_obj():
    a, b = _Slot(), _Slot()
    assert _same_callable(a.on_event, b.on_event) is False


def test_same_callable_same_func():
    f = lambda _: None  # noqa: E731
    assert _same_callable(f, f) is True
    assert _same_callable(lambda _: None, lambda _: None) is False


def test_same_callable_non_bool_eq_fails_closed():
    """__eq__ 返回非 bool 时按不相同处理。"""
    class Weird:
        def __eq__(self, other):
            return "yes"        # 非 bool

    assert _same_callable(Weird(), Weird()) is False