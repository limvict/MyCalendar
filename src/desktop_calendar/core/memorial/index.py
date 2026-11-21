# coding: utf-8
"""纪念日索引：按「公历/农历 × 年/月/周」建表，供日历快速查询。"""

from __future__ import annotations

from typing import Any

from desktop_calendar.utils.coerce import to_bool

from .common import REPEAT_ONCE, REPEAT_WEEK, REPEAT_YEAR, _index_int


def build_memorial_index(memorial_list) -> dict[str, dict[Any, list[dict]]]:
    idx: dict[str, dict[Any, list[dict]]] = {
        "solar_year": {},
        "solar_month": {},
        "solar_week": {},
        "lunar_year": {},
        "lunar_month": {},
        "once": {},
    }
    if not isinstance(memorial_list, (list, tuple)):
        return idx

    for mem in memorial_list:
        if not isinstance(mem, dict):
            continue
        if not to_bool(mem.get("enabled"), default=True):
            continue
        rep = mem.get("repeat_type")
        typ = mem.get("type")
        if rep is None or typ is None:
            continue

        # 索引端保留原始 day，月末收敛由查询端兜底
        if rep == REPEAT_WEEK:
            wd = _index_int(mem.get("day"), 1, 7)
            if wd is None:
                continue
            idx["solar_week"].setdefault(wd, []).append(mem)
        elif rep == REPEAT_ONCE:
            year = _index_int(mem.get("year"), 1900, 2100)
            month = _index_int(mem.get("month"), 1, 12)
            day = _index_int(mem.get("day"), 1, 31)
            if year is None or month is None or day is None:
                continue
            idx["once"].setdefault((year, month, day), []).append(mem)
        elif typ == "solar":
            if rep == REPEAT_YEAR:
                month = _index_int(mem.get("month"), 1, 12)
                day = _index_int(mem.get("day"), 1, 31)
                if month is None or day is None:
                    continue
                idx["solar_year"].setdefault((month, day), []).append(mem)
            else:
                day = _index_int(mem.get("day"), 1, 31)
                if day is None:
                    continue
                idx["solar_month"].setdefault(day, []).append(mem)
        else:  # lunar
            leap = to_bool(mem.get("isleap"), default=False)
            if rep == REPEAT_YEAR:
                month = _index_int(mem.get("month"), 1, 12)
                day = _index_int(mem.get("day"), 1, 30)
                if month is None or day is None:
                    continue
                idx["lunar_year"].setdefault((month, day, leap), []).append(mem)
            else:
                day = _index_int(mem.get("day"), 1, 30)
                if day is None:
                    continue
                idx["lunar_month"].setdefault((day, leap), []).append(mem)

    return idx
