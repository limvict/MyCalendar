# coding: utf-8
"""theme_resolver 补充：qcolor 短 hex、命名色、px 边界。"""
from PyQt6.QtGui import QColor

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.ui.theme.resolver import ThemeResolver


def test_qcolor_three_digit_hex():
    r = ThemeResolver({"bg_main": "#abc"})
    c = r.qcolor("bg_main")
    assert c.isValid()
    assert c == QColor("#abc")


def test_qcolor_named_color():
    r = ThemeResolver({"bg_main": "red"})
    c = r.qcolor("bg_main")
    assert c.isValid()
    assert c == QColor("red")


def test_qcolor_invalid_falls_back():
    r = ThemeResolver({"bg_main": "not-a-color-at-all"})
    assert r.qcolor("bg_main") == QColor(DEFAULT_THEME["bg_main"])


def test_px_zero():
    r = ThemeResolver({"x": 0})
    assert r.px("x") == "0px"


def test_px_negative():
    r = ThemeResolver({"x": -5})
    assert r.px("x") == "-5px"


def test_int_from_float_truncates():
    r = ThemeResolver({"window_width": 440.7})
    assert r.int("window_width") == 440


def test_float_from_numeric_string():
    r = ThemeResolver({"font_size": "13.5"})
    assert r.float("font_size") == 13.5