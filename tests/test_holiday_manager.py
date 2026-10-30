# coding: utf-8
"""HolidayManager.apply_cached 过期清理逻辑。

构造时传入 source_factory=None，避免启动网络线程与 QTimer；
apply_cached 本身是纯 dict 处理，可直接测。
"""
import time

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