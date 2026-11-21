# coding: utf-8
"""主窗口各 mixin 共用的常量与纯函数。"""

from __future__ import annotations

from PyQt6.QtGui import QScreen

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.config.i18n import tr
from desktop_calendar.ui.theme.bundle import LAYOUT
from desktop_calendar.ui.theme.scaling import fit_scale

_DEFER_RESCHEDULE_THRESHOLD = 100


# 设计稿尺寸（未缩放），运行期一律使用 bundle.layout 里缩放后的值
_SIDEBAR_WIDTH = LAYOUT["sidebar_width"]


def _tr_fmt(key: str, fallback: str, **kwargs) -> str:
    """格式化 i18n 文案；缺键或格式化失败时返回 fallback。"""
    raw = tr(key)
    if raw.startswith("attendance."):
        return fallback
    try:
        return raw.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return fallback


def _screen_ui_scale(
    screen: QScreen | None,
    *,
    sidebar_visible: bool = False,
) -> float:
    if screen is None:
        return 1.0
    available = screen.availableGeometry()
    return fit_scale(
        available.width(),
        available.height(),
        DEFAULT_THEME["window_width"] + (_SIDEBAR_WIDTH if sidebar_visible else 0),
        DEFAULT_THEME["window_height"],
    )
