# coding: utf-8
"""节假日数据源端口。

core 层只依赖本协议，不 import 任何 Qt 网络实现。
"""
from __future__ import annotations

from typing import Any, Callable, Protocol

OnReady = Callable[[int, dict], None]
OnError = Callable[[str], None]


class HolidaySource(Protocol):
    """节假日数据源。

    实现约定：
    - on_ready / on_error 必须在构造本实例的线程（通常主线程）执行。
    - shutdown 幂等。
    """

    def start(self) -> bool:
        """启动后台资源。返回 False 表示不可用。幂等。"""
        ...

    def request(self, year: int) -> None:
        """请求拉取某年数据。允许排队。"""
        ...

    def shutdown(self, timeout_ms: int = 3000) -> bool:
        """停止并回收后台资源。返回 True 表示干净退出。幂等。"""
        ...


class HolidaySourceFactory(Protocol):
    """source 工厂签名。HolidayManager 通过它注入实现。"""

    def __call__(
        self,
        *,
        on_ready: OnReady,
        on_error: OnError,
        parent: Any = None,
    ) -> HolidaySource: ...
