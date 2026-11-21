# coding: utf-8
"""纪念日的日期匹配与「下一次发生日期」计算。"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.lunar import get_lunar_by_datetime, lunar_to_gregorian
from desktop_calendar.utils.logging_setup import get_logger

from .common import (
    REPEAT_MONTH,
    REPEAT_ONCE,
    REPEAT_WEEK,
    REPEAT_YEAR,
    _to_pydate,
)
from .normalize import normalize_memorial

logger = get_logger()


# 农历搜索窗口。闰月大周期 19 年，罕见闰月（闰九月等）可达 38 年，
# 这里覆盖绝大多数情况。
_LUNAR_YEAR_LOOKAHEAD = 5


_LUNAR_MONTH_LOOKAHEAD = 13


_LUNAR_LEAP_YEAR_LOOKAHEAD = 19


_warned_leap_no_next: set = set()


_LEAP_WARN_LIMIT = 200


# ===================== 公历 =====================
def _match_solar_monthly(d: date, day: int) -> bool:
    _, last = calendar.monthrange(d.year, d.month)
    return d.day == min(day, last)


def _match_solar_yearly(d: date, month: int, day: int) -> bool:
    if d.month != month:
        return False
    _, last = calendar.monthrange(d.year, month)
    return d.day == min(day, last)


def _next_solar_monthly(d: date, day: int) -> date | None:
    y, m = d.year, d.month
    for _ in range(2):
        target = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        if target > d:
            return target
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def _next_solar_yearly(d: date, month: int, day: int) -> date | None:
    for y in (d.year, d.year + 1):
        target = date(y, month, min(day, calendar.monthrange(y, month)[1]))
        if target > d:
            return target
    return None


def _next_week_date(d: date, target_weekday: int) -> date:
    diff = (target_weekday - (d.weekday() + 1)) % 7 or 7
    return d + timedelta(days=diff)


# ===================== 农历 =====================
def _lunar_day_or_month_end(ly, lm, day, is_leap):
    """查农历日；超过实际天数时收敛到月末（30/29）。"""
    for d in dict.fromkeys((day, 30, 29)):
        g = lunar_to_gregorian(ly, lm, d, is_leap)
        if g is not None:
            return g
    return None


def _iter_leap_months(ly):
    return sorted(
        ((lm, g) for lm in range(1, 13) if (g := lunar_to_gregorian(ly, lm, 1, True)) is not None),
        key=lambda x: x[1],
    )


def _iter_lunar_months(base_ly, base_lm, count):
    """从 (base_ly, base_lm) 按正常月推进，忽略闰月。"""
    for offset in range(count):
        total = base_lm + offset - 1
        yield base_ly + total // 12, total % 12 + 1


def _match_lunar(base_date, month, day, is_leap):
    lunar = get_lunar_by_datetime((base_date.year, base_date.month, base_date.day))
    if lunar is None:
        return False
    if month is not None and getattr(lunar, "lunarMonth", None) != month:
        return False
    if bool(getattr(lunar, "isLunarLeapMonth", False)) != bool(is_leap):
        return False
    ld = getattr(lunar, "lunarDay", None)
    if ld == day:
        return True
    if isinstance(ld, int) and day > ld:
        nxt_d = base_date + timedelta(days=1)
        nxt = get_lunar_by_datetime((nxt_d.year, nxt_d.month, nxt_d.day))
        if nxt is not None and getattr(nxt, "lunarDay", None) == 1:
            return True
    return False


def _next_lunar_monthly(base_date, day, is_leap):
    if not lunar_mod.HAS_CNLUNAR:
        return None
    lunar = get_lunar_by_datetime((base_date.year, base_date.month, base_date.day))
    if lunar is None:
        return None
    base_ly, base_lm = lunar.lunarYear, lunar.lunarMonth
    if is_leap:
        for ly in range(base_ly, base_ly + _LUNAR_LEAP_YEAR_LOOKAHEAD):
            for lm, _ in _iter_leap_months(ly):
                g = _lunar_day_or_month_end(ly, lm, day, True)
                if g is not None and g > base_date:
                    return g
        return None
    for ly, lm in _iter_lunar_months(base_ly, base_lm, _LUNAR_MONTH_LOOKAHEAD):
        g = _lunar_day_or_month_end(ly, lm, day, False)
        if g is not None and g > base_date:
            return g
    return None


def _next_lunar_yearly(base_date, month, day, is_leap):
    if not lunar_mod.HAS_CNLUNAR:
        return None
    base_lunar = get_lunar_by_datetime(base_date)
    if base_lunar is None:
        base_ly = base_date.year - 1
    else:
        base_ly = int(base_lunar.lunarYear)

    lookahead = _LUNAR_LEAP_YEAR_LOOKAHEAD if is_leap else _LUNAR_YEAR_LOOKAHEAD
    for ly in range(base_ly, base_ly + lookahead):
        g = _lunar_day_or_month_end(ly, month, day, is_leap)
        if g is not None and g > base_date:
            return g
    return None


# ===================== 对外 =====================
def get_next_memorial_date(mem, base_date, include_base=False, normalized=False):
    if base_date is None:
        return None
    base_date = _to_pydate(base_date)
    if not normalized:
        mem = normalize_memorial(mem)

    rep, day, is_solar = mem["repeat_type"], mem["day"], mem["type"] == "solar"

    if rep == REPEAT_WEEK:
        if include_base and base_date.weekday() + 1 == day:
            return base_date
        return _next_week_date(base_date, day)

    if rep == REPEAT_MONTH:
        if is_solar:
            if include_base and _match_solar_monthly(base_date, day):
                return base_date
            return _next_solar_monthly(base_date, day)
        if include_base and _match_lunar(base_date, None, day, mem["isleap"]):
            return base_date
        result = _next_lunar_monthly(base_date, day, mem["isleap"])
        if result is None and mem["isleap"]:
            _note_leap_no_next(mem)
        return result

    if rep == REPEAT_ONCE:
        try:
            target = date(mem["year"], mem["month"], day)
        except (KeyError, TypeError, ValueError):
            return None
        if target > base_date or (include_base and target == base_date):
            return target
        return None

    if is_solar:
        if include_base and _match_solar_yearly(base_date, mem["month"], day):
            return base_date
        return _next_solar_yearly(base_date, mem["month"], day)
    if include_base and _match_lunar(base_date, mem["month"], day, mem["isleap"]):
        return base_date
    result = _next_lunar_yearly(base_date, mem["month"], day, mem["isleap"])
    if result is None and mem["isleap"]:
        _note_leap_no_next(mem)
    return result


def _note_leap_no_next(mem: dict) -> None:
    key = (mem.get("name") or "", mem.get("month"), mem.get("day"))
    if key in _warned_leap_no_next:
        return
    if len(_warned_leap_no_next) >= _LEAP_WARN_LIMIT:
        _warned_leap_no_next.clear()
    _warned_leap_no_next.add(key)
    logger.info(
        "闰月纪念日 %r（%s 月 %s 日，闰）在未来 %d 年内无对应闰月，本次不返回下次日期。",
        mem.get("name") or "<unnamed>",
        mem.get("month", "?"),
        mem.get("day", "?"),
        _LUNAR_LEAP_YEAR_LOOKAHEAD,
    )


def match_memorial_date(mem, base_date, normalized=False):
    if base_date is None:
        return False
    base_date = _to_pydate(base_date)
    if not normalized:
        mem = normalize_memorial(mem)
    return get_next_memorial_date(mem, base_date, include_base=True, normalized=True) == base_date


def get_anniversary_years(mem, on_date, normalized=False, by_calendar=True):
    """on_date 是该纪念日的第几周年；不满足条件返回 None。

    条件：since_year 已设置、repeat_type == REPEAT_YEAR、on_date 命中
    该纪念日、on_date 对应年份 >= since_year。起始年当天为 0 周年。

    by_calendar=True：solar 用公历年差，lunar 用农历年差（since_year
    应与 type 的日历体系一致录入）。False：统一按公历年差。
    """
    if on_date is None:
        return None
    on_date = _to_pydate(on_date)
    if not normalized:
        mem = normalize_memorial(mem)

    if mem.get("repeat_type") != REPEAT_YEAR:
        return None
    since_year = mem.get("since_year")
    if since_year is None:
        return None
    if not match_memorial_date(mem, on_date, normalized=True):
        return None

    if by_calendar and mem["type"] == "lunar":
        lunar = get_lunar_by_datetime(on_date)
        if lunar is None:
            return None
        cur_year = int(getattr(lunar, "lunarYear", 0) or 0)
    else:
        cur_year = on_date.year

    diff = cur_year - int(since_year)
    return diff if diff >= 0 else None
