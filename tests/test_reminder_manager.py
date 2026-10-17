# coding: utf-8
"""ReminderManager 单元测试。

覆盖 _get_int_cfg / _get_bool_cfg 的边界 + _first_future_remind_ts
的精确时间语义（原版"ts > now"是弱断言，容易假绿）。
"""
from datetime import datetime

import pytest
from PyQt6.QtCore import QDate

from desktop_calendar.core.reminder_manager import ReminderManager


class FakeCfg:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def get_nested(self, *keys, default=None):
        cur = self.data
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k)
            if cur is None:
                return default
        return cur


# ---------- _get_int_cfg ----------

@pytest.mark.parametrize("raw,expected,default", [
    (25, 23, 8),     # 上界钳制
    (-5, 0, 8),      # 下界钳制
    (8, 8, 99),      # 正常 int；default=99 故意与输入不同 → 证明返回的是输入而非 default
    ("12", 12, 99),  # 数字字符串同样走转换；default=99 同理
    ("bad", 8, 8),   # 不可转换 → 落回 default
    (None, 8, 8),    # None → 落回 default
])
def test_get_int_cfg_variants(raw, expected, default):
    cfg = FakeCfg({"memorial_cfg": {"remind_start_hour": raw}})
    assert ReminderManager._get_int_cfg(
        cfg, "memorial_cfg", "remind_start_hour",
        default=default, lo=0, hi=23) == expected

def test_get_int_cfg_missing_key_returns_default():
    cfg = FakeCfg({"memorial_cfg": {}})
    assert ReminderManager._get_int_cfg(
        cfg, "memorial_cfg", "remind_start_hour",
        default=8, lo=0, hi=23) == 8


# ---------- _get_bool_cfg ----------

@pytest.mark.parametrize("raw,expected", [
    ("false", False),
    ("False", False),
    ("FALSE", False),
    ("0",     False),
    (0,       False),
    (0.0,     False),
    ("true",  True),
    ("1",     True),
    (1,       True),
    (True,    True),
])
def test_get_bool_cfg_variants(raw, expected):
    cfg = FakeCfg({"memorial_cfg": {"enable_remind": raw}})
    assert ReminderManager._get_bool_cfg(
        cfg, "memorial_cfg", "enable_remind",
        default=True) is expected
    
# ---------- _first_future_remind_ts ----------

class TestFirstFutureRemindTs:
    def test_before_remind_hour_returns_today(self, qapp):
        today = QDate.currentDate()
        tomorrow = today.addDays(1)
        now = datetime(today.year(), today.month(), today.day(), 10, 0, 0)

        ts = ReminderManager._first_future_remind_ts(
            today, tomorrow, remind_h=23, now_dt=now)

        expected = datetime(
            today.year(), today.month(), today.day(), 23, 0, 0)
        assert ts == int(expected.timestamp() * 1000)

    def test_after_remind_hour_returns_tomorrow(self, qapp):
        today = QDate.currentDate()
        tomorrow = today.addDays(1)
        now = datetime(today.year(), today.month(), today.day(), 23, 30, 0)

        ts = ReminderManager._first_future_remind_ts(
            today, tomorrow, remind_h=23, now_dt=now)

        expected = datetime(
            tomorrow.year(), tomorrow.month(), tomorrow.day(), 23, 0, 0)
        assert ts == int(expected.timestamp() * 1000)

    def test_exactly_at_remind_hour_is_not_future(self, qapp):
        """now == remind_h 整点时，今天的候选不算"未来"。"""
        today = QDate.currentDate()
        tomorrow = today.addDays(1)
        now = datetime(today.year(), today.month(), today.day(), 23, 0, 0)

        ts = ReminderManager._first_future_remind_ts(
            today, tomorrow, remind_h=23, now_dt=now)

        expected = datetime(
            tomorrow.year(), tomorrow.month(), tomorrow.day(), 23, 0, 0)
        assert ts == int(expected.timestamp() * 1000)