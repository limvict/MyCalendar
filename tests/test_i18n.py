# coding: utf-8
"""i18n：tr、语言切换、监听器、validate_keys 及补充边界。"""
from desktop_calendar.config import i18n


class TestTr:
    def test_known_key(self):
        assert i18n.tr("app.title") == "桌面日历"

    def test_unknown_key_returns_key(self):
        assert i18n.tr("nonexistent.key") == "nonexistent.key"

    def test_format_kwargs(self):
        text = i18n.tr("cal.title_format", year=2024, month=3)
        assert "2024" in text and "3" in text

    def test_bad_format_returns_template(self):
        # 缺少 max_day，format 会失败并原样返回模板
        text = i18n.tr("memorial.warn_solar_day", month=1, day=2)
        assert "{" in text

    def test_fallback_to_zh_cn(self):
        i18n.set_language("en_US")
        assert i18n.tr("app.title") == "Desktop Calendar"

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

    def test_tr_format_value_error_returns_template(self, monkeypatch):
        """语言包文本花括号语法错 → format 抛 ValueError → 原样返回。"""
        monkeypatch.setitem(i18n._current_table, "test.bad",
                            "unbalanced { brace")
        assert i18n.tr("test.bad", x=1) == "unbalanced { brace"

    def test_tr_format_keyerror_logs_missing_key(
            self, caplog, app_logger_propagate):
        import logging
        with caplog.at_level(logging.WARNING):
            i18n.tr("memorial.warn_solar_day", month=1, day=2)
        msgs = [r.getMessage() for r in caplog.records
                if r.levelno == logging.WARNING]
        assert any("max_day" in m for m in msgs), f"日志: {msgs}"

class TestSetLanguage:
    def test_set_known(self):
        i18n.set_language("en_US")
        assert i18n.get_language() == "en_US"

    def test_set_unknown_falls_back(self):
        i18n.set_language("xx_XX")
        assert i18n.get_language() == "zh_CN"

    def test_set_none_falls_back(self):
        i18n.set_language(None)
        assert i18n.get_language() == "zh_CN"

    def test_set_empty_string_resets_to_zh(self):
        i18n.set_language("en_US")
        i18n.set_language("")
        assert i18n.get_language() == "zh_CN"

    def test_set_none_resets_to_zh(self):
        i18n.set_language("en_US")
        i18n.set_language(None)
        assert i18n.get_language() == "zh_CN"


class TestListeners:
    def test_on_change_called(self):
        calls = []
        cb = lambda lang: calls.append(lang)
        i18n.on_language_changed(cb)
        try:
            i18n.set_language("en_US")
            assert calls == ["en_US"]
        finally:
            i18n.off_language_changed(cb)

    def test_off_idempotent(self):
        cb = lambda lang: None
        i18n.off_language_changed(cb)
        i18n.off_language_changed(cb)


class TestValidateKeys:
    def test_returns_report(self):
        report = i18n.validate_keys()
        assert isinstance(report, dict)

    def test_current_packs_consistent(self):
        """当前 zh_CN / en_US 应该没有 key 缺失或占位符不一致。"""
        report = i18n.validate_keys(strict=False)
        assert report == {}, f"语言包不一致：{report}"

    def test_en_us_extra_reported(self, monkeypatch):
        """en_US 有而 zh_CN 没有的 key 应在 extra 里报告。"""
        from desktop_calendar.config import translations
        monkeypatch.setitem(translations.EN_US, "test.only_en", "only en")
        report = i18n.validate_keys()
        assert "en_US" in report
        assert "test.only_en" in report["en_US"]["extra"]

    def test_placeholder_mismatch(self, monkeypatch):
        from desktop_calendar.config import translations
        monkeypatch.setitem(translations.ZH_CN, "test.ph", "{a}{b}")
        monkeypatch.setitem(translations.EN_US, "test.ph", "{a}")
        report = i18n.validate_keys()
        assert "en_US" in report
        assert "test.ph" in report["en_US"]["placeholder_mismatch"]

    def test_missing(self, monkeypatch):
        from desktop_calendar.config import translations
        monkeypatch.setitem(translations.ZH_CN, "test.only_zh", "x")
        report = i18n.validate_keys()
        assert "test.only_zh" in report["en_US"]["missing"]
