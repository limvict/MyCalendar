# coding: utf-8
"""ThemeBundle + build_bundle：唯一把 dict 转成控件形态的地方。"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from PyQt6.QtGui import QColor, QFont

from . import fonts, qss
from .resolver import ThemeResolver

_CALENDAR_COLOR_KEYS = (
    "weekend_header_red", "calendar_header_text",
    "adjacent_cell_bg", "adjacent_text_color",
    "today_bg", "select_bg", "normal_cell_bg",
    "today_text_color", "select_text_color",
    "festival_red", "workday_orange",
    "normal_num_color", "memorial_orange",
    "normal_lunar_color", "tag_bg", "tag_text_color",
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


@dataclass(frozen=True)
class QssSet:
    content_widget: str
    calendar: str
    nav_buttons: str
    cal_title: str
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
    theme: Mapping[str, Any]        # 只读快照，供仍用 dict 的旧接口读取
    resolver: ThemeResolver
    window: WindowMetrics
    fonts: FontSet
    calendar_colors: Mapping[str, QColor]
    calendar_metrics: CalendarMetrics
    qss: QssSet
    dialog: DialogMetrics


def build_bundle(name: str, theme: Mapping[str, Any]) -> ThemeBundle:
    # ThemeResolver 内部会 dict(theme) 做防御性拷贝，并持有可变的
    # _theme 快照；对外通过只读属性 theme 暴露 MappingProxyType 视图。
    # 这样 bundle.theme 与 resolver 的 color()/qcolor() 基于同一数据源，
    # 外部对 bundle.theme 的任何写入都会抛 TypeError，也不会出现
    # "改了 theme 但 _qcolor 缓存未失效"导致的不一致。
    r = ThemeResolver(theme)

    dlg_base = qss.dialog_base(r)
    dlg_buttons = qss.dialog_buttons(r)
    dlg_buttons_wide = qss.dialog_buttons(
        r,
        min_width=r.int("btn_min_width_wide"),
        padding_v=7,
        padding_h=18,
    )
    dlg_buttons_manage = qss.dialog_buttons(
        r, min_width=r.int("btn_min_width"), padding_v=7, padding_h=10)
    dlg_inputs = qss.dialog_inputs(r)
    dlg_checkboxes = qss.dialog_checkboxes(r)
    dlg_groupbox = qss.dialog_groupbox(r)
    dlg_slider = qss.dialog_slider(r)
    dlg_list = qss.dialog_list(r)

    return ThemeBundle(
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
        # dict 字段本身也要只读，否则 frozen dataclass 只冻结了"字段指向"，
        # 外部仍可修改字典内容。
        calendar_colors=MappingProxyType(
            {k: r.qcolor(k) for k in _CALENDAR_COLOR_KEYS}),
        calendar_metrics=CalendarMetrics(
            cell_radius=r.int("cell_corner_radius"),
            dot_size=r.int("dot_size"),
            tag_size=r.int("tag_size"),
        ),
        qss=QssSet(
            content_widget=qss.content_widget(r),
            calendar=qss.calendar(r),
            nav_buttons=qss.nav_buttons(r),
            cal_title=qss.cal_title(r),
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
            qss_standard=(dlg_base + dlg_buttons + dlg_inputs + dlg_checkboxes),
            qss_manage=(dlg_base + dlg_buttons_manage + dlg_list),
            qss_remind=(dlg_base + dlg_buttons_wide),
            qss_picker=(dlg_base + dlg_buttons + dlg_inputs),
            qss_settings=(dlg_base + dlg_buttons + dlg_inputs + dlg_checkboxes
                          + dlg_groupbox + dlg_slider),
        ),
    )