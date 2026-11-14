# coding: utf-8
from unittest.mock import MagicMock

from desktop_calendar.ui.info_panel import (
    InfoParts, build_info_parts, render_html, placeholder_key,
    _as_list,
)


class TestAsList:
    def test_none(self):
        assert _as_list(None) == []

    def test_wu_string(self):
        assert _as_list("无") == []

    def test_list_filters_wu(self):
        assert _as_list(["a", "无", "b"]) == ["a", "b"]

    def test_tuple_filters_wu(self):
        assert _as_list(("a", "无", "b")) == ["a", "b"]

    def test_single(self):
        assert _as_list("节日") == ["节日"]


class TestPlaceholderKey:
    def test_no_lib(self):
        assert placeholder_key(
            InfoParts(lunar_lib_available=False)) == "info.no_cnlunar"

    def test_no_data(self):
        assert placeholder_key(
            InfoParts(lunar_lib_available=True,
                      has_lunar_data=False)) == "info.lunar_unavailable"

    def test_has_data(self):
        assert placeholder_key(
            InfoParts(lunar_lib_available=True,
                      has_lunar_data=True)) == "info.no_events"


class TestRenderHtml:

    def test_lunar_only(self):
        result = render_html(InfoParts(lunar_str="甲辰龙年 正月初一"))
        assert result is not None
        assert "甲辰龙年" in result

    def test_escapes_html(self):
        result = render_html(InfoParts(lunar_str="<script>"))
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_memorial(self):
        result = render_html(InfoParts(memorial_names=("生日",)))
        assert result is not None
        assert "生日" in result

    def test_escapes_memorial_html(self):
        result = render_html(InfoParts(memorial_names=("<script>",)))
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_memorial_next_today(self):
        # days <= 0 应显示"今天"
        result = render_html(InfoParts(memorial_next=(("生日", 0),)))
        assert "生日（今天）" in result

    def test_memorial_next_days(self):
        result = render_html(InfoParts(memorial_next=(("生日", 3),)))
        assert "生日（还有3天）" in result


class TestBuildInfoParts:
    def test_none_lunar(self):
        parts = build_info_parts(
            memorial_names=[], lunar_obj=None, has_cnlunar=False)
        assert parts.lunar_lib_available is False
        assert parts.has_lunar_data is False

    def test_empty_memorial_normalized(self):
        parts = build_info_parts(
            memorial_names=[], lunar_obj=None, has_cnlunar=True)
        assert parts.memorial_names == ()

    def test_mock_lunar_extraction(self):
        lunar = MagicMock()
        lunar.lunarMonthCn = "大正月"
        lunar.lunarDayCn = "初一"
        lunar.lunarYearCn = "甲辰"
        lunar.chineseYearZodiac = "龙"
        lunar.todaySolarTerms = "无"
        lunar.get_legalHolidays.return_value = ["元旦节"]
        lunar.get_otherHolidays.return_value = []

        # lunarMonthCn 中的 "大" 会被去掉
        # get_legalHolidays 返回的 "元旦节" 会被 FESTIVAL_NAME_MAP 映射为 "元旦"
        parts = build_info_parts([], lunar, True)

        assert parts.lunar_str == "甲辰【龙】 正月初一"
        assert parts.legal_holiday_names == ("元旦",)
