# coding: utf-8
"""EventBus 基础契约。"""
from desktop_calendar.contracts.event_bus import EventBus


def test_publish_subscribe(qapp):
    bus = EventBus()
    got = []

    def slot(data):
        got.append(data)

    bus.subscribe("e", slot)
    bus.publish("e", x=1)
    assert got == [{"x": 1}]

    bus.unsubscribe("e", slot)
    bus.publish("e", x=2)
    assert got == [{"x": 1}]


def test_exception_isolation(qapp):
    bus = EventBus()
    got = []

    def bad(data):
        raise RuntimeError("boom")

    def good(data):
        got.append(data)

    bus.subscribe("e", bad)
    bus.subscribe("e", good)
    bus.publish("e", n=1)

    assert got == [{"n": 1}]


def test_unsubscribe_bound_method(qapp):
    bus = EventBus()
    got = []

    class S:
        def cb(self, data):
            got.append(data)

    s = S()
    bus.subscribe("e", s.cb)
    bus.unsubscribe("e", s.cb)
    bus.publish("e")

    assert got == []


def test_publish_no_subscriber_is_noop(qapp):
    bus = EventBus()
    bus.publish("nonexistent", x=1)   # 不抛即通过


def test_unsubscribe_nonexistent_is_noop(qapp):
    bus = EventBus()
    bus.unsubscribe("e", lambda d: None)   # 不抛即通过


def test_double_subscribe_same_slot(qapp):
    """同一回调重复订阅只注册一次（实现做了去重）。"""
    bus = EventBus()
    got = []

    def slot(data):
        got.append(data)

    bus.subscribe("e", slot)
    bus.subscribe("e", slot)
    bus.publish("e", n=1)

    assert len(got) == 1