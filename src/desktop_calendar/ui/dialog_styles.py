# coding: utf-8
"""消息框样式兜底构造器：无 ThemeBundle 时用 DEFAULT_THEME 编译 QSS。"""

from __future__ import annotations

from typing import Literal

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.ui.theme.qss import message_box
from desktop_calendar.ui.theme.resolver import ThemeResolver

MessageKind = Literal["info", "warn", "error"]

# 图标形制与前缀色沿用消息框按钮的配色，保证图标和按钮是同一套颜色
_ICON_SPEC: dict[str, tuple[str, str, str]] = {
    "info": ("msg_info_btn", "msg_info_btn_text", "i"),
    "warn": ("msg_warn_btn", "msg_warn_btn_text", "!"),
    "error": ("msg_error_btn", "msg_error_btn_text", "×"),
}


def build_message_box(theme: dict, kind: MessageKind) -> str:
    # ThemeResolver 对缺失 key 逐个回退 DEFAULT_THEME，空 / 部分缺字段均可。
    return message_box(ThemeResolver(theme or DEFAULT_THEME), kind)


def build_message_icon(
    theme: dict,
    kind: MessageKind,
    *,
    size: int = 32,
) -> QPixmap:
    """用主题色画一个消息框图标，替代系统原生图标。

    原生图标由 QStyle 绘制，浅色/深色主题下都对不上；这里用消息框按钮的
    填充色 + 文字色画同心圆，"i" / "!" / "×" 作字形，颜色天然一致。
    """
    resolver = ThemeResolver(theme or DEFAULT_THEME)
    fill_key, text_key, glyph = _ICON_SPEC[kind]
    size = max(16, int(size))

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fill = QColor(resolver.color(fill_key))
        painter.setPen(QPen(fill, 1))
        painter.setBrush(fill)
        inset = 1.0
        painter.drawEllipse(QRectF(inset, inset, size - 2 * inset, size - 2 * inset))

        font = QFont()
        font.setPixelSize(max(10, round(size * 0.6)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(resolver.color(text_key)))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    finally:
        painter.end()
    return pixmap
