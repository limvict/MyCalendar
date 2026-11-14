# coding: utf-8
import html
from dataclasses import dataclass
from typing import List, Optional

from datetime import date

from desktop_calendar.config.i18n import tr
from desktop_calendar.config.constants import (
    DEFAULT_THEME, FESTIVAL_NAME_MAP, LUNAR_FESTIVALS, RED_TEXT_SET,
)
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.ui.theme import ThemeResolver

# 纪念日倒计时超过该数量时折叠为"等 N 项"，避免底栏文本过长。
_MEMORIAL_NEXT_DISPLAY_MAX = 3


@dataclass(frozen=True)
class InfoParts:
    lunar_str: Optional[str] = None
    term_text: Optional[str] = None
    memorial_names: tuple = ()
    memorial_next: tuple = ()
    has_lunar_data: bool = False
    lunar_lib_available: bool = True
    legal_holiday_names: tuple = ()
    ordinary_holiday_names: tuple = ()


def _as_list(v) -> List[str]:
    """把 cnlunar 的"无 / 单值 / list"归一化为 list[str]。"""
    if v is None or v == "无":
        return []
    if isinstance(v, (list, tuple)):
        return [x for x in v if x and x != "无"]
    return [v]


def _extract_lunar_str(lunar) -> Optional[str]:
    if lunar is None:
        return None
    try:
        month_cn = lunar.lunarMonthCn.replace("大", "").replace("小", "")
        return (f"{lunar.lunarYearCn}【{lunar.chineseYearZodiac}】 "
                f"{month_cn}{lunar.lunarDayCn}")
    except Exception:
        return None


def _extract_term_text(lunar) -> Optional[str]:
    if lunar is None:
        return None
    term = getattr(lunar, "todaySolarTerms", "")
    if isinstance(term, list) and term:
        term = term[0]
    return term if term and term != "无" else None


def _extract_holidays(lunar, solar_date: Optional[date]) -> tuple:
    if lunar is None:
        return (), ()
    try:
        legal_raw = [
            FESTIVAL_NAME_MAP.get(x, x)
            for x in _as_list(lunar.get_legalHolidays())
            if x and x != "无"
        ]

        if lunar_mod.is_new_year_eve(lunar, solar_date):
            legal_raw.append("除夕")

        ordinary_raw = [
            FESTIVAL_NAME_MAP.get(x, x)
            for x in _as_list(lunar.get_otherHolidays())
            if x and x != "无"
        ]

        lm = getattr(lunar, "lunarMonth", 0)
        ld = getattr(lunar, "lunarDay", 0)
        leap = bool(getattr(lunar, "isLunarLeapMonth", False))
        if not leap:
            name = LUNAR_FESTIVALS.get((lm, ld))
            if name:
                # 只有真正属于法定节假日的名称才标红；
                # 元宵 / 龙抬头 / 七夕 / 重阳 / 腊八 / 小年等
                # 仅作为普通节日灰色展示。
                if name in RED_TEXT_SET:
                    legal_raw.append(name)
                else:
                    ordinary_raw.append(name)

        legal = tuple(dict.fromkeys(legal_raw))
        ordinary = tuple(dict.fromkeys(
            n for n in ordinary_raw if n not in legal
        ))
        return legal, ordinary
    except Exception:
        return (), ()


def build_info_parts(
    memorial_names,
    lunar_obj,
    has_cnlunar: bool,
    memorial_next=(),
    solar_date: Optional[date] = None,
) -> InfoParts:
    legal, ordinary = _extract_holidays(lunar_obj, solar_date)
    return InfoParts(
        lunar_str=_extract_lunar_str(lunar_obj),
        term_text=_extract_term_text(lunar_obj),
        memorial_names=tuple(memorial_names or ()),
        memorial_next=tuple(memorial_next or ()),
        has_lunar_data=lunar_obj is not None,
        lunar_lib_available=bool(has_cnlunar),
        legal_holiday_names=legal,
        ordinary_holiday_names=ordinary,
    )


def _span(color: str, label: str, value: str) -> str:
    """统一片段构造：label 为空时只显示 value。"""
    body = (f"{html.escape(label)}：{html.escape(value)}"
            if label else html.escape(value))
    return f"<span style='color:{color}'>{body}</span>"


def _format_memorial_next(memorial_next) -> str:
    """纪念日倒计时格式化，超量折叠。"""
    items = []
    shown = memorial_next[:_MEMORIAL_NEXT_DISPLAY_MAX]
    for name, days in shown:
        if days is None:
            items.append(name)
        elif days <= 0:
            items.append(tr("info.memorial_countdown_today").format(name=name))
        else:
            items.append(tr("info.memorial_countdown_fmt").format(
                name=name, days=days))
    rest = len(memorial_next) - len(shown)
    if rest > 0:
        items.append(tr("info.memorial_more").format(count=rest))
    return "、".join(items)


def render_html(parts: InfoParts,
                resolver: Optional[ThemeResolver] = None) -> Optional[str]:
    if resolver is None:
        resolver = ThemeResolver(dict(DEFAULT_THEME))

    pieces = []
    if parts.lunar_str:
        pieces.append(_span(resolver.color("lunar_text_color"), "",
                            parts.lunar_str))
    if parts.term_text:
        pieces.append(_span(resolver.color("solar_term_text_color"),
                            tr("info.solar_term"), parts.term_text))
    if parts.legal_holiday_names:
        pieces.append(_span(resolver.color("festival_red"),
                            tr("info.festival"),
                            "、".join(parts.legal_holiday_names)))
    if parts.ordinary_holiday_names:
        pieces.append(_span(resolver.color("normal_num_color"),
                            tr("info.festival"),
                            "、".join(parts.ordinary_holiday_names)))
    if parts.memorial_next:
        pieces.append(_span(resolver.color("memorial_orange"),
                            tr("info.memorial"),
                            _format_memorial_next(parts.memorial_next)))
    elif parts.memorial_names:
        pieces.append(_span(resolver.color("memorial_orange"),
                            tr("info.memorial"),
                            "、".join(parts.memorial_names)))

    if not pieces:
        return None
    # 紧凑分隔：默认主题窗口 440px，用 "·" 而非 "｜" 可显著缩短单行长度，
    # 减少换行概率。
    return "&nbsp;·&nbsp;".join(pieces)


def placeholder_key(parts: InfoParts) -> str:
    if not parts.lunar_lib_available:
        return "info.no_cnlunar"
    if not parts.has_lunar_data:
        return "info.lunar_unavailable"
    return "info.no_events"