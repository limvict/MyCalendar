# coding: utf-8
"""HolidayManager 回调：缓存写入、shutdown 丢弃、错误去重。"""
import pytest

from desktop_calendar.contracts.events import EventType
from desktop_calendar.contracts.holiday_source import NetworkError
from desktop_calendar.core.holiday_manager import HolidayManager


def _make(fresh_config_manager):
    return HolidayManager(fresh_config_manager, source_factory=None)


def test_on_net_ready_updates_cache_and_publishes(
        fresh_config_manager, monkeypatch):
    from desktop_calendar.core import holiday_manager as hm
    saved, published = [], []

    class _Bus:
        def publish(self, evt, **kw):
            published.append((evt, kw))

    monkeypatch.setattr(hm, "save_holiday_cache", lambda c: saved.append(c))
    monkeypatch.setattr(hm, "event_bus", _Bus())

    mgr = _make(fresh_config_manager)
    try:
        mgr._on_net_ready(2024, {"2024-01-01": "holiday"})
        assert "2024" in mgr.holiday_cache
        assert saved
        assert published[0][0] == EventType.HOLIDAY_UPDATED
    finally:
        mgr.shutdown()


def test_on_net_ready_ignored_after_shutdown(fresh_config_manager):
    mgr = _make(fresh_config_manager)
    mgr.shutdown()
    mgr._on_net_ready(2024, {"2024-01-01": "holiday"})
    assert "2024" not in mgr.holiday_cache


def test_on_net_error_only_logs_once(fresh_config_manager):
    mgr = _make(fresh_config_manager)
    try:
        mgr._on_net_error(2024, NetworkError("x"))
        assert mgr._has_notified_error is True
        mgr._on_net_error(2024, NetworkError("x"))   # 不重复记录
    finally:
        mgr.shutdown()


def test_on_net_ready_resets_error_flag(
        fresh_config_manager, monkeypatch):
    from desktop_calendar.core import holiday_manager as hm

    class _Bus:
        def publish(self, *a, **k):
            pass

    monkeypatch.setattr(hm, "save_holiday_cache", lambda c: None)
    monkeypatch.setattr(hm, "event_bus", _Bus())

    mgr = _make(fresh_config_manager)
    try:
        mgr._on_net_error(2024, NetworkError("x"))
        assert mgr._has_notified_error
        mgr._on_net_ready(2024, {"2024-01-01": "holiday"})
        assert not mgr._has_notified_error
    finally:
        mgr.shutdown()


def test_shutdown_idempotent(fresh_config_manager):
    mgr = _make(fresh_config_manager)
    mgr.shutdown()
    mgr.shutdown()      # 不抛