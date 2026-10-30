# coding: utf-8
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
        """当前 zh_CN / en_US 应该没有 key 缺失或占位符不一致。

        如果未来新增 key 未同步，这条用例会提醒；要么补齐翻译，
        要么显式调整本测试。
        """
        report = i18n.validate_keys(strict=False)
        assert report == {}, f"语言包不一致：{report}"