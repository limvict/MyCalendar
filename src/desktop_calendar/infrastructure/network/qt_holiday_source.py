# coding: utf-8
"""HolidaySource 的 Qt 实现：QThread + HolidayNetWorker（同文件）。"""
import json
import threading
from collections import deque

from PyQt6.QtCore import (
    QObject, QThread, QUrl, QTimer, pyqtSignal, pyqtSlot,
)
from PyQt6.QtNetwork import (
    QNetworkAccessManager, QNetworkRequest, QNetworkReply,
)

from desktop_calendar.contracts.holiday_source import (
    NetworkError, ParseError, CancelledError,
)
from desktop_calendar.config.manager import get_logger
from desktop_calendar.utils.coerce import to_bool

logger = get_logger()

_ERROR_KIND_MAP = {
    "network": NetworkError,
    "parse": ParseError,
    "cancelled": CancelledError,
}


class HolidayNetWorker(QObject):
    finished = pyqtSignal(int, dict)
    net_error = pyqtSignal(int, str, str)
    request_fetch = pyqtSignal(int)
    abort_requested = pyqtSignal()

    CDN_LIST = [
        "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
        "https://fastly.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
        "https://mirror.ghproxy.com/https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
        "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
        "https://cdn.jsdelivr.net/npm/chinese-days/dist/years/{year}.json",
    ]
    RETRY_DELAY_MS = 200

    def __init__(self):
        super().__init__()
        self.manager: QNetworkAccessManager = None
        self.reply: QNetworkReply = None
        self.try_idx = 0
        self.target_year = 0
        self.is_fetching = False
        # 用 Event 而非裸 bool：跨线程读写语义清晰
        self._abort_event = threading.Event()
        self._pending_years = deque()
        # 延迟创建，见类 docstring 的【_retry_timer 延迟创建】
        self._retry_timer: "QTimer | None" = None
        self.request_fetch.connect(self.fetch_year_holiday)
        self.abort_requested.connect(self._do_abort)
        self._last_error_kind = "network"

    def request_abort(self):
        """线程安全地请求中止当前拉取。可在主线程调用（如 shutdown）。"""
        self.abort_requested.emit()

    def _do_abort(self):
        """在 worker 线程执行：set Event + 立即中断挂起的 reply。"""
        self._abort_event.set()
        self._pending_years.clear()
        self._abort_current_reply()

    def _ensure_retry_timer(self):
        """在 worker 当前线程里创建 retry timer（幂等）。

        必须在 worker 线程首次调用：QTimer 的线程亲和性由构造时的
        当前线程决定，早于 moveToThread 构造会留下主线程 timerId，
        timeout 可能在主线程触发。
        """
        if self._retry_timer is None:
            self._retry_timer = QTimer(self)
            self._retry_timer.setSingleShot(True)
            self._retry_timer.timeout.connect(self._request_next_cdn)

    def _setup_manager(self):
        """仅在子线程初始化网络管理器，保证线程亲和性。

        同时把 _retry_timer 的创建一并带进来：两者都必须在
        worker 线程里完成。
        """
        if not self.manager:
            self.manager = QNetworkAccessManager(self)
        self._ensure_retry_timer()

    @pyqtSlot(int)
    def fetch_year_holiday(self, year: int):
        """拉取单年节假日；若正在拉取则入队，完成后自动取下一个。"""
        if self._abort_event.is_set():
            logger.info(f"已请求中止，忽略 {year} 年拉取")
            # 清空队列，避免残留
            self._pending_years.clear()
            return
        if self.is_fetching:
            if year not in self._pending_years:
                self._pending_years.append(year)
            logger.info(f"节假日拉取中，{year}年已入队等待")
            return
        self.is_fetching = True
        self._abort_event.clear()
        self._last_error_kind = "network"
        self.target_year = year      
        self.try_idx = 0
        self._setup_manager()
        self._abort_current_reply()
        self._request_next_cdn()

    def _abort_current_reply(self):
        """只清理挂起的 reply 和 retry timer，不碰 abort Event。"""
        if self._retry_timer is not None:
            self._retry_timer.stop()
        if self.reply is not None:
            reply = self.reply
            self.reply = None
            try:
                reply.finished.disconnect(self.on_reply)
            except (TypeError, RuntimeError):
                pass
            reply.abort()
            reply.deleteLater()

    def _request_next_cdn(self):
        if self._abort_event.is_set():
            self._finish_with_result({})
            return

        if self.try_idx >= len(self.CDN_LIST):
            err_msg = (f"所有CDN获取{self.target_year}年节假日全部失败，"
                       f"将使用本地库兜底")
            logger.warning(err_msg)
            self.net_error.emit(self.target_year, self._last_error_kind, err_msg)
            self._finish_with_result({})
            return

        url_str = self.CDN_LIST[self.try_idx].format(year=self.target_year)
        req = QNetworkRequest(QUrl(url_str))
        req.setTransferTimeout(8000)
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        self.reply = self.manager.get(req)
        self.reply.finished.connect(self.on_reply)

    def _finish_with_result(self, result: dict):
        next_year = None
        if not self._abort_event.is_set() and self._pending_years:
            next_year = self._pending_years.popleft()
        else:
            self._pending_years.clear()
        self.is_fetching = False
        self.finished.emit(self.target_year, result)
        if next_year is not None:
            self.request_fetch.emit(next_year)

    @staticmethod
    def _parse_holiday_json(raw: str, default_year: int) -> dict:
        """
        兼容多种源：
        1. NateScarlet/holiday-cn:
           {"year":2024,"days":[{"date":"2024-01-01","isOffDay":true}, ...]}
        2. chinese-days:
           {"2024-01-01": true, ...} 或 {"days": {"2024-01-01": true, ...}}
        3. list of {"date":..., "isOffDay":...}
        """
        j = json.loads(raw)
        result = {}

        if isinstance(j, dict):
            days = j.get("days")
            if isinstance(days, list):
                for item in days:
                    if isinstance(item, dict) and item.get("date"):
                        result[item["date"]] = to_bool(
                            item.get("isOffDay", False), default=False)
                return result

            if isinstance(days, dict):
                for date_str, is_off in days.items():
                    result[date_str] = to_bool(is_off, default=False)
                return result

            date_like = [k for k in j.keys()
                         if isinstance(k, str) and len(k) == 10 and k[4] == "-"]
            if date_like:
                for date_str in date_like:
                    result[date_str] = to_bool(j[date_str], default=False)
                return result

        if isinstance(j, list):
            for item in j:
                if isinstance(item, dict) and item.get("date"):
                    result[item["date"]] = to_bool(
                        item.get("isOffDay", False), default=False)
            return result

        raise ValueError(f"无法识别的节假日JSON结构，year={default_year}")

    @pyqtSlot()
    def on_reply(self):
        # 防御：reply 已被清理或已 abort
        if self._abort_event.is_set() or self.reply is None:
            return

        reply = self.reply
        try:
            reply.finished.disconnect(self.on_reply)
        except (TypeError, RuntimeError):
            pass

        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                raw = reply.readAll().data().decode("utf-8")
                result = self._parse_holiday_json(raw, self.target_year)
                logger.info(
                    f"网络获取{self.target_year}节假日成功，共{len(result)}条")
                self.reply = None
                reply.deleteLater()
                self._finish_with_result(result)
            else:
                logger.warning(f"CDN[{self.try_idx}]失败: {reply.errorString()}")
                self._last_error_kind = "network"
                self.reply = None
                reply.deleteLater()
                self.try_idx += 1
                self._ensure_retry_timer()
                self._retry_timer.start(self.RETRY_DELAY_MS)
        except Exception as e:
            err_msg = f"节假日解析异常: {e}"
            logger.error(err_msg)
            self._last_error_kind = "parse"
            self.reply = None
            reply.deleteLater()
            self.try_idx += 1
            self._ensure_retry_timer()
            self._retry_timer.start(self.RETRY_DELAY_MS)

