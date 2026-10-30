# coding: utf-8
"""i18n 补充：extra key 报告、多参 format、语言回退边界。"""
from desktop_calendar.config import i18n
from desktop_calendar.config import translations


class TestExtraKey:
    def test_en_us_extra_reported(self, monkeypatch):
        """en_US 有而 zh_CN 没有的 key 应在 extra 里报告。"""
        monkeypatch.setitem(translations.EN_US, "test.only_en", "only en")
        report = i18n.validate_keys()
        assert "en_US" in report
        assert "test.only_en" in report["en_US"]["extra"]


class TestTrMore:
    def test_no_kwargs_returns_raw(self):
        assert i18n.tr("app.title") == "桌面日历"

    def test_multiple_kwargs_substituted(self):
        text = i18n.tr("cal.title_format", year=2024, month=12)
        assert "2024" in text and "12" in text

    def test_unknown_key_with_kwargs_still_returns_key(self):
        # 未知 key 直接返回 key，不应尝试 format
        assert i18n.tr("nonexistent.key", x=1) == "nonexistent.key"

    def test_extra_kwargs_ignored(self):
        # 模板无占位符时，多余 kwargs 被忽略
        assert i18n.tr("app.title", extra=1) == "桌面日历"


class TestLanguageFallbackMore:
    def test_set_empty_string_resets_to_zh(self):
        i18n.set_language("en_US")
        i18n.set_language("")
        assert i18n.get_language() == "zh_CN"

    def test_set_none_resets_to_zh(self):
        i18n.set_language("en_US")
        i18n.set_language(None)
        assert i18n.get_language() == "zh_CN"