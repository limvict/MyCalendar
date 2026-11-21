# coding: utf-8
"""主题取值器：统一回退 + 类型归一化 + QColor 缓存。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from PyQt6.QtGui import QColor

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.config.manager import get_logger

logger = get_logger()

_DARK_LIGHTNESS_THRESHOLD = 128
# DEFAULT_THEME 颜色值也损坏时的最终兜底，保证 QSS 规则不整条失效
_FALLBACK_COLOR = "#000000"


def _default(key: str) -> Any:
    try:
        return DEFAULT_THEME[key]
    except KeyError:
        raise KeyError(f"DEFAULT_THEME missing key {key!r}") from None


class ThemeResolver:
    def __init__(self, theme: Mapping[str, Any]):
        # 防御性拷贝：切断与调用方原 dict 的别名，保证 _qcolor 缓存与取值一致
        self._theme: dict[str, Any] = dict(theme)
        self._qcolor: dict[str, QColor] = {}
        self._is_dark: bool | None = None

    @property
    def theme(self) -> Mapping[str, Any]:
        return MappingProxyType(self._theme)

    @property
    def is_dark(self) -> bool:
        """基于 bg_main 亮度判断，对自定义预设同样有效；结果缓存。"""
        if self._is_dark is None:
            self._is_dark = self.qcolor("bg_main").lightness() < _DARK_LIGHTNESS_THRESHOLD
        return self._is_dark

    def color(self, key: str) -> str:
        """返回经校验的颜色字符串；无效值回退 DEFAULT_THEME 并告警。"""
        v = self._theme.get(key)
        if isinstance(v, str) and QColor(v).isValid():
            return v
        if v is not None:
            logger.warning("主题 key %r 的颜色值 %r 无效，回退默认", key, v)
        return str(_default(key))

    def qcolor(self, key: str) -> QColor:
        c = self._qcolor.get(key)
        if c is None:
            c = QColor(self.color(key))
            if not c.isValid():
                logger.warning("主题 key %r 的默认颜色值也无效，使用 %s 兜底", key, _FALLBACK_COLOR)
                c = QColor(_FALLBACK_COLOR)
            self._qcolor[key] = c
        return c

    def int(self, key: str) -> int:
        v = self._theme.get(key)
        if v is None:
            return int(_default(key))
        try:
            return int(v)
        except (TypeError, ValueError, OverflowError):
            logger.warning("主题 key %r 的值 %r 无法转 int，回退默认", key, v)
            return int(_default(key))

    def float(self, key: str) -> float:
        v = self._theme.get(key)
        if v is None:
            return float(_default(key))
        try:
            return float(v)
        except (TypeError, ValueError, OverflowError):
            logger.warning("主题 key %r 的值 %r 无法转 float，回退默认", key, v)
            return float(_default(key))

    def str(self, key: str) -> str:
        v = self._theme.get(key)
        return str(v) if v is not None else str(_default(key))

    def px(self, key: str) -> str:
        return f"{self.int(key)}px"