class QtHolidaySource(QObject):
    """用 QThread 承载 HolidayNetWorker。...（类 docstring 不变）"""

    def __init__(self, *, on_ready, on_error, parent=None):
        super().__init__(parent)
        self._on_ready = on_ready
        self._on_error = on_error
        self._thread: QThread | None = None
        self._worker: HolidayNetWorker | None = None
        self._started = False
        self._orphan_threads: list[QThread] = []
        self._inflight_years: set[int] = set()
        
    def start(self) -> bool:
        if self._started:
            return self._thread is not None
        self._started = True

        thread = None
        worker = None
        thread_started = False
        try:
            thread = QThread()
            worker = HolidayNetWorker()
            worker.moveToThread(thread)
            worker.finished.connect(self._handle_ready)
            worker.net_error.connect(self._handle_error)
            thread.finished.connect(worker.deleteLater)
            thread.start()
            thread_started = True
        except Exception:
            logger.warning(
                "网络线程初始化失败，节假日将只用本地缓存", exc_info=True)
            if worker is not None:
                for sig, slot in (
                    (worker.finished, self._handle_ready),
                    (worker.net_error, self._handle_error),
                ):
                    try:
                        sig.disconnect(slot)
                    except (TypeError, RuntimeError):
                        pass
            if thread is not None:
                if thread_started:
                    try:
                        thread.quit()
                        thread.wait(1000)
                    except Exception:
                        pass
                thread.deleteLater()
            self._thread = None
            self._worker = None
            return False

        self._thread = thread
        self._worker = worker
        return True

    def request(self, year: int) -> bool:
        if self._worker is None:
            return False
        if year in self._inflight_years:
            logger.debug("请求 %s 年时该年已在途，忽略重复请求", year)
            return False
        self._inflight_years.add(year)
        self._worker.request_fetch.emit(year)
        return True

    def shutdown(self, timeout_ms: int = 3000) -> bool:
        thread = self._thread
        worker = self._worker
        self._thread = None
        self._worker = None
        self._inflight_years.clear()

        if worker is not None:
            try:
                worker.request_abort()
            except Exception:
                logger.debug("request_abort 失败", exc_info=True)

        if thread is None:
            return True

        thread.quit()
        if thread.wait(timeout_ms):
            thread.deleteLater()
            return True

        logger.warning(
            "网络线程未在 %dms 内退出，保留引用交由进程退出清理", timeout_ms)
        self._orphan_threads.append(thread)
        return False

    # ---------- worker 信号 → 主线程回调 ----------
    def _handle_ready(self, year: int, data: dict) -> None:
        self._inflight_years.discard(year)
        try:
            self._on_ready(year, data)
        except Exception:
            logger.exception("on_ready 回调异常")

    def _handle_error(self, year: int, kind: str, err: str) -> None:
        self._inflight_years.discard(year)
        cls = _ERROR_KIND_MAP.get(kind, NetworkError)
        try:
            self._on_error(year, cls(err))
        except Exception:
            logger.exception("on_error 回调异常")
            
def make_qt_holiday_source(*, on_ready, on_error, parent=None) -> QtHolidaySource:
    """HolidaySourceFactory 的 Qt 实现。"""
    return QtHolidaySource(on_ready=on_ready, on_error=on_error, parent=parent)