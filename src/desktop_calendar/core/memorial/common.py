# coding: utf-8
"""纪念日模块共用的重复类型常量与基础工具。"""

from __future__ import annotations

from datetime import date, datetime

from ...utils.coerce import to_int_clamped

REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK = "year", "month", "week"
REPEAT_ONCE = "once"
_VALID_REPEAT_TYPES = (REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK, REPEAT_ONCE)
_VALID_TYPES = ("solar", "lunar")


# ===================== 基础工具 =====================
def _to_pydate(qdate) -> date:
    if isinstance(qdate, datetime):
        return qdate.date()
    if isinstance(qdate, date):
        return qdate
    if hasattr(qdate, "toPyDate"):
        return qdate.toPyDate()
    try:
        return date(qdate.year(), qdate.month(), qdate.day())
    except AttributeError as exc:
        raise TypeError(f"不支持的日期类型: {type(qdate).__name__}") from exc


def _clamp_int(val, lo: int, hi: int, default: int) -> int:
    return to_int_clamped(val, lo=lo, hi=hi, default=default)


def _index_int(val, lo: int, hi: int):
    """索引键归一化到 [lo, hi]；非数值返回 None（调用方跳过该条）。"""
    try:
        v = int(val)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(lo, min(hi, v))
