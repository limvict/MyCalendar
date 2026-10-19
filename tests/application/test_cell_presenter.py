# coding: utf-8
import pytest
from PyQt6.QtCore import QDate

from desktop_calendar.application.cell_presenter import (
    CellPresenter, CELL_NORMAL, CELL_MEMORIAL, CELL_RED,
)


@pytest.fixture
def presenter():
    return CellPresenter()


def test_no_memorial_returns_normal(presenter):
    data = presenter.compute(QDate(2024, 6, 15))
    assert data.kind in (CELL_NORMAL, CELL_RED)


def test_solar_yearly_memorial_hits(presenter):
    presenter.set_memorial_list([
        {"name": "测试生日", "type": "solar", "month": 6, "day": 15,
         "repeat_type": "year", "enabled": True},
    ])
    data = presenter.compute(QDate(2024, 6, 15))
    assert data.kind == CELL_MEMORIAL
    assert data.lunar_text == "测试生日"
    assert presenter.memorials_for(QDate(2024, 6, 15)) == ["测试生日"]
    # 另一天不命中
    assert presenter.compute(QDate(2024, 6, 16)).kind != CELL_MEMORIAL


def test_disabled_memorial_ignored(presenter):
    presenter.set_memorial_list([
        {"name": "关闭", "type": "solar", "month": 6, "day": 15,
         "repeat_type": "year", "enabled": False},
    ])
    assert presenter.memorials_for(QDate(2024, 6, 15)) == []


def test_net_holiday_overrides(presenter):
    presenter.set_net_holiday({"2024-10-01": True})
    data = presenter.compute(QDate(2024, 10, 1))
    assert data.is_hol is True
    assert data.is_legal_hol is True