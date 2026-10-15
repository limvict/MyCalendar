# coding: utf-8
from datetime import datetime

import holiday_manager as hm_mod


class _BareHM(hm_mod.HolidayManager):
    """跳过 __init__：直接注入 holiday_cache 测 apply_cached。"""

    def __init__(self):
        self.holiday_cache = {}
      

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