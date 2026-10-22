# coding: utf-8
"""纪念日归一化、日期匹配、下次发生日期计算。"""
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
    "build_memorial_index",
]

REPEAT_YEAR = "year"
REPEAT_MONTH = "month"
REPEAT_WEEK = "week"

_VALID_REPEAT_TYPES = (REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK)
_VALID_TYPES = ("solar", "lunar")

# 农历"每年重复"搜索窗口：闰月最长间隔可达 30+ 年，5 年是常见闰月
# 密集期的折中。窗口是"单次搜索深度边界"，与 reminder_manager 的
# MAX_RETRY_PER_MEMORIAL（候选已过后的推进次数）语义正交。
_LUNAR_YEAR_LOOKAHEAD = 5
# 农历"每月重复"非闰月：13 个月足以跨过任何一年农历循环。
_LUNAR_MONTH_LOOKAHEAD = 13
# 农历"每月重复"闰月：闰月分布稀疏（19 年 7 闰），按年探测。
# 已知限制：闰月间隔可超 5 年，超出窗口返回 None。
_LUNAR_LEAP_YEAR_LOOKAHEAD = 5

_MEMORIAL_DEFAULTS = {
    "name": "",
    "type": "solar",
    "month": 1,
    "day": 1,
    "enabled": True,
    "advance_days": 0,
    "repeat_type": REPEAT_YEAR,
    "isleap": False,
}


# ===================== 基础工具 =====================
def _to_pydate(qdate) -> date:
    """统一把 QDate / datetime / date 归一化为 datetime.date。"""
    if isinstance(qdate, datetime):
        return qdate.date()
    if isinstance(qdate, date):
        return qdate
    if hasattr(qdate, "toPyDate"):
        return qdate.toPyDate()
    return date(qdate.year(), qdate.month(), qdate.day())


def _clamp_int(val, lo: int, hi: int, default: int) -> int:
    """转 int 并夹取到 [lo, hi]；转换失败返回 default。"""
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError):
        return default


# ===================== 公历匹配 =====================
def _match_solar_monthly(base_date: date, day: int) -> bool:
    """base_date 是否命中"公历每月 day"（含月末收敛）。"""
    _, last_day = calendar.monthrange(base_date.year, base_date.month)
    return base_date.day == min(day, last_day)


def _match_solar_yearly(base_date: date, month: int, day: int) -> bool:
    """base_date 是否命中"公历每年 month/day"（含月末收敛）。"""
    if base_date.month != month:
        return False
    _, last_day = calendar.monthrange(base_date.year, month)
    return base_date.day == min(day, last_day)


# ===================== 公历推进 =====================
def _next_solar_monthly(base_date: date, day: int) -> Optional[date]:
    """公历"每月重复"：返回 > base_date 的下一次。"""
    y, m = base_date.year, base_date.month
    for _ in range(2):
        target = date(y, m, min(day, calendar.monthrange(y, m)[1]))
        if target > base_date:
            return target
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def _next_solar_yearly(base_date: date, month: int, day: int) -> Optional[date]:
    for y in (base_date.year, base_date.year + 1):
        target = date(y, month, min(day, calendar.monthrange(y, month)[1]))
        if target > base_date:
            return target
    return None


def _next_week_date(base_date: date, target_weekday: int) -> date:
    """返回严格大于 base_date 的下一个目标星期（diff==0 推 7 天）。"""
    diff = (target_weekday - (base_date.weekday() + 1)) % 7 or 7
    return base_date + timedelta(days=diff)


# ===================== 农历：辅助 =====================
def _lunar_day_or_month_end(ly, lm, day, is_leap):
    """查 (农历年 ly, 正常月 lm, 是否闰月) 的 day 日；超过实际天数时收敛到月末。

    农历月最多 30 天、最少 29 天：精确 day 未命中时退到 30 / 29。
    """
    for d in dict.fromkeys((day, 30, 29)):
        g = lunar_to_gregorian(ly, lm, d, is_leap)
        if g is not None:
            return g
    return None


def _iter_leap_months(ly):
    """探测该农历年的所有闰月，返回 [(lm, 闰月初一公历日期), ...]，按公历排序。"""
    return sorted(
        ((lm, g) for lm in range(1, 13)
         if (g := lunar_to_gregorian(ly, lm, 1, True)) is not None),
        key=lambda x: x[1],
    )


def _iter_lunar_months(base_ly, base_lm, count):
    """从 (base_ly, base_lm) 起按正常月推进，产出 count 项 (ly, lm)。

    忽略闰月：闰月不会出现在序列里，与 is_leap=False 的语义一致。
    """
    for offset in range(count):
        total = base_lm + offset - 1
        yield base_ly + total // 12, total % 12 + 1


