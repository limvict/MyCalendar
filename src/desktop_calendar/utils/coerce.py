# coding: utf-8
"""类型归一化工具。

本模块不依赖任何 desktop_calendar 包内其他模块，可被任意层安全 import。
"""
from __future__ import annotations

import math
from typing import Any, Optional

_BOOL_TRUE_STR = frozenset(("true", "1", "yes", "on"))
_BOOL_FALSE_STR = frozenset(("false", "0", "no", "off"))
_HOLIDAY_KINDS = frozenset(("holiday", "workday"))


def to_bool(val: Any, default: bool = False) -> bool:
    """把 JSON 里的各种"布尔表示"归一化。

    - bool 直接返回
    - int/float 按 0/非 0 判定；NaN 视为无效，返回 default
      （json.load 的 parse_constant 会把 NaN 解析为 float('nan')，
      用户手改 config.json 写入 NaN 是编辑错误，应按 default 处理
      而非"非 0 即 True"）
    - str 在 true/false 集合里查表，不在集合内返回 default
    - 其它类型返回 default
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        # NaN 与任何值（含 0）比较都是 False，不拦截会在 val != 0
        # 返回 True。用 math.isnan 精确判断，避免 inf 被误伤。
        if isinstance(val, float) and math.isnan(val):
            return default
        return val != 0
    if isinstance(val, str):
        low = val.strip().lower()
        if low in _BOOL_TRUE_STR:
            return True
        if low in _BOOL_FALSE_STR:
            return False
        return default
    return default


def to_holiday_kind(val: Any) -> Optional[str]:
    """把网络 / 旧缓存里的节假日值归一化为 'holiday' / 'workday'。

    接受 bool（旧格式）、字符串（新格式或 "true"/"false" 等）、
    数字（非零视为 holiday；NaN 视为无效返回 None，调用方丢弃）。
    无法识别返回 None。
    """
    if isinstance(val, str):
        low = val.strip().lower()
        if low in _HOLIDAY_KINDS:
            return low
        if low in _BOOL_TRUE_STR:
            return "holiday"
        if low in _BOOL_FALSE_STR:
            return "workday"
        return None
    if isinstance(val, bool):
        return "holiday" if val else "workday"
    if isinstance(val, (int, float)):
        if isinstance(val, float) and math.isnan(val):
            return None
        return "holiday" if val != 0 else "workday"
    return None


__all__ = ["to_bool", "to_holiday_kind"]