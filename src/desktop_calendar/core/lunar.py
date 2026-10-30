# coding: utf-8
"""农历 / 节假日 / 公农历互转。依赖不可用时降级，不抛导入错误。"""
from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from desktop_calendar.utils.logging_setup import get_logger

logger = get_logger()

__all__ = [
    "HAS_CHINESE_CAL", "HAS_CNLUNAR",
    "is_holiday", "is_workday",
    "get_lunar_by_datetime", "lunar_to_gregorian",
    "qdate_to_pydate", "clear_lunar_caches",
    "warmup_lunar_index", "warmup_lunar_index_async",
    "is_new_year_eve",
]

DateLike = Union[date, datetime, Tuple[int, int, int], List[int]]
LunarKey = Tuple[int, int, bool]


# ===================== 节假日 =====================
try:
    from chinese_calendar import is_holiday as _cc_is_holiday
    from chinese_calendar import is_workday as _cc_is_workday
    HAS_CHINESE_CAL = True
except Exception:
    logger.warning("未安装或加载 chinese_calendar 失败，使用周末降级判断")
    HAS_CHINESE_CAL = False


def _to_date(d: Any) -> date:
    """归一化为 datetime.date。bool 是 int 子类，必须优先拦截。"""
    if isinstance(d, bool):
        raise TypeError("bool 不是有效日期")
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, (tuple, list)) and len(d) == 3:
        return date(int(d[0]), int(d[1]), int(d[2]))
    raise TypeError(f"不支持的日期类型: {type(d).__name__}")


def _fallback_is_holiday(d: Any) -> bool:
    return _to_date(d).weekday() >= 5


def _fallback_is_workday(d: Any) -> bool:
    return _to_date(d).weekday() < 5


def _cc_or_fallback(cc_func, fallback_func, name, d, *args, **kwargs) -> bool:
    if HAS_CHINESE_CAL and cc_func is not None:
        try:
            return bool(cc_func(d, *args, **kwargs))
        except Exception:
            logger.debug("chinese_calendar.%s 降级 date=%r", name, d, exc_info=True)
    return fallback_func(d)


def is_holiday(d: Any, *args, **kwargs) -> bool:
    return _cc_or_fallback(
        _cc_is_holiday if HAS_CHINESE_CAL else None,
        _fallback_is_holiday, "is_holiday", d, *args, **kwargs)


def is_workday(d: Any, *args, **kwargs) -> bool:
    return _cc_or_fallback(
        _cc_is_workday if HAS_CHINESE_CAL else None,
        _fallback_is_workday, "is_workday", d, *args, **kwargs)


# ===================== 农历 =====================
try:
    import cnlunar
    HAS_CNLUNAR = True
except Exception:
    logger.warning("未安装或加载 cnlunar 失败，农历功能不可用")
    HAS_CNLUNAR = False
    cnlunar = None


def get_lunar_by_datetime(dt: DateLike) -> Optional[Any]:
    if not HAS_CNLUNAR:
        return None
    try:
        d = _to_date(dt)
    except (TypeError, ValueError) as e:
        logger.warning("get_lunar_by_datetime 参数非法: %r (%s)", dt, e)
        return None
    return _get_lunar_cached(d.year, d.month, d.day)


@lru_cache(maxsize=512)
def _get_lunar_cached(y: int, m: int, d: int) -> Optional[Any]:
    if cnlunar is None:
        return None
    try:
        return cnlunar.Lunar(datetime(y, m, d), godType="8char")
    except Exception:
        logger.debug("农历转换降级 date=(%s, %s, %s)", y, m, d, exc_info=True)
        return None

def is_new_year_eve(lunar, solar_date: date) -> bool:
    """除夕判定：腊月且次日为正月初一（非闰月）。

    参数约定：lunar 与 solar_date 必须对应同一天。

    实现取舍：
      - 先查 lunar 的"腊月且非闰"做快速短路，避免每个非腊月日期
        都白跑一次 get_lunar_by_datetime；
      - 权威判定用次日农历，不依赖 lunar 自己的字段——若调用方
        传错 lunar（例如传成昨天的），快速短路可能放过，但次日
        查询会兜住，不会误报。
      - date(9999,12,31)+1 会 OverflowError；日历选中范围理论上
        到不了，但 info_panel 由 UI 层透传 sel_date，防御一下。
    """
    if lunar is None or solar_date is None:
        return False
    if bool(getattr(lunar, "isLunarLeapMonth", False)):
        return False
    if getattr(lunar, "lunarMonth", 0) != 12:
        return False
    try:
        nxt_date = solar_date + timedelta(days=1)
    except (OverflowError, TypeError):
        return False
    nxt = get_lunar_by_datetime(
        (nxt_date.year, nxt_date.month, nxt_date.day))
    if nxt is None:
        return False
    return (getattr(nxt, "lunarMonth", None) == 1
            and not bool(getattr(nxt, "isLunarLeapMonth", False))
            and getattr(nxt, "lunarDay", None) == 1)
    
_INDEX_CACHE_MAX = 16
_index_cache: "OrderedDict[int, Dict[LunarKey, date]]" = OrderedDict()
_index_locks: Dict[int, threading.Lock] = {}
_index_meta_lock = threading.Lock()