# ===================== 农历匹配 =====================
def _match_lunar(base_date, month, day, is_leap):
    """base_date 是否命中农历纪念日。month=None 表示"每月"（不比月份）。

    月末收敛：仅"每月重复"且配置 day 超过今日农历日、次日为初一时命中
    （闰月月末与正常月月末都算）。
    """
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
    if month is None and isinstance(ld, int) and day > ld:
        nxt_day = base_date + timedelta(days=1)
        nxt = get_lunar_by_datetime(
            (nxt_day.year, nxt_day.month, nxt_day.day))
        if nxt is not None and getattr(nxt, "lunarDay", None) == 1:
            return True
    return False


# ===================== 农历推进 =====================
def _next_lunar_monthly(base_date, day, is_leap):
    """农历"每月重复"：返回 > base_date 的下一次。

    is_leap=True 按农历年探测该年闰月；is_leap=False 按正常月 1..12 推进。
    """
    if not lunar_mod.HAS_CNLUNAR:
        logger.debug(f"农历每月：cnlunar 未安装，{base_date} 的纪念日无法计算")
        return None
    lunar = get_lunar_by_datetime(
        (base_date.year, base_date.month, base_date.day))
    if lunar is None:
        logger.warning(f"农历每月：基准日 {base_date} 无农历信息，无法推进")
        return None

    base_ly, base_lm = lunar.lunarYear, lunar.lunarMonth

    if is_leap:
        for ly in range(base_ly, base_ly + _LUNAR_LEAP_YEAR_LOOKAHEAD):
            for lm, _ in _iter_leap_months(ly):
                g = _lunar_day_or_month_end(ly, lm, day, True)
                if g is not None and g > base_date:
                    return g
        logger.warning(
            f"农历每月（闰月）：从 {base_date} 起 "
            f"{_LUNAR_LEAP_YEAR_LOOKAHEAD} 个农历年内"
            f"未找到闰月农历{day} 日，返回 None")
        return None

    for ly, lm in _iter_lunar_months(base_ly, base_lm, _LUNAR_MONTH_LOOKAHEAD):
        g = _lunar_day_or_month_end(ly, lm, day, False)
        if g is not None and g > base_date:
            return g
    logger.warning(
        f"农历每月（非闰月）：从 {base_date} 起 "
        f"{_LUNAR_MONTH_LOOKAHEAD} 个农历月内"
        f"未找到农历{day} 日，返回 None")
    return None


def _next_lunar_yearly(base_date: date, month: int, day: int,
                       is_leap: bool) -> Optional[date]:
    """农历"每年重复"：返回 > base_date 的下一次。"""
    if not lunar_mod.HAS_CNLUNAR:
        logger.debug(f"农历每年：cnlunar 未安装，{base_date} 的纪念日无法计算")
        return None
    start_year = base_date.year - 1
    for gy in range(start_year, start_year + _LUNAR_YEAR_LOOKAHEAD):
        g = lunar_to_gregorian(gy, month, day, is_leap)
        if g is not None and g > base_date:
            return g
    logger.warning(
        f"农历每年：从 {base_date} 起 {_LUNAR_YEAR_LOOKAHEAD} 个农历年内"
        f"未找到农历{month}月{day} 日（isleap={is_leap}），返回 None")
    return None


