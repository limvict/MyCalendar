# contracts/holiday_source.py
from __future__ import annotations

from typing import Callable, Literal, Mapping, Protocol, TypeAlias

HolidayKind: TypeAlias = Literal["holiday", "workday"]
HolidayMap: TypeAlias = Mapping[str, HolidayKind]


class HolidaySourceError(Exception):
    """端口层错误基类。"""

class NetworkError(HolidaySourceError): ...
class ParseError(HolidaySourceError): ...
class CancelledError(HolidaySourceError): ...


# year 回传是为了让回调无状态（同一回调可服务多次请求）。
OnReady: TypeAlias = Callable[[int, HolidayMap], None]
# year 用于丢弃过期响应；err 是结构化异常子类，调用方可按类型分支。
OnError: TypeAlias = Callable[[int, HolidaySourceError], None]


class HolidaySource(Protocol):
    """节假日数据源。

    线程约定：
    - 所有方法必须在构造实例的同一线程调用（通常主线程）。
    - on_ready / on_error 也保证在该线程执行；实现负责把 worker 结果 marshal 回来。

    生命周期：
    - start() → request()* → shutdown()
    - start() 返回 False 表示不可用；此后 request() 返回 False，on_error 不会被调用。
    - start/shutdown 幂等；shutdown 后 request 返回 False。
    """

    def start(self) -> bool:
        """启动后台资源。幂等。"""

    def request(self, year: int) -> bool:
        """请求某年数据。返回 False 表示未接受（未 start、已 shutdown、或同 year 在途）。

        接受后，恰好一次 on_ready(year, ...) 或 on_error(year, ...)。
        """

    def shutdown(self, timeout_ms: int = 3000) -> bool:
        """停止并回收后台资源。幂等。返回 True 表示干净退出（无在途请求）。"""


class HolidaySourceFactory(Protocol):
    """source 工厂。HolidayManager 通过它注入实现。

    parent 是 Qt 父对象（可选）。契约层不 import Qt，因此这里只是
    ``object | None`` 语义——需要 QObject 父对象的实现自行 cast。
    """

    def __call__(
        self,
        *,
        on_ready: OnReady,
        on_error: OnError,
        parent=None,
    ) -> HolidaySource: ...