# coding: utf-8
"""HolidaySource 的 Qt 实现：QThread + HolidayNetWorker。"""
from PyQt6.QtCore import QObject, QThread

from desktop_calendar.config.config import get_logger
from desktop_calendar.infrastructure.network.holiday_worker import (
    HolidayNetWorker,
)

logger = get_logger()


class QtHolidaySource(QObject):
    """用 QThread 承载 HolidayNetWorker。

    回调线程保证：worker 在子线程 emit，本类 slot 连的是 AutoConnection，
    跨线程自动排队到主线程执行，因此 on_ready / on_error 一定在主线程。
    """

    def __init__(self, *, on_ready, on_error, parent=None):
        super().__init__(parent)
        self._on_ready = on_ready
        self._on_error = on_error
        self._thread: QThread | None = None
        self._worker: HolidayNetWorker | None = None
        self._started = False
        self._orphan_threads: list[QThread] = []

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

    def request(self, year: int) -> None:
        if self._worker is None:
            return
        self._worker.request_fetch.emit(year)

    def shutdown(self, timeout_ms: int = 3000) -> bool:
        thread = self._thread
        worker = self._worker
        self._thread = None
        self._worker = None

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

        # 不 terminate：QThread.terminate 不执行栈展开，会遗留
        # QNetworkAccessManager 内部锁，退出时可能死锁。
        logger.warning(
            "网络线程未在 %dms 内退出，保留引用交由进程退出清理", timeout_ms)
        self._orphan_threads.append(thread)
        return False

    # ---------- worker 信号 → 主线程回调 ----------
    def _handle_ready(self, year: int, data: dict) -> None:
        try:
            self._on_ready(year, data)
        except Exception:
            logger.exception("on_ready 回调异常")

    def _handle_error(self, err: str) -> None:
        try:
            self._on_error(err)
        except Exception:
            logger.exception("on_error 回调异常")