def _get_index_lock(lunar_year: int) -> threading.Lock:
    with _index_meta_lock:
        lock = _index_locks.get(lunar_year)
        if lock is None:
            lock = threading.Lock()
            _index_locks[lunar_year] = lock
        return lock


def _build_lunar_index(lunar_year: int) -> Dict[LunarKey, date]:
    with _index_meta_lock:
        cached = _index_cache.get(lunar_year)
        if cached is not None:
            _index_cache.move_to_end(lunar_year)
            return cached

    with _get_index_lock(lunar_year):
        # 二次检查：等锁期间其他线程可能已构建完成
        with _index_meta_lock:
            cached = _index_cache.get(lunar_year)
            if cached is not None:
                _index_cache.move_to_end(lunar_year)
                return cached

        result = _compute_lunar_index(lunar_year)

        with _index_meta_lock:
            _index_cache[lunar_year] = result
            _index_cache.move_to_end(lunar_year)
            while len(_index_cache) > _INDEX_CACHE_MAX:
                _index_cache.popitem(last=False)
        return result


def _compute_lunar_index(lunar_year: int) -> Dict[LunarKey, date]:
    """构建单农历年的 (月, 日, 闰) → 公历日 索引。

    扫描范围 [lunar_year-01-05, (lunar_year+1)-02-25]：农历正月初一
    最早 1 月 21 日、最晚 2 月 20 日；腊月三十最晚次年 2 月 19 日。
    范围覆盖全年且留有余量。
    """
    index: Dict[LunarKey, date] = {}
    try:
        start_date = date(lunar_year, 1, 5)
        end_date = date(lunar_year + 1, 2, 25)
    except ValueError:
        logger.warning("农历年份超出可处理范围: %s", lunar_year)
        return {}

    current = start_date
    while current <= end_date:
        lunar = _get_lunar_cached(current.year, current.month, current.day)
        if lunar is not None and getattr(lunar, "lunarYear", None) == lunar_year:
            try:
                key = (int(lunar.lunarMonth), int(lunar.lunarDay),
                       bool(lunar.isLunarLeapMonth))
            except (AttributeError, TypeError, ValueError):
                current += timedelta(days=1)
                continue
            index.setdefault(key, current)
        current += timedelta(days=1)
    return index


@lru_cache(maxsize=1024)
def lunar_to_gregorian(lunar_year: int, lunar_month: int, lunar_day: int,
                       is_leap_month: bool = False) -> Optional[date]:
    if not HAS_CNLUNAR:
        return None
    try:
        y, m, d = int(lunar_year), int(lunar_month), int(lunar_day)
    except (TypeError, ValueError):
        logger.warning("lunar_to_gregorian 参数无法转为整数: %r",
                       (lunar_year, lunar_month, lunar_day))
        return None
    if not (1 <= m <= 12 and 1 <= d <= 30):
        return None
    return _build_lunar_index(y).get((m, d, bool(is_leap_month)))


def qdate_to_pydate(qdate: Any) -> date:
    if qdate is None:
        raise TypeError("qdate 不能为 None")
    try:
        return date(int(qdate.year()), int(qdate.month()), int(qdate.day()))
    except AttributeError as exc:
        raise TypeError(f"qdate 不是有效的 QDate: {type(qdate).__name__}") from exc


def clear_lunar_caches() -> None:
    """清空农历相关缓存。仅供测试 / 手动调试，生产路径不调用。

    注意：_index_locks 有意不清——Lock 对象无外部状态，清理会导致
    正在等锁的线程永久阻塞（锁被替换后没人释放）。保留的 Lock 在
    下次构建时复用，无副作用。
    """
    _get_lunar_cached.cache_clear()
    lunar_to_gregorian.cache_clear()
    with _index_meta_lock:
        _index_cache.clear()


def warmup_lunar_index(years) -> None:
    if not HAS_CNLUNAR:
        return
    for y in years:
        try:
            _build_lunar_index(int(y))
        except Exception:
            logger.debug("农历索引预热失败 year=%r", y, exc_info=True)


def warmup_lunar_index_async(years, *, on_done: Optional[Callable[[], None]] = None,
                             ) -> Optional[threading.Thread]:
    """后台 daemon 线程预热农历索引，立即返回。

    - 预热是纯 CPU 短任务，QThread 开销不划算；
    - daemon=True：进程退出时丢弃；
    - _build_lunar_index 是 single-flight 的，主线程同时命中同一
      lunar_year 时只会算一次；
    - 失败静默：正式路径有完整降级。
    """
    if not HAS_CNLUNAR:
        return None

    year_list: List[int] = []
    for y in years or ():
        try:
            year_list.append(int(y))
        except (TypeError, ValueError):
            logger.debug("warmup_lunar_index_async 跳过非法年份 %r", y)
    if not year_list:
        return None

    def _run() -> None:
        try:
            warmup_lunar_index(year_list)
        except Exception:
            logger.debug("农历索引异步预热异常 years=%r", year_list, exc_info=True)
        finally:
            if on_done is not None:
                try:
                    on_done()
                except Exception:
                    logger.debug("农历预热完成回调异常", exc_info=True)

    t = threading.Thread(target=_run, name="LunarWarmup", daemon=True)
    t.start()
    return t