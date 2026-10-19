# coding: utf-8
from datetime import datetime

from PyQt6.QtCore import QObject, QDate, QTimer

from desktop_calendar.contracts.ports.holiday_source import HolidaySourceFactory
from desktop_calendar.config.config import (
    ConfigManager, load_holiday_cache, save_holiday_cache, get_logger,
)
from desktop_calendar.contracts.event_bus import event_bus
from desktop_calendar.contracts.events import EventType

logger = get_logger()


class HolidayManager(QObject):
    """节假日数据管理：缓存、数据源拉取、自动刷新、过期清理。

    网络实现由装配层通过 source_factory 注入，core 不 import 任何
    Qt 网络代码。数据源不可用时静默降级为纯本地缓存。
    """
    CACHE_EXPIRE_SEC = 7 * 24 * 3600
    REFRESH_INTERVAL_MS = 6 * 60 * 60 * 1000  # 6 小时刷新

    def __init__(self, config: ConfigManager,
                 source_factory: HolidaySourceFactory):
        super().__init__()
        self.config = config
        self.holiday_cache = load_holiday_cache()
        self._has_notified_error = False
        self._shutting_down = False

        self._source = source_factory(
            on_ready=self._on_net_ready,
            on_error=self._on_net_error,
            parent=self,
        )
        started = False
        try:
            started = bool(self._source.start())
        except Exception:
            logger.warning("HolidaySource.start 失败", exc_info=True)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self.fetch_current_year)
        if started:
            self._refresh_timer.start()

    def apply_cached(self) -> dict:
        """清理过期缓存并返回有效节假日数据。

        返回合并后的 dict；缓存全部失效 / 为空时返回空 dict（绝不返回 None）。
        过期清理只在循环外统一执行，且仅在确实删掉条目时落盘，
        避免主窗口启动时无谓写盘。
        """
        all_days: dict = {}
        now_ts = datetime.now().timestamp()
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
            if now_ts - ts > self.CACHE_EXPIRE_SEC:
                expired.append(year_str)
                continue
            all_days.update(days)

        if expired:
            for year_str in expired:
                self.holiday_cache.pop(year_str, None)
            save_holiday_cache(self.holiday_cache)

        return all_days

    def fetch_current_year(self):
        """拉取当年节假日，12 月自动预取下一年。"""
        source = self._source
        if source is None:
            return
        y = QDate.currentDate().year()
        try:
            source.request(y)
            if QDate.currentDate().month() == 12:
                source.request(y + 1)
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
        event_bus.publish(EventType.HOLIDAY_UPDATED, data=self.apply_cached())

    def _on_net_error(self, err: str):
        if self._shutting_down:
            return
        if not self._has_notified_error:
            self._has_notified_error = True
            logger.warning(f"节假日网络错误: {err}")

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
            if not ok:
                logger.warning("HolidaySource 未在 3s 内退出，保留引用")
        except Exception:
            logger.exception("HolidaySource.shutdown 异常")