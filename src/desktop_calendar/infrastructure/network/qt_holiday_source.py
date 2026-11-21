# coding: utf-8
"""HolidaySource 的 Qt 实现：QThread + HolidayNetWorker（同文件）。

线程模型：
- HolidayNetWorker 运行在 QThread 中，QNetworkAccessManager 与
  _retry_timer 均在 worker 线程首次使用时构造（线程亲和性）。
- QtHolidaySource 位于主线程，负责线程生命周期与回调 marshal。
"""

import threading
from collections import deque

from PyQt6.QtCore import (
    QMetaObject,
    QObject,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from desktop_calendar.config.manager import get_logger
from desktop_calendar.contracts.holiday_source import (
    CancelledError,
    NetworkError,
    ParseError,
)

from .holiday_parsing import (
    parse_holiday_json,
)

logger = get_logger()

_ERROR_KIND_MAP = {
    "network": NetworkError,
    "parse": ParseError,
    "cancelled": CancelledError,
}


class HolidayNetWorker(QObject):
    """在子线程中依次尝试免费节假日 API 与 CDN。"""

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
    SOURCE_LIST = [
        "https://timor.tech/api/holiday/year/{year}",
    ] + CDN_LIST
    RETRY_DELAY_MS = 200

    def __init__(self):
        super().__init__()
        self.manager: QNetworkAccessManager = None
        self.reply: QNetworkReply = None
        self.try_idx = 0
        self.target_year = 0
        self.is_fetching = False
        self._abort_event = threading.Event()
        self._pending_years = deque()
        self._retry_timer: QTimer | None = None
        self._last_error_kind = "network"
        self.request_fetch.connect(self.fetch_year_holiday)
        self.abort_requested.connect(self._do_abort)

    def request_abort(self):
        """线程安全地请求中止当前拉取（可从主线程调用）。"""
        self.abort_requested.emit()

    @pyqtSlot()
    def _do_abort(self):
        """在 worker 线程执行：置 Event、清队列、立即中断挂起的 reply。"""
        self._abort_event.set()
        self._pending_years.clear()
        self._abort_current_reply()
        self.is_fetching = False
        QThread.currentThread().quit()

    def _ensure_retry_timer(self):
        """在 worker 线程内创建 retry timer（幂等）。

        必须首次在 worker 线程调用：QTimer 线程亲和性由构造线程决定。
        """
        if self._retry_timer is None:
            self._retry_timer = QTimer(self)
            self._retry_timer.setSingleShot(True)
            self._retry_timer.timeout.connect(self._request_next_cdn)

    def _setup_manager(self):
        """仅在 worker 线程初始化网络管理器与 retry timer（幂等）。"""
        if not self.manager:
            self.manager = QNetworkAccessManager(self)
        self._ensure_retry_timer()

    @pyqtSlot(int)
    def fetch_year_holiday(self, year: int):
        """拉取单年数据；若正在拉取则入队，完成后自动取下一个。"""
        if self._abort_event.is_set():
            logger.info(f"已请求中止，忽略 {year} 年拉取")
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
        """只清理挂起 reply 和 retry timer，不碰 abort Event。"""
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

        if self.try_idx >= len(self.SOURCE_LIST):
            err_msg = f"所有节假日数据源获取{self.target_year}年数据均失败，将使用本地库兜底"
            logger.warning(err_msg)
            self.net_error.emit(self.target_year, self._last_error_kind, err_msg)
            self._finish_with_result({})
            return

        url_str = self.SOURCE_LIST[self.try_idx].format(year=self.target_year)
        req = QNetworkRequest(QUrl(url_str))
        req.setTransferTimeout(8000)
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        self.reply = self.manager.get(req)
        self.reply.finished.connect(self.on_reply)

    def _finish_with_result(self, result: dict):
        """完成本次拉取并触发下一个。

        result 必须是本次拉取独有的新 dict：finished.emit 跨线程按引用
        投递，复用会让主线程收到"修改后"的值。
        """
        next_year = None
        if not self._abort_event.is_set() and self._pending_years:
            next_year = self._pending_years.popleft()
        else:
            self._pending_years.clear()
        self.is_fetching = False
        self.finished.emit(self.target_year, result)
        if next_year is not None:
            self.request_fetch.emit(next_year)

    @pyqtSlot()
    def on_reply(self):
        # 防御：reply 已被清理或已 abort。
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
                result = parse_holiday_json(raw, self.target_year)
                logger.info(f"网络获取{self.target_year}节假日成功，共{len(result)}条")
                self.reply = None
                reply.deleteLater()
                self._finish_with_result(result)
            else:
                logger.warning("节假日数据源[%d]失败: %s", self.try_idx, reply.errorString())
                self._last_error_kind = "network"
                self.reply = None
                reply.deleteLater()
                self.try_idx += 1
                self._ensure_retry_timer()
                self._retry_timer.start(self.RETRY_DELAY_MS)
        except Exception as e:
            logger.error(f"节假日解析异常: {e}")
            self._last_error_kind = "parse"
            self.reply = None
            reply.deleteLater()
            self.try_idx += 1
            self._ensure_retry_timer()
            self._retry_timer.start(self.RETRY_DELAY_MS)


class QtHolidaySource(QObject):
    # 单年在途兜底超时：worker 已死 / emit 静默丢失时防止永久卡在
    # _inflight_years 里。
    _INFLIGHT_TIMEOUT_MS = 180_000

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
            logger.warning("网络线程初始化失败，节假日将只用本地缓存", exc_info=True)
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
        # 保护性超时：worker 在 emit 前被删除时 _handle_ready /
        # _handle_error 不会触发，这里兜底清理。
        QTimer.singleShot(self._INFLIGHT_TIMEOUT_MS, lambda y=year: self._inflight_years.discard(y))
        self._worker.request_fetch.emit(year)
        return True

    def shutdown(self, timeout_ms: int = 3000) -> bool:
        thread = self._thread
        worker = self._worker
        self._thread = None
        self._worker = None
        self._inflight_years.clear()
        if thread is None:
            return True
        abort_dispatched = False
        if worker is not None and thread.isRunning():
            # 用 QueuedConnection 而非 BlockingQueuedConnection：
            # worker 忙于解析时 Blocking 会让主线程无限等待。
            # invokeMethod 返回 False 时不抛异常，需检查。
            try:
                ok = QMetaObject.invokeMethod(
                    worker, "_do_abort", Qt.ConnectionType.QueuedConnection
                )
                abort_dispatched = bool(ok)
            except Exception:
                logger.debug("同步派发 _do_abort 失败，退回异步 request_abort", exc_info=True)
            if not abort_dispatched:
                try:
                    worker.request_abort()
                    abort_dispatched = True
                except Exception:
                    logger.debug("request_abort 失败", exc_info=True)

        if not abort_dispatched:
            thread.quit()

        if thread.wait(timeout_ms):
            thread.deleteLater()
            return True

        logger.warning("网络线程未在 %dms 内退出，保留引用交由进程退出清理", timeout_ms)
        self._orphan_threads.append(thread)
        return False

    def _handle_ready(self, year: int, data: dict) -> None:
        if self._worker is None:
            return
        self._inflight_years.discard(year)
        try:
            self._on_ready(year, data)
        except Exception:
            logger.exception("on_ready 回调异常")

    def _handle_error(self, year: int, kind: str, err: str) -> None:
        if self._worker is None:
            return
        self._inflight_years.discard(year)
        cls = _ERROR_KIND_MAP.get(kind, NetworkError)
        try:
            self._on_error(year, cls(err))
        except Exception:
            logger.exception("on_error 回调异常")


def make_qt_holiday_source(*, on_ready, on_error, parent=None) -> QtHolidaySource:
    """HolidaySourceFactory 的 Qt 实现。"""
    return QtHolidaySource(on_ready=on_ready, on_error=on_error, parent=parent)
