# coding: utf-8
"""纪念日归一化：把外部数据收敛成合法结构（纯函数）。"""

from __future__ import annotations

import calendar
from typing import Any

from desktop_calendar.config.constants import REFERENCE_LEAP_YEAR
from desktop_calendar.utils.coerce import to_bool
from desktop_calendar.utils.logging_setup import get_logger

from .common import (
    _VALID_REPEAT_TYPES,
    _VALID_TYPES,
    REPEAT_ONCE,
    REPEAT_WEEK,
    REPEAT_YEAR,
    _clamp_int,
)

logger = get_logger()


_MEMORIAL_DEFAULTS = {
    "name": "",
    "type": "solar",
    "month": 1,
    "day": 1,
    "enabled": True,
    "advance_days": 0,
    "repeat_type": REPEAT_YEAR,
    "isleap": False,
    "since_year": None,  # 周年起始年；None 表示不算周年
}


# ===================== 归一化 =====================
def normalize_memorial(mem: dict) -> dict:
    mem = mem.copy()
    for k, v in _MEMORIAL_DEFAULTS.items():
        if mem.get(k) is None:
            mem[k] = v

    if mem["repeat_type"] not in _VALID_REPEAT_TYPES:
        mem["repeat_type"] = REPEAT_YEAR
    if mem["repeat_type"] in (REPEAT_WEEK, REPEAT_ONCE) and mem["type"] != "solar":
        mem["type"] = "solar"
    if mem["type"] not in _VALID_TYPES:
        mem["type"] = "solar"

    mem["month"] = _clamp_int(mem["month"], 1, 12, 1)

    if mem["repeat_type"] == REPEAT_WEEK:
        mem["day"] = _clamp_int(mem["day"], 1, 7, 1)
    elif mem["repeat_type"] == REPEAT_ONCE:
        mem["year"] = _clamp_int(mem.get("year"), 1900, 2100, REFERENCE_LEAP_YEAR)
        day = _clamp_int(mem["day"], 1, 31, 1)
        try:
            last = calendar.monthrange(mem["year"], mem["month"])[1]
            day = min(day, last)
        except Exception:
            day = min(day, 28)
        mem["day"] = day
    else:
        upper = 30 if mem["type"] == "lunar" else 31
        day = _clamp_int(mem["day"], 1, upper, 1)
        if mem["type"] == "solar" and mem["repeat_type"] == REPEAT_YEAR:
            try:
                last = calendar.monthrange(REFERENCE_LEAP_YEAR, mem["month"])[1]
                day = min(day, last)
            except Exception:
                day = min(day, 28)
        mem["day"] = day

    mem["advance_days"] = _clamp_int(mem["advance_days"], 0, 365, 0)
    mem["enabled"] = to_bool(mem.get("enabled"), default=True)
    mem["isleap"] = (
        False
        if mem["repeat_type"] in (REPEAT_WEEK, REPEAT_ONCE) or mem["type"] == "solar"
        else to_bool(mem.get("isleap"), default=False)
    )

    # since_year：0 / 负数 / 非数值统一视为不计算周年
    sy = mem.get("since_year")
    if sy is None or isinstance(sy, bool):
        mem["since_year"] = None
    else:
        try:
            v = int(sy)
        except (TypeError, ValueError, OverflowError):
            v = 0
        mem["since_year"] = max(1900, min(2100, v)) if v > 0 else None
    return mem


def normalize_memorial_days(value: Any) -> tuple[list, int]:
    if not isinstance(value, list):
        return [], 0
    result, skipped = [], 0
    for item in value:
        if not isinstance(item, dict):
            skipped += 1
            continue
        try:
            result.append(normalize_memorial(item))
        except Exception:
            skipped += 1
    if skipped:
        logger.debug("memorial_days 归一化：保留 %d 条，跳过 %d 条", len(result), skipped)
    return result, skipped
