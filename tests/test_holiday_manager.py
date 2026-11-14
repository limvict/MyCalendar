# coding: utf-8
"""HolidayManager：apply_cached 过期清理、网络回调、shutdown 幂等。"""
import time

import pytest

from desktop_calendar.contracts.event_bus import EventType
from desktop_calendar.contracts.holiday_source import NetworkError
from desktop_calendar.core.holiday_manager import HolidayManager


class TestApplyCached:
    def test_empty(self, fresh_config_manager):
        mgr = HolidayManager(fresh_config_manager, source_factory=None)
        try:
            mgr.holiday_cache = {}
            assert mgr.apply_cached() == {}
        finally:
            mgr.shutdown()

    def test_valid_and_expired(self, fresh_config_manager, isolated_paths):
        mgr = HolidayManager(fresh_config_manager, source_factory=None)
        try:
            now = time.time()
            mgr.holiday_cache = {
                "2024": {
                    "ts": now,
                    "days": {"2024-01-01": "holiday"},
                },
                "2023": {
                    "ts": now - 100 * 24 * 3600,  # 100 天前，过期
                    "days": {"2023-01-01": "holiday"},
                },
            }
            result = mgr.apply_cached()
            assert "2024-01-01" in result
            assert "2023-01-01" not in result
            assert "2023" not in mgr.holiday_cache
        finally:
            mgr.shutdown()

    def test_malformed_entries_removed(self, fresh_config_manager):
        mgr = HolidayManager(fresh_config_manager, source_factory=None)
        try:
            mgr.holiday_cache = {
                "2024": {"ts": "not-a-number", "days": {}},
                "2025": {"ts": time.time(), "days": "not-a-dict"},
                "bad": "string",
                "2026": {"ts": time.time(), "days": {"x": "holiday"}},
            }
            result = mgr.apply_cached()
            assert result == {"x": "holiday"}
            assert "2024" not in mgr.holiday_cache
            assert "2025" not in mgr.holiday_cache
            assert "bad" not in mgr.holiday_cache
        finally:
            mgr.shutdown()


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
