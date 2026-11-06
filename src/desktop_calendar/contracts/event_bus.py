# coding: utf-8
import threading
from typing import Callable, Any, Dict, List, Tuple

from PyQt6.QtCore import (
    QObject, pyqtSignal, QThread, QCoreApplication, QTimer,
)

from desktop_calendar.utils.logging_setup import get_logger

logger = get_logger()


class EventType:
    """事件类型常量。

    本模块不 import 任何 desktop_calendar 业务模块，只依赖 Qt 与
    logging_setup，因此 core / application / infrastructure /
    presentation 都可安全 import。
    """
    HOLIDAY_UPDATED = "holiday_updated"
    MEMORIAL_CHANGED = "memorial_changed"
    MEMORIAL_REMIND_TRIGGERED = "memorial_remind_triggered"

    WINDOW_SHOW = "window_show"
    WINDOW_QUIT = "window_quit"

    OPEN_SETTINGS = "open_settings"
    # 当前未使用：settings_controller 直接调用 window_state / theme_mgr
    # 等方法。保留以备未来解耦设置变更通知。
    SETTINGS_CHANGED = "settings_changed"
    BACKUP_MEMORIAL = "backup_memorial"
    RESTORE_MEMORIAL = "restore_memorial"

    UPDATE_AVAILABLE = "update_available"
    UPDATE_FAILED = "update_failed"
    UPDATE_READY = "update_ready"
    UPDATE_PROGRESS = "update_progress"


def _same_callable(a, b) -> bool:
    """安全比较两个 callable 是否指向同一个绑定方法。

    优先 `is`（同一对象），其次绑定方法语义比较（同一 self + 同一 func），
    最后 fallback 到 `==`（仅当结果是明确的 bool 时采纳）。

    `==` fallback 的风险：某些对象（MagicMock、返回 ndarray 的自定义
    `__eq__` 等）返回非 bool，`bool()` 转换可能得到意外的 True。
    因此严格要求结果类型为 bool，否则视为不相同（fail closed）。
    """
    try:
        if a is b:
            return True
        sa = getattr(a, "__self__", None)
        sb = getattr(b, "__self__", None)
        fa = getattr(a, "__func__", None)
        fb = getattr(b, "__func__", None)
        if sa is not None and sb is not None and fa is not None and fb is not None:
            return sa is sb and fa is fb
        eq = a == b
        return eq if isinstance(eq, bool) else False
    except Exception:
        logger.debug(
            "比较 callable 失败，按不相同处理: %r vs %r", a, b, exc_info=True)
        return False


def _warn_if_not_main_thread(action: str) -> None:
    """从非主线程调用 EventBus 时记 warning。"""
    app = QCoreApplication.instance()
    if app is not None and QThread.currentThread() is not app.thread():
        logger.warning(
            f"EventBus.{action} 从非主线程调用，"
            f"订阅者槽可能在错误线程执行")

def _safe_unsubscribe(bus, event_type: str, slot) -> None:
    """延迟退订的安全包装：EventBus 已销毁时静默。

    不能写成 lambda 捕获 self：EventBus 若在定时器触发前被
    deleteLater，lambda 内的 self.unsubscribe 会抛 RuntimeError，
    且发生在 Qt 事件循环里无人捕获。
    """
    try:
        bus.unsubscribe(event_type, slot)
    except RuntimeError:
        logger.debug("EventBus 已销毁，跳过延迟退订 event=%s", event_type)
    except Exception:
        logger.exception("延迟退订失败 event=%s", event_type)
        
