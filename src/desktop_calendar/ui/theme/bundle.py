# coding: utf-8
"""ThemeBundle 装配：把主题 dict 编译成控件可用的形态，并按比例缩放。"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from PyQt6.QtGui import QFont

from . import fonts, qss
from .metrics import (
    _CALENDAR_COLOR_KEYS,
    LAYOUT,
    CalendarMetrics,
    DialogMetrics,
    FontSet,
    LayoutMetrics,
    QssSet,
    ThemeBundle,
    WindowMetrics,
)
from .resolver import ThemeResolver

_QSS_PIXEL_SIZE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)px\b")


def normalize_ui_scale(scale: float) -> float:
    try:
        scale = float(scale)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("UI scale must be a finite number") from error
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("UI scale must be a positive finite number")
    return min(1.0, max(0.5, scale))


def _scaled_metric(value: int, scale: float) -> int:
    return 0 if value == 0 else max(1, round(value * scale))


def _scale_qss_pixels(stylesheet: str, scale: float) -> str:
    def replace(match: re.Match[str]) -> str:
        value = float(match.group(1)) * scale
        if value == 0:
            return "0px"
        return f"{value:.2f}".rstrip("0").rstrip(".") + "px"

    return _QSS_PIXEL_SIZE.sub(replace, stylesheet)


def _scale_bundle(bundle: ThemeBundle, scale: float) -> ThemeBundle:
    if scale == 1.0:
        return bundle

    def scale_font(font: QFont) -> QFont:
        result = QFont(font)
        point_size = font.pointSizeF()
        if point_size > 0:
            result.setPointSizeF(max(1.0, point_size * scale))
        return result

    window = WindowMetrics(
        width=_scaled_metric(bundle.window.width, scale),
        height=_scaled_metric(bundle.window.height, scale),
        corner_radius=_scaled_metric(bundle.window.corner_radius, scale),
        shadow_size=_scaled_metric(bundle.window.shadow_size, scale),
        shadow_color=bundle.window.shadow_color,
        nav_btn_width=_scaled_metric(bundle.window.nav_btn_width, scale),
        info_label_height=_scaled_metric(bundle.window.info_label_height, scale),
    )
    fonts_set = FontSet(
        global_=scale_font(bundle.fonts.global_),
        calendar_day=scale_font(bundle.fonts.calendar_day),
        calendar_small=scale_font(bundle.fonts.calendar_small),
    )
    calendar_metrics = CalendarMetrics(
        cell_radius=_scaled_metric(bundle.calendar_metrics.cell_radius, scale),
        dot_size=_scaled_metric(bundle.calendar_metrics.dot_size, scale),
        tag_size=_scaled_metric(bundle.calendar_metrics.tag_size, scale),
    )
    layout_metrics = LayoutMetrics(
        **{
            field: (
                tuple(_scaled_metric(item, scale) for item in value)
                if isinstance(value, tuple)
                else _scaled_metric(value, scale)
            )
            for field, value in vars(bundle.layout).items()
        }
    )
    qss_set = QssSet(
        **{field: _scale_qss_pixels(value, scale) for field, value in vars(bundle.qss).items()}
    )
    dialog = bundle.dialog
    dialog_metrics = DialogMetrics(
        new_size=tuple(_scaled_metric(value, scale) for value in dialog.new_size),
        manage_size=tuple(_scaled_metric(value, scale) for value in dialog.manage_size),
        remind_size=tuple(_scaled_metric(value, scale) for value in dialog.remind_size),
        picker_size=tuple(_scaled_metric(value, scale) for value in dialog.picker_size),
        settings_size=tuple(_scaled_metric(value, scale) for value in dialog.settings_size),
        margin=_scaled_metric(dialog.margin, scale),
        spacing=_scaled_metric(dialog.spacing, scale),
        margin_wide=_scaled_metric(dialog.margin_wide, scale),
        spacing_wide=_scaled_metric(dialog.spacing_wide, scale),
        title_font_size=_scaled_metric(dialog.title_font_size, scale),
        content_font_size=_scaled_metric(dialog.content_font_size, scale),
        btn_font_size=_scaled_metric(dialog.btn_font_size, scale),
        qss_standard=_scale_qss_pixels(dialog.qss_standard, scale),
        qss_manage=_scale_qss_pixels(dialog.qss_manage, scale),
        qss_remind=_scale_qss_pixels(dialog.qss_remind, scale),
        qss_picker=_scale_qss_pixels(dialog.qss_picker, scale),
        qss_settings=_scale_qss_pixels(dialog.qss_settings, scale),
    )
    return ThemeBundle(
        name=bundle.name,
        theme=bundle.theme,
        resolver=bundle.resolver,
        window=window,
        fonts=fonts_set,
        calendar_colors=bundle.calendar_colors,
        calendar_metrics=calendar_metrics,
        layout=layout_metrics,
        qss=qss_set,
        dialog=dialog_metrics,
        scale_factor=scale,
    )


def build_bundle(
    name: str,
    theme: Mapping[str, Any],
    *,
    scale: float = 1.0,
) -> ThemeBundle:
    scale = normalize_ui_scale(scale)
    r = ThemeResolver(theme)

    # 对话框里的右键菜单 / 弹出菜单默认是原生样式，一并挂上统一的菜单 QSS
    dlg_base = qss.dialog_base(r) + qss.menu(r)
    dlg_buttons = qss.dialog_buttons(r)
    dlg_buttons_wide = qss.dialog_buttons(
        r, min_width=r.int("btn_min_width_wide"), padding_v=7, padding_h=18
    )
    dlg_buttons_manage = qss.dialog_buttons(
        r, min_width=r.int("btn_min_width"), padding_v=7, padding_h=10
    )
    dlg_inputs = qss.dialog_inputs(r)
    dlg_checkboxes = qss.dialog_checkboxes(r)
    dlg_groupbox = qss.dialog_groupbox(r)
    dlg_slider = qss.dialog_slider(r)
    dlg_list = qss.dialog_list(r)
    scrollbar_qss = qss.scrollbar(r)
    sidebar_services_qss = qss.sidebar_services(r)
    weather_panel_qss = qss.weather_panel(r)

    bundle = ThemeBundle(
        name=name,
        theme=r.theme,
        resolver=r,
        window=WindowMetrics(
            width=r.int("window_width"),
            height=r.int("window_height"),
            corner_radius=r.int("corner_radius"),
            shadow_size=r.int("shadow_size"),
            shadow_color=r.qcolor("shadow_color"),
            nav_btn_width=r.int("nav_btn_width"),
            info_label_height=r.int("info_label_height"),
        ),
        fonts=FontSet(
            global_=fonts.global_font(r),
            calendar_day=fonts.calendar_day(r),
            calendar_small=fonts.calendar_small(r),
        ),
        calendar_colors=MappingProxyType({k: r.qcolor(k) for k in _CALENDAR_COLOR_KEYS}),
        calendar_metrics=CalendarMetrics(
            cell_radius=r.int("cell_corner_radius"),
            dot_size=r.int("dot_size"),
            tag_size=r.int("tag_size"),
        ),
        layout=LayoutMetrics(**LAYOUT),
        qss=QssSet(
            content_widget=qss.content_widget(r),
            calendar=qss.calendar(r),
            nav_buttons=qss.nav_buttons(r),
            today_button=qss.today_button(r),
            cal_title=qss.cal_title(r),
            header_combo=qss.header_combo(r),
            window_buttons=qss.window_buttons(r),
            tooltip=qss.tooltip(r),
            content_widget_sidebar=qss.content_widget_with_sidebar(r),
            sidebar_panel=qss.sidebar_panel(r),
            sidebar_panel_flat=qss.sidebar_panel(r, rounded=False),
            sidebar_close=qss.sidebar_close_button(r),
            header_separator=qss.header_separator(r),
            sidebar_action=qss.sidebar_action_button(r),
            sidebar_section_title=qss.sidebar_section_title(r),
            sidebar_status=qss.sidebar_status_card(r),
            sidebar_title=qss.sidebar_title(r),
            sidebar_subtitle=qss.sidebar_subtitle(r),
            attendance_punch=qss.attendance_punch_button(r),
            attendance_stats=qss.attendance_stats_link(r),
            info_label=qss.info_label(r),
            menu=qss.menu(r),
            message_info=qss.message_box(r, "info"),
            message_warn=qss.message_box(r, "warn"),
            message_error=qss.message_box(r, "error"),
            dialog_base=dlg_base,
            dialog_buttons=dlg_buttons,
            dialog_buttons_wide=dlg_buttons_wide,
            dialog_inputs=dlg_inputs,
            dialog_checkboxes=dlg_checkboxes,
            dialog_groupbox=dlg_groupbox,
            dialog_slider=dlg_slider,
            dialog_list=dlg_list,
            scrollbar=scrollbar_qss,
            schedule_panel=qss.schedule_panel(r),
            sidebar_services=sidebar_services_qss,
            weather_panel=weather_panel_qss,
        ),
        dialog=DialogMetrics(
            new_size=(r.int("dialog_new_width"), r.int("dialog_new_height")),
            manage_size=(r.int("dialog_manage_width"), r.int("dialog_manage_height")),
            remind_size=(r.int("dialog_remind_width"), r.int("dialog_remind_height")),
            picker_size=(r.int("dialog_picker_width"), r.int("dialog_picker_height")),
            settings_size=(r.int("dialog_settings_width"), r.int("dialog_settings_height")),
            margin=r.int("dialog_margin"),
            spacing=r.int("dialog_spacing"),
            margin_wide=r.int("dialog_margin_wide"),
            spacing_wide=r.int("dialog_spacing_wide"),
            title_font_size=r.int("dialog_title_font_size"),
            content_font_size=r.int("dialog_content_font_size"),
            btn_font_size=r.int("dialog_btn_font_size"),
            # 拼装时加上 scrollbar，确保原生带有滚动条的视图风格统一
            qss_standard=(dlg_base + dlg_buttons + dlg_inputs + dlg_checkboxes + scrollbar_qss),
            qss_manage=(dlg_base + dlg_buttons_manage + dlg_list + scrollbar_qss),
            qss_remind=(dlg_base + dlg_buttons_wide),
            # ScheduleDialog 也用 qss_picker，但里面是 QTableWidget，
            # 所以把列表/表格样式一并拼上
            qss_picker=(
                dlg_base + dlg_buttons + dlg_inputs + dlg_checkboxes + dlg_list + scrollbar_qss
            ),
            qss_settings=(
                dlg_base + dlg_buttons + dlg_checkboxes + dlg_groupbox + dlg_slider + scrollbar_qss
            ),
        ),
    )
    return _scale_bundle(bundle, scale)
