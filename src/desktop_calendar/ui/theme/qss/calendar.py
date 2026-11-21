# coding: utf-8
"""日历网格 QSS：单元格、表头、今天/选中态与农历文字。"""

from __future__ import annotations

from ..resolver import ThemeResolver
from .palette import _font_family, _get_safe_palette, _hover_accent


def calendar(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    return f"""
    QCalendarWidget {{
        background-color: {p.bg_main};
        font-family: {_font_family(r)};
        color: {p.text_main};
    }}
    QCalendarWidget QWidget {{
        background-color: {p.bg_main};
    }}
    QCalendarWidget QTableView {{
        background-color: {p.bg_main};
        alternate-background-color: {p.bg_main};
        selection-background-color: {p.accent};
        selection-color: {p.text_main};
        gridline-color: {p.border};
        border: none;
    }}
    /* 导航栏（上/下月、月份、年份）不写就会掉回系统原生样式：
       深色主题下悬停会闪出原生白底，也是这里统一成主题悬停 */
    QCalendarWidget QToolButton {{
        color: {p.text_main};
        background: transparent;
        border: 1px solid transparent;
        border-radius: {r.px("btn_radius_small")};
        padding: 2px 6px;
        font-family: {_font_family(r)};
        font-size: {r.px("font_size")};
    }}
    QCalendarWidget QToolButton:hover {{
        background: {r.color("btn_hover")};
        border-color: {_hover_accent(r)};
    }}
    QCalendarWidget QToolButton:pressed {{
        background: {r.color("btn_pressed")};
    }}
    QCalendarWidget QToolButton::menu-indicator {{
        image: none;
    }}
    /* 月份 / 年份下拉是日历内部的 QMenu，同样默认是原生白底 */
    QCalendarWidget QMenu {{
        background-color: {r.color("menu_bg")};
        border: 1px solid {p.border};
        border-radius: {r.px("menu_radius")};
        padding: 6px;
        color: {p.text_main};
    }}
    QCalendarWidget QMenu::item {{
        padding: 4px 16px;
        border-radius: {r.px("btn_radius_small")};
        background: transparent;
        color: {p.text_main};
    }}
    QCalendarWidget QMenu::item:selected {{
        background: {r.color("menu_hover")};
    }}
    QCalendarWidget QSpinBox {{
        border: 1px solid {p.border};
        border-radius: {r.px("input_radius")};
        background: {p.bg_input};
        color: {p.text_input};
        padding: 2px 6px;
    }}
    QCalendarWidget QSpinBox:hover,
    QCalendarWidget QSpinBox:focus {{
        border-color: {_hover_accent(r)};
    }}
    QCalendarWidget QHeaderView {{
        background-color: {r.color("calendar_header_bg") or p.bg_main};
        border: none;
        min-height: 32px;
    }}
    QCalendarWidget QHeaderView::section {{
        background-color: {r.color("calendar_header_bg") or p.bg_main};
        color: {p.text_main};
        border: 1px solid {p.border};
        padding: 8px 0px;
        font-family: {_font_family(r)};
        font-size: {r.px("week_header_font_size")};
    }}
    """
