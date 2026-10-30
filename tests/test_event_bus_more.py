# coding: utf-8
"""EventBus 补充：多槽顺序、clear_all 跨事件、_same_callable 更多分支。"""
from desktop_calendar.contracts.event_bus import EventBus, _same_callable


class _Recorder:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def on(self, data):
        self.calls.append((self.name, data))


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
class TestSameCallableMore:
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