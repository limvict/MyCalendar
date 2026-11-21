# coding: utf-8
"""业务面板 QSS：日程列表、侧栏信息服务与天气卡。"""

from __future__ import annotations

from ..resolver import ThemeResolver
from .palette import (
    _ensure_contrast,
    _get_safe_palette,
    _hover_accent,
    _image,
    _shade,
    _svg_uri,
)


# ===================== 日程面板 =====================
def schedule_panel(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)

    # 按钮背景与文字对比度
    btn_bg = r.color("btn_bg") or p.bg_input
    btn_text = _ensure_contrast(btn_bg, r.color("btn_text") or p.text_main)
    btn_hover = r.color("btn_hover") or p.accent
    btn_pressed = r.color("btn_pressed") or p.border

    today_bg = r.color("today_bg") or p.accent
    today_text = _ensure_contrast(today_bg, r.color("today_text_color") or p.text_main)

    # QListWidget 复选框打钩颜色
    check_color = _ensure_contrast(p.accent, p.bg_input)
    check_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{check_color}" stroke-width="3" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="20 6 9 17 4 12"/></svg>'
    )
    check_uri = _svg_uri(check_svg)

    scroll_handle = r.color("scrollbar_handle")
    scroll_hover = r.color("scrollbar_handle_hover")
    border = r.color("border_color")

    return f"""
    #schedule_panel {{
        background-color: {p.bg_input};
        border: 1px solid {border};
        border-radius: {r.px("btn_radius")};
    }}
    QLabel#schedule_date {{
        color: {p.text_input};
        font-size: {r.px("font_size")};
        font-weight: 600;
        background: transparent;
    }}
    QListWidget {{
        background: transparent;
        border: none;
        color: {p.text_input};
        font-size: {r.px("font_size")};
        outline: none;
    }}
    QListWidget::item {{
        padding: 3px 4px;
        border-radius: {r.px("btn_radius_small")};
        color: {p.text_input};
    }}
    QListWidget::item:hover {{
        background: {r.color("menu_hover")};
    }}
    QListWidget::item:selected {{
        background: {p.accent};
        color: {_ensure_contrast(p.accent, p.text_input)};
    }}
    QListWidget::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 3px;
        border: 1px solid {p.border};
        background: {p.bg_input};
    }}
    QListWidget::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
        {_image(check_uri)}
    }}
    QPushButton {{
        background-color: {btn_bg};
        color: {btn_text};
        border: 1px solid {p.border};
        border-radius: {r.px("btn_radius_small")};
        padding: {r.px("btn_padding_v")} {r.px("btn_padding_h")};
        font-weight: 600;
        font-size: {r.px("font_size")};
    }}
    QPushButton:hover {{
        background-color: {btn_hover};
        border-color: {_hover_accent(r)};
    }}
    QPushButton:focus {{ border-color: {_hover_accent(r)}; }}
    QPushButton:pressed {{ background-color: {btn_pressed}; }}
    QPushButton#quick_add_schedule {{
        background-color: {today_bg};
        color: {today_text};
    }}
    QPushButton#quick_add_schedule:hover {{
        background-color: {_shade(today_bg, 12)};
        border-color: {_hover_accent(r)};
    }}
    QScrollBar:vertical {{
        border: none;
        background: transparent;
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {scroll_handle};
        min-height: 20px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {scroll_hover}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    """


