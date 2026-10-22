# coding: utf-8
"""
农历 / 节假日 / 公农历互转。

依赖：
- chinese_calendar：可选，节假日 / 工作日判断。
- cnlunar：可选，农历转换。

未安装依赖时降级，不抛导入错误。
"""

from __future__ import annotations
import threading
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from desktop_calendar.utils.logging_setup import get_logger

logger = get_logger()

__all__ = [
    "HAS_CHINESE_CAL",
    "HAS_CNLUNAR",
    "is_holiday",
    "is_workday",
    "get_lunar_by_datetime",
    "lunar_to_gregorian",
    "qdate_to_pydate",
    "clear_lunar_caches",
    "warmup_lunar_index",
    "warmup_lunar_index_async",
]

DateLike = Union[date, datetime, Tuple[int, int, int], List[int]]
LunarKey = Tuple[int, int, bool]


# ===================== 节假日本地库 =====================
HAS_CHINESE_CAL: bool

try:
    from chinese_calendar import is_holiday as _cc_is_holiday
    from chinese_calendar import is_workday as _cc_is_workday
    HAS_CHINESE_CAL = True
except Exception:  # noqa: BLE001
    logger.warning("未安装或加载 chinese_calendar 失败，使用周末降级判断")
    HAS_CHINESE_CAL = False

def _to_date(d: Any) -> date:
    """把 chinese_calendar 可接受的日期输入归一化为 datetime.date。

    bool 是 int 子类，必须优先拦截 —— 否则 `date(True, True, True)` 会
    被解释为 `date(1, 1, 1)`，语义上明显是误用。
    """
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


def _cc_or_fallback(
    cc_func: Optional[Callable[..., bool]],
    fallback_func: Callable[[Any], bool],
    name: str,
    d: Any, *args: Any, **kwargs: Any,
) -> bool:
    """chinese_calendar 可用时优先；其抛异常（如超出内置数据库范围）
    时降级到 fallback。

    两个公开入口（is_holiday / is_workday）唯一差异是 cc_func / name，
    合并到此处可避免两处降级日志措辞漂移。
    """
    if HAS_CHINESE_CAL and cc_func is not None:
        try:
            return bool(cc_func(d, *args, **kwargs))
        except Exception:
            logger.debug(
                "chinese_calendar.%s 降级 date=%r", name, d, exc_info=True)
    return fallback_func(d)

def is_holiday(d: Any, *args: Any, **kwargs: Any) -> bool:
    return _cc_or_fallback(
        _cc_is_holiday if HAS_CHINESE_CAL else None,
        _fallback_is_holiday, "is_holiday", d, *args, **kwargs)

def is_workday(d: Any, *args: Any, **kwargs: Any) -> bool:
    return _cc_or_fallback(
        _cc_is_workday if HAS_CHINESE_CAL else None,
        _fallback_is_workday, "is_workday", d, *args, **kwargs)

try:
    import cnlunar
    HAS_CNLUNAR = True
except Exception:  # noqa: BLE001
    logger.warning("未安装或加载 cnlunar 失败，农历功能不可用")
    HAS_CNLUNAR = False
    cnlunar = None  # type: ignore[assignment]

def get_lunar_by_datetime(dt: DateLike) -> Optional[Any]:
    """获取公历日期对应的农历对象。HAS_CNLUNAR 检查放在这里
    （不做缓存的入口），使 monkeypatch 后无需清缓存即可生效。
    """
    if not HAS_CNLUNAR:
        return None
    try:
        d = _to_date(dt)
    except (TypeError, ValueError) as e:
        logger.warning(
            "get_lunar_by_datetime 参数非法: %r (%s)", dt, e)
        return None
    return _get_lunar_cached(d.year, d.month, d.day)

# ===================== 农历缓存 =====================
@lru_cache(maxsize=4096)
def _get_lunar_cached(y: int, m: int, d: int) -> Optional[Any]:
    """
    按公历年月日缓存农历对象。失败返回 None。

    本函数不检查 HAS_CNLUNAR —— 该判断由不做缓存的入口承担，避免
    "无库时返回的 None"被缓存后，运行时 monkeypatch HAS_CNLUNAR=True
    仍拿到旧值。两个入口：
      - get_lunar_by_datetime（检查 HAS_CNLUNAR）
      - _build_lunar_index（由调用方 lunar_to_gregorian 检查）
    """
    if cnlunar is None:
        return None
    try:
        return cnlunar.Lunar(datetime(y, m, d), godType="8char")
    except Exception:  # noqa: BLE001
        logger.debug("农历转换降级 date=(%s, %s, %s)", y, m, d, exc_info=True)
        return None

@lru_cache(maxsize=64)
def _build_lunar_index(lunar_year: int) -> Dict[LunarKey, date]:
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
                key = (
                    int(getattr(lunar, "lunarMonth")),
                    int(getattr(lunar, "lunarDay")),
                    bool(getattr(lunar, "isLunarLeapMonth", False)),
                )
            except (AttributeError, TypeError, ValueError):
                current += timedelta(days=1)
                continue
            index.setdefault(key, current)
        current += timedelta(days=1)
    return index


