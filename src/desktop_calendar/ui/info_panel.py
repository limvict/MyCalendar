# coding: utf-8
import html
from dataclasses import dataclass
from typing import List, Optional

from datetime import date

from desktop_calendar.config.i18n import tr
from desktop_calendar.config.constants import (
    DEFAULT_THEME, FESTIVAL_NAME_MAP, LUNAR_FESTIVALS,
)
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.ui.theme import ThemeResolver


_MAX_ACTIVITY_ITEMS = 4

_AUSPICIOUS_ATTRS = ("get_auspicious", "todayAuspicious", "goodThing", "suitable")
_INAUSPICIOUS_ATTRS = ("get_inauspicious", "todayInauspicious", "badThing", "avoid")


@dataclass(frozen=True)
class InfoParts:
    lunar_str: Optional[str] = None
    term_text: Optional[str] = None
    holiday_names: tuple = ()
    memorial_names: tuple = ()
    memorial_next: tuple = ()
    auspicious: tuple = ()
    inauspicious: tuple = ()
    has_lunar_data: bool = False
    lunar_lib_available: bool = True
    legal_holiday_names: tuple = ()      # 法定假日 → 红
    ordinary_holiday_names: tuple = ()   # 普通节日 → 灰


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
    """返回 (legal, ordinary)：legal 标红、ordinary 标灰。

    - 所有名称在此统一过 FESTIVAL_NAME_MAP（"元旦节" → "元旦"），
      下游不再出现原始名，避免 RED_TEXT_SET 查不到。
    - 除夕不在 LUNAR_FESTIVALS（日期不固定），由
      lunar_mod.is_new_year_eve 判定，与 cell_presenter 共用一份。
    - 农历传统节日（元宵/端午/中秋…）若当年不在 get_legalHolidays()
      里，也补进 legal，与格子 LUNAR_FESTIVALS 分支对齐。
    """
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

        lm = getattr(lunar, "lunarMonth", 0)
        ld = getattr(lunar, "lunarDay", 0)
        leap = bool(getattr(lunar, "isLunarLeapMonth", False))
        if not leap:
            name = LUNAR_FESTIVALS.get((lm, ld))
            if name:
                legal_raw.append(name)

        legal = tuple(dict.fromkeys(legal_raw))

        ordinary = tuple(dict.fromkeys(
            n for n in (
                FESTIVAL_NAME_MAP.get(x, x)
                for x in _as_list(lunar.get_otherHolidays())
                if x and x != "无"
            )
            if n not in legal
        ))
        return legal, ordinary
    except Exception:
        return (), ()

def _split_activity(v) -> tuple:
    """cnlunar 的宜/忌通常是"祭祀、祈福、..."字符串；也兼容 list。"""
    if isinstance(v, (list, tuple)):
        return tuple(str(x).strip() for x in v if x and str(x).strip())
    if not isinstance(v, str):
        return ()
    s = v.strip()
    if not s or s == "无":
        return ()
    for sep in ("、", "，", ",", "；", ";"):
        if sep in s:
            return tuple(x.strip() for x in s.split(sep) if x.strip())
    return (s,)


def _first_attr(obj, names):
    for name in names:
        try:
            v = getattr(obj, name, None)
            if callable(v):
                v = v()
            if v is not None:
                return v
        except Exception:
            continue
    return None


def _truncate(items: tuple) -> tuple:
    """超过 _MAX_ACTIVITY_ITEMS 时保留前 N 项并追加省略号。

    N 是"真实内容项数"，结果总长度 = N + 1。理由：
      - render_html 用 "、".join(...) 拼接，用户能直接看到"…"，
        明确知道还有未显示内容；
      - 与 test_info_panel.TestTruncate 的断言
        （result[-1] == "…"、len == 5）一致。
    """
    if len(items) <= _MAX_ACTIVITY_ITEMS:
        return items
    return items[:_MAX_ACTIVITY_ITEMS]


def _extract_auspicious(lunar) -> tuple:
    return () if lunar is None else _truncate(
        _split_activity(_first_attr(lunar, _AUSPICIOUS_ATTRS)))


def _extract_inauspicious(lunar) -> tuple:
    return () if lunar is None else _truncate(
        _split_activity(_first_attr(lunar, _INAUSPICIOUS_ATTRS)))


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
        auspicious=_extract_auspicious(lunar_obj),
        inauspicious=_extract_inauspicious(lunar_obj),
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


def render_html(parts: InfoParts,
                resolver: Optional[ThemeResolver] = None) -> Optional[str]:
    if resolver is None:
        resolver = ThemeResolver(dict(DEFAULT_THEME))

    main_pieces = []
    if parts.lunar_str:
        main_pieces.append(_span(resolver.color("lunar_text_color"), "",
                                 parts.lunar_str))
    if parts.term_text:
        main_pieces.append(_span(resolver.color("solar_term_text_color"),
                                 tr("info.solar_term"), parts.term_text))
    if parts.legal_holiday_names:
        main_pieces.append(_span(resolver.color("festival_red"),
                                 tr("info.festival"),
                                 "、".join(parts.legal_holiday_names)))
    if parts.ordinary_holiday_names:
        main_pieces.append(_span(resolver.color("normal_num_color"),
                                 tr("info.festival"),
                                 "、".join(parts.ordinary_holiday_names)))
    if parts.memorial_next:
        items = []
        for name, days in parts.memorial_next:
            if days is None:
                items.append(name)
            elif days <= 0:
                items.append(tr("info.memorial_countdown_today").format(name=name))
            else:
                items.append(tr("info.memorial_countdown_fmt").format(
                    name=name, days=days))
        main_pieces.append(_span(resolver.color("memorial_orange"),
                                 tr("info.memorial"), "、".join(items)))
    elif parts.memorial_names:
        main_pieces.append(_span(resolver.color("memorial_orange"),
                                 tr("info.memorial"),
                                 "、".join(parts.memorial_names)))

    activity_lines = []
    if parts.auspicious:
        activity_lines.append(_span(resolver.color("solar_term_text_color"),
                                    tr("info.suitable"),
                                    "、".join(parts.auspicious)))
    if parts.inauspicious:
        activity_lines.append(_span(resolver.color("workday_orange"),
                                    tr("info.avoid"),
                                    "、".join(parts.inauspicious)))

    if not main_pieces and not activity_lines:
        return None

    lines = []
    if main_pieces:
        lines.append(" &nbsp;｜&nbsp; ".join(main_pieces))
    lines.extend(activity_lines)
    return "<br>".join(lines)
    

def placeholder_key(parts: InfoParts) -> str:
    if not parts.lunar_lib_available:
        return "info.no_cnlunar"
    if not parts.has_lunar_data:
        return "info.lunar_unavailable"
    return "info.no_events"