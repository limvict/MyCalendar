# coding: utf-8

from __future__ import annotations
from datetime import datetime

from PyQt6.QtCore import QObject, QDate, QTimer

from desktop_calendar.contracts.holiday_source import HolidaySourceFactory, HolidaySourceError
from desktop_calendar.config.manager import (
    ConfigManager, load_holiday_cache, save_holiday_cache, get_logger,
)
from desktop_calendar.contracts.event_bus import  EventType, event_bus


logger = get_logger()


class HolidayManager(QObject):
    """节假日数据管理：缓存、数据源拉取、自动刷新、过期清理。

    网络实现由装配层通过 source_factory 注入，core 不 import 任何
    Qt 网络代码。数据源不可用时静默降级为纯本地缓存。
    """
    # 当年 / 往年数据：一年仅变化数次，30 天过期在离线场景下仍能保留
    # 全部法定节假日/调休标记，避免退化为纯周末判断（本地 chinese_calendar
    # 仅覆盖其发布年份）。30 天足够容忍短期离线，又不至于让缓存
    # 永久滞留错误数据 —— 在线时 24 小时一次的刷新会持续更新 ts。
    CACHE_EXPIRE_SEC = 30 * 24 * 3600

    # 未来年份数据：官方发布即冻结（元旦/春节/调休安排一旦发布不会
    # 再改），无需 30 天强制刷新。365 天足够长，保证用户从"发布年"
    # 用到"成为当年"之前始终有效；成为当年后自动切换回 30 天策略，
    # 由 24h 刷新定时器持续更新 ts。
    #
    # 典型场景：2027 数据于 2026-11-05 发布，用户 2026-11-11 手动写入
    # 或网络拉取。若沿用 30 天策略，2026-12-11 之后数据被清，用户在
    # 2027 年 1 月看到元旦/春节全部丢失。365 天策略覆盖到 2027-11 之前
    # 都有效，成为当年后由在线刷新接管。
    FUTURE_YEAR_EXPIRE_SEC = 365 * 24 * 3600

    REFRESH_INTERVAL_MS = 24 * 60 * 60 * 1000  # 24 小时刷新

    def __init__(self, config: ConfigManager,
                 source_factory: HolidaySourceFactory):
        super().__init__()
        self.config = config
        self.holiday_cache = load_holiday_cache()
        self._has_notified_error = False
        self._shutting_down = False
        self._source = None
        self._orphan_source = None
        if callable(source_factory):
            try:
                self._source = source_factory(
                    on_ready=self._on_net_ready,
                    on_error=self._on_net_error,
                    parent=self,
                )
            except Exception:
                logger.warning(
                    "HolidaySource 工厂构造失败，节假日将只用本地缓存",
                    exc_info=True)
        elif source_factory is not None:
            logger.warning(
                "HolidaySource 工厂不可调用（%s），节假日将只用本地缓存",
                type(source_factory).__name__)

        started = False
        if self._source is not None:
            try:
                started = bool(self._source.start())
            except Exception:
                logger.warning("HolidaySource.start 失败", exc_info=True)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self.fetch_current_year)
        if started:
            self._refresh_timer.start()

    def apply_cached(self, *, save: bool = True) -> dict:
        """清理过期缓存并返回有效节假日数据。

        返回合并后的 dict；缓存全部失效 / 为空时返回空 dict（绝不返回 None）。
        过期清理只在循环外统一执行，且仅在确实删掉条目时落盘，
        避免主窗口启动时无谓写盘。

        过期策略按"未来 / 当年或往年"分级：
          - 未来年份：官方发布即冻结，365 天内不清理（FUTURE_YEAR_EXPIRE_SEC）；
          - 当年 / 往年：30 天内有效（CACHE_EXPIRE_SEC），由在线刷新续期。

        `year_str` 非整数（如手工编辑写错的 "bad"）时按当年处理，走
        30 天过期，避免脏数据永久滞留。
        """
        all_days: dict = {}
        now_ts = datetime.now().timestamp()
        current_year = datetime.now().year
        expired: list = []

        for year_str, year_data in self.holiday_cache.items():
            if not isinstance(year_data, dict):
                expired.append(year_str)
                continue
            days = year_data.get("days")
            ts = year_data.get("ts")
            if not isinstance(days, dict) or not isinstance(ts, (int, float)):
                expired.append(year_str)
                continue

            try:
                year_int = int(year_str)
            except (TypeError, ValueError):
                year_int = current_year

            expire_sec = (
                self.FUTURE_YEAR_EXPIRE_SEC
                if year_int > current_year
                else self.CACHE_EXPIRE_SEC
            )
            if now_ts - ts > expire_sec:
                expired.append(year_str)
                continue
            all_days.update(days)

        if expired:
            for year_str in expired:
                self.holiday_cache.pop(year_str, None)
            if save:
                save_holiday_cache(self.holiday_cache)

        return all_days

    def fetch_current_year(self):
        """拉取当年节假日，11 月起自动预取下一年。

        国务院通常于 11 月上旬发布次年安排（如 2027 年安排于
        2026-11-05 发布）。原实现只在 12 月预取，11 月存在空窗；
        改为 11 月起即预取，用户 11 月切换年视图时即可看到次年数据。

        request() 内部对"同年在途 / 已 shutdown"返回 False，重复调用
        无害，故此处的"提前一月"不会引入额外网络开销。
        """
        source = self._source
        if source is None:
            return
        today = QDate.currentDate()
        y = today.year()
        try:
            if not source.request(y):
                logger.debug("HolidaySource 未接受 %s 年请求（可能已在途）", y)
            if today.month() >= 11:
                if not source.request(y + 1):
                    logger.debug(
                        "HolidaySource 未接受 %s 年请求（可能已在途）", y + 1)
        except Exception:
            logger.warning("HolidaySource.request 失败", exc_info=True)

    def _on_net_ready(self, year: int, net_data: dict):
        if self._shutting_down:
            return
        if not net_data or year <= 0:
            return
        self.holiday_cache[str(year)] = {
            "ts": datetime.now().timestamp(),
            "days": net_data,
        }
        self._has_notified_error = False
        save_holiday_cache(self.holiday_cache)
        event_bus.publish(
            EventType.HOLIDAY_UPDATED, holiday_data=self.apply_cached(save=False))

    def _on_net_error(self, year: int, err: HolidaySourceError):
        if self._shutting_down:
            return
        if not self._has_notified_error:
            self._has_notified_error = True
            logger.warning("节假日网络错误（%s 年）: %s", year, err)

    def shutdown(self):
        """安全关闭数据源。幂等。"""
        if self._shutting_down:
            return
        self._shutting_down = True
        self._refresh_timer.stop()

        source = self._source
        self._source = None
        if source is None:
            return
        try:
            ok = source.shutdown(timeout_ms=3000)
        except Exception:
            logger.exception("HolidaySource.shutdown 异常")
            self._orphan_source = source
            return
        if not ok:
            logger.warning(
                "HolidaySource 未在 3s 内退出，保留引用至进程退出")
            self._orphan_source = source