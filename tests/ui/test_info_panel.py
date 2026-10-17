# coding: utf-8
"""info_panel 单测：不依赖 Qt 事件循环、不 import lunar_mod。"""
import pytest

from desktop_calendar.ui import info_panel


class _FakeLunar:
    """最小化 mock：只提供 info_panel 读取的属性。"""

    def __init__(self, **kw):
        self.lunarMonthCn = kw.get("lunarMonthCn", "正月")
        self.lunarDayCn = kw.get("lunarDayCn", "初一")
        self.lunarYearCn = kw.get("lunarYearCn", "甲辰年")
        self.chineseYearZodiac = kw.get("chineseYearZodiac", "龙")
        self.todaySolarTerms = kw.get("todaySolarTerms", "无")
        self._legal = kw.get("legal_holidays", ["无"])
        self._other = kw.get("other_holidays", ["无"])

    def get_legalHolidays(self):
        return self._legal

    def get_otherHolidays(self):
        return self._other


def test_build_info_parts_no_lunar():
    parts = info_panel.build_info_parts(
        sel_date=None, memorial_names=[], lunar_obj=None, has_cnlunar=True)
    assert parts.lunar_str is None
    assert parts.term_text is None
    assert parts.holiday_names == ()
    assert parts.has_lunar_data is False
    assert parts.lunar_lib_available is True


def test_build_info_parts_full():
    lunar = _FakeLunar(
        lunarMonthCn="大正月", lunarDayCn="十五",
        todaySolarTerms="立春",
        legal_holidays=["春节"],
        other_holidays=["元宵节", "情人节"],
    )
    parts = info_panel.build_info_parts(
        sel_date=None,
        memorial_names=["老婆生日"],
        lunar_obj=lunar,
        has_cnlunar=True,
    )
    # "大" 要被去掉；节气取首项
    assert parts.lunar_str and "正月十五" in parts.lunar_str
    assert parts.term_text == "立春"
    # 去重且保序
    assert parts.holiday_names == ("春节", "元宵节", "情人节")
    assert parts.memorial_names == ("老婆生日",)
    assert parts.has_lunar_data is True


def test_render_html_empty_returns_none():
    parts = info_panel.InfoParts()
    assert info_panel.render_html(parts) is None


def test_render_html_escapes_user_input():
    parts = info_panel.InfoParts(
        lunar_str=None, term_text=None,
        holiday_names=(),
        memorial_names=("<script>alert(1)</script>",),
    )
    html_text = info_panel.render_html(parts)
    assert html_text is not None
    assert "<script>" not in html_text
    assert "&lt;script&gt;" in html_text


def test_placeholder_key_branches():
    p1 = info_panel.InfoParts(lunar_lib_available=False)
    assert info_panel.placeholder_key(p1) == "info.no_cnlunar"

    p2 = info_panel.InfoParts(lunar_lib_available=True, has_lunar_data=False)
    assert info_panel.placeholder_key(p2) == "info.lunar_unavailable"

    p3 = info_panel.InfoParts(lunar_lib_available=True, has_lunar_data=True)
    assert info_panel.placeholder_key(p3) == "info.no_events"


def test_as_list_normalizes():
    assert info_panel._as_list(None) == []
    assert info_panel._as_list("无") == []
    assert info_panel._as_list("春节") == ["春节"]
    assert info_panel._as_list(["春节", "无", "元宵"]) == ["春节", "元宵"]