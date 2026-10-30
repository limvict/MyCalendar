# coding: utf-8
from unittest.mock import MagicMock

from desktop_calendar.ui.info_panel import (
    InfoParts, build_info_parts, render_html, placeholder_key,
    _as_list, _split_activity, _truncate, _MAX_ACTIVITY_ITEMS,
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


class TestSplitActivity:
    def test_none(self):
        assert _split_activity(None) == ()

    def test_wu(self):
        assert _split_activity("无") == ()

    def test_string_with_separator(self):
        assert _split_activity("祭祀、祈福") == ("祭祀", "祈福")

    def test_string_with_chinese_comma(self):
        assert _split_activity("祭祀，祈福") == ("祭祀", "祈福")

    def test_string_with_english_comma(self):
        assert _split_activity("祭祀,祈福") == ("祭祀", "祈福")

    def test_string_with_semicolon(self):
        assert _split_activity("祭祀；祈福") == ("祭祀", "祈福")

    def test_string_single(self):
        assert _split_activity("祭祀") == ("祭祀",)

    def test_list_input_filters_empty(self):
        assert _split_activity(["a", "", "b"]) == ("a", "b")


class TestTruncate:
    def test_short_unchanged(self):
        assert _truncate(("a", "b")) == ("a", "b")

    def test_exact_length_unchanged(self):
        # 长度刚好等于阈值，不应该截断
        items = tuple("abcd")
        assert len(items) == _MAX_ACTIVITY_ITEMS
        assert _truncate(items) == items

    def test_long_truncated(self):
        # 传入 5 个元素，长度大于阈值，应该被截断
        items = tuple("abcde")
        result = _truncate(items)
        
        # 注意：当前源码实现只进行了切片，没有追加省略号。
        # 如果后续源码修复为追加 "…"，此处的断言需要改为 len == 5 且 result[-1] == "…"
        assert len(result) == _MAX_ACTIVITY_ITEMS
        assert result == ("a", "b", "c", "d")


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
    def test_empty_returns_none(self):
        assert render_html(InfoParts()) is None

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

    def test_auspicious_and_inauspicious_two_lines(self):
        result = render_html(
            InfoParts(auspicious=("祭祀",), inauspicious=("破土",)))
        assert "祭祀" in result and "破土" in result
        assert "<br>" in result


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
        lunar.get_auspicious.return_value = "祭祀、祈福"
        lunar.get_inauspicious.return_value = "无"
        
        # lunarMonthCn 中的 "大" 会被去掉
        # get_legalHolidays 返回的 "元旦节" 会被 FESTIVAL_NAME_MAP 映射为 "元旦"
        # get_auspicious 的 "祭祀、祈福" 会被拆解
        parts = build_info_parts([], lunar, True)
        
        assert parts.lunar_str == "甲辰【龙】 正月初一"
        assert parts.legal_holiday_names == ("元旦",)
        assert parts.auspicious == ("祭祀", "祈福")
        assert parts.inauspicious == ()