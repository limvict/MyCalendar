# coding: utf-8
"""info_panel 纯函数单元测试。"""
import pytest

from app import info_panel
from app.info_panel import InfoParts
from constants import DEFAULT_THEME

# ---------- _as_list ----------

class TestAsList:
    def test_none_returns_empty(self):
        assert info_panel._as_list(None) == []

    def test_wu_string_returns_empty(self):
        assert info_panel._as_list("无") == []

    def test_single_string_wrapped(self):
        assert info_panel._as_list("春节") == ["春节"]

    def test_list_filters_wu_and_falsy(self):
        got = info_panel._as_list(["春节", "无", "", None, "元旦"])
        assert got == ["春节", "元旦"]

    def test_tuple_input(self):
        assert info_panel._as_list(("春节", "元旦")) == ["春节", "元旦"]

    def test_empty_list(self):
        assert info_panel._as_list([]) == []


# ---------- _extract_lunar_str ----------

class TestExtractLunarStr:
    def test_none_lunar(self):
        assert info_panel._extract_lunar_str(None) is None

    def test_normal_strips_da(self, fake_lunar):
        lunar = fake_lunar(
            lunarYearCn="二〇二五年", chineseYearZodiac="蛇",
            lunarMonthCn="正月大", lunarDayCn="初一",
        )
        assert (info_panel._extract_lunar_str(lunar)
                == "二〇二五年【蛇】 正月初一")

    def test_xiao_also_stripped(self, fake_lunar):
        lunar = fake_lunar(
            lunarYearCn="二〇二五年", chineseYearZodiac="蛇",
            lunarMonthCn="腊月小", lunarDayCn="廿九",
        )
        assert (info_panel._extract_lunar_str(lunar)
                == "二〇二五年【蛇】 腊月廿九")

    def test_missing_attribute_returns_none(self, fake_lunar):
        lunar = fake_lunar(lunarYearCn="二〇二五年")
        assert info_panel._extract_lunar_str(lunar) is None


# ---------- _extract_term_text ----------

class TestExtractTermText:
    def test_none_lunar(self):
        assert info_panel._extract_term_text(None) is None

    def test_missing_attr(self, fake_lunar):
        assert info_panel._extract_term_text(fake_lunar()) is None

    def test_empty_string(self, fake_lunar):
        assert info_panel._extract_term_text(
            fake_lunar(todaySolarTerms="")) is None

    def test_wu_is_none(self, fake_lunar):
        assert info_panel._extract_term_text(
            fake_lunar(todaySolarTerms="无")) is None

    def test_plain_string(self, fake_lunar):
        assert info_panel._extract_term_text(
            fake_lunar(todaySolarTerms="清明")) == "清明"

    def test_list_takes_first(self, fake_lunar):
        assert info_panel._extract_term_text(
            fake_lunar(todaySolarTerms=["清明", "谷雨"])) == "清明"

    def test_empty_list(self, fake_lunar):
        assert info_panel._extract_term_text(
            fake_lunar(todaySolarTerms=[])) is None


# ---------- _extract_holidays ----------

class TestExtractHolidays:
    def test_none_lunar(self):
        assert info_panel._extract_holidays(None) == ()

    def test_methods_missing(self, fake_lunar):
        assert info_panel._extract_holidays(fake_lunar()) == ()

    def test_merge_legal_and_other(self, fake_lunar):
        lunar = fake_lunar(
            get_legalHolidays=lambda: "春节",
            get_otherHolidays=lambda: ["小年", "元宵"],
        )
        assert (info_panel._extract_holidays(lunar)
                == ("春节", "小年", "元宵"))

    def test_dedup_preserve_order(self, fake_lunar):
        lunar = fake_lunar(
            get_legalHolidays=lambda: "春节",
            get_otherHolidays=lambda: ["春节", "小年"],
        )
        assert (info_panel._extract_holidays(lunar)
                == ("春节", "小年"))

    def test_wu_filtered(self, fake_lunar):
        lunar = fake_lunar(
            get_legalHolidays=lambda: "无",
            get_otherHolidays=lambda: "小年",
        )
        assert info_panel._extract_holidays(lunar) == ("小年",)

    def test_exception_returns_empty(self, fake_lunar):
        def boom():
            raise RuntimeError("cnlunar 内部错误")

        lunar = fake_lunar(get_legalHolidays=boom,
                          get_otherHolidays=boom)
        assert info_panel._extract_holidays(lunar) == ()


# ---------- build_info_parts ----------

