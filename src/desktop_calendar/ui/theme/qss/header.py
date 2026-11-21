# coding: utf-8
"""顶部栏 QSS：月份导航、标题按钮、视图下拉与窗口按钮。"""

from __future__ import annotations

from ..resolver import ThemeResolver
from .palette import (
    _arrow_svg,
    _ensure_contrast,
    _font_family,
    _get_safe_palette,
    _hover_accent,
    _image,
    _shade,
)


def info_label(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    return (
        f"QLabel {{ font-size: {r.px('info_label_font_size')};"
        f" font-family: {_font_family(r)};"
        f" color: {p.text_main};"
        f" padding: 6px; background: transparent; }}"
    )


def nav_buttons(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    return f"""
    QPushButton {{
        background: {r.color("btn_bg") or "transparent"};
        color: {p.text_main};
        border: 1px solid transparent;
        border-radius: {r.px("btn_radius")};
        padding: 6px;
        font-size: {r.px("font_size")};
    }}
    QPushButton:hover {{
        background: {r.color("btn_hover")};
        border-color: {_hover_accent(r)};
    }}
    QPushButton:focus {{ border-color: {_hover_accent(r)}; }}
    QPushButton:pressed {{ background: {r.color("btn_pressed")}; }}
    """


def today_button(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    accent = _hover_accent(r)
    return f"""
    QPushButton#today_btn {{
        background: {accent};
        color: {_ensure_contrast(accent, p.text_main)};
        border: none;
        border-radius: {r.px("btn_radius")};
        padding: 6px 14px;
        font-size: {r.px("font_size")};
    }}
    QPushButton#today_btn:hover {{ background: {_shade(accent, 12)}; }}
    QPushButton#today_btn:pressed {{ background: {_shade(accent, 22)}; }}
    """


def cal_title(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    return f"""
    #cal_title {{
        font-size: {r.px("cal_title_font_size")};
        font-weight: 500;
        background: transparent;
        border: none;
        border-radius: {r.px("btn_radius_small")};
        padding: 0 6px;
        color: {p.text_main};
        text-align: center;
    }}
    #cal_title:hover {{
        color: {_hover_accent(r)};
    }}
    """


def header_combo(r: ThemeResolver) -> str:
    """顶栏的视图下拉：和两侧按钮同一套胶囊样式，箭头用主题色 SVG。"""
    p = _get_safe_palette(r)
    btn_bg = r.color("btn_bg")
    arrow = _arrow_svg(p.text_input, down=True)
    return f"""
    QComboBox {{
        background: {btn_bg};
        color: {_ensure_contrast(btn_bg, r.color("btn_text") or p.text_main)};
        border: 1px solid transparent;
        border-radius: {r.px("btn_radius")};
        padding: 0 16px 0 8px;
        font-size: {r.px("font_size")};
    }}
    QComboBox:hover {{
        border-color: {_hover_accent(r)};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 16px;
        border: none;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        {_image(arrow)}
        width: 10px;
        height: 6px;
    }}
    QComboBox QAbstractItemView {{
        background: {p.bg_input};
        color: {p.text_input};
        border: 1px solid {p.border};
        border-radius: {r.px("input_radius")};
        selection-background-color: {r.color("select_bg")};
        selection-color: {_ensure_contrast(r.color("select_bg"), p.text_input)};
        outline: none;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: {r.color("menu_hover")};
    }}
    """


def window_buttons(r: ThemeResolver) -> str:
    """标题栏右上角的最小化 / 关闭：默认无底色，悬停才出现反馈。"""
    p = _get_safe_palette(r)
    accent = _hover_accent(r)
    error_bg = r.color("msg_error_btn")
    return f"""
    QPushButton#win_minimize, QPushButton#win_close {{
        background: transparent;
        color: {p.text_main};
        border: 1px solid transparent;
        border-radius: {r.px("btn_radius_small")};
        padding: 0;
        font-size: {r.px("font_size")};
    }}
    QPushButton#win_minimize:hover {{
        background: {r.color("btn_hover")};
        border-color: {accent};
    }}
    QPushButton#win_minimize:pressed {{
        background: {r.color("btn_pressed")};
    }}
    QPushButton#win_close:hover {{
        background: {error_bg};
        color: {r.color("msg_error_btn_text")};
        border-color: {accent};
    }}
    QPushButton#win_close:pressed {{
        background: {r.color("msg_error_btn_hover")};
    }}
    """


def header_separator(r: ThemeResolver) -> str:
    return f"""
    QFrame#header_sep {{
        border: none;
        background: {r.color("border_color")};
    }}
    """
