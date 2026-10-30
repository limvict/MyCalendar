# coding: utf-8
"""所有 QSS 纯函数：ThemeResolver → str。不接触 QWidget。"""
from __future__ import annotations

from typing import Literal

from .resolver import ThemeResolver

MessageKind = Literal["info", "warn", "error"]


def _font_family(r: ThemeResolver) -> str:
    families = [f.strip() for f in r.str("font_family").split(",") if f.strip()]
    return ", ".join(f'"{f}"' for f in families)


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
    QCalendarWidget QTableView {{
        background-color: {r.color('bg_main')};
        selection-background-color: transparent;
        selection-color: transparent;
        gridline-color: transparent;
    }}
    QCalendarWidget QTableView QHeaderView::section {{
        background-color: {r.color('calendar_header_bg')};
        color: {r.color('calendar_header_text')};
        border: none;
        padding: 5px 0px;
        font-size: {r.px('week_header_font_size')};
    }}
    """


def nav_buttons(r: ThemeResolver) -> str:
    return f"""
    QPushButton {{
        background: {r.color('btn_bg')};
        color: {r.color('btn_text')};
        border: none;
        border-radius: 10px;
        padding: 6px;
        font-size: {r.px('font_size')};
    }}
    QPushButton:hover {{ background: {r.color('btn_hover')}; }}
    QPushButton:pressed {{ background: {r.color('btn_pressed')}; }}
    """


def cal_title(r: ThemeResolver) -> str:
    return (
        f"font-size: {r.px('cal_title_font_size')}; font-weight: 500;"
        f"background: transparent; color: {r.color('date_text_color')};"
    )


def info_label(r: ThemeResolver) -> str:
    return (
        f"QLabel {{ color: {r.color('date_text_color')};"
        f"font-size: {r.px('info_label_font_size')}; padding: 4px; }}"
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
_MSG_KEYS: dict[MessageKind, tuple[str, str]] = {
    "info":  ("msg_info_btn",  "msg_info_btn_hover"),
    "warn":  ("msg_warn_btn",  "msg_warn_btn_hover"),
    "error": ("msg_error_btn", "msg_error_btn_hover"),
}


def message_box(r: ThemeResolver, kind: MessageKind) -> str:
    bg_key, hover_key = _MSG_KEYS[kind]
    return f"""
    QMessageBox {{
        background-color: {r.color('msg_box_bg')};
        /* 顶层窗口的圆角需 frameless + translucent 才生效，否则仅作声明。 */
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
        color: {r.color('dialog_btn_text')};
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
        /* 顶层窗口的圆角需 frameless + translucent 才生效，否则仅作声明。 */
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
    # 深色模式下，按钮不要那么大，否则很笨重
    mw = min_width if min_width is not None else r.int("btn_min_width_narrow")
    pv = padding_v if padding_v is not None else 5
    ph = padding_h if padding_h is not None else 12
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
    return f"""
    QLineEdit, QComboBox, QSpinBox {{
        padding: 4px 8px;
        border: 1px solid {r.color('border_color')};
        border-radius: {r.px('input_radius')};
        background: {r.color('input_bg')};
        color: {r.color('dialog_text')};
        font-size: {r.px('font_size')};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {r.color('solar_term_text_color')};
    }}
    /* Qt QSS 不支持用 border 拼三角形的 CSS hack；这里只控制下拉区域宽度，
       箭头交由系统绘制。如需自定义箭头，请配置 down-arrow 的 image 资源。 */
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 20px;
        border-left-width: 0px;
        border-top-right-radius: {r.px('input_radius')};
        border-bottom-right-radius: {r.px('input_radius')};
    }}
    """


def dialog_checkboxes(r: ThemeResolver) -> str:
    return f"""
    QCheckBox, QRadioButton {{
        font-size: {r.px('font_size')};
        color: {r.color('dialog_text')};
        spacing: 8px;
        padding: 2px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {r.color('border_color')};
        background: {r.color('input_bg')};
    }}
    /* 无勾选图片资源时，用实心色块 + 高对比边框强化选中态，
       避免仅靠背景色难以辨识（尤其深色主题）。 */
    QCheckBox::indicator:checked {{
        background: {r.color('dialog_btn_bg')};
        border: 2px solid {r.color('dialog_btn_text')};
    }}
    """


def dialog_groupbox(r: ThemeResolver) -> str:
    return f"""
    QGroupBox {{
        font-size: {r.px('font_size')};
        border: 1px solid {r.color('border_color')};
        border-radius: {r.px('btn_radius_small')};
        margin-top: 8px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        margin-left: 10px;
        padding: 0 4px;
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
    QListWidget::item:hover {{
        background: {r.color('menu_hover')};
    }}
    QListWidget::item:selected {{
        background: {r.color('dialog_btn_bg')};
        color: {r.color('dialog_btn_text')};
    }}
    """