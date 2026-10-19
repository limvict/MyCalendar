# coding: utf-8
from datetime import datetime
from PyQt6.QtCore import QDate
from desktop_calendar.core import holiday_manager as hm_mod
from desktop_calendar.core.holiday_manager import HolidayManager

class _BareHM(hm_mod.HolidayManager):
    """跳过 __init__：直接注入 holiday_cache 测 apply_cached。"""

    def __init__(self):
        self.holiday_cache = {}
      
class FakeHolidaySource:
    def __init__(self, *, on_ready, on_error, parent=None):
        self.on_ready = on_ready
        self.on_error = on_error
        self.started = False
        self.requests = []
        self.shutdown_called = False
        self.shutdown_result = True

    def start(self):
        self.started = True
        return True

    def request(self, year):
        self.requests.append(year)

    def shutdown(self, timeout_ms=3000):
        self.shutdown_called = True
        return self.shutdown_result


def make_manager(config):
    return HolidayManager(config, source_factory=FakeHolidaySource)


def test_request_current_year(config, monkeypatch):
    mgr = make_manager(config)
    src = mgr._source
    assert src.started
    monkeypatch.setattr(
        "desktop_calendar.core.holiday_manager.QDate.currentDate",
        lambda: QDate(2024, 12, 31),
    )
    mgr.fetch_current_year()
    assert src.requests == [2024, 2025]


def test_shutdown_idempotent(config):
    mgr = make_manager(config)
    src = mgr._source
    mgr.shutdown()
    mgr.shutdown()  # 第二次不抛异常
    assert src.shutdown_called

def test_apply_cached_removes_expired(monkeypatch):
    obj = _BareHM()
    now_ts = datetime.now().timestamp()

    obj.holiday_cache = {
        "2024": {"ts": now_ts, "days": {"2024-01-01": True}},
        "2020": {"ts": 0, "days": {"2020-01-01": True}},
        "bad":  "not-a-dict",
    }
    monkeypatch.setattr(hm_mod, "save_holiday_cache", lambda data: None)

    result = obj.apply_cached()

    assert result == {"2024-01-01": True}
    assert "2024" in obj.holiday_cache
    assert "2020" not in obj.holiday_cache
    assert "bad" not in obj.holiday_cache


def test_apply_cached_merges_multiple_fresh_years(monkeypatch):
    """多个未过期年份的 days 应合并，而不是只保留最后一个。"""
    obj = _BareHM()
    now_ts = datetime.now().timestamp()
    obj.holiday_cache = {
        "2024": {"ts": now_ts, "days": {"2024-01-01": True}},
        "2025": {"ts": now_ts,
                 "days": {"2025-01-01": True, "2025-01-02": False}},
    }
    monkeypatch.setattr(hm_mod, "save_holiday_cache", lambda data: None)

    result = obj.apply_cached()
    assert result == {
        "2024-01-01": True,
        "2025-01-01": True,
        "2025-01-02": False,
    }


def test_apply_cached_empty_cache(monkeypatch):
    obj = _BareHM()
    obj.holiday_cache = {}
    monkeypatch.setattr(hm_mod, "save_holiday_cache", lambda data: None)
    assert obj.apply_cached() == {}