@lru_cache(maxsize=1024)
def lunar_to_gregorian(
    lunar_year: int,
    lunar_month: int,
    lunar_day: int,
    is_leap_month: bool = False,
) -> Optional[date]:
    """
    农历转公历。
    :return: 对应公历 date；依赖不可用或找不到时返回 None
    """
    if not HAS_CNLUNAR:
        return None

    try:
        y, m, d = int(lunar_year), int(lunar_month), int(lunar_day)
    except (TypeError, ValueError):
        logger.warning(
            "lunar_to_gregorian 参数无法转为整数: %r",
            (lunar_year, lunar_month, lunar_day))
        return None

    if not (1 <= m <= 12 and 1 <= d <= 30):
        return None

    index = _build_lunar_index(y)
    return index.get((m, d, bool(is_leap_month)))

def qdate_to_pydate(qdate: Any) -> date:
    """
    :raises TypeError: qdate 为 None 或缺少 year/month/day 方法
    :raises ValueError: 年月日不合法
    """
    if qdate is None:
        raise TypeError("qdate 不能为 None")
    try:
        return date(int(qdate.year()), int(qdate.month()), int(qdate.day()))
    except AttributeError as exc:
        raise TypeError(f"qdate 不是有效的 QDate: {type(qdate).__name__}") from exc

def clear_lunar_caches() -> None:
    """
    清空农历相关的 LRU 缓存。

    - 测试中 monkeypatch lunar.HAS_CNLUNAR 后需要让新状态彻底生效
    （入口已做 HAS_CNLUNAR 检查，但缓存里若已有"无库前"的 None 条目，
    翻回 True 后仍会命中旧 None）；
    """
    _get_lunar_cached.cache_clear()
    _build_lunar_index.cache_clear()
    lunar_to_gregorian.cache_clear()
    
def warmup_lunar_index(years) -> None:
    """
    预热农历年索引。用于程序启动后异步把当年（及相邻年）的
    "农历月/日/是否闰月 -> 公历 date" 索引构建好，避免用户首次
    翻页 / 打开月份选择器 / 触发纪念日计算时卡顿。

    一次索引构建约扫描 415 天，单线程下耗时数百毫秒；放在
    QTimer.singleShot(0, ...) 里跑不会阻塞窗口显示。

    失败静默：预热只是优化，cnlunar 不可用或异常时应让调用方
    的正式路径去处理（正式路径有完整的降级）。
    """
    if not HAS_CNLUNAR:
        return
    for y in years:
        try:
            _build_lunar_index(int(y))
        except Exception:
            logger.debug("农历索引预热失败 year=%r", y, exc_info=True)
            
def warmup_lunar_index_async(
    years, *, on_done: Optional[Callable[[], None]] = None,
) -> Optional[threading.Thread]:
    """后台 daemon 线程预热农历年索引，立即返回。

    为什么用 threading.Thread 而非 QThread：
      - 预热是纯 CPU 短任务（每年约 100–500ms），QThread 的构造/销毁
        与信号连接开销与之相比不划算；
      - 预热不与主线程交互、无需 Qt 事件循环参与，daemon 线程跑完
        即自然结束；
      - daemon=True：进程退出时若尚未完成，直接丢弃。lru_cache 的
        缓存写入是原子性的（单 key 单次写），强杀不会破坏状态。

    并发安全：
      - `_build_lunar_index` / `_get_lunar_cached` 均为 lru_cache 包装，
        CPython 内部持锁，主线程与预热线程可安全并行访问；
      - 同一 key 的并发 miss 会各自完整计算一次，最后写入值确定
        （cnlunar 转换确定性），只是浪费一点 CPU，不影响正确性。

    失败静默：预热只是优化；cnlunar 不可用或异常时，正式路径
    （`lunar_to_gregorian` / `get_lunar_by_datetime`）会各自降级。

    GIL 说明：cnlunar 是纯 Python，预热线程会与主线程争 GIL。因
    预热窗口通常在窗口展示后几百毫秒，用户首次交互前基本已完成，
    主线程感知到的额外延迟可忽略。若未来预热范围扩大（如一次
    预热 5 年），应改为分片（每年一 tick）或在年与年之间主动
    让出 GIL，届时再评估。

    :param years: 需要预热的年份序列（int 可转）。
    :param on_done: 可选回调，预热结束后在后台线程里调用。调用方
        如需切回主线程，自行用 ``QTimer.singleShot(0, ...)`` 或信号。
        回调抛异常仅记 debug，不影响预热结果。
    :return: 已启动的线程对象；无预热需求（HAS_CNLUNAR=False 或
        years 为空 / 全部非法）时返回 None。
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
            logger.debug(
                "农历索引异步预热异常 years=%r", year_list, exc_info=True)
        finally:
            if on_done is not None:
                try:
                    on_done()
                except Exception:
                    logger.debug("农历预热完成回调异常", exc_info=True)

    t = threading.Thread(
        target=_run, name="LunarWarmup", daemon=True)
    t.start()
    return t