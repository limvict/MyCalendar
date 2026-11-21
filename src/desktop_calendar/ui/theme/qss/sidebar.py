# coding: utf-8
"""快捷侧栏 QSS：面板、标题、分区标题、状态卡与操作按钮。"""

from __future__ import annotations

from ..resolver import ThemeResolver
from .palette import _ensure_contrast, _hover_accent


def sidebar_panel(r: ThemeResolver, *, rounded: bool = True) -> str:
    """右侧快捷侧边栏面板；收起时不需要圆角。"""
    radius = r.px("corner_radius") if rounded else "0px"
    return f"""
    #quick_sidebar {{
        background-color: {r.color("bg_main")};
        border-left: 1px solid {r.color("border_color")};
        border-top-right-radius: {radius};
        border-bottom-right-radius: {radius};
    }}
    """


def sidebar_close_button(r: ThemeResolver) -> str:
    return f"""
    QPushButton {{
        background: {r.color("input_bg")};
        color: {r.color("date_text_color")};
        border: 1px solid {r.color("border_color")};
        border-radius: 8px;
        font-size: 18px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: {r.color("btn_hover")};
        border-color: {_hover_accent(r)};
    }}
    QPushButton:focus {{
        border-color: {_hover_accent(r)};
    }}
    """


def sidebar_action_button(r: ThemeResolver) -> str:
    """侧边栏「常用」网格里的功能按钮。"""
    return f"""
    QPushButton {{
        background-color: {r.color("btn_bg")};
        color: {_ensure_contrast(r.color("btn_bg"), r.color("btn_text"))};
        border: 1px solid transparent;
        border-radius: 9px;
        padding: 8px 11px;
        font-size: 12px;
        text-align: left;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {r.color("btn_hover")};
        border-color: {_hover_accent(r)};
    }}
    QPushButton:focus {{
        border-color: {_hover_accent(r)};
    }}
    QPushButton:pressed {{
        background-color: {r.color("btn_pressed")};
    }}
    """


def sidebar_section_title(r: ThemeResolver) -> str:
    """侧边栏区块标题（天气 / 今日状态 / 专注 / 常用）。"""
    return f"""
    QLabel {{
        color: {r.color("date_text_color")};
        font-size: {r.px("sidebar_section_font_size")};
        font-weight: 600;
        padding: 3px 2px;
        border-bottom: 1px solid {r.color("border_color")};
        background: transparent;
    }}
    """


def sidebar_status_card(r: ThemeResolver) -> str:
    """侧边栏里的状态卡片（考勤 / 专注）。"""
    return f"""
    QLabel {{
        background-color: {r.color("input_bg")};
        color: {r.color("date_text_color")};
        border: 1px solid {r.color("border_color")};
        border-radius: 10px;
        font-size: 12px;
        padding: 10px;
    }}
    """


def sidebar_title(r: ThemeResolver) -> str:
    return f"""
    QLabel {{
        font-size: 18px;
        font-weight: 700;
        color: {r.color("date_text_color")};
        padding: 0;
        background: transparent;
    }}
    """


def sidebar_subtitle(r: ThemeResolver) -> str:
    return f"""
    QLabel {{
        font-size: 11px;
        color: {r.color("date_text_color")};
        background: transparent;
    }}
    """
