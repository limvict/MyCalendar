# coding: utf-8
"""纪念日索引：把 O(N) 的逐日扫描降为 O(1) 查表。"""
from __future__ import annotations

from typing import Any, Dict, List

from desktop_calendar.core.memorial import (
    REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK,
    normalize_memorial,
)


def build_memorial_index(memorial_list) -> Dict[str, Dict[Any, List[dict]]]:
    """构建五个桶：solar_year / solar_month / solar_week / lunar_year / lunar_month。

    桶内保留输入顺序；同一 key 下多条按出现顺序排列。
    """
    idx: Dict[str, Dict[Any, List[dict]]] = {
        "solar_year": {}, "solar_month": {}, "solar_week": {},
        "lunar_year": {}, "lunar_month": {},
    }
    if not isinstance(memorial_list, (list, tuple)):
        return idx

    for mem in memorial_list:
        if not isinstance(mem, dict):
            continue
        try:
            m = normalize_memorial(mem)
        except Exception:
            continue
        if not m.get("enabled", True):
            continue
        rep, typ = m["repeat_type"], m["type"]
        if rep == REPEAT_WEEK:
            idx["solar_week"].setdefault(m["day"], []).append(m)
        elif typ == "solar":
            if rep == REPEAT_YEAR:
                idx["solar_year"].setdefault(
                    (m["month"], m["day"]), []).append(m)
            else:
                idx["solar_month"].setdefault(m["day"], []).append(m)
        else:
            leap = bool(m.get("isleap", False))
            if rep == REPEAT_YEAR:
                idx["lunar_year"].setdefault(
                    (m["month"], m["day"], leap), []).append(m)
            else:
                idx["lunar_month"].setdefault((m["day"], leap), []).append(m)
    return idx