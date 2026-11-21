# coding: utf-8
"""日期倒计时纯逻辑。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.lunar import (
    get_lunar_by_datetime,
    lunar_to_gregorian,
)


def _to_date(d: Any) -> date:
    if isinstance(d, bool):
        raise TypeError("bool 不是有效日期")
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, (tuple, list)) and len(d) == 3:
        return date(int(d[0]), int(d[1]), int(d[2]))
    if hasattr(d, "toPyDate"):
        return d.toPyDate()
    raise TypeError(f"不支持的日期类型: {type(d).__name__}")


def next_lunar_new_year(base_date: Any) -> date | None:
    """返回 base_date 之后（含）的下一个农历正月初一的公历日期。

    - 当天是农历正月初一时返回当天；
    - 农历库不可用 / 索引构建失败时返回 None（调用方不展示倒计时）。
    """
    if not lunar_mod.HAS_CNLUNAR:
        return None
    d = _to_date(base_date)
    lunar = get_lunar_by_datetime(d)
    if lunar is None:
        return None
    try:
        ly = int(getattr(lunar, "lunarYear", 0) or 0)
    except (TypeError, ValueError):
        return None
    if ly <= 0:
        return None

    # 农历年 ly 的正月初一若已过（如公历 12 月/次年 1 月），取 ly+1。
    # 正月初一最晚 2 月 20 日，故 g.year == 目标农历年。
    for y in (ly, ly + 1):
        try:
            g = lunar_to_gregorian(y, 1, 1, False)
        except Exception:
            g = None
        if g is not None and g >= d:
            return g
    return None


def days_until_lunar_new_year(base_date: Any) -> int | None:
    """距下一个农历正月初一的天数；当天返回 0；农历不可用返回 None。"""
    d = _to_date(base_date)
    g = next_lunar_new_year(d)
    if g is None:
        return None
    return (g - d).days
