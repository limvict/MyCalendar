# coding: utf-8
import html
from dataclasses import dataclass
from datetime import date

from desktop_calendar.config.constants import (
    DEFAULT_THEME,
    FESTIVAL_NAME_MAP,
    LUNAR_FESTIVALS,
    RED_TEXT_SET,
)
from desktop_calendar.config.i18n import tr
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.countdown import next_lunar_new_year
from desktop_calendar.ui.theme import ThemeResolver

_MEMORIAL_NEXT_DISPLAY_MAX = 3


@dataclass(frozen=True)
class InfoParts:
    lunar_str: str | None = None
    term_text: str | None = None
    memorial_names: tuple = ()
    memorial_next: tuple = ()
    has_lunar_data: bool = False
    lunar_lib_available: bool = True
    legal_holiday_names: tuple = ()
    ordinary_holiday_names: tuple = ()
    new_year_year: int | None = None
    new_year_days: int | None = None


def _as_list(v) -> list[str]:
    if v is None or v == "无":
        return []
    if isinstance(v, (list, tuple)):
        return [x for x in v if x and x != "无"]
    return [v]


def _extract_lunar_str(lunar) -> str | None:
    if lunar is None:
        return None
    try:
        month_cn = lunar.lunarMonthCn.replace("大", "").replace("小", "")
        return f"{lunar.lunarYearCn}【{lunar.chineseYearZodiac}】 {month_cn}{lunar.lunarDayCn}"
    except Exception:
        return None


def _extract_term_text(lunar) -> str | None:
    if lunar is None:
        return None
    term = getattr(lunar, "todaySolarTerms", "")
    if isinstance(term, list) and term:
        term = term[0]
    return term if term and term != "无" else None


def _extract_holidays(lunar, solar_date: date | None) -> tuple:
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
                (legal_raw if name in RED_TEXT_SET else ordinary_raw).append(name)

        legal = tuple(dict.fromkeys(legal_raw))
        ordinary = tuple(dict.fromkeys(n for n in ordinary_raw if n not in legal))
        return legal, ordinary
    except Exception:
        return (), ()


def _coerce_int(v) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    return None


def _memorial_name(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("name") or "")
    if isinstance(item, (tuple, list)):
        return str(item[0]) if item else ""
    return str(item)


def _unpack_memorial_next(item) -> tuple:
    if isinstance(item, dict):
        return str(item.get("name") or ""), _coerce_int(item.get("days"))
    if isinstance(item, (tuple, list)):
        name = str(item[0]) if item else ""
        days = _coerce_int(item[1]) if len(item) >= 2 else None
        return name, days
    return str(item), None


def _format_memorial_names(memorial_names) -> str:
    return "、".join(_memorial_name(x) for x in memorial_names)


def _format_memorial_next(memorial_next) -> str:
    items = []
    shown = memorial_next[:_MEMORIAL_NEXT_DISPLAY_MAX]
    for raw in shown:
        name, days = _unpack_memorial_next(raw)
        if days is None:
            items.append(name)
        elif days <= 0:
            items.append(tr("info.memorial_countdown_today").format(name=name))
        else:
            items.append(tr("info.memorial_countdown_fmt").format(name=name, days=days))
    rest = len(memorial_next) - len(shown)
    if rest > 0:
        items.append(tr("info.memorial_more").format(count=rest))
    return "、".join(items)


def build_info_parts(
    memorial_names,
    lunar_obj,
    has_cnlunar: bool,
    memorial_next=(),
    solar_date: date | None = None,
    *,
    today: date | None = None,
    show_new_year_countdown: bool = True,
) -> InfoParts:
    legal, ordinary = _extract_holidays(lunar_obj, solar_date)

    new_year_year = None
    new_year_days = None
    if show_new_year_countdown:
        base = today if today is not None else date.today()
        try:
            ny = next_lunar_new_year(base)
            if ny is not None:
                new_year_year = ny.year
                new_year_days = (ny - base).days
        except Exception:
            new_year_year = None
            new_year_days = None

    return InfoParts(
        lunar_str=_extract_lunar_str(lunar_obj),
        term_text=_extract_term_text(lunar_obj),
        memorial_names=tuple(memorial_names or ()),
        memorial_next=tuple(memorial_next or ()),
        has_lunar_data=lunar_obj is not None,
        lunar_lib_available=bool(has_cnlunar),
        legal_holiday_names=legal,
        ordinary_holiday_names=ordinary,
        new_year_year=new_year_year,
        new_year_days=new_year_days,
    )


def _span(color: str, label: str, value: str) -> str:
    body = f"{html.escape(label)}：{html.escape(value)}" if label else html.escape(value)
    return f"<span style='color:{color}'>{body}</span>"


def _render_new_year(pieces: list, parts: InfoParts, resolver: ThemeResolver) -> None:
    if parts.new_year_year is None or parts.new_year_days is None:
        return
    if parts.new_year_days == 0:
        text = tr("info.new_year_date").format(year=parts.new_year_year)
    else:
        text = tr("info.new_year_days").format(year=parts.new_year_year, days=parts.new_year_days)
    # 主题缺键时由 ThemeResolver 回退 DEFAULT_THEME 的 new_year_text_color。
    color = resolver.color("new_year_text_color")
    pieces.append(_span(color, "", text))


def render_html(parts: InfoParts, resolver: ThemeResolver | None = None) -> str | None:
    if resolver is None:
        resolver = ThemeResolver(dict(DEFAULT_THEME))

    pieces = []
    if parts.lunar_str:
        pieces.append(_span(resolver.color("lunar_text_color"), "", parts.lunar_str))
    if parts.term_text:
        pieces.append(
            _span(resolver.color("solar_term_text_color"), tr("info.solar_term"), parts.term_text)
        )
    if parts.legal_holiday_names:
        pieces.append(
            _span(
                resolver.color("festival_red"),
                tr("info.festival"),
                "、".join(parts.legal_holiday_names),
            )
        )
    if parts.ordinary_holiday_names:
        pieces.append(
            _span(
                resolver.color("normal_num_color"),
                tr("info.festival"),
                "、".join(parts.ordinary_holiday_names),
            )
        )
    if parts.memorial_next:
        pieces.append(
            _span(
                resolver.color("memorial_orange"),
                tr("info.memorial"),
                _format_memorial_next(parts.memorial_next),
            )
        )
    elif parts.memorial_names:
        pieces.append(
            _span(
                resolver.color("memorial_orange"),
                tr("info.memorial"),
                _format_memorial_names(parts.memorial_names),
            )
        )

    _render_new_year(pieces, parts, resolver)

    if not pieces:
        return None
    return "&nbsp;·&nbsp;".join(pieces)


def placeholder_key(parts: InfoParts) -> str:
    if not parts.lunar_lib_available:
        return "info.no_cnlunar"
    if not parts.has_lunar_data:
        return "info.lunar_unavailable"
    return "info.no_events"


def format_weather(city: str, temperature: float, description: str) -> str:
    """Render the concise weather status used alongside the info panel."""
    return f"{city} {temperature:.0f}℃ {description}"
