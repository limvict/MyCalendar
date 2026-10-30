# coding: utf-8
"""HolidaySource 的 Qt 实现：QThread + HolidayNetWorker（同文件）。

线程模型：
- HolidayNetWorker 运行在 QThread 中，QNetworkAccessManager 与
  _retry_timer 均在 worker 线程首次使用时构造（线程亲和性）。
- QtHolidaySource 位于主线程，负责线程生命周期与回调 marshal。
"""
import json
import threading
from collections import deque

from PyQt6.QtCore import (
    QObject, QThread, QUrl, QTimer, pyqtSignal, pyqtSlot, QMetaObject,
    Qt,
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
    """在子线程中依次尝试多个 CDN 拉取节假日 JSON。"""

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
        self._abort_event = threading.Event()
        self._pending_years = deque()
        self._retry_timer: "QTimer | None" = None
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
        if self._retry_timer is not None:
            self._retry_timer.stop()
        self.is_fetching = False
        QThread.currentThread().quit()

    def _ensure_retry_timer(self):
        """在 worker 线程内创建 retry timer（幂等）。

        必须首次在 worker 线程调用：QTimer 线程亲和性由构造线程决定，
        早于 moveToThread 构造会留下主线程 timerId。
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
        """完成本次拉取并触发下一个。

        【约束】result 必须是本次拉取独有的新 dict，不能复用实例属性
        或跨调用共享。finished.emit 跨线程（QueuedConnection），PyQt6
        按引用投递 Python 对象；若 result 后续被 worker 线程修改（如
        复用作 next_year 的 result），主线程收到的是"修改后"的值。
        当前 _request_next_cdn 每次新建 result，约束成立。
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

    # ===================== 节假日 JSON 解析 =====================
    # 三种上游格式 → 统一 {date: "holiday" | "workday"}。
    # 拆成 helper 便于单测，也避免单方法内多层嵌套。

    @staticmethod
    def _kind_from_off(is_off) -> str:
        """isOffDay 语义：True=不上班(holiday)，False=调休上班(workday)。

        字段缺失时默认 False → workday：NateScarlet 格式必带该字段，
        缺失说明源数据不完整，按"调休上班"处理比按"休息"处理更保守
        （漏报休息日好于把工作日误标为休息日）。
        """
        return "holiday" if to_bool(is_off, default=False) else "workday"

    @staticmethod
    def _is_date_like(s: str) -> bool:
        """YYYY-MM-DD 形状判断（宽松版，不校验月日范围）。"""
        return len(s) == 10 and s[4] == "-" and s[7] == "-"

    @classmethod
    def _parse_day_items(cls, items) -> dict:
        """[{"date": "2024-01-01", "isOffDay": true}, ...] → {date: kind}。

        NateScarlet 与 list-of-dict 两种格式共用此路径。
        """
        result = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            date_str = item.get("date")
            if not isinstance(date_str, str) or not date_str:
                continue
            result[date_str] = cls._kind_from_off(item.get("isOffDay", False))
        return result

    @classmethod
    def _parse_day_map(cls, mapping, *, date_keys_only: bool) -> dict:
        """{date: is_off, ...} → {date: kind}。

        date_keys_only=True 时只保留日期形状的 key（顶层 {date: is_off}
        格式可能混入 version/updated 等元数据）；False 时保留全部字符串
        key（chinese-days 的 "days" 字段保证纯日期映射）。
        """
        result = {}
        for date_str, is_off in mapping.items():
            if not isinstance(date_str, str):
                continue
            if date_keys_only and not cls._is_date_like(date_str):
                continue
            result[date_str] = cls._kind_from_off(is_off)
        return result

    @classmethod
    def _looks_like_date_map(cls, mapping) -> bool:
        """至少一个 key 是 YYYY-MM-DD 形状。"""
        return any(
            isinstance(k, str) and cls._is_date_like(k) for k in mapping.keys())

    @classmethod
    def _parse_holiday_json(cls, raw: str, default_year: int) -> dict:
        """兼容三种源格式，统一输出 {date_str: "holiday" | "workday"}。

        1. NateScarlet/holiday-cn:
           {"year":2024, "days":[{"date":..., "isOffDay":...}, ...]}
        2. chinese-days:
           {"days": {"2024-01-01": true, ...}} 或顶层 {"2024-01-01": true, ...}
        3. list of {"date":..., "isOffDay":...}

        无法识别结构时抛 ValueError，由 on_reply 捕获后重试下一个 CDN。
        """
        j = json.loads(raw)

        if isinstance(j, dict):
            days = j.get("days")
            if isinstance(days, list):
                return cls._parse_day_items(days)
            if isinstance(days, dict):
                return cls._parse_day_map(days, date_keys_only=False)
            # 顶层直接是 {date: is_off}；只取日期形状 key，避免元数据污染
            if cls._looks_like_date_map(j):
                return cls._parse_day_map(j, date_keys_only=True)

        if isinstance(j, list):
            return cls._parse_day_items(j)

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
                logger.info(f"网络获取{self.target_year}节假日成功，共{len(result)}条")
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
            logger.error(f"节假日解析异常: {e}")
            self._last_error_kind = "parse"
            self.reply = None
            reply.deleteLater()
            self.try_idx += 1
            self._ensure_retry_timer()
            self._retry_timer.start(self.RETRY_DELAY_MS)


class QtHolidaySource(QObject):
    """用 QThread 承载 HolidayNetWorker；主线程侧管理生命周期。

    - start/shutdown 幂等；shutdown 后 request 返回 False。
    - worker 结果通过信号回到主线程执行回调；_inflight_years 去重同年在途请求。

    关于 on_ready / on_error 的强引用：这两个回调通常是
    HolidayManager 的绑定方法，强引用会形成
    HolidayManager ↔ QtHolidaySource 的循环引用。这是有意为之：

      - 不能用 weakref.ref(bound_method)：bound method 每次属性访问
        都新建临时对象，weakref 立即失效，回调永远拿不到
        （这是 Python 语义，不是配置问题）。
      - 可行的 weakref.ref(on_ready.__self__) 方案要求 on_ready
        必须是绑定方法（排除 lambda / 闭包），且需经 __func__ 调用，
        复杂化换来的收益（避免一个可接受的循环引用）几乎为零。
      - 循环引用由 CPython 循环 GC 回收；HolidayManager 生命周期
        等于进程，从不单独销毁，生产路径无泄漏。
      - 测试若频繁创建 HolidayManager，在 conftest 里 gc.collect()
        即可，不需要改生产代码。
    """

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
        if thread is None:
            return True
        abort_dispatched = False
        if worker is not None and thread.isRunning():
            # 用 QueuedConnection 而非 BlockingQueuedConnection：
            # worker 若正忙于解析大 JSON / 处理 reply，Blocking 会让
            # 主线程无限期等待（无 timeout 上限），UI 卡死。
            # Queued 投递后立即返回，由下方 thread.wait(timeout_ms)
            # 提供明确上限。
            #
            # 必须检查 invokeMethod 返回值：worker 已 delete / 方法名
            # 不存在时 PyQt6 返回 False 而不是抛异常，当前若不检查会
            # 误判"已派发"，thread.wait 等一个不会 quit 的线程。
            try:
                ok = QMetaObject.invokeMethod(
                    worker, "_do_abort",
                    Qt.ConnectionType.QueuedConnection)
                abort_dispatched = bool(ok)
            except Exception:
                logger.debug(
                    "同步派发 _do_abort 失败，退回异步 request_abort",
                    exc_info=True)
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

        logger.warning(
            "网络线程未在 %dms 内退出，保留引用交由进程退出清理", timeout_ms)
        self._orphan_threads.append(thread)
        return False

    # ---------- worker 信号 → 主线程回调 ----------
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