# ===================== 归一化 =====================
def normalize_memorial(mem: dict) -> dict:
    mem = mem.copy()
    for k, v in _MEMORIAL_DEFAULTS.items():
        if mem.get(k) is None:
            mem[k] = v

    if mem["repeat_type"] not in _VALID_REPEAT_TYPES:
        logger.warning(
            f"纪念日 repeat_type 非法：{mem['repeat_type']!r}，"
            f"已回落为 {REPEAT_YEAR}")
        mem["repeat_type"] = REPEAT_YEAR

    # 每周重复是纯公历概念
    if mem["repeat_type"] == REPEAT_WEEK and mem["type"] != "solar":
        logger.warning(
            f"纪念日 repeat_type=week 时 type 必须为 solar，"
            f"已从 {mem['type']!r} 修正为 'solar'")
        mem["type"] = "solar"

    if mem["type"] not in _VALID_TYPES:
        logger.warning(
            f"纪念日 type 非法：{mem['type']!r}，已回落为 'solar'")
        mem["type"] = "solar"

    mem["month"] = _clamp_int(mem["month"], 1, 12, 1)

    if mem["repeat_type"] == REPEAT_WEEK:
        mem["day"] = _clamp_int(mem["day"], 1, 7, 1)  # 1=周一 ~ 7=周日
    else:
        day_upper = 30 if mem["type"] == "lunar" else 31
        day = _clamp_int(mem["day"], 1, day_upper, 1)
        # 仅"公历 + 每年重复"时按实际月份天数收敛
        if mem["type"] == "solar" and mem["repeat_type"] == REPEAT_YEAR:
            try:
                last_day = calendar.monthrange(
                    REFERENCE_LEAP_YEAR, mem["month"])[1]
                day = min(day, last_day)
            except Exception:
                day = min(day, 28)
        mem["day"] = day

    # advance_days 上限 365（UI 30，但 JSON 可手改）
    mem["advance_days"] = _clamp_int(mem["advance_days"], 0, 365, 0)
    mem["enabled"] = to_bool(mem.get("enabled"), default=True)
    mem["isleap"] = (
        False
        if mem["repeat_type"] == REPEAT_WEEK or mem["type"] == "solar"
        else to_bool(mem.get("isleap"), default=False)
    )
    return mem


def normalize_memorial_days(value: Any) -> tuple[list, int]:
    """对 memorial_days 做归一化，返回 (归一化列表, 跳过的条数)。"""
    if not isinstance(value, list):
        logger.warning(
            f"memorial_days 类型异常（{type(value).__name__}），按空列表处理")
        return [], 0

    result: list = []
    skipped = 0
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            logger.warning(f"memorial_days[{i}] 非 dict，已跳过：{item!r}")
            skipped += 1
            continue
        try:
            result.append(normalize_memorial(item))
        except Exception as e:
            logger.warning(f"memorial_days[{i}] 归一化失败，已跳过：{e}")
            skipped += 1
    if skipped:
        logger.info(
            f"memorial_days 归一化：保留 {len(result)} 条，跳过 {skipped} 条")
    return result, skipped


# ===================== 对外：日期计算 =====================
def get_next_memorial_date(mem, base_date, include_base=False,
                           normalized=False):
    """下次发生日期。

    :param normalized: 若调用方已 normalize 过，传 True 跳过重复 normalize。
    """
    if base_date is None:
        return None
    base_date = _to_pydate(base_date)

    if not normalized:
        mem = normalize_memorial(mem)

    rep = mem["repeat_type"]
    day = mem["day"]
    is_solar = mem["type"] == "solar"

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
        return _next_lunar_monthly(base_date, day, mem["isleap"])

    # REPEAT_YEAR
    if is_solar:
        if include_base and _match_solar_yearly(base_date, mem["month"], day):
            return base_date
        return _next_solar_yearly(base_date, mem["month"], day)
    if include_base and _match_lunar(
            base_date, mem["month"], day, mem["isleap"]):
        return base_date
    return _next_lunar_yearly(base_date, mem["month"], day, mem["isleap"])


def match_memorial_date(mem, base_date, normalized=False):
    """判断 base_date 是否命中该纪念日（含收敛语义）。"""
    if base_date is None:
        return False
    base_date = _to_pydate(base_date)
    if not normalized:
        mem = normalize_memorial(mem)
    target = get_next_memorial_date(
        mem, base_date, include_base=True, normalized=True)
    return target == base_date


# ===================== 对外：索引构建 =====================
def build_memorial_index(memorial_list) -> Dict[str, Dict[Any, List[dict]]]:
    """构建五个桶：solar_year / solar_month / solar_week / lunar_year / lunar_month。"""
    idx: Dict[str, Dict[Any, List[dict]]] = {
        "solar_year": {}, "solar_month": {}, "solar_week": {},
        "lunar_year": {}, "lunar_month": {},
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
        day = mem.get("day")
        month = mem.get("month")
        if rep is None or typ is None or day is None:
            continue

        if rep == REPEAT_WEEK:
            idx["solar_week"].setdefault(day, []).append(mem)
        elif typ == "solar":
            if rep == REPEAT_YEAR:
                if month is None:
                    continue
                idx["solar_year"].setdefault((month, day), []).append(mem)
            else:
                idx["solar_month"].setdefault(day, []).append(mem)
        else:
            leap = bool(mem.get("isleap", False))
            if rep == REPEAT_YEAR:
                if month is None:
                    continue
                idx["lunar_year"].setdefault(
                    (month, day, leap), []).append(mem)
            else:
                idx["lunar_month"].setdefault((day, leap), []).append(mem)
    return idx