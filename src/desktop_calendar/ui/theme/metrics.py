# coding: utf-8
"""主题产物：尺寸 / 字体 / 颜色 / QSS 的结构体定义与设计稿尺寸表。

只放不可变数据声明，装配逻辑在 `bundle.py`。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PyQt6.QtGui import QColor, QFont

from .resolver import ThemeResolver

_CALENDAR_COLOR_KEYS = (
    "weekend_header_red",
    "calendar_header_text",
    "adjacent_cell_bg",
    "adjacent_text_color",
    "today_bg",
    "select_bg",
    "normal_cell_bg",
    "today_text_color",
    "select_text_color",
    "festival_red",
    "workday_orange",
    "normal_num_color",
    "memorial_orange",
    "normal_lunar_color",
    "tag_bg",
    "tag_text_color",
)


@dataclass(frozen=True)
class WindowMetrics:
    width: int
    height: int
    corner_radius: int
    shadow_size: int
    shadow_color: QColor
    nav_btn_width: int
    info_label_height: int


@dataclass(frozen=True)
class FontSet:
    global_: QFont
    calendar_day: QFont
    calendar_small: QFont


@dataclass(frozen=True)
class CalendarMetrics:
    cell_radius: int
    dot_size: int
    tag_size: int


# 设计稿尺寸（未缩放）。主窗口的布局间距/尺寸都从这里取，
# 由 _scale_bundle 统一乘缩放系数，避免界面代码里散落字面量。
LAYOUT = {
    "margin": 14,
    "section_spacing": 8,
    "row_spacing": 8,
    "sidebar_width": 260,
    "content_min_width": 360,
    "view_selector_width": 62,
    "window_button_width": 28,
    "schedule_panel_max_height": 164,
    "week_view_min_height": 180,
    "year_view_min_height": 220,
    "weather_min_width": 145,
    "attendance_status_min_height": 54,
    "focus_status_min_height": 50,
    "sidebar_margin": 16,
    "sidebar_spacing": 11,
    "sidebar_close_size": 32,
    "sidebar_button_min_height": 42,
    "sidebar_heading_spacing": 2,
    "sidebar_header_spacing": 10,
    "sidebar_grid_spacing": 8,
    # 天气卡
    "weather_nav_width": 28,
    "weather_action_width": 24,
    "weather_icon_width": 32,
    "weather_status_min_width": 90,
    "weather_row_spacing": 4,
    "weather_margin": 8,
    "weather_layout_spacing": 7,
    # 今日灵感卡
    "saying_quote_min_height": 52,
    "saying_refresh_height": 22,
    "saying_header_spacing": 6,
    "saying_body_margins": (11, 9, 11, 10),
    "saying_body_spacing": 4,
    # 日程面板
    "schedule_list_min_height": 46,
    "schedule_list_max_height": 120,
    "schedule_list_icon": (5, 18),
    "schedule_margin_h": 9,
    "schedule_margin_v": 8,
    "schedule_panel_spacing": 6,
}


@dataclass(frozen=True)
class LayoutMetrics:
    margin: int
    section_spacing: int
    row_spacing: int
    sidebar_width: int
    content_min_width: int
    view_selector_width: int
    window_button_width: int
    schedule_panel_max_height: int
    week_view_min_height: int
    year_view_min_height: int
    weather_min_width: int
    attendance_status_min_height: int
    focus_status_min_height: int
    sidebar_margin: int
    sidebar_spacing: int
    sidebar_close_size: int
    sidebar_button_min_height: int
    sidebar_heading_spacing: int
    sidebar_header_spacing: int
    sidebar_grid_spacing: int
    weather_nav_width: int
    weather_action_width: int
    weather_icon_width: int
    weather_status_min_width: int
    weather_row_spacing: int
    weather_margin: int
    weather_layout_spacing: int
    saying_quote_min_height: int
    saying_refresh_height: int
    saying_header_spacing: int
    saying_body_margins: tuple[int, int, int, int]
    saying_body_spacing: int
    schedule_list_min_height: int
    schedule_list_max_height: int
    schedule_list_icon: tuple[int, int]
    schedule_margin_h: int
    schedule_margin_v: int
    schedule_panel_spacing: int


@dataclass(frozen=True)
class QssSet:
    content_widget: str
    calendar: str
    nav_buttons: str
    today_button: str
    cal_title: str
    header_combo: str
    window_buttons: str
    tooltip: str
    content_widget_sidebar: str
    sidebar_panel: str
    sidebar_panel_flat: str
    sidebar_close: str
    header_separator: str
    sidebar_action: str
    sidebar_section_title: str
    sidebar_status: str
    sidebar_title: str
    sidebar_subtitle: str
    attendance_punch: str
    attendance_stats: str
    info_label: str
    menu: str
    message_info: str
    message_warn: str
    message_error: str
    dialog_base: str
    dialog_buttons: str
    dialog_buttons_wide: str
    dialog_inputs: str
    dialog_checkboxes: str
    dialog_groupbox: str
    dialog_slider: str
    dialog_list: str
    scrollbar: str
    schedule_panel: str
    sidebar_services: str
    weather_panel: str


@dataclass(frozen=True)
class DialogMetrics:
    new_size: tuple[int, int]
    manage_size: tuple[int, int]
    remind_size: tuple[int, int]
    picker_size: tuple[int, int]
    settings_size: tuple[int, int]
    margin: int
    spacing: int
    margin_wide: int
    spacing_wide: int
    title_font_size: int
    content_font_size: int
    btn_font_size: int
    qss_standard: str
    qss_manage: str
    qss_remind: str
    qss_picker: str
    qss_settings: str


@dataclass(frozen=True)
class ThemeBundle:
    name: str
    theme: Mapping[str, Any]
    resolver: ThemeResolver
    window: WindowMetrics
    fonts: FontSet
    calendar_colors: Mapping[str, QColor]
    calendar_metrics: CalendarMetrics
    layout: LayoutMetrics
    qss: QssSet
    dialog: DialogMetrics
    scale_factor: float = 1.0
