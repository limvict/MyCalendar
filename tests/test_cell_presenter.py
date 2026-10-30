# coding: utf-8
import pytest
from PyQt6.QtCore import QDate

from desktop_calendar.ui.cell_presenter import (
    CellPresenter, CellData,
)


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