# coding: utf-8
"""event_wiring 订阅/退订对称性单测。"""
import pytest

from event_bus import event_bus, EventType
from app import event_wiring


class _StubWindow:
    """只提供 _subscriptions 里用到的回调属性。"""

    def __init__(self):
        # 每个回调都返回一个稳定可调用的 bound method
        for name in (
            "_on_holiday_updated", "_on_memorial_changed",
            "_on_window_show", "_on_window_quit", "_on_toggle_topmost",
            "_on_open_settings", "_on_backup_memorial",
            "_on_restore_memorial",
            "_on_update_available", "_on_update_failed",
            "_on_update_ready", "_on_update_progress",
        ):
            setattr(self, name, (lambda name=name: name))


@pytest.fixture(autouse=True)
def _reset_bus():
    event_bus.clear_all()
    yield
    event_bus.clear_all()


def test_connect_then_disconnect_is_symmetric():
    w = _StubWindow()
    event_wiring.connect(w)
    # 通过私有 _subscriber_map 检查（唯一可靠的原子化观测点）
    impl = event_bus._ensure()
    assert impl._subscriber_map, "connect 后订阅表不应为空"

    event_wiring.disconnect(w)
    assert impl._subscriber_map == {}, "disconnect 后订阅表应清空"


def test_double_connect_is_idempotent():
    w = _StubWindow()
    event_wiring.connect(w)
    event_wiring.connect(w)
    impl = event_bus._ensure()
    # 每个 event_type 下每个 slot 最多一条
    for entries in impl._subscriber_map.values():
        assert len(entries) == 1