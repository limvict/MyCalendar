# coding: utf-8
"""对话框 QSS：基础容器、按钮、输入控件、分组、滑块、列表与消息框。"""

from __future__ import annotations

from ..resolver import ThemeResolver
from .palette import (
    MessageKind,
    _arrow_svg,
    _ensure_contrast,
    _get_safe_palette,
    _hover_accent,
    _image,
    _is_dark,
    _svg_uri,
)

# 每种消息框对应的一组主题键：(底色, hover 底色, 文字色)
_MSG_KEYS: dict[MessageKind, tuple[str, str, str]] = {
    "info": ("msg_info_btn", "msg_info_btn_hover", "msg_info_btn_text"),
    "warn": ("msg_warn_btn", "msg_warn_btn_hover", "msg_warn_btn_text"),
    "error": ("msg_error_btn", "msg_error_btn_hover", "msg_error_btn_text"),
}


def message_box(r: ThemeResolver, kind: MessageKind) -> str:
    p = _get_safe_palette(r)
    bg_key, hover_key, text_key = _MSG_KEYS[kind]
    return f"""
    QMessageBox {{
        background-color: {p.bg_main};
    }}
    QMessageBox QLabel {{
        color: {p.text_main};
        background: transparent;
        font-size: {r.px("font_size")};
    }}
    QMessageBox QPushButton {{
        min-width: {r.px("btn_min_width_narrow")};
        padding: {r.px("btn_padding_v")} {r.px("btn_padding_h")};
        border: none;
        border-radius: {r.px("btn_radius_small")};
        color: {r.color(text_key) or p.text_main};
        font-size: {r.px("dialog_btn_font_size")};
        background: {r.color(bg_key) or p.accent};
    }}
    QMessageBox QPushButton:hover {{ background: {r.color(hover_key)}; }}
    """


