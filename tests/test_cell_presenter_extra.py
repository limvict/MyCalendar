# coding: utf-8
"""CellPresenter 月末收敛。"""
from PyQt6.QtCore import QDate

from desktop_calendar.ui.cell_presenter import CellPresenter


def _mem(name, month, day, repeat="year", typ="solar"):
    return {"name": name, "type": typ, "repeat_type": repeat,
            "month": month, "day": day, "enabled": True,
            "advance_days": 0, "isleap": False}


def test_solar_yearly_day_30_falls_back_to_feb_end():
    p = CellPresenter()
    p.set_memorial_list([_mem("月末", 2, 30)])
    # 2024-02-29 是闰年 2 月最后一天
    assert p.memorials_for(QDate(2024, 2, 29)) == ["月末"]


def test_solar_monthly_day_31_falls_back_to_apr_end():
    p = CellPresenter()
    p.set_memorial_list([_mem("月末", 1, 31, repeat="month")])
    assert p.memorials_for(QDate(2024, 4, 30)) == ["月末"]


def test_disabled_not_shown():
    p = CellPresenter()
    m = _mem("禁用", 6, 15)
    m["enabled"] = False
    p.set_memorial_list([m])
    assert p.memorials_for(QDate(2024, 6, 15)) == []


def test_week_index_keyed_by_int():
    """周重复索引键必须是 int（查询端 dayOfWeek() 是 int）。"""
    p = CellPresenter()
    p.set_memorial_list([_mem("周一", 1, 1, repeat="week")])
    # 2024-06-17 是周一
    assert p.memorials_for(QDate(2024, 6, 17)) == ["周一"]