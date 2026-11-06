# coding: utf-8
"""主题化图标：按主题色给应用单色图标着色。

Windows 任务栏 / 系统托盘 / 窗口标题栏共用同一份原始 .ico。主题切换时
用 CompositionMode_SourceIn 将图标不透明像素整体替换为主题色，得到与
当前主题一致的图标。

注意：原始图标若为彩色，会被替换为纯色剪影——这正是"图标跟随主题颜色"
的预期效果。若要保留内部细节，请提供 alpha 单色图标。
"""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap

from desktop_calendar.config.manager import get_logger

logger = get_logger()

_DEFAULT_DARK_ICON = "#333333"   # 浅色主题下的兜底图标色
_DEFAULT_LIGHT_ICON = "#e6e6e6"  # 深色主题下的兜底图标色


def _as_color(value) -> Optional[QColor]:
    if not value:
        return None
    try:
        c = QColor(value)
    except (TypeError, ValueError):
        return None
    return c if c.isValid() else None


def resolve_icon_color(bundle) -> QColor:
    """从 ThemeBundle 推导图标色。

    取值优先级：
    1. 显式 icon_color / accent_color；
    2. 复用日历表头文字色（本身即"与背景对比度足够的前景色"）；
    3. 按 bg_main 亮度在深/浅两个默认色里兜底。
    """
    if bundle is None:
        return QColor(_DEFAULT_DARK_ICON)

    theme = getattr(bundle, "theme", None) or {}
    for key in ("icon_color", "accent_color"):
        c = _as_color(theme.get(key))
        if c is not None:
            return c

    cal = getattr(bundle, "calendar_colors", None) or {}
    for key in ("calendar_header_text", "normal_num_color"):
        c = _as_color(cal.get(key))
        if c is not None:
            return c

    bg = _as_color(theme.get("bg_main"))
    if bg is not None and bg.lightness() < 128:
        return QColor(_DEFAULT_LIGHT_ICON)
    return QColor(_DEFAULT_DARK_ICON)


def standard_fallback_icon() -> QIcon:
    """系统托盘不可用 / 图标文件缺失时的兜底图标。"""
    from PyQt6.QtWidgets import QApplication, QStyle
    app = QApplication.instance()
    if app is None:
        return QIcon()
    return app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)


def _tint_pixmap(pm: QPixmap, color: QColor) -> Optional[QPixmap]:
    try:
        out = QPixmap(pm.size())
        out.setDevicePixelRatio(pm.devicePixelRatio())
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        try:
            painter.drawPixmap(0, 0, pm)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(out.rect(), color)
        finally:
            painter.end()
        return out
    except Exception:
        logger.debug("图标着色失败", exc_info=True)
        return None


def tinted_icon(path: str, color: QColor,
                fallback: Optional[QIcon] = None) -> QIcon:
    """加载 path 并用 color 着色；失败返回 fallback。"""
    if not path or not os.path.exists(path):
        return fallback or QIcon()
    src = QIcon(path)
    if src.isNull():
        return fallback or QIcon()

    sizes = src.availableSizes() or [QSize(256, 256)]
    result = QIcon()
    seen = set()
    for size in sizes:
        pm = src.pixmap(size)
        if pm.isNull():
            continue
        key = (pm.width(), pm.height(), pm.devicePixelRatio())
        if key in seen:
            continue
        seen.add(key)
        tinted = _tint_pixmap(pm, color)
        if tinted is not None:
            result.addPixmap(tinted)
    return result if not result.isNull() else (fallback or QIcon())