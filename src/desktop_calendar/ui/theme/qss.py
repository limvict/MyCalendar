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
    
    /* 强制日历内部的所有子控件使用主题背景 */
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
    
    /* 强制让 QHeaderView 使用主题表头背景色 */
    QCalendarWidget QHeaderView {{
        background-color: {r.color('calendar_header_bg')};
        border: none;
        min-height: 32px;
    }}
    
    QCalendarWidget QHeaderView::section {{
        background-color: {r.color('calendar_header_bg')};
        border: 1px solid {r.color('calendar_header_bg')};
        padding: 8px 0px;
        
        /* 【关键修复】移除 font-weight: bold; 避免深色模式下的假粗体发虚 */
        /* 【关键修复】显式声明字体族，防止表头回退到系统默认的丑陋字体 */
        font-family: {_font_family(r)};
        font-size: {r.px('week_header_font_size')};
    }}
    """
def info_label(r: ThemeResolver) -> str:
    # 加回 color 作为纯文本模式（无 HTML）时的兜底色
    # 若有 HTML 富文本，内联的 span 颜色会覆盖此处的 color
    return (
        f"QLabel {{ font-size: {r.px('info_label_font_size')};"
        f" font-family: {_font_family(r)};"
        f" color: {r.color('date_text_color')};" 
        f" padding: 4px; background: transparent; }}"
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
    
    # 焦点边框色（使用稍微明显的颜色）
    focus_border = r.color("msg_info_btn")
    
    # 生成 SVG 箭头
    arrow_down = _arrow_svg(dialog_text, down=True)
    arrow_up = _arrow_svg(dialog_text, down=False)

    # 下拉列表悬停与选中颜色
    hover_bg = r.color("menu_hover")
    select_bg = r.color("msg_info_btn")
    select_text = r.color("msg_info_btn_text")

    return f"""
    /* ================== 输入框 / 下拉框 / 微调框 基础样式 ================== */
    QLineEdit, QComboBox, QSpinBox {{
        padding: 6px 8px;               /* 从 4px 提升到 6px，让控件更挺拔 */
        min-height: 18px;               /* 防止某些系统下高度被压扁 */
        border: 1px solid {border};
        border-radius: {r.px('input_radius')};
        background: {input_bg};
        color: {dialog_text};
        font-size: {r.px('font_size')};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {focus_border};
    }}

    /* ================== QComboBox 下拉框专属 ================== */
    /* 预留右侧箭头空间，防止文字过长时被箭头遮挡 */
    QComboBox {{
        padding-right: 24px;
    }}
    
    /* 右侧箭头区域：去掉左侧分割线，背景透明，居中放置 */
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

    /* 【关键】下拉弹出的列表视图（不设这个，展开后会是一块白底） */
    QComboBox QAbstractItemView {{
        border: 1px solid {border};
        border-radius: {r.px('input_radius')};
        background-color: {input_bg};
        color: {dialog_text};
        selection-background-color: {select_bg};
        selection-color: {select_text};
        outline: none; /* 去除选中时的虚线框 */
    }}
    QComboBox QAbstractItemView::item {{
        padding: 6px 8px;
        min-height: 20px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background-color: {hover_bg};
    }}

    /* ================== QSpinBox 微调框专属 ================== */
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
    # 使用 msg_info_btn 作为高亮强调色
    accent = r.color("msg_info_btn")
    accent_hover = r.color("msg_info_btn_hover")
    # 未选中状态边框：使用 btn_pressed，比默认深灰更清晰
    border = r.color("btn_pressed")
    input_bg = r.color("input_bg")
    dialog_text = r.color("dialog_text")
    
    # 【关键】让对勾的颜色动态跟随主题的强调文字颜色
    check_color = r.color("msg_info_btn_text")

    # 内联 SVG 生成对勾图标，颜色由 check_color 决定
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
        padding: 6px 2px; /* 稍微增加行高，避免拥挤 */
    }}

    /* ================== 复选框 ================== */
    /* 未选中：清晰的边框 + 深色背景 */
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
    
    /* 选中：主题强调色背景 + 自适应颜色的对勾 */
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

    /* ================== 单选框 ================== */
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

    /* 选中时文字加粗，并同步变成强调色 */
    QCheckBox:checked, QRadioButton:checked {{
        font-weight: bold;
        color: {accent};
    }}
    """


def dialog_groupbox(r: ThemeResolver) -> str:
    return f"""
    QGroupBox {{
        /* 标题字体稍微放大并加粗 */
        font-size: {r.px('dialog_content_font_size')};
        font-weight: bold;
        color: {r.color('dialog_text')};
        
        /* 【关键优化 1】使用柔和的 border_color（而非高亮色），降低视觉干扰 */
        border: 1px solid {r.color('border_color')};
        /* 【关键优化 2】统一使用较大的圆角，看起来更现代化 */
        border-radius: {r.px('btn_radius')};
        
        /* 【关键优化 3】留出上边距给标题，以及四周的内边距让内容呼吸 */
        margin-top: 16px;
        padding-top: 20px;    /* 防止内部复选框等贴紧标题 */
        padding-left: 14px;
        padding-right: 14px;
        padding-bottom: 14px;
    }}
    
    QGroupBox::title {{
        /* 标题定位在边框的上边缘 */
        subcontrol-origin: margin;
        subcontrol-position: top left;
        /* 往右缩进一点，不和左侧边角对齐 */
        margin-left: 12px;
        /* 左右留出一点空白 */
        padding: 0 6px;
        color: {r.color('dialog_text')};
        
        /* 【关键优化 4】使用与主背景相同的颜色，把边框"切断"，视觉更透气 */
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