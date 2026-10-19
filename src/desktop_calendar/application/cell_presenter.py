# coding: utf-8
"""日历单元格的展示规则。

输入：QDate + 纪念日索引 + 网络节假日数据。
输出：CellData（文本、样式类别、节假日标记）。

本模块不含任何 QWidget 绘制逻辑，可独立单测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QDate

from desktop_calendar.application.memorial_index import build_memorial_index
from desktop_calendar.config.constants import (
    LUNAR_FESTIVALS, SOLAR_FESTIVALS, FESTIVAL_NAME_MAP,
    RED_TEXT_SET, MONTH_CN, NUM_CN_MAP,
)
from desktop_calendar.config.i18n import tr
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.lunar import (
    get_lunar_by_datetime, is_holiday, is_workday, qdate_to_pydate,
)

CELL_NORMAL = "normal"
CELL_MEMORIAL = "memorial"
CELL_RED = "red"

_UNSET = object()


@dataclass(frozen=True)
class CellData:
    lunar_text: str
    kind: str
    is_hol: bool
    is_weekend_work: bool
    is_legal_hol: bool


class CellPresenter:
    def __init__(self):
        self._memorial_index = build_memorial_index([])
        self._net: Dict[str, bool] = {}

    # ---------------- 数据注入 ----------------
    def set_memorial_list(self, memorial_list) -> None:
        self._memorial_index = build_memorial_index(memorial_list)

    def set_net_holiday(self, data) -> None:
        self._net = data if isinstance(data, dict) else {}

    @property
    def net_count(self) -> int:
        return len(self._net)

    # ---------------- 对外查询 ----------------
    def compute(self, qdate: QDate) -> CellData:
        date_str = qdate.toString("yyyy-MM-dd")
        try:
            lunar = self._get_lunar(qdate)
            legal_raw = self._first_legal_holiday_raw(lunar)
            lunar_text, kind = self._lunar_text_and_kind(
                qdate, lunar=lunar, legal_raw=legal_raw)
            return CellData(
                lunar_text=lunar_text,
                kind=kind,
                is_hol=self._is_holiday(qdate, date_str=date_str),
                is_weekend_work=self._is_weekend_workday(
                    qdate, date_str=date_str),
                is_legal_hol=self._is_legal_holiday(
                    qdate, lunar=lunar, legal_raw=legal_raw,
                    date_str=date_str),
            )
        except Exception:
            return CellData("", CELL_NORMAL, False, False, False)

    def memorials_for(self, qdate: QDate) -> List[str]:
        names: List[str] = []
        idx = self._memorial_index
        for bucket, key in (
            ("solar_year", (qdate.month(), qdate.day())),
            ("solar_week", qdate.dayOfWeek()),
            ("solar_month", qdate.day()),
        ):
            for m in idx[bucket].get(key, ()):
                if m.get("name"):
                    names.append(m["name"])
        if lunar_mod.HAS_CNLUNAR:
            lunar = self._get_lunar(qdate)
            if lunar is not None:
                lm = getattr(lunar, "lunarMonth", 0)
                ld = getattr(lunar, "lunarDay", 0)
                leap = bool(getattr(lunar, "isLunarLeapMonth", False))
                for bucket, key in (
                    ("lunar_year", (lm, ld, leap)),
                    ("lunar_month", (ld, leap)),
                ):
                    for m in idx[bucket].get(key, ()):
                        if m.get("name"):
                            names.append(m["name"])
        return names

    def lunar_text_and_kind(self, qdate, lunar=_UNSET, legal_raw=_UNSET):
        if lunar is _UNSET:
            lunar = self._get_lunar(qdate)
        return self._lunar_text_and_kind(qdate, lunar=lunar, legal_raw=legal_raw)
    
    # ---------------- 内部：农历对象 ----------------
    def _get_lunar(self, qdate: QDate):
        if not lunar_mod.HAS_CNLUNAR:
            return None
        try:
            return get_lunar_by_datetime(
                (qdate.year(), qdate.month(), qdate.day()))
        except Exception:
            return None

    # ---------------- 内部：农历文本解析 ----------------
    @staticmethod
    def _first_legal_holiday_raw(lunar) -> Optional[str]:
        if lunar is None:
            return None
        try:
            f_list = lunar.get_legalHolidays()
        except Exception:
            return None
        if not f_list:
            return None
        raw = f_list[0] if isinstance(f_list, (list, tuple)) else f_list
        if not raw or raw == "无":
            return None
        return raw

    def _lookup_solar_memorial_name(self, qdate: QDate) -> Optional[str]:
        idx = self._memorial_index
        for bucket, key in (
            ("solar_year", (qdate.month(), qdate.day())),
            ("solar_week", qdate.dayOfWeek()),
            ("solar_month", qdate.day()),
        ):
            mems = idx[bucket].get(key)
            if mems:
                return mems[0].get("name") or tr("memorial.default_name")
        return None

    def _lookup_lunar_memorial_name(self, lm, ld, leap) -> Optional[str]:
        idx = self._memorial_index
        for bucket, key in (
            ("lunar_year", (lm, ld, leap)),
            ("lunar_month", (ld, leap)),
        ):
            mems = idx[bucket].get(key)
            if mems:
                return mems[0].get("name") or tr("memorial.default_name")
        return None

    def _is_new_year_eve(self, qdate, lm, leap) -> bool:
        if leap or lm != 12:
            return False
        nxt = self._get_lunar(qdate.addDays(1))
        return (nxt is not None
                and getattr(nxt, "lunarMonth", None) == 1
                and not bool(getattr(nxt, "isLunarLeapMonth", False))
                and getattr(nxt, "lunarDay", None) == 1)

    def _resolve_after_memorial(self, qdate, lunar, lm, ld, leap, legal_raw):
        if self._is_new_year_eve(qdate, lm, leap):
            return tr("cell.new_year_eve"), CELL_RED
        if legal_raw is _UNSET:
            legal_raw = self._first_legal_holiday_raw(lunar)
        if legal_raw is not None:
            name = FESTIVAL_NAME_MAP.get(legal_raw, legal_raw)
            return name, (CELL_RED if name in RED_TEXT_SET else CELL_NORMAL)
        if not leap and (lm, ld) in LUNAR_FESTIVALS:
            return LUNAR_FESTIVALS[(lm, ld)], CELL_RED
        if (qdate.month(), qdate.day()) in SOLAR_FESTIVALS:
            return SOLAR_FESTIVALS[(qdate.month(), qdate.day())], CELL_NORMAL
        term = getattr(lunar, "todaySolarTerms", "")
        if isinstance(term, list) and term:
            term = term[0]
        if term and term != "无":
            return term, CELL_NORMAL
        if ld == 1:
            prefix = tr("cell.leap_prefix") if leap else ""
            return f"{prefix}{MONTH_CN[lm]}", CELL_NORMAL
        return NUM_CN_MAP.get(str(ld), str(ld)), CELL_NORMAL

    def _lunar_text_and_kind(self, qdate, lunar=_UNSET, legal_raw=_UNSET):
        try:
            name = self._lookup_solar_memorial_name(qdate)
            if name is not None:
                return name, CELL_MEMORIAL
            if not lunar_mod.HAS_CNLUNAR:
                return self._solar_festival_fallback(qdate)
            if lunar is _UNSET:
                lunar = self._get_lunar(qdate)
            if not lunar:
                return self._solar_festival_fallback(qdate)
            lm = getattr(lunar, "lunarMonth", 0)
            ld = getattr(lunar, "lunarDay", 0)
            leap = bool(getattr(lunar, "isLunarLeapMonth", False))
            name = self._lookup_lunar_memorial_name(lm, ld, leap)
            if name is not None:
                return name, CELL_MEMORIAL
            return self._resolve_after_memorial(
                qdate, lunar, lm, ld, leap, legal_raw)
        except Exception:
            return "", CELL_NORMAL

    @staticmethod
    def _solar_festival_fallback(qdate) -> Tuple[str, str]:
        s = SOLAR_FESTIVALS.get((qdate.month(), qdate.day()))
        return (s, CELL_NORMAL) if s else ("", CELL_NORMAL)

    # ---------------- 内部：节假日判断 ----------------
    def _is_holiday(self, qdate, date_str=None) -> bool:
        try:
            key = date_str or qdate.toString("yyyy-MM-dd")
            if key in self._net:
                return self._net[key]
            if lunar_mod.HAS_CHINESE_CAL:
                return is_holiday(qdate_to_pydate(qdate))
            return qdate_to_pydate(qdate).weekday() >= 5
        except Exception:
            return False

    def _is_weekend_workday(self, qdate, date_str=None) -> bool:
        try:
            if qdate.dayOfWeek() not in (6, 7):
                return False
            key = date_str or qdate.toString("yyyy-MM-dd")
            if key in self._net:
                return self._net[key] is False
            if lunar_mod.HAS_CHINESE_CAL:
                return is_workday(qdate_to_pydate(qdate))
            return False
        except Exception:
            return False

    def _is_legal_holiday(self, qdate, lunar=None, legal_raw=_UNSET,
                          date_str=None) -> bool:
        key = date_str or qdate.toString("yyyy-MM-dd")
        if key in self._net:
            return self._net[key]
        if not lunar_mod.HAS_CNLUNAR:
            return False
        if legal_raw is _UNSET:
            if lunar is None:
                lunar = self._get_lunar(qdate)
            legal_raw = self._first_legal_holiday_raw(lunar)
        return legal_raw is not None