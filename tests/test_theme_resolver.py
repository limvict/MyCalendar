# coding: utf-8
"""ThemeResolver 回退 + ThemeBundle 不可变性。"""
import pytest
from PyQt6.QtGui import QColor

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.ui.theme.resolver import ThemeResolver
from desktop_calendar.ui.theme.bundle import build_bundle


def test_missing_key_falls_back_to_default():
    r = ThemeResolver({})
    assert r.color("bg_main") == DEFAULT_THEME["bg_main"]
    assert r.int("window_width") == DEFAULT_THEME["window_width"]
    assert r.str("font_family") == DEFAULT_THEME["font_family"]


def test_invalid_int_falls_back():
    r = ThemeResolver({"window_width": "not-a-number"})
    assert r.int("window_width") == DEFAULT_THEME["window_width"]


def test_invalid_float_falls_back():
    # DEFAULT_THEME 里没有 float 类型的键，用 int 键验证 float() 路径：
    # 非法字符串触发 except → 回退 float(DEFAULT_THEME["font_size"]) == 13.0
    r = ThemeResolver({"font_size": "bad"})
    assert r.float("font_size") == float(DEFAULT_THEME["font_size"])


def test_float_from_int_value():
    r = ThemeResolver({"font_size": 14})
    assert r.float("font_size") == 14.0


def test_invalid_color_falls_back():
    r = ThemeResolver({"bg_main": "not-a-color"})
    c = r.qcolor("bg_main")
    assert c.isValid()
    assert c == QColor(DEFAULT_THEME["bg_main"])


def test_qcolor_cached():
    r = ThemeResolver({"bg_main": "#111111"})
    assert r.qcolor("bg_main") is r.qcolor("bg_main")


def test_defensive_copy():
    """修改入参 dict 不影响 resolver。"""
    theme = {"bg_main": "#111111"}
    r = ThemeResolver(theme)
    theme["bg_main"] = "#999999"
    assert r.color("bg_main") == "#111111"


def test_px():
    r = ThemeResolver({"window_width": 440})
    assert r.px("window_width") == "440px"


def test_bundle_theme_readonly(qapp):
    b = build_bundle("light", dict(DEFAULT_THEME))
    with pytest.raises(TypeError):
        b.theme["bg_main"] = "#000000"       # MappingProxyType


def test_bundle_calendar_colors_readonly(qapp):
    b = build_bundle("light", dict(DEFAULT_THEME))
    with pytest.raises(TypeError):
        b.calendar_colors["today_bg"] = QColor("#000000")