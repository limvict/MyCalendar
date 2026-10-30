# coding: utf-8
"""memorial 补充：match_memorial_date、索引月末不收敛。"""
from datetime import date

from desktop_calendar.core import memorial as M


def test_match_memorial_date():
    mem = {"repeat_type": "year", "type": "solar",
           "month": 6, "day": 15, "enabled": True,
           "advance_days": 0, "isleap": False}
    assert M.match_memorial_date(mem, date(2024, 6, 15)) is True
    assert M.match_memorial_date(mem, date(2024, 6, 14)) is False


def test_match_memorial_date_none_base():
    assert M.match_memorial_date({"repeat_type": "year"}, None) is False


def test_build_index_keeps_raw_day():
    """索引端不收敛 day：day=30 保留 30，由查询端月末收敛兜底。"""
    idx = M.build_memorial_index([{
        "enabled": True, "repeat_type": "year",
        "type": "solar", "month": 2, "day": 30,
    }])
    assert (2, 30) in idx["solar_year"]
    assert (2, 29) not in idx["solar_year"]


def test_index_int():
    assert M._index_int("abc", 1, 10) is None
    assert M._index_int(None, 1, 10) is None
    assert M._index_int(float("inf"), 1, 10) is None
    assert M._index_int(5, 1, 10) == 5
    assert M._index_int(0, 1, 10) == 1
    assert M._index_int(99, 1, 10) == 10