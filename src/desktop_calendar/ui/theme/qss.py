# coding: utf-8
"""所有 QSS 纯函数：ThemeResolver → str。不接触 QWidget。"""
from __future__ import annotations

import base64
from typing import Literal

from .resolver import ThemeResolver

MessageKind = Literal["info", "warn", "error"]

_GENERIC_FONT_FAMILIES = {
    "serif", "sans-serif", "monospace", "cursive",
    "fantasy", "system-ui",
}


def _font_family(r: ThemeResolver) -> str:
    families = [f.strip() for f in r.str("font_family").split(",") if f.strip()]
    if not families:
        return "sans-serif"
    parts = [
        f if f.lower() in _GENERIC_FONT_FAMILIES else f'"{f}"'
        for f in families
    ]
    return ", ".join(parts)


def _is_dark(r: ThemeResolver) -> bool:
    return bool(getattr(r, "is_dark", False))


def _svg_uri(svg: str) -> str:
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"url(data:image/svg+xml;base64,{b64})"


def _arrow_svg(color: str, *, down: bool) -> str:
    d = "M0 0 L5 6 L10 0 Z" if down else "M0 6 L5 0 L10 6 Z"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" '
        f'viewBox="0 0 10 6"><path d="{d}" fill="{color}"/></svg>'
    )
    return _svg_uri(svg)


# ===================== 主窗口 =====================
def content_widget(r: ThemeResolver) -> str:
    return f"""
    QWidget#content_widget {{
        background-color: {r.color('bg_main')};
        border-radius: {r.px('corner_radius')};
    }}
    """


def calendar(r: ThemeResolver) -> str:
    return f"""
    QCalendarWidget {{
        background-color: {r.color('bg_main')};
        font-family: {_font_family(r)};
    }}

    QCalendarWidget QWidget {{
        background-color: {r.color('bg_main')};
    }}

    QCalendarWidget QTableView {{
        background-color: {r.color('bg_main')};
        alternate-background-color: {r.color('bg_main')};
        selection-background-color: transparent;
        selection-color: transparent;
        gridline-color: transparent;
        border: none;
    }}

    QCalendarWidget QHeaderView {{
        background-color: {r.color('calendar_header_bg')};
        border: none;
        min-height: 32px;
    }}

    QCalendarWidget QHeaderView::section {{
        background-color: {r.color('calendar_header_bg')};
        border: 1px solid {r.color('calendar_header_bg')};
        padding: 8px 0px;
        font-family: {_font_family(r)};
        font-size: {r.px('week_header_font_size')};
    }}
    """


def info_label(r: ThemeResolver) -> str:
    # padding 与 nav_buttons / today_button 一致（6px），
    # 保证底栏 label 文字与按钮文字左缘精确对齐。
    return (
        f"QLabel {{ font-size: {r.px('info_label_font_size')};"
        f" font-family: {_font_family(r)};"
        f" color: {r.color('date_text_color')};"
        f" padding: 6px; background: transparent; }}"
    )


def nav_buttons(r: ThemeResolver) -> str:
    return f"""
    QPushButton {{
        background: {r.color('btn_bg')};
        color: {r.color('btn_text')};
        border: none;
        border-radius: {r.px('btn_radius')};
        padding: 6px;
        font-size: {r.px('font_size')};
    }}
    QPushButton:hover {{ background: {r.color('btn_hover')}; }}
    QPushButton:pressed {{ background: {r.color('btn_pressed')}; }}
    """


def today_button(r: ThemeResolver) -> str:
    return f"""
    QPushButton#today_btn {{
        background: {r.color('today_bg')};
        color: {r.color('today_text_color')};
        border: none;
        border-radius: {r.px('btn_radius')};
        padding: 6px 14px;
        font-size: {r.px('font_size')};
    }}
    QPushButton#today_btn:hover {{ background: {r.color('btn_hover')}; }}
    QPushButton#today_btn:pressed {{ background: {r.color('btn_pressed')}; }}
    """


def cal_title(r: ThemeResolver) -> str:
    return (
        f"font-size: {r.px('cal_title_font_size')}; font-weight: 500;"
        f"background: transparent; color: {r.color('date_text_color')};"
    )


