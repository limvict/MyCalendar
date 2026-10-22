# coding: utf-8
"""类型归一化工具。

本模块不依赖任何 desktop_calendar 包内其他模块，可被任意层安全 import。
"""
from __future__ import annotations

from typing import Any

_BOOL_TRUE_STR = frozenset(("true", "1", "yes", "on"))
_BOOL_FALSE_STR = frozenset(("false", "0", "no", "off"))


def to_bool(val: Any, default: bool = False) -> bool:
    """把 JSON 里的各种"布尔表示"归一化。

    - bool 直接返回
    - int/float 按 0/非 0 判定
    - str 在 true/false 集合里查表，不在集合内返回 default
    - 其它类型返回 default
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        low = val.strip().lower()
        if low in _BOOL_TRUE_STR:
            return True
        if low in _BOOL_FALSE_STR:
            return False
        return default
    return default


__all__ = ["to_bool"]