# coding: utf-8
"""LunarCalendarWidget 的对外契约 + 内部索引测试。"""
from PyQt6.QtCore import QDate

from desktop_calendar.ui import calendar_widget as cw
from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.application import cell_presenter as cp
from desktop_calendar.application.cell_presenter import (
    CELL_NORMAL, CELL_MEMORIAL, CELL_RED,
)

def _make_widget(memorials=None):
    return cw.LunarCalendarWidget(None, DEFAULT_THEME, memorials or [])


class _FakeLunar:
    lunarMonth = 1
    lunarDay = 1
    isLunarLeapMonth = False
    todaySolarTerms = "无"

    def get_legalHolidays(self):
        return ["元旦节"]


# ---------- 索引构建 ----------

def test_build_memorial_index(qapp):
    w = _make_widget([
        {"name": "元旦", "type": "solar", "repeat_type": "year",
         "month": 1, "day": 1, "enabled": True},
        {"name": "周一", "type": "solar", "repeat_type": "week",
         "day": 1, "enabled": True},
        {"name": "农历", "type": "lunar", "repeat_type": "year",
         "month": 1, "day": 1, "enabled": True},
        {"name": "禁用", "enabled": False},
    ])

    assert w._presenter._memorial_index["solar_year"][(1, 1)][0]["name"] == "元旦"
    assert w._presenter._memorial_index["solar_week"][1][0]["name"] == "周一"
    assert w._presenter._memorial_index["lunar_year"][(1, 1, False)][0]["name"] == "农历"


# ---------- 格子文本 ----------

def test_get_lunar_cell_text_solar_memorial(qapp):
    w = _make_widget([
        {"name": "元旦", "type": "solar", "repeat_type": "year",
         "month": 1, "day": 1, "enabled": True},
    ])
    text, kind = w.get_lunar_cell_text(QDate(2025, 1, 1))
    assert text == "元旦"
    assert kind == CELL_MEMORIAL


def test_legal_holiday_name_map_red(qapp, monkeypatch):
    monkeypatch.setattr(cp.lunar_mod, "HAS_CNLUNAR", True)
    w = _make_widget([])
    text, kind = w.get_lunar_cell_text(
        QDate(2025, 1, 1),
        lunar=_FakeLunar(),
        legal_raw="元旦节",
    )
    assert text == "元旦"
    assert kind == CELL_RED


def test_lunar_festival_red(qapp, monkeypatch):
    monkeypatch.setattr(cp.lunar_mod, "HAS_CNLUNAR", True)

    class L:
        lunarMonth = 1
        lunarDay = 1
        isLunarLeapMonth = False
        todaySolarTerms = "无"

        def get_legalHolidays(self):
            return []

    w = _make_widget([])
    text, kind = w.get_lunar_cell_text(
        QDate(2025, 1, 29), lunar=L(), legal_raw=None)
    assert text == "春节"
    assert kind == CELL_RED


def test_chuxi_red(qapp, monkeypatch):
    monkeypatch.setattr(cp.lunar_mod, "HAS_CNLUNAR", True)

    class L12:
        lunarMonth = 12
        lunarDay = 29
        isLunarLeapMonth = False
        todaySolarTerms = "无"

        def get_legalHolidays(self):
            return []

    class L1:
        lunarMonth = 1
        lunarDay = 1
        isLunarLeapMonth = False

    w = _make_widget([])
    monkeypatch.setattr(w._presenter, "_get_lunar", lambda qd: L1())
    text, kind = w.get_lunar_cell_text(
        QDate(2025, 1, 28), lunar=L12(), legal_raw=None)
    assert text == "除夕"
    assert kind == CELL_RED


# ---------- 对外查询接口 ----------

def test_get_memorials_for_date(qapp):
    w = _make_widget([
        {"name": "元旦", "type": "solar", "repeat_type": "year",
         "month": 1, "day": 1, "enabled": True},
    ])
    assert w.get_memorials_for_date(QDate(2025, 1, 1)) == ["元旦"]
    assert w.get_memorials_for_date(QDate(2025, 1, 2)) == []


def test_set_memorial_list_rebuilds_index(qapp):
    w = _make_widget([])
    assert w.get_memorials_for_date(QDate(2025, 1, 1)) == []

    w.set_memorial_list([
        {"name": "元旦", "type": "solar", "repeat_type": "year",
         "month": 1, "day": 1, "enabled": True},
    ])
    assert w.get_memorials_for_date(QDate(2025, 1, 1)) == ["元旦"]


def test_set_net_holiday_does_not_raise(qapp):
    """set_net_holiday 接受各种输入且不抛。

    覆盖正常 dict、空 dict、None、非 dict——实现对后两者会退化为
    空数据，属于防御性契约。
    """
    w = _make_widget([])
    w.set_net_holiday({"2025-01-01": True})
    w.set_net_holiday({})
    w.set_net_holiday(None)
    w.set_net_holiday(["not", "a", "dict"])
    
    
def test_solar_festival_shown_without_cnlunar(qapp, monkeypatch):
    """无 cnlunar 时公历节日仍应显示（回归保护）。"""
    monkeypatch.setattr(cp.lunar_mod, "HAS_CNLUNAR", False)
    w = _make_widget([])
    text, kind = w.get_lunar_cell_text(QDate(2025, 1, 1))
    assert text == "元旦"
    assert kind == CELL_NORMAL


def test_lunar_obj_failure_falls_back_to_solar_festival(qapp, monkeypatch):
    """有 cnlunar 但取不到 lunar 对象时，公历节日兜底。"""
    monkeypatch.setattr(cp.lunar_mod, "HAS_CNLUNAR", True)
    w = _make_widget([])
    monkeypatch.setattr(w._presenter, "_get_lunar", lambda qd: None)
    text, kind = w.get_lunar_cell_text(QDate(2025, 1, 1))
    assert text == "元旦"
    assert kind == CELL_NORMAL
    
def test_solar_memorial_beats_builtin_festival(qapp):
    """同一天既有内置公历节日又有纪念日时，纪念日优先。"""
    w = _make_widget([
        {"name": "我的元旦", "type": "solar", "repeat_type": "year",
         "month": 1, "day": 1, "enabled": True},
    ])
    text, kind = w.get_lunar_cell_text(QDate(2025, 1, 1))
    assert text == "我的元旦"
    assert kind == CELL_MEMORIAL
    
def test_calc_cell_data_returns_real_data(qapp):
    """回归保护：_calc_cell_data 必须返回非空 lunar_text。

    若 is_date_holiday / is_weekend_workday / _is_legal_holiday
    的签名与 _calc_cell_data 的调用不一致（如 date_str= 传了但
    形参没加），TypeError 会被 _calc_cell_data 的大 try/except
    吞掉，所有新单元格静默返回全空——本条测试会在单元格空白之前
    先变红。用 1/1 这种纯公历纪念日，不依赖 cnlunar，无 mock 需求。
    """
    w = _make_widget([
        {"name": "元旦", "type": "solar", "repeat_type": "year",
         "month": 1, "day": 1, "enabled": True},
    ])
    cell = w._presenter.compute(QDate(2025, 1, 1))
    assert cell.lunar_text == "元旦"
    assert cell.kind == CELL_MEMORIAL