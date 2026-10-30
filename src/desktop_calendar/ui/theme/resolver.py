# coding: utf-8
"""主题取值器：统一回退 + 类型归一化 + QColor 缓存。"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from PyQt6.QtGui import QColor

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.config.manager import get_logger

logger = get_logger()


class ThemeResolver:
    def __init__(self, theme: Mapping[str, Any]):
        # 防御性拷贝：切断与调用方原 dict 的别名。否则外部修改原 dict
        # 后，_qcolor 缓存不会失效，color() / qcolor() 会与 str/int 等
        # 读到不一致的数据。这里由类自身保证不变量，而不是依赖调用方
        # 遵守"构建后不要改原 dict"的约定。
        self._theme: dict[str, Any] = dict(theme)
        self._qcolor: dict[str, QColor] = {}

    @property
    def theme(self) -> Mapping[str, Any]:
        """只读快照视图，供 Bundle 暴露给外部读取。"""
        return MappingProxyType(self._theme)

    def color(self, key: str) -> str:
        v = self._theme.get(key)
        return v if v is not None else DEFAULT_THEME[key]

    def qcolor(self, key: str) -> QColor:
        c = self._qcolor.get(key)
        if c is None:
            c = QColor(self.color(key))
            if not c.isValid():
                logger.warning("主题 key %r 的颜色值无效，回退默认", key)
                c = QColor(DEFAULT_THEME[key])
            self._qcolor[key] = c
        return c

    def int(self, key: str) -> int:
        v = self._theme.get(key)
        if v is None:
            return int(DEFAULT_THEME[key])
        try:
            return int(v)
        except (TypeError, ValueError, OverflowError):
            logger.warning("主题 key %r 的值 %r 无法转 int，回退默认", key, v)
            return int(DEFAULT_THEME[key])

    def float(self, key: str) -> float:
        v = self._theme.get(key)
        if v is None:
            return float(DEFAULT_THEME[key])
        try:
            return float(v)
        except (TypeError, ValueError):
            logger.warning("主题 key %r 的值 %r 无法转 float，回退默认", key, v)
            return float(DEFAULT_THEME[key])

    def str(self, key: str) -> str:
        v = self._theme.get(key)
        return v if v is not None else DEFAULT_THEME[key]

    def px(self, key: str) -> str:
        return f"{self.int(key)}px"