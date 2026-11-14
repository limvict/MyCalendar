# coding: utf-8
"""theme/qss：字体族、SVG data URI、深色 compact、三 kind。"""
import pytest

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.ui.theme import qss
from desktop_calendar.ui.theme.resolver import ThemeResolver


def _r(overrides=None):
    theme = dict(DEFAULT_THEME)
    if overrides:
        theme.update(overrides)
    return ThemeResolver(theme)


class TestFontFamily:
    def test_quoted(self):
        r = _r({"font_family": "微软雅黑,SimHei"})
        result = qss._font_family(r)
        assert '"微软雅黑"' in result
        assert '"SimHei"' in result

    def test_generic_unquoted(self):
        r = _r({"font_family": "sans-serif"})
        assert qss._font_family(r) == "sans-serif"

    def test_mixed(self):
        r = _r({"font_family": "微软雅黑,sans-serif"})
        result = qss._font_family(r)
        assert '"微软雅黑"' in result
        assert "sans-serif" in result
        # 通用族不应被引号
        assert '"sans-serif"' not in result

    def test_empty_falls_back(self):
        r = _r({"font_family": ""})
        assert qss._font_family(r) == "sans-serif"


class TestSvgUri:
    def test_format(self):
        uri = qss._svg_uri("<svg></svg>")
        assert uri.startswith("url(data:image/svg+xml;base64,")
        assert uri.endswith(")")


class TestDialogButtons:
    def test_light_no_compact(self):
        r = _r({"bg_main": "#FFFFFF"})
        css = qss.dialog_buttons(r)
        assert "QPushButton" in css
        assert "QPushButton:hover" in css
        assert "QPushButton:pressed" in css

    def test_dark_compact(self):
        r = _r({"bg_main": "#000000"})
        css = qss.dialog_buttons(r)
        assert "QPushButton" in css


class TestMessageBox:
    @pytest.mark.parametrize("kind", ["info", "warn", "error"])
    def test_three_kinds(self, kind):
        r = _r()
        css = qss.message_box(r, kind)
        assert "QMessageBox" in css
        assert "QMessageBox QPushButton" in css


class TestKeySections:
    def test_calendar(self):
        assert "QCalendarWidget" in qss.calendar(_r())

    def test_dialog_inputs_has_svg_arrows(self):
        css = qss.dialog_inputs(_r())
        assert "QComboBox::down-arrow" in css
        assert "QSpinBox::up-arrow" in css
        assert "base64" in css

    def test_checkbox_indicator(self):
        css = qss.dialog_checkboxes(_r())
        assert "QCheckBox::indicator" in css
        assert "QRadioButton::indicator:checked" in css

    def test_menu(self):
        assert "QMenu::item:selected" in qss.menu(_r())
