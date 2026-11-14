# coding: utf-8
"""CellPresenter：网络节假日归一、CellData、纪念日命中、月末收敛。"""
import pytest
from PyQt6.QtCore import QDate

from desktop_calendar.ui.cell_presenter import (
    CellPresenter, CellData,
)


def _mem(name, month, day, repeat="year", typ="solar"):
    return {"name": name, "type": typ, "repeat_type": repeat,
            "month": month, "day": day, "enabled": True,
            "advance_days": 0, "isleap": False}


class TestSetNetHoliday:
    def test_str_input(self):
        p = CellPresenter()
        p.set_net_holiday({"2024-01-01": "holiday"})
        assert p.net_count == 1

    def test_bool_input_normalized(self):
        p = CellPresenter()
        p.set_net_holiday({"2024-01-01": True, "2024-01-02": False})
        assert p.net_count == 2

    def test_non_dict(self):
        p = CellPresenter()
        p.set_net_holiday("not a dict")
        assert p.net_count == 0

    def test_invalid_values_dropped(self):
        p = CellPresenter()
        p.set_net_holiday({
            "2024-01-01": "holiday",
            "2024-01-02": "maybe",  # 丢弃
            "2024-01-03": 5,        # 视为 holiday
        })
        assert p.net_count == 2


class TestCompute:
    def test_returns_cell_data(self):
        p = CellPresenter()
        assert isinstance(p.compute(QDate(2024, 6, 15)), CellData)

    def test_net_holiday_sets_legal_holiday(self):
        p = CellPresenter()
        p.set_net_holiday({"2024-06-15": "holiday"})
        result = p.compute(QDate(2024, 6, 15))
        assert result.is_legal_hol is True

    def test_net_workday_marks_weekend_work(self):
        p = CellPresenter()
        p.set_net_holiday({"2024-06-15": "workday"})
        # 2024-06-15 是周六
        result = p.compute(QDate(2024, 6, 15))
        assert result.is_weekend_work is True

    def test_normal_saturday_is_not_weekend_work(self):
        p = CellPresenter()
        result = p.compute(QDate(2024, 6, 15))
        assert result.is_weekend_work is False


class TestMemorialsFor:
    def test_empty_by_default(self):
        p = CellPresenter()
        assert p.memorials_for(QDate(2024, 6, 15)) == []

    def test_solar_yearly_hit(self):
        p = CellPresenter()
        p.set_memorial_list([{
            "name": "生日", "type": "solar", "repeat_type": "year",
            "month": 6, "day": 15, "enabled": True,
            "advance_days": 0, "isleap": False,
        }])
        assert p.memorials_for(QDate(2024, 6, 15)) == ["生日"]

    def test_solar_yearly_day_30_falls_back_to_feb_end(self):
        p = CellPresenter()
        p.set_memorial_list([_mem("月末", 2, 30)])
        # 2024-02-29 是闰年 2 月最后一天
        assert p.memorials_for(QDate(2024, 2, 29)) == ["月末"]

    def test_solar_monthly_day_31_falls_back_to_apr_end(self):
        p = CellPresenter()
        p.set_memorial_list([_mem("月末", 1, 31, repeat="month")])
        assert p.memorials_for(QDate(2024, 4, 30)) == ["月末"]

    def test_disabled_not_shown(self):
        p = CellPresenter()
        m = _mem("禁用", 6, 15)
        m["enabled"] = False
        p.set_memorial_list([m])
        assert p.memorials_for(QDate(2024, 6, 15)) == []

    def test_week_index_keyed_by_int(self):
        """周重复索引键必须是 int（查询端 dayOfWeek() 是 int）。"""
        p = CellPresenter()
        p.set_memorial_list([_mem("周一", 1, 1, repeat="week")])
        # 2024-06-17 是周一
        assert p.memorials_for(QDate(2024, 6, 17)) == ["周一"]


# ===================== 农历索引预热（P2 建议回归） =====================
@pytest.mark.skipif(
    not hasattr(CellPresenter, "warmup_for_years"),
    reason="P2 农历预热未实施")
class TestWarmupForYears:
    def test_no_cnlunar_noop(self, monkeypatch):
        from desktop_calendar.ui import cell_presenter as cp
        monkeypatch.setattr(cp.lunar_mod, "HAS_CNLUNAR", False)
        p = cp.CellPresenter()
        p.warmup_for_years([2024])   # 不抛

    def test_delegates_to_lunar(self, monkeypatch):
        from desktop_calendar.ui import cell_presenter as cp
        called = []
        monkeypatch.setattr(cp.lunar_mod, "HAS_CNLUNAR", True)
        monkeypatch.setattr(
            cp.lunar_mod, "warmup_lunar_index_async",
            lambda years: called.append(tuple(years)))
        p = cp.CellPresenter()
        p.warmup_for_years([2023, 2024])
        assert called == [(2023, 2024)]

    def test_swallows_lunar_exception(self, monkeypatch):
        from desktop_calendar.ui import cell_presenter as cp
        monkeypatch.setattr(cp.lunar_mod, "HAS_CNLUNAR", True)

        def boom(_years):
            raise RuntimeError("x")

        monkeypatch.setattr(
            cp.lunar_mod, "warmup_lunar_index_async", boom)
        p = cp.CellPresenter()
        p.warmup_for_years([2024])   # 不抛