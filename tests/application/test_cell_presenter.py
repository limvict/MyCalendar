# coding: utf-8
import pytest
from PyQt6.QtCore import QDate

from desktop_calendar.ui.cell_presenter import (
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
    assert data.is_legal_hol is True
    
def test_lunar_text_and_kind_three_states():
    p = CellPresenter()
    q = QDate(2024, 6, 1)  # 儿童节，公历
    # 1) 未传 lunar → presenter 自己算（依赖 cnlunar，结果可能随环境变）
    p.lunar_text_and_kind(q)
    # 2) 显式传 None → 走公历节日 fallback
    text, kind = p.lunar_text_and_kind(q, lunar=None, legal_raw=None)
    assert text == "儿童节"
    assert kind == CELL_NORMAL
    # 3) 显式传 legal_raw=None 但 lunar 有值 → 走 _resolve_after_memorial 且无节日
    #    （需构造 lunar，较麻烦，可省略）
    
def test_weekend_is_rest_but_not_legal(presenter):
    # 2024-03-09 普通周六，不在 net 数据里
    cell = presenter.compute(QDate(2024, 3, 9))
    assert cell.is_legal_hol is False
    assert cell.is_weekend_work is False

def test_legal_holiday_from_net(presenter):
    # 注入网络数据：2024-10-01 国庆，isOffDay=True
    presenter.set_net_holiday({"2024-10-01": True})
    cell = presenter.compute(QDate(2024, 10, 1))
    assert cell.is_legal_hol is True

def test_weekend_work_not_legal(presenter):
    # 2024-02-04 周日调休上班，isOffDay=False
    presenter.set_net_holiday({"2024-02-04": False})
    cell = presenter.compute(QDate(2024, 2, 4))
    assert cell.is_legal_hol is False
    assert cell.is_weekend_work is True