class TestBuildInfoParts:
    def test_all_empty(self):
        parts = info_panel.build_info_parts(
            sel_date=None, memorial_names=None,
            lunar_obj=None, has_cnlunar=False)
        assert parts.lunar_str is None
        assert parts.term_text is None
        assert parts.holiday_names == ()
        assert parts.memorial_names == ()
        assert parts.has_lunar_data is False
        assert parts.lunar_lib_available is False

    def test_memorial_names_normalized_to_tuple(self):
        parts = info_panel.build_info_parts(
            sel_date=None, memorial_names=["生日", "纪念日"],
            lunar_obj=None, has_cnlunar=True)
        assert parts.memorial_names == ("生日", "纪念日")
        assert isinstance(parts.memorial_names, tuple)

    def test_full_data(self, fake_lunar):
        lunar = fake_lunar(
            lunarYearCn="二〇二五年", chineseYearZodiac="蛇",
            lunarMonthCn="正月小", lunarDayCn="十五",
            todaySolarTerms="元宵",
            get_legalHolidays=lambda: "无",
            get_otherHolidays=lambda: "元宵节",
        )
        parts = info_panel.build_info_parts(
            sel_date=None, memorial_names=["生日"],
            lunar_obj=lunar, has_cnlunar=True)
        assert parts.lunar_str == "二〇二五年【蛇】 正月十五"
        assert parts.term_text == "元宵"
        assert parts.holiday_names == ("元宵节",)
        assert parts.memorial_names == ("生日",)
        assert parts.has_lunar_data is True
        assert parts.lunar_lib_available is True


# ---------- render_html ----------

class TestRenderHtml:
    @pytest.fixture(autouse=True)
    def _stub_tr(self, monkeypatch):
        table = {
            "info.solar_term": "节气",
            "info.festival": "节日",
            "info.memorial": "纪念日",
        }
        monkeypatch.setattr(
            info_panel, "tr", lambda key: table.get(key, key))

    def test_empty_returns_none(self):
        assert info_panel.render_html(InfoParts()) is None

    def test_lunar_only(self):
        html = info_panel.render_html(InfoParts(lunar_str="正月初一"))
        assert html is not None
        assert "正月初一" in html
        assert DEFAULT_THEME["lunar_text_color"] in html

    def test_term_label_and_color(self):
        html = info_panel.render_html(InfoParts(term_text="清明"))
        assert DEFAULT_THEME["solar_term_text_color"] in html
        assert "清明" in html

    def test_holiday_joined_without_separator(self):
        html = info_panel.render_html(
            InfoParts(holiday_names=("春节", "小年")))
        assert "春节小年" in html

    def test_memorial_joined_with_dunhao(self):
        html = info_panel.render_html(
            InfoParts(memorial_names=("生日", "纪念日")))
        assert "生日、纪念日" in html

    def test_html_escaped(self):
        html = info_panel.render_html(InfoParts(lunar_str="<script>"))
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_multi_pieces_all_present_and_ordered(self):
        """4 段都拼进去，且按 农历 → 节气 → 节日 → 纪念日 顺序出现。

        不数分隔符字面量（原测试数 "｜"）——那是实现细节，
        改分隔符（比如换成 " | " 或 <br>）不应让契约测试变红。
        改数 <span 贴合"4 段都在"的意图。
        """
        html = info_panel.render_html(InfoParts(
            lunar_str="正月初一", term_text="清明",
            holiday_names=("春节",), memorial_names=("生日",)))
        assert html is not None
        for text in ("正月初一", "清明", "春节", "生日"):
            assert text in html
        # 顺序契约：位置严格递增。用唯一子串定位（各段内容在两处
        # 都不重复），不依赖分隔符形式。
        assert (html.index("正月初一")
                < html.index("清明")
                < html.index("春节")
                < html.index("生日"))

    def test_pieces_are_separated(self):
        """段与段之间必须有分隔物，但不指定分隔物长什么样。

        与上一条职责分开：
        - 上一条管"4 段都在、顺序对"
        - 本条只管"不是粘在一起的"
        """
        html = info_panel.render_html(InfoParts(
            lunar_str="ALPHA", term_text="BETA"))
        assert html is not None
        between = html[html.index("ALPHA") + len("ALPHA"):
                        html.index("BETA")]
        assert between != "", f"两段之间没有分隔物：{between!r}"
        
    def test_render_html_follows_passed_theme(self):
        html = info_panel.render_html(
            InfoParts(lunar_str="正月初一"),
            theme={"lunar_text_color": "#123456"})
        assert "#123456" in html
        assert DEFAULT_THEME["lunar_text_color"] not in html
        
# ---------- placeholder_key ----------

class TestPlaceholderKey:
    def test_no_lib(self):
        assert (info_panel.placeholder_key(
                    InfoParts(lunar_lib_available=False))
                == "info.no_cnlunar")

    def test_lib_ok_but_no_data(self):
        assert (info_panel.placeholder_key(InfoParts(
                    lunar_lib_available=True, has_lunar_data=False))
                == "info.lunar_unavailable")

    def test_data_ok_no_events(self):
        assert (info_panel.placeholder_key(InfoParts(
                    lunar_lib_available=True, has_lunar_data=True))
                == "info.no_events")