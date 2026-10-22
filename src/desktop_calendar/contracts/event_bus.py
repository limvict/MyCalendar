# coding: utf-8
import threading
from typing import Callable, Any, Dict, List, Tuple

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QCoreApplication

from desktop_calendar.utils.logging_setup import get_logger

logger = get_logger()


def _same_callable(a, b) -> bool:
    """安全比较两个 callable 是否指向同一个绑定方法。"""
    try:
        if a is b:
            return True
        sa = getattr(a, "__self__", None)
        sb = getattr(b, "__self__", None)
        fa = getattr(a, "__func__", None)
        fb = getattr(b, "__func__", None)
        if sa is not None and sb is not None and fa is not None and fb is not None:
            return sa is sb and fa is fb
        return bool(a == b)
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


class EventBus(QObject):
    """事件总线：发布-订阅模式，解耦各模块间通信。"""
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
                except Exception:
                    logger.exception(
                        f"事件 {event_type} 的订阅者 {slot} 抛异常，已隔离")

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

    def publish(self, event_type, **kwargs):
        _warn_if_not_main_thread("publish")
        self._dispatch_signal.emit(event_type, kwargs)

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
    """懒创建 + 线程安全的全局代理，API 与原 EventBus 完全兼容。"""
    __slots__ = ("_impl", "_lock")

    def __init__(self):
        self._impl: "EventBus | None" = None
        self._lock = threading.Lock()

    def _ensure(self) -> EventBus:
        if self._impl is None:
            with self._lock:
                if self._impl is None:
                    # 首次构造必须在主线程，否则 AutoConnection 会把
                    # 后续主线程 emit 投递到子线程
                    _warn_if_not_main_thread("首次构造")
                    self._impl = EventBus()
        return self._impl

    def subscribe(self, event_type, slot):
        _warn_if_not_main_thread("subscribe")
        return self._ensure().subscribe(event_type, slot)

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