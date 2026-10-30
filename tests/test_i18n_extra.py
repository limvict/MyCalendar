# coding: utf-8
"""i18n 补充：格式化 ValueError 分支、placeholder mismatch。"""
from desktop_calendar.config import i18n


def test_tr_format_value_error_returns_template(monkeypatch):
    """语言包文本花括号语法错 → format 抛 ValueError → 原样返回。"""
    monkeypatch.setitem(i18n._current_table, "test.bad", "unbalanced { brace")
    assert i18n.tr("test.bad", x=1) == "unbalanced { brace"


def test_validate_keys_placeholder_mismatch(monkeypatch):
    from desktop_calendar.config import translations
    monkeypatch.setitem(translations.ZH_CN, "test.ph", "{a}{b}")
    monkeypatch.setitem(translations.EN_US, "test.ph", "{a}")
    report = i18n.validate_keys()
    assert "en_US" in report
    assert "test.ph" in report["en_US"]["placeholder_mismatch"]


def test_validate_keys_missing(monkeypatch):
    from desktop_calendar.config import translations
    monkeypatch.setitem(translations.ZH_CN, "test.only_zh", "x")
    report = i18n.validate_keys()
    assert "test.only_zh" in report["en_US"]["missing"]