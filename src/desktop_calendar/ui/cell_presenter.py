# coding: utf-8
"""日历单元格的展示规则：QDate + 纪念日索引 + 网络节假日 → CellData。

本模块不含任何 QWidget 绘制逻辑，可独立单测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

from PyQt6.QtCore import QDate

from desktop_calendar.core.memorial import build_memorial_index
from desktop_calendar.config.constants import (
    LUNAR_FESTIVALS, SOLAR_FESTIVALS, FESTIVAL_NAME_MAP,
    RED_TEXT_SET, MONTH_CN, NUM_CN_MAP,
)
from desktop_calendar.config.i18n import tr
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.lunar import (
    get_lunar_by_datetime, is_workday, qdate_to_pydate,
)
from desktop_calendar.utils.logging_setup import get_logger
from desktop_calendar.utils.coerce import to_holiday_kind
logger = get_logger()

CELL_NORMAL = "normal"
CELL_MEMORIAL = "memorial"
CELL_RED = "red"

UNSET = object()
_REPORTED_ERROR_MAX = 2000

__all__ = [
    "CellData", "CellPresenter",
    "CELL_NORMAL", "CELL_MEMORIAL", "CELL_RED", "UNSET",
]


@dataclass(frozen=True)
class CellData:
    lunar_text: str
    kind: str
    is_weekend_work: bool
    is_legal_hol: bool


class CellPresenter:
    def __init__(self):
        self._memorial_index = build_memorial_index([])
        self._net: Dict[str, str] = {}
        self._reported_error_dates = set()

    def set_memorial_list(self, memorial_list) -> None:
        self._memorial_index = build_memorial_index(memorial_list)

    def set_net_holiday(self, data) -> None:
        # 统一在入口归一化：无论上游给 bool / str / 数字，
        # self._net 恒为 {date: "holiday" | "workday"}。
        if not isinstance(data, dict):
            self._net = {}
            return
        normalized: Dict[str, str] = {}
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            kind = to_holiday_kind(v)
            if kind is not None:
                normalized[k] = kind
        self._net = normalized

    @property
    def net_count(self) -> int:
        return len(self._net)

    # ---------- 对外查询 ----------
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
                is_weekend_work=self._is_weekend_workday(qdate, date_str=date_str),
                is_legal_hol=self._is_legal_holiday(
                    qdate, lunar=lunar, legal_raw=legal_raw, date_str=date_str),
            )
        except Exception:
            if self._should_report(date_str):
                logger.debug(f"CellPresenter.compute 异常 date={date_str}",
                             exc_info=True)
            return CellData("", CELL_NORMAL, False, False)

    def memorial_items_for(self, qdate: QDate) -> List[dict]:
        """返回该日命中的纪念日原始 dict 列表（详情面板倒计时需要）。"""
        items = list(self._iter_solar_memorials(qdate))
        if lunar_mod.HAS_CNLUNAR:
            items.extend(self._iter_lunar_memorials(qdate, self._get_lunar(qdate)))
        return items

    def memorials_for(self, qdate: QDate) -> List[str]:
        return [m.get("name") for m in self.memorial_items_for(qdate)
                if m.get("name")]

    def lunar_text_and_kind(
        self, qdate, lunar=UNSET, legal_raw=UNSET,
    ) -> Tuple[str, str]:
        if lunar is UNSET:
            lunar = self._get_lunar(qdate)
        return self._lunar_text_and_kind(qdate, lunar=lunar, legal_raw=legal_raw)

    # ---------- 农历对象 / 法定节假日 ----------
    def _get_lunar(self, qdate: QDate):
        if not lunar_mod.HAS_CNLUNAR:
            return None
        try:
            return get_lunar_by_datetime(
                (qdate.year(), qdate.month(), qdate.day()))
        except Exception:
            return None

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

    # ---------- 纪念日 bucket 遍历 ----------
    def _iter_solar_memorials(self, qdate: QDate) -> Iterator[dict]:
        idx = self._memorial_index
        for bucket, key in (
            ("solar_year", (qdate.month(), qdate.day())),
            ("once", (qdate.year(), qdate.month(), qdate.day())),
            ("solar_week", qdate.dayOfWeek()),
            ("solar_month", qdate.day()),
        ):
            yield from idx[bucket].get(key, ())
        # 月末收敛：配置的 day 超过本月天数时在今天也展示
        last = qdate.daysInMonth()
        if qdate.day() == last:
            for d in range(last + 1, 32):
                yield from idx["solar_month"].get(d, ())
                yield from idx["solar_year"].get((qdate.month(), d), ())

    def _iter_lunar_memorials(self, qdate: QDate, lunar) -> Iterator[dict]:
        if lunar is None:
            return
        lm = getattr(lunar, "lunarMonth", 0)
        ld = getattr(lunar, "lunarDay", 0)
        leap = bool(getattr(lunar, "isLunarLeapMonth", False))
        idx = self._memorial_index
        for bucket, key in (
            ("lunar_year", (lm, ld, leap)),
            ("lunar_month", (ld, leap)),
        ):
            yield from idx[bucket].get(key, ())
        # 月末收敛：下一天是农历初一即今天为月末；ld < 30 避免 30 日当天重复
        if ld < 30:
            nxt = self._get_lunar(qdate.addDays(1))
            if nxt is not None and getattr(nxt, "lunarDay", None) == 1:
                yield from idx["lunar_month"].get((30, leap), ())
                yield from idx["lunar_year"].get((lm, 30, leap), ())

    def _first_memorial_name(self, qdate: QDate, lunar) -> Optional[str]:
        for m in self._iter_solar_memorials(qdate):
            return m.get("name") or tr("memorial.default_name")
        if lunar is None:
            return None
        for m in self._iter_lunar_memorials(qdate, lunar):
            return m.get("name") or tr("memorial.default_name")
        return None

    # ---------- 农历文本解析 ----------

    def _resolve_after_memorial(
        self, qdate, lunar, legal_raw: Optional[str],
    ) -> Tuple[str, str]:
        lm = getattr(lunar, "lunarMonth", 0)
        ld = getattr(lunar, "lunarDay", 0)
        leap = bool(getattr(lunar, "isLunarLeapMonth", False))

        if lunar_mod.is_new_year_eve(lunar, qdate_to_pydate(qdate)):
            return "除夕", CELL_RED
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

    def _lunar_text_and_kind(
        self, qdate, lunar, legal_raw=UNSET,
    ) -> Tuple[str, str]:
        try:
            name = self._first_memorial_name(qdate, lunar)
            if name is not None:
                return name, CELL_MEMORIAL
            if lunar is None:
                return self._solar_festival_fallback(qdate)
            if legal_raw is UNSET:
                legal_raw = self._first_legal_holiday_raw(lunar)
            return self._resolve_after_memorial(qdate, lunar, legal_raw)
        except Exception:
            key = f"ltk:{qdate.toString('yyyy-MM-dd')}"
            if self._should_report(key):
                logger.debug(
                    f"CellPresenter._lunar_text_and_kind 异常 date="
                    f"{qdate.toString('yyyy-MM-dd')}", exc_info=True)
            return "", CELL_NORMAL

    @staticmethod
    def _solar_festival_fallback(qdate) -> Tuple[str, str]:
        s = SOLAR_FESTIVALS.get((qdate.month(), qdate.day()))
        return (s, CELL_NORMAL) if s else ("", CELL_NORMAL)

    # ---------- 布尔判断 ----------
    def _is_weekend_workday(self, qdate, date_str=None) -> bool:
        try:
            if qdate.dayOfWeek() not in (6, 7):
                return False
            key = date_str or qdate.toString("yyyy-MM-dd")
            if key in self._net:
                return self._net[key] == "workday"
            if lunar_mod.HAS_CHINESE_CAL:
                return is_workday(qdate_to_pydate(qdate))
            return False
        except Exception:
            return False

    def _is_legal_holiday(self, qdate, lunar=None, legal_raw=UNSET,
                          date_str=None) -> bool:
        key = date_str or qdate.toString("yyyy-MM-dd")
        if key in self._net:
            return self._net[key] == "holiday"
        if not lunar_mod.HAS_CNLUNAR:
            return False
        if legal_raw is UNSET:
            if lunar is None:
                lunar = self._get_lunar(qdate)
            legal_raw = self._first_legal_holiday_raw(lunar)
        return legal_raw is not None

    # ---------- 工具 ----------
    def _should_report(self, key: str) -> bool:
        """去重 + 上限保护；返回 True 表示本次应记录日志。"""
        if key in self._reported_error_dates:
            return False
        if len(self._reported_error_dates) >= _REPORTED_ERROR_MAX:
            # 清空后旧 key 重新可报，避免"静默丢弃后续异常"。记 warning
            # 让运维知道去重表被打满，可能意味着某个 date 持续异常。
            logger.warning("CellPresenter 异常上报去重表已达上限，已清空")
            self._reported_error_dates.clear()
        self._reported_error_dates.add(key)
        return True