# ===================== 菜单 =====================
def menu(r: ThemeResolver) -> str:
    return f"""
    QMenu {{
        background-color: {r.color('menu_bg')};
        border: 1px solid {r.color('menu_border')};
        border-radius: {r.px('menu_radius')};
        padding: 6px;
    }}
    QMenu::item {{
        padding: 6px 20px;
        background: transparent;
        border-radius: {r.px('btn_radius_small')};
        color: {r.color('menu_text')};
    }}
    QMenu::item:selected {{ background: {r.color('menu_hover')}; }}
    """


# ===================== 消息框 =====================
_MSG_KEYS: dict[MessageKind, tuple[str, str, str]] = {
    "info":  ("msg_info_btn",  "msg_info_btn_hover",  "msg_info_btn_text"),
    "warn":  ("msg_warn_btn",  "msg_warn_btn_hover",  "msg_warn_btn_text"),
    "error": ("msg_error_btn", "msg_error_btn_hover", "msg_error_btn_text"),
}


def message_box(r: ThemeResolver, kind: MessageKind) -> str:
    bg_key, hover_key, text_key = _MSG_KEYS[kind]
    return f"""
    QMessageBox {{
        background-color: {r.color('msg_box_bg')};
        border-radius: {r.px('menu_radius')};
    }}
    QMessageBox QLabel {{
        color: {r.color('dialog_text')};
        background: transparent;
        font-size: {r.px('font_size')};
    }}
    QMessageBox QPushButton {{
        min-width: {r.px('btn_min_width_narrow')};
        padding: {r.px('btn_padding_v')} {r.px('btn_padding_h')};
        border: none;
        border-radius: {r.px('btn_radius_small')};
        color: {r.color(text_key)};
        font-size: {r.px('dialog_btn_font_size')};
        background: {r.color(bg_key)};
    }}
    QMessageBox QPushButton:hover {{ background: {r.color(hover_key)}; }}
    """


# ===================== 对话框 =====================
def dialog_base(r: ThemeResolver) -> str:
    return f"""
    QDialog {{
        background-color: {r.color('bg_main')};
        border-radius: {r.px('dialog_radius')};
    }}
    QLabel {{
        font-size: {r.px('font_size')};
        color: {r.color('dialog_text')};
        background: transparent;
    }}
    """


def dialog_buttons(
    r: ThemeResolver,
    *,
    min_width: int | None = None,
    padding_v: int | None = None,
    padding_h: int | None = None,
) -> str:
    compact = _is_dark(r)
    mw = min_width if min_width is not None else r.int("btn_min_width_narrow")
    pv = padding_v if padding_v is not None else r.int("btn_padding_v")
    if compact:
        pv = max(3, pv - 2)
    ph = padding_h if padding_h is not None else r.int("btn_padding_h")
    return f"""
    QPushButton {{
        min-width: {mw}px;
        padding: {pv}px {ph}px;
        background: {r.color('dialog_btn_bg')};
        color: {r.color('dialog_btn_text')};
        border: none;
        border-radius: {r.px('btn_radius_small')};
        font-size: {r.px('dialog_btn_font_size')};
    }}
    QPushButton:hover {{ background: {r.color('dialog_btn_hover')}; }}
    QPushButton:pressed {{ background: {r.color('dialog_btn_pressed')}; }}
    """


def dialog_inputs(r: ThemeResolver) -> str:
    border = r.color("border_color")
    dialog_text = r.color("dialog_text")
    input_bg = r.color("input_bg")
    focus_border = r.color("msg_info_btn")
    arrow_down = _arrow_svg(dialog_text, down=True)
    arrow_up = _arrow_svg(dialog_text, down=False)
    hover_bg = r.color("menu_hover")
    select_bg = r.color("msg_info_btn")
    select_text = r.color("msg_info_btn_text")

    return f"""
    QLineEdit, QComboBox, QSpinBox {{
        padding: 6px 8px;
        min-height: 18px;
        border: 1px solid {border};
        border-radius: {r.px('input_radius')};
        background: {input_bg};
        color: {dialog_text};
        font-size: {r.px('font_size')};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {focus_border};
    }}

    QComboBox {{
        padding-right: 24px;
    }}

    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 24px;
        border: none;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: {arrow_down};
        width: 10px;
        height: 6px;
    }}

    QComboBox QAbstractItemView {{
        border: 1px solid {border};
        border-radius: {r.px('input_radius')};
        background-color: {input_bg};
        color: {dialog_text};
        selection-background-color: {select_bg};
        selection-color: {select_text};
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        padding: 6px 8px;
        min-height: 20px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background-color: {hover_bg};
    }}

    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border;
        width: 20px;
        background: transparent;
        border-left: 1px solid {border};
    }}
    QSpinBox::up-arrow {{
        image: {arrow_up};
        width: 8px;
        height: 5px;
    }}
    QSpinBox::down-arrow {{
        image: {arrow_down};
        width: 8px;
        height: 5px;
    }}
    """


