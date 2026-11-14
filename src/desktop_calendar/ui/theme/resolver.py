# coding: utf-8
"""主题取值器：统一回退 + 类型归一化 + QColor 缓存。"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from PyQt6.QtGui import QColor

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.config.manager import get_logger

logger = get_logger()

# 亮度阈值：Qt QColor.lightness() 返回 0-255，128 是常见的明暗分界。
_DARK_LIGHTNESS_THRESHOLD = 128

# 当 DEFAULT_THEME 自身颜色值也损坏时的最终兜底色，保证 qcolor()
# 永不返回无效 QColor（QSS 里无效颜色会让整条规则静默失效）。
_FALLBACK_COLOR = "#000000"


def _default(key: str) -> Any:
    """取 DEFAULT_THEME[key]，缺失时给出带 key 名的 KeyError。

    直接 DEFAULT_THEME[key] 抛的 KeyError 只显示 key，不显示来源，
    开发期定位"哪个主题键没在 DEFAULT_THEME 定义"要翻调用栈。
    """
    try:
        return DEFAULT_THEME[key]
    except KeyError:
        raise KeyError(f"DEFAULT_THEME missing key {key!r}") from None

class ThemeResolver:
    def __init__(self, theme: Mapping[str, Any]):
        # 防御性拷贝：切断与调用方原 dict 的别名。否则外部修改原 dict
        # 后，_qcolor 缓存不会失效，color() / qcolor() 会与 str/int 等
        # 读到不一致的数据。这里由类自身保证不变量，而不是依赖调用方
        # 遵守"构建后不要改原 dict"的约定。
        self._theme: dict[str, Any] = dict(theme)
        self._qcolor: dict[str, QColor] = {}
        self._is_dark: bool | None = None   # 惰性计算 + 缓存

    @property
    def theme(self) -> Mapping[str, Any]:
        """只读快照视图，供 Bundle 暴露给外部读取。"""
        return MappingProxyType(self._theme)

    @property
    def is_dark(self) -> bool:
        """基于 bg_main 亮度判断是否深色主题。

        不要求调用方额外传主题名，对自定义预设同样有效；结果缓存，
        因为同一 bundle 生命周期内主题 dict 不会变。
        """
        if self._is_dark is None:
            self._is_dark = (
                self.qcolor("bg_main").lightness() < _DARK_LIGHTNESS_THRESHOLD
            )
        return self._is_dark

    def color(self, key: str) -> str:
        """返回经过校验的颜色字符串。

        与 qcolor() 使用同一套校验：主题里写错的颜色值（如 #GGGGGG、
        空串、数字）一律回退 DEFAULT_THEME 并打告警，而不是把无效值
        静默拼进 QSS 导致控件样式整体失效。
        """
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
                # color() 已保证主题值有效，走到这里说明 DEFAULT_THEME
                # 本身被改坏了。用固定兜底色保证 QSS 不整条失效。
                logger.warning(
                    "主题 key %r 的默认颜色值也无效，使用 %s 兜底",
                    key, _FALLBACK_COLOR)
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
        """字符串归一化：非 None 值统一转 str。

        主题里若把 font_family 之类写成数字，下游的 .split(",") 不会
        再 AttributeError；与 int/float 的"类型归一化 + 回退"契约一致。
        """
        v = self._theme.get(key)
        return str(v) if v is not None else str(_default(key))

    def px(self, key: str) -> str:
        return f"{self.int(key)}px"