# ===================== 侧边栏组件 =====================
def sidebar_services(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    border = r.color("border_color")
    btn_bg = r.color("btn_bg") or p.bg_input
    btn_hover = r.color("btn_hover") or p.accent
    # 禁用态走独立主题键（DEFAULT_THEME 提供浅色基线，深色/樱花各有覆盖）
    btn_disabled_bg = r.color("btn_disabled_bg")
    btn_disabled_text = r.color("btn_disabled_text")
    btn_disabled_border = r.color("btn_disabled_border")

    return f"""
    #sidebar_services {{
        background: transparent;
    }}
    /* 折叠开关即区块标题：和侧边栏「天气 / 今日状态 / 常用」的标题保持同款 */
    QWidget#sidebar_services_header {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {border};
    }}
    QToolButton#sidebar_services_toggle {{
        color: {p.text_main};
        background: transparent;
        border: none;
        padding: 3px 2px;
        font-size: {r.px("sidebar_section_font_size")};
        font-weight: 600;
        text-align: left;
    }}
    QToolButton#sidebar_services_toggle:hover {{
        color: {_hover_accent(r)};
    }}
    QToolButton#sidebar_services_toggle:checked {{
        color: {p.text_main};
    }}
    QPushButton#sidebar_services_refresh {{
        color: {p.text_input};
        background: transparent;
        border: 1px solid {border};
        border-radius: {r.px("btn_radius_small")};
        padding: 1px 8px;
        min-width: 40px;
        font-size: {r.px("small_font_size")};
    }}
    QPushButton#sidebar_services_refresh:hover {{
        background: {btn_hover};
        border-color: {_hover_accent(r)};
    }}
    QPushButton#sidebar_services_refresh:pressed {{
        background: {r.color("btn_pressed") or btn_bg};
    }}
    QPushButton#sidebar_services_refresh:disabled {{
        color: {btn_disabled_text};
        background: {btn_disabled_bg};
        border-color: {btn_disabled_border};
    }}
    QWidget#sidebar_services_body {{
        background: {p.bg_input};
        border: 1px solid {border};
        border-radius: {r.px("btn_radius_small")};
    }}
    QLabel#sidebar_services_quote {{
        color: {p.text_input};
        background: transparent;
        border: none;
        font-size: {r.px("font_size")};
    }}
    QLabel#sidebar_services_source {{
        color: {r.color("normal_lunar_color")};
        background: transparent;
        border: none;
        font-size: {r.px("small_font_size")};
    }}
    """


def weather_panel(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    border = r.color("border_color")
    btn_bg = r.color("btn_bg") or p.bg_input
    btn_text = _ensure_contrast(btn_bg, r.color("btn_text") or p.text_main)
    btn_hover = r.color("btn_hover") or p.accent
    today_bg = r.color("today_bg") or p.accent

    return f"""
    #weather_panel {{
        background-color: {p.bg_input};
        border: 1px solid {border};
        border-radius: {r.px("btn_radius")};
    }}
    QLabel#weather_city_name {{
        color: {p.text_input};
        font-size: {r.px("font_size")};
        font-weight: 700;
        background: transparent;
    }}
    QLabel#weather_city_pages {{
        color: {today_bg};
        font-size: {r.px("small_font_size")};
        background: transparent;
    }}
    QLabel#weather_details {{
        color: {p.text_input};
        font-size: {r.px("small_font_size")};
        font-weight: 500;
        background: transparent;
    }}
    QLabel#weather_icon {{
        background: transparent;
        font-size: {r.px("font_size")};
    }}
    QLabel#weather_status {{
        color: {p.text_input};
        font-size: {r.px("font_size")};
        background: transparent;
    }}
    QPushButton#weather_nav {{
        background: {btn_bg};
        color: {btn_text};
        border: 1px solid transparent;
        border-radius: {r.px("btn_radius_small")};
        font-size: {r.px("font_size")};
        font-weight: 600;
    }}
    QPushButton#weather_nav:hover {{
        background: {btn_hover};
        border-color: {_hover_accent(r)};
    }}
    QPushButton#weather_nav:disabled {{
        color: {r.color("adjacent_text_color") or p.border};
    }}
    QPushButton#weather_add {{
        background: {btn_bg};
        color: {btn_text};
        border: 1px solid {border};
        border-radius: {r.px("btn_radius_small")};
        font-weight: 600;
    }}
    QPushButton#weather_add:hover {{
        background: {btn_hover};
        border-color: {_hover_accent(r)};
    }}
    QPushButton#weather_add:disabled {{
        color: {r.color("adjacent_text_color") or p.border};
    }}
    QPushButton#weather_remove {{
        background: {btn_bg};
        color: {btn_text};
        border: 1px solid {border};
        border-radius: {r.px("btn_radius_small")};
        font-weight: 600;
    }}
    QPushButton#weather_remove:hover {{
        background: {btn_hover};
        border-color: {_hover_accent(r)};
    }}
    QPushButton#weather_remove:disabled {{
        color: {r.color("adjacent_text_color") or p.border};
    }}
    """