def dialog_checkboxes(r: ThemeResolver) -> str:
    accent = r.color("msg_info_btn")
    accent_hover = r.color("msg_info_btn_hover")
    border = r.color("btn_pressed")
    input_bg = r.color("input_bg")
    dialog_text = r.color("dialog_text")
    check_color = r.color("msg_info_btn_text")

    check_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{check_color}" stroke-width="3" stroke-linecap="round" '
        'stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
    )
    check_uri = _svg_uri(check_svg)

    return f"""
    QCheckBox, QRadioButton {{
        font-size: {r.px('font_size')};
        color: {dialog_text};
        spacing: 8px;
        padding: 6px 2px;
    }}

    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 2px solid {border};
        background: {input_bg};
    }}
    QCheckBox::indicator:hover {{
        border-color: {accent};
    }}
    QCheckBox::indicator:checked {{
        border-color: {accent};
        background: {accent};
        image: {check_uri};
    }}
    QCheckBox::indicator:checked:hover {{
        border-color: {accent_hover};
        background: {accent_hover};
    }}
    QCheckBox::indicator:disabled {{
        border-color: {border};
        background: transparent;
    }}
    QCheckBox::indicator:checked:disabled {{
        border-color: {border};
        background: {border};
    }}

    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 8px;
        border: 2px solid {border};
        background: {input_bg};
    }}
    QRadioButton::indicator:hover {{
        border-color: {accent};
    }}
    QRadioButton::indicator:checked {{
        border: 5px solid {accent};
        background: {input_bg};
    }}
    QRadioButton::indicator:checked:hover {{
        border-color: {accent_hover};
    }}
    QRadioButton::indicator:disabled {{
        border-color: {border};
        background: transparent;
    }}
    QRadioButton::indicator:checked:disabled {{
        border-color: {border};
        background: {input_bg};
    }}

    QCheckBox:checked, QRadioButton:checked {{
        font-weight: bold;
        color: {accent};
    }}
    """


def dialog_groupbox(r: ThemeResolver) -> str:
    return f"""
    QGroupBox {{
        font-size: {r.px('dialog_content_font_size')};
        font-weight: bold;
        color: {r.color('dialog_text')};
        border: 1px solid {r.color('border_color')};
        border-radius: {r.px('btn_radius')};
        margin-top: 16px;
        padding-top: 20px;
        padding-left: 14px;
        padding-right: 14px;
        padding-bottom: 14px;
    }}

    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        margin-left: 12px;
        padding: 0 6px;
        color: {r.color('dialog_text')};
        background-color: {r.color('bg_main')};
    }}
    """


def dialog_slider(r: ThemeResolver) -> str:
    hs = r.int("slider_handle_size")
    return f"""
    QSlider::handle:horizontal {{
        background: {r.color('slider_handle')};
        border-radius: {r.px('slider_handle_radius')};
        width: {hs}px;
        height: {hs}px;
    }}
    QSlider::groove:horizontal {{
        height: {r.px('slider_groove_height')};
        background: {r.color('slider_groove')};
        border-radius: {r.px('slider_groove_radius')};
    }}
    """


def dialog_list(r: ThemeResolver) -> str:
    return f"""
    QListWidget {{
        background: {r.color('input_bg')};
        border: 1px solid {r.color('border_color')};
        border-radius: {r.px('btn_radius_small')};
        padding: 4px;
    }}
    QListWidget::item {{
        color: {r.color('dialog_text')};
        padding: 4px;
        border-radius: {r.px('btn_radius_small')};
    }}
    QListWidget::item:hover {{ background: {r.color('menu_hover')}; }}
    QListWidget::item:selected {{
        background: {r.color('dialog_btn_bg')};
        color: {r.color('dialog_btn_text')};
    }}
    """