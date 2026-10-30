# coding: utf-8
"""纪念日归一化、日期匹配、下次发生日期计算。"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.lunar import get_lunar_by_datetime, lunar_to_gregorian
from desktop_calendar.utils.coerce import to_bool
from desktop_calendar.utils.logging_setup import get_logger
from desktop_calendar.config.constants import REFERENCE_LEAP_YEAR

logger = get_logger()

__all__ = [
    "REPEAT_YEAR", "REPEAT_MONTH", "REPEAT_WEEK",
    "normalize_memorial", "normalize_memorial_days",
    "get_next_memorial_date", "match_memorial_date",
    "build_memorial_index", "REPEAT_ONCE",
]

REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK = "year", "month", "week"
REPEAT_ONCE = "once"
_VALID_REPEAT_TYPES = (REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK, REPEAT_ONCE)
_VALID_TYPES = ("solar", "lunar")

# 农历搜索窗口。
# - 正常月年度/月度重复：每年都有该月，5 年 / 13 个月足够。
# - 闰月重复：闰月大周期为 19 年（7 闰），罕见闰月（闰九月等）
#   间隔可达 38 年。这里取 19 年覆盖绝大多数情况；更罕见的间隔
#   仍可能漏提醒，UI 侧 AddMemorialDialog 已有 memorial.warn_leap_rare
#   的告知弹窗。
_LUNAR_YEAR_LOOKAHEAD = 5
_LUNAR_MONTH_LOOKAHEAD = 13
_LUNAR_LEAP_YEAR_LOOKAHEAD = 19

_warned_leap_no_next: set = set()
_LEAP_WARN_LIMIT = 200

_MEMORIAL_DEFAULTS = {
    "name": "", "type": "solar", "month": 1, "day": 1,
    "enabled": True, "advance_days": 0, "repeat_type": REPEAT_YEAR,
    "isleap": False,
}


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
        raise TypeError(
            f"不支持的日期类型: {type(qdate).__name__}") from exc


def _clamp_int(val, lo: int, hi: int, default: int) -> int:
    """把 val 收敛到 [lo, hi]；非数值返回 default。

    OverflowError 单独列出：int(float('inf')) 抛 OverflowError 而非
    ValueError（json.load 的 parse_constant 会把 Infinity/NaN 解析为
    float，用户的 config.json 里手写 Infinity 会走到这里）。
    """
    try:
        v = int(val)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, v))


# ===================== 公历 =====================
def _match_solar_monthly(d: date, day: int) -> bool:
    _, last = calendar.monthrange(d.year, d.month)
    return d.day == min(day, last)


def _match_solar_yearly(d: date, month: int, day: int) -> bool:
    if d.month != month:
        return False
    _, last = calendar.monthrange(d.year, month)
    return d.day == min(day, last)


def _next_solar_monthly(d: date, day: int) -> Optional[date]:
    y, m = d.year, d.month
    for _ in range(2):
        target = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        if target > d:
            return target
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def _next_solar_yearly(d: date, month: int, day: int) -> Optional[date]:
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
        ((lm, g) for lm in range(1, 13)
         if (g := lunar_to_gregorian(ly, lm, 1, True)) is not None),
        key=lambda x: x[1])


def _iter_lunar_months(base_ly, base_lm, count):
    """从 (base_ly, base_lm) 按正常月推进，忽略闰月。"""
    for offset in range(count):
        total = base_lm + offset - 1
        yield base_ly + total // 12, total % 12 + 1


def _match_lunar(base_date, month, day, is_leap):
    lunar = get_lunar_by_datetime(
        (base_date.year, base_date.month, base_date.day))
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
    lunar = get_lunar_by_datetime(
        (base_date.year, base_date.month, base_date.day))
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


# _next_lunar_yearly：day=30 遇小月时 lunar_to_gregorian 返回 None，
# 该年静默漏提醒；与 monthly 路径的 _lunar_day_or_month_end 收敛不一致。
def _next_lunar_yearly(base_date, month, day, is_leap):
    if not lunar_mod.HAS_CNLUNAR:
        return None
    # 起算点必须用农历年：_lunar_day_or_month_end 内部走
    # lunar_to_gregorian(ly, ...)，ly 语义是农历年（_build_lunar_index
    # 按 lunarYear == ly 过滤）。历史实现用 base_date.year - 1（公历年）
    # 传入，依赖 lookahead 足够宽才"碰巧"命中：
    #   1. 公历 1~2 月（农历上一年腊月）时起点早 1 年，多迭代一次；
    #   2. 与 _next_lunar_monthly 用 base_ly 的写法不一致；
    #   3. 若未来缩小 lookahead，会静默漏提醒。
    base_lunar = get_lunar_by_datetime(base_date)
    if base_lunar is None:
        # 农历库可用但转换失败（cnlunar 内部异常等）：退回公历近似起点，
        # 保持原有可用性，不因农历转换失败而彻底不提醒。
        base_ly = base_date.year - 1
    else:
        base_ly = int(base_lunar.lunarYear)

    lookahead = (_LUNAR_LEAP_YEAR_LOOKAHEAD if is_leap
                 else _LUNAR_YEAR_LOOKAHEAD)
    for ly in range(base_ly, base_ly + lookahead):
        # 用 _lunar_day_or_month_end 收敛 day=30 遇小月的情况，
        # 与 _next_lunar_monthly 的路径保持一致。
        g = _lunar_day_or_month_end(ly, month, day, is_leap)
        if g is not None and g > base_date:
            return g
    return None



# ===================== 归一化 =====================
def normalize_memorial(mem: dict) -> dict:
    mem = mem.copy()
    for k, v in _MEMORIAL_DEFAULTS.items():
        if mem.get(k) is None:
            mem[k] = v

    if mem["repeat_type"] not in _VALID_REPEAT_TYPES:
        mem["repeat_type"] = REPEAT_YEAR
    # once 与 week 一样只支持公历：强制 type=solar，避免农历/闰月分支
    if mem["repeat_type"] in (REPEAT_WEEK, REPEAT_ONCE) and mem["type"] != "solar":
        mem["type"] = "solar"
    if mem["type"] not in _VALID_TYPES:
        mem["type"] = "solar"

    mem["month"] = _clamp_int(mem["month"], 1, 12, 1)

    if mem["repeat_type"] == REPEAT_WEEK:
        mem["day"] = _clamp_int(mem["day"], 1, 7, 1)
    elif mem["repeat_type"] == REPEAT_ONCE:
        # once 的 year 必须落在可处理范围内；上限 2100 足够覆盖纪念日场景
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
        False if mem["repeat_type"] in (REPEAT_WEEK, REPEAT_ONCE)
        or mem["type"] == "solar"
        else to_bool(mem.get("isleap"), default=False)
    )
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
        logger.debug("memorial_days 归一化：保留 %d 条，跳过 %d 条",
                     len(result), skipped)
    return result, skipped


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
    """闰月纪念日在 lookahead 窗口内无对应闰月时记一条 info。

    去重原因：get_next_memorial_date 在 MemorialDialog._sort_by_date
    等路径被高频调用，同一闰月纪念日会反复触发。按 (name, month, day)
    去重，上限 200 条后清空（用户批量导入时不会无限增长）。
    """
    key = (mem.get("name") or "", mem.get("month"), mem.get("day"))
    if key in _warned_leap_no_next:
        return
    if len(_warned_leap_no_next) >= _LEAP_WARN_LIMIT:
        _warned_leap_no_next.clear()
    _warned_leap_no_next.add(key)
    logger.info(
        "闰月纪念日 %r（%s 月 %s 日，闰）在未来 %d 年内无对应闰月，"
        "本次不返回下次日期。罕见闰月（间隔可达 38 年）属预期行为；"
        "若用户反馈漏提醒，检查 _LUNAR_LEAP_YEAR_LOOKAHEAD。",
        mem.get("name") or "<unnamed>",
        mem.get("month", "?"), mem.get("day", "?"),
        _LUNAR_LEAP_YEAR_LOOKAHEAD)

def match_memorial_date(mem, base_date, normalized=False):
    if base_date is None:
        return False
    base_date = _to_pydate(base_date)
    if not normalized:
        mem = normalize_memorial(mem)
    return get_next_memorial_date(
        mem, base_date, include_base=True, normalized=True) == base_date


def _index_int(val, lo: int, hi: int):
    """把索引键归一化为 [lo, hi] 内的 int；非数值返回 None。

    与 normalize_memorial._clamp_int 的区别：非数值不补默认值，而是
    返回 None 让调用方跳过该条。这里保持「不合规就跳过」的过滤语义，
    与现有 `if ... day is None: continue` 的意图一致。
    """
    try:
        v = int(val)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(lo, min(hi, v))


def build_memorial_index(memorial_list) -> Dict[str, Dict[Any, List[dict]]]:
    idx: Dict[str, Dict[Any, List[dict]]] = {
        "solar_year": {}, "solar_month": {}, "solar_week": {},
        "lunar_year": {}, "lunar_month": {},
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

        # 索引键必须与查询端类型一致（int）且范围合法：
        # cell_presenter 用 qdate.day() / month() / dayOfWeek()（int）查询，
        # 用 lunar.lunarMonth / lunarDay（int）查询。索引键若是字符串或
        # 越界值，查询时 dict.get 静默返回 None，纪念日不显示。
        # 注意：这里**不做** calendar.monthrange 收敛——索引端必须保留
        # 原始 day，由查询端的月末收敛逻辑（遍历 [last+1, 31]）兜底；
        # 若在此把 day=30 收敛成 29，非闰年 3 月 30 日的查询就会漏。
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