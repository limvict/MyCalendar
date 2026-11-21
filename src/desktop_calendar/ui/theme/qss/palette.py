# coding: utf-8
"""QSS 调色板：把主题取值器整理成可直接写进样式表的颜色。

这里的函数只做颜色计算（对比度、明暗、SVG 转 URI），不产出 QSS 规则。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, NamedTuple

from PyQt6.QtGui import QColor

from .. import svg_assets
from ..resolver import ThemeResolver

MessageKind = Literal["info", "warn", "error"]


_GENERIC_FONT_FAMILIES = {
    "serif",
    "sans-serif",
    "monospace",
    "cursive",
    "fantasy",
    "system-ui",
}


# ===================== 颜色安全辅助函数 =====================


def _split_families(raw: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    in_quote = False
    for ch in raw:
        if ch in ('"', "'"):
            in_quote = not in_quote
            buf.append(ch)
        elif ch == "," and not in_quote:
            parts.append("".join(buf).strip())
            buf.clear()
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _font_family(r: ThemeResolver) -> str:
    parts = _split_families(r.str("font_family"))
    if not parts:
        return "sans-serif"
    out: list[str] = []
    for f in parts:
        name = f.strip().strip('"').strip("'").strip()
        if not name:
            continue
        if name.lower().replace(" ", "-") in _GENERIC_FONT_FAMILIES:
            out.append(name)
        else:
            out.append(f'"{name}"')
    return ", ".join(out) or "sans-serif"


def _is_dark(r: ThemeResolver) -> bool:
    return bool(getattr(r, "is_dark", False))


@lru_cache(maxsize=64)
def _svg_uri(svg: str) -> str:
    # QSS 的图片只认文件路径，data URI 不生效，见 svg_assets 模块说明
    return svg_assets.asset_url(svg)


def _image(uri: str) -> str:
    return svg_assets.image_declaration(uri)


@lru_cache(maxsize=8)
def _arrow_svg(color: str, *, down: bool) -> str:
    d = "M0 0 L5 6 L10 0 Z" if down else "M0 6 L5 0 L10 6 Z"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" '
        f'viewBox="0 0 10 6"><path d="{d}" fill="{color}"/></svg>'
    )
    return _svg_uri(svg)


def _luminance(hex_color: str) -> float:
    """计算颜色的相对亮度，用于判断对比度"""
    if not hex_color or not hex_color.startswith("#"):
        return 0.5
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return 0.5
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    except ValueError:
        return 0.5


def _ensure_contrast(bg_hex: str, text_hex: str, threshold: float = 0.3) -> str:
    """如果文字颜色与背景颜色太接近，强制反转颜色"""
    bg_l = _luminance(bg_hex)
    text_l = _luminance(text_hex) if text_hex else -1

    if text_l == -1 or abs(bg_l - text_l) < threshold:
        return "#ffffff" if bg_l < 0.5 else "#000000"
    return text_hex


class SafePalette(NamedTuple):
    text_main: str  # 主界面的文字
    text_input: str  # 输入框的文字
    border: str  # 边框
    bg_main: str  # 主背景
    bg_input: str  # 输入框背景
    accent: str  # 强调色（按钮、高亮）


def _get_safe_palette(r: ThemeResolver) -> SafePalette:
    """提取主题色，并强制修复颜色冲突"""
    bg_main = r.color("bg_main") or ("#1e1e1e" if _is_dark(r) else "#ffffff")
    input_bg = r.color("input_bg") or bg_main

    raw_text = r.color("dialog_text")
    safe_text_main = _ensure_contrast(bg_main, raw_text)
    safe_text_input = _ensure_contrast(input_bg, raw_text)

    raw_border = r.color("border_color")
    bg_l = _luminance(bg_main)
    # 如果边框颜色与背景色亮度太近，则强制给定可见的边框
    if not raw_border or abs(bg_l - _luminance(raw_border)) < 0.15:
        raw_border = "#e0e0e0" if bg_l < 0.5 else "#c0c0c0"

    return SafePalette(
        text_main=safe_text_main,
        text_input=safe_text_input,
        border=raw_border,
        bg_main=bg_main,
        bg_input=input_bg,
        accent=r.color("msg_info_btn") or "#0078d4",
    )


def transparent_widget(object_name: str) -> str:
    """返回只作用于指定 objectName 的透明规则（用于挡住白底容器）。

    必须带选择器：Qt 会把没有选择器的「裸声明」样式表应用到该控件及其
    **所有后代**，连 QToolTip 也会被套上，表现为侧边栏里的提示框背景变黑
    （文字仍是主题色）。所以这里固定用 `#objectName` 收窄到控件自身。
    """
    return f"#{object_name} {{ background: transparent; border: none; }}"


def _hover_accent(r: ThemeResolver) -> str:
    """全站统一的交互强调色：hover / focus 的描边与文字高亮都用它。

    约定（见各控件 QSS）：
      - 按钮 hover：背景换成各自的 hover 底色，边框统一用本强调色；
      - 填充式按钮（今天 / 快速添加）：hover 用自身底色的加深版本，不用 btn_hover；
      - 条目（菜单 / 列表 / 下拉）hover：背景统一 `menu_hover`；
      - 纯文字型控件 hover：文字转本强调色，不改背景；
      - hover 一律不改正文颜色。
    """
    return r.color("today_bg") or _get_safe_palette(r).accent


def _shade(color: str, percent: int) -> str:
    """把颜色压暗 percent%（负数表示提亮）。非法颜色原样返回。"""
    c = QColor(color)
    if not c.isValid():
        return color
    if percent >= 0:
        return c.darker(100 + percent).name()
    return c.lighter(100 - percent).name()