class EventBus(QObject):
    """事件总线：发布-订阅模式，解耦各模块间通信。

    线程模型：
    - subscribe / unsubscribe 应在主线程调用（非主线程会 warning）。
    - publish 可从任意线程调用：
        * 主线程调用：同线程 emit，slot 同步执行（DirectConnection）；
        * 跨线程调用：投递到 EventBus 亲和性线程（通常是主线程）
          执行 emit，slot 在主线程执行（异步，不阻塞调用方）。
    - slot 应快速返回，不应阻塞；抛异常会被隔离并记日志，不影响其他
      subscriber。
    """

    _dispatch_signal = pyqtSignal(str, dict)

    def __init__(self):
        super().__init__()
        self._subscriber_map: Dict[str, List[Tuple[Callable, Callable]]] = {}
        self._lock = threading.RLock()

    def subscribe(self, event_type: str, slot: Callable[[dict], Any]) -> None:
        with self._lock:
            entries = self._subscriber_map.setdefault(event_type, [])
            # 幂等：同一 event_type 下同一 slot 不重复订阅
            for s, _ in entries:
                if _same_callable(s, slot):
                    return

            def _wrapper(etype: str, data: dict):
                if etype != event_type:
                    return
                try:
                    slot(data)
                except RuntimeError as e:
                    # PyQt6 在 C++ 对象被删除后访问其槽会抛 RuntimeError，
                    # 消息可能是 "has been deleted"（新版本）或
                    # "already deleted"（部分版本 / 绑定层），两者都视为
                    # 悬空订阅。此时订阅已悬空，
                    # 继续保留会让每次 publish 都刷一条 traceback；主动退订。
                    #
                    # 延迟到事件循环下一轮执行 unsubscribe：wrapper 当前
                    # 处于 Qt signal emit 的遍历中，直接 disconnect 虽然
                    # PyQt6 允许，但延迟更稳妥，也避开 EventBus lock 与
                    # Qt 内部 mutex 的嵌套顺序问题。
                    _msg = str(e)
                    if ("has been deleted" in _msg
                            or "already deleted" in _msg):
                        logger.warning(
                            "事件 %s 的订阅者 %r 所属对象已删除，自动退订",
                            event_type, slot)
                        QTimer.singleShot(
                            0, lambda: _safe_unsubscribe(
                                self, event_type, slot))
                    else:
                        logger.exception(
                            "事件 %s 的订阅者 %r 抛 RuntimeError，已隔离",
                            event_type, slot)
                except Exception:
                    logger.exception(
                        "事件 %s 的订阅者 %r 抛异常，已隔离",
                        event_type, slot)

            entries.append((slot, _wrapper))
            self._dispatch_signal.connect(_wrapper)

    def unsubscribe(self, event_type: str, slot: Callable[[dict], Any]) -> None:
        with self._lock:
            entries = self._subscriber_map.get(event_type, [])
            removed_indices = []
            for i, (s, w) in enumerate(entries):
                if _same_callable(s, slot):
                    try:
                        self._dispatch_signal.disconnect(w)
                    except (TypeError, RuntimeError):
                        pass
                    removed_indices.append(i)
            for i in reversed(removed_indices):
                entries.pop(i)
            if not entries and event_type in self._subscriber_map:
                del self._subscriber_map[event_type]
                
    def publish(self, event_type: str, **kwargs) -> None:
        """发布事件。

        event_type 非 str 时静默丢弃并记 debug：pyqtSignal(str, dict) 对
        参数类型做严格检查，int / None 会抛 TypeError。静默丢弃比让调用方
        处理异常更符合事件总线"尽力而为"的语义。
        """
        if not isinstance(event_type, str):
            logger.debug("publish 收到非 str event_type=%r，已丢弃", event_type)
            return
        self._safe_emit(event_type, kwargs)

    def _safe_emit(self, event_type: str, kwargs: dict) -> None:
        """emit 包装：self 已被 deleteLater 时静默忽略。"""
        try:
            self._dispatch_signal.emit(event_type, kwargs)
        except RuntimeError:
            # C++ 对象已销毁：进程退出期或测试 teardown 场景，忽略。
            logger.debug(
                "EventBus 已销毁，丢弃事件 %r", event_type, exc_info=True)

    def clear_all(self) -> None:
        with self._lock:
            for entries in self._subscriber_map.values():
                for _, wrapper in entries:
                    try:
                        self._dispatch_signal.disconnect(wrapper)
                    except (TypeError, RuntimeError):
                        pass
            self._subscriber_map.clear()


class _EventBusProxy:
    __slots__ = ("_impl", "_lock")

    def __init__(self):
        self._impl: "EventBus | None" = None
        self._lock = threading.Lock()

    def _ensure(self) -> EventBus:
        # ① 快路径：已构造则直接返回，不碰锁
        if self._impl is None:
            # ② 慢路径：双重检查锁
            with self._lock:
                if self._impl is None:
                    app = QCoreApplication.instance()
                    if app is None:
                        # QApplication 尚未创建：EventBus 亲和性将绑在
                        # 构造线程。若构造线程不是未来的主线程，后续
                        # 主线程 emit 会走 QueuedConnection，需要主线程
                        # 事件循环运行才能投递。合法但值得记录。
                        logger.debug(
                            "EventBus 在 QApplication 创建前构造，"
                            "线程亲和性绑定到当前线程 %r",
                            QThread.currentThread())
                        self._impl = EventBus()
                    else:
                        on_main = QThread.currentThread() is app.thread()
                        if not on_main:
                            logger.warning(
                                "EventBus 首次构造在非主线程，"
                                "修正线程亲和性到主线程")
                        bus = EventBus()
                        if not on_main:
                            # QObject 亲和性绑在构造线程上。构造落在子线程时，
                            # 主线程后续 emit 的 AutoConnection 会被判为跨线程，
                            # 订阅者槽被投递到子线程。moveToThread 无 parent 对象
                            # 在构造线程内调用是合法的，移到主线程后 emit 走 Direct。
                            bus.moveToThread(app.thread())
                        self._impl = bus
        return self._impl

    def subscribe(self, event_type, slot):
        _warn_if_not_main_thread("subscribe")
        return self._ensure().subscribe(event_type, slot)

    def init(self) -> None:
        """显式构造 EventBus。应在 QApplication 创建后调用。

        不调用时仍可工作（首次 subscribe/publish 惰性构造），但构造
        时机不可控：测试环境下 QApplication 可能尚未创建，线程亲和性
        会绑到构造线程。显式 init 让时机确定，且便于测试断言。
        """
        self._ensure()
    
    def unsubscribe(self, event_type, slot):
        _warn_if_not_main_thread("unsubscribe")
        return self._ensure().unsubscribe(event_type, slot)

    def publish(self, event_type, **kwargs):
        _warn_if_not_main_thread("publish")
        return self._ensure().publish(event_type, **kwargs)

    def clear_all(self):
        if self._impl is not None:
            self._impl.clear_all()


event_bus = _EventBusProxy()