# ===================== 对话框 =====================
def dialog_base(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    return f"""
    QDialog {{
        background-color: {p.bg_main};
    }}
    /* 【关键修复】强行消除 QScrollArea 内部白底 */
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background-color: transparent;
        border: none;
    }}
    QLabel {{
        font-size: {r.px("font_size")};
        color: {p.text_main};
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
    p = _get_safe_palette(r)
    mw = min_width if min_width is not None else r.int("btn_min_width_narrow")

    if padding_v is None:
        pv = r.int("btn_padding_v")
        if _is_dark(r):
            pv = max(3, pv - 2)
    else:
        pv = padding_v
    ph = padding_h if padding_h is not None else r.int("btn_padding_h")

    return f"""
    QPushButton {{
        min-width: {mw}px;
        padding: {pv}px {ph}px;
        background: {r.color("dialog_btn_bg") or p.bg_input};
        color: {p.text_main};
        border: 1px solid {p.border};
        border-radius: {r.px("btn_radius_small")};
        font-size: {r.px("dialog_btn_font_size")};
    }}
    QPushButton:hover {{
        background: {r.color("dialog_btn_hover")};
        border-color: {_hover_accent(r)};
    }}
    QPushButton:pressed {{
        background: {r.color("dialog_btn_pressed")};
        border-color: {_hover_accent(r)};
    }}
    """


def dialog_inputs(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    arrow_down = _arrow_svg(p.text_input, down=True)
    arrow_up = _arrow_svg(p.text_input, down=False)

    return f"""
    QLineEdit, QComboBox, QAbstractSpinBox {{
        padding: 6px 8px;
        min-height: 18px;
        border: 1px solid {p.border};
        border-radius: {r.px("input_radius")};
        background: {p.bg_input};
        color: {p.text_input};
        font-size: {r.px("font_size")};
    }}
    QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover {{
        border: 1px solid {_hover_accent(r)};
    }}
    QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{
        border: 1px solid {_hover_accent(r)};
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
        {_image(arrow_down)}
        width: 10px;
        height: 6px;
    }}

    QComboBox QAbstractItemView {{
        border: 1px solid {p.border};
        border-radius: {r.px("input_radius")};
        background-color: {p.bg_input};
        color: {p.text_input};
        selection-background-color: {p.accent};
        selection-color: {_ensure_contrast(p.accent, p.text_input)};
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        padding: 6px 8px;
        min-height: 20px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background-color: {r.color("menu_hover")};
    }}

    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        subcontrol-origin: border;
        width: 20px;
        background: transparent;
        border-left: 1px solid {p.border};
    }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
        background: {r.color("btn_hover")};
    }}
    QAbstractSpinBox::up-arrow {{
        {_image(arrow_up)}
        width: 8px;
        height: 5px;
    }}
    QAbstractSpinBox::down-arrow {{
        {_image(arrow_down)}
        width: 8px;
        height: 5px;
    }}
    """


def dialog_checkboxes(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)

    # 打钩的颜色取强调色或背景色的对比色
    check_color = _ensure_contrast(p.accent, p.bg_main)
    check_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{check_color}" stroke-width="3" stroke-linecap="round" '
        'stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'
    )
    check_uri = _svg_uri(check_svg)

    return f"""
    QCheckBox, QRadioButton {{
        font-size: {r.px("font_size")};
        color: {p.text_main};
        spacing: 8px;
        padding: 6px 2px;
    }}

    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {p.border};
        background: {p.bg_input};
    }}
    QCheckBox::indicator:hover {{
        border-color: {_hover_accent(r)};
    }}
    QCheckBox::indicator:checked {{
        border-color: {p.accent};
        background: {p.accent};
        {_image(check_uri)}
    }}

    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 8px;
        border: 1px solid {p.border};
        background: {p.bg_input};
    }}
    QRadioButton::indicator:hover {{
        border-color: {_hover_accent(r)};
    }}
    QRadioButton::indicator:checked {{
        border: 5px solid {p.accent};
        background: {p.bg_input};
    }}

    /* 选中时文字保持清晰，绝不改变颜色 */
    QCheckBox:checked, QRadioButton:checked {{
        font-weight: bold;
        color: {p.text_main};
    }}
    QCheckBox:disabled, QRadioButton:disabled {{
        color: {p.border};
    }}
    """


def dialog_groupbox(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    return f"""
    QGroupBox {{
        font-size: {r.px("dialog_content_font_size")};
        font-weight: bold;
        color: {p.text_main};
        border: 1px solid {p.border};
        border-radius: {r.px("btn_radius")};
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
        color: {p.text_main};
        background-color: {p.bg_main};
    }}
    """


def dialog_slider(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    hs = r.int("slider_handle_size")
    groove_h = r.px("slider_groove_height")
    return f"""
    QSlider::handle:horizontal, QSlider::handle:vertical {{
        background: {p.text_main};
        border: 2px solid {p.bg_main};
        border-radius: {r.px("slider_handle_radius")};
        width: {hs}px;
        height: {hs}px;
        margin: -4px 0;
    }}
    QSlider::groove:horizontal, QSlider::groove:vertical {{
        background: {p.bg_input};
        border: 1px solid {p.border};
        border-radius: {r.px("slider_groove_radius")};
    }}
    QSlider::groove:horizontal {{
        height: {groove_h};
    }}
    QSlider::groove:vertical {{
        width: {groove_h};
    }}
    QSlider::sub-page:horizontal, QSlider::sub-page:vertical {{
        background: {p.accent};
        border-radius: {r.px("slider_groove_radius")};
    }}
    """


def dialog_list(r: ThemeResolver) -> str:
    p = _get_safe_palette(r)
    check_color = _ensure_contrast(p.accent, p.bg_input)
    check_uri = _svg_uri(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{check_color}" stroke-width="3" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<polyline points="20 6 9 17 4 12"/></svg>'
    )
    return f"""
    QListWidget {{
        background: {p.bg_input};
        border: 1px solid {p.border};
        border-radius: {r.px("btn_radius_small")};
        padding: 4px;
        color: {p.text_input};
    }}
    QListWidget::item {{
        padding: 4px;
        border-radius: {r.px("btn_radius_small")};
    }}
    QListWidget::item:hover {{
        background: {r.color("menu_hover")};
    }}
    QListWidget::item:selected {{
        background: {p.accent};
        color: {_ensure_contrast(p.accent, p.text_input)};
    }}
    /* 表格（如日程管理）不写同样会回落成原生白底 */
    QTableWidget, QTableView {{
        background: {p.bg_input};
        alternate-background-color: {p.bg_main};
        border: 1px solid {p.border};
        border-radius: {r.px("btn_radius_small")};
        gridline-color: {p.border};
        color: {p.text_input};
        selection-background-color: {p.accent};
        selection-color: {_ensure_contrast(p.accent, p.text_input)};
        outline: none;
    }}
    QTableWidget::item, QTableView::item {{
        padding: 4px;
    }}
    QTableWidget::item:hover, QTableView::item:hover {{
        background: {r.color("menu_hover")};
    }}
    QTableWidget::indicator, QTableView::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 3px;
        border: 1px solid {p.border};
        background: {p.bg_input};
    }}
    QTableWidget::indicator:checked, QTableView::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
        {_image(check_uri)}
    }}
    QHeaderView {{
        background: {p.bg_main};
        border: none;
    }}
    QHeaderView::section {{
        background: {p.bg_main};
        color: {p.text_input};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 6px 4px;
        font-weight: 600;
    }}
    QTableCornerButton::section {{
        background: {p.bg_main};
        border: none;
        border-right: 1px solid {p.border};
        border-bottom: 1px solid {p.border};
    }}
    """
