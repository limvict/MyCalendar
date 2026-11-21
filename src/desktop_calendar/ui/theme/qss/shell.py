# coding: utf-8
"""窗口外壳 QSS：主窗背景、工具提示、菜单与滚动条。"""

from __future__ import annotations

from ..resolver import ThemeResolver
from .palette import (
    _get_safe_palette,
)


# ===================== 主窗口 =====================
def content_widget(r: ThemeResolver) -> str:
    return f"""
    QWidget#content_widget {{
        background-color: {r.color("bg_main")};
        border-radius: {r.px("corner_radius")};
    }}
    """


# ===================== 主窗口外壳 / 侧边栏骨架 =====================
# 这两条与主题色无关，做成常量供 main_window 直接引用
WINDOW_SHELL = "#MainWindow { background: transparent; }"


TRANSPARENT_SCROLL_AREA = "QScrollArea { background: transparent; border: none; }"


def tooltip(r: ThemeResolver) -> str:
    """应用级 QToolTip 样式（Qt 只认应用级样式表里的 QToolTip 规则）。"""
    return f"""
    QToolTip {{
        background-color: {r.color("input_bg")};
        color: {r.color("date_text_color")};
        border: 1px solid {r.color("border_color")};
        border-radius: 6px;
        padding: 6px;
    }}
    """


def content_widget_with_sidebar(r: ThemeResolver) -> str:
    """侧边栏展开时主内容只保留左侧圆角。"""
    return f"""
    #content_widget {{
        background-color: {r.color("bg_main")};
        border-top-left-radius: {r.px("corner_radius")};
        border-top-right-radius: 0px;
        border-bottom-right-radius: 0px;
        border-bottom-left-radius: {r.px("corner_radius")};
    }}
    """


# ===================== 菜单 =====================
def menu(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    return f"""
    QMenu {{
        background-color: {r.color("menu_bg") or p.bg_main};
        border: 1px solid {p.border};
        border-radius: {r.px("menu_radius")};
        padding: 6px;
    }}
    QMenu::item {{
        padding: 6px 20px;
        background: transparent;
        border-radius: {r.px("btn_radius_small")};
        color: {p.text_main};
    }}
    QMenu::item:selected {{
        background: {r.color("menu_hover")};
    }}
    """


# ===================== 全局滚动条 =====================
def scrollbar(r: ThemeResolver) -> str:
    # 滚动条滑块走独立主题键：它没有"底色可加深"，用强调色会过艳
    handle_bg = r.color("scrollbar_handle")
    handle_hover = r.color("scrollbar_handle_hover")

    return f"""
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 10px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {handle_bg};
        min-height: 20px;
        border-radius: 5px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {handle_hover};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}

    QScrollBar:horizontal {{
        border: none;
        background: transparent;
        height: 10px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background: {handle_bg};
        min-width: 20px;
        border-radius: 5px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {handle_hover};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}
    """
