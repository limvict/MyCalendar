# coding: utf-8
"""P0 回归：QtHolidaySource 的 on_ready / on_error 必须是强引用。

历史 bug：曾用 weakref.ref(bound_method)，bound method 每次属性访问
都新建临时对象，weakref 立即失效，回调永远拿不到，节假日永远不更新。
"""
import pytest


def test_handle_ready_calls_on_ready(qapp):
    """P0 回归：_handle_ready 必须调到 on_ready，不得 AttributeError。"""
    from desktop_calendar.infrastructure.network.qt_holiday_source import (
        make_qt_holiday_source,
    )

    received = []
    src = make_qt_holiday_source(
        on_ready=lambda y, d: received.append((y, d)),
        on_error=lambda y, e: received.append(("err", y, e)),
    )
    assert src.start() is True
    try:
        # 模拟 worker 信号到达主线程。_worker 非 None 时才转发，
        # 所以需保证 start() 成功。
        src._handle_ready(2024, {"2024-01-01": "holiday"})
        assert received == [(2024, {"2024-01-01": "holiday"})]
    finally:
        src.shutdown()


def test_handle_error_calls_on_error(qapp):
    """P0 回归：_handle_error 必须调到 on_error。"""
    from desktop_calendar.contracts.holiday_source import NetworkError
    from desktop_calendar.infrastructure.network.qt_holiday_source import (
        make_qt_holiday_source,
    )

    received = []
    src = make_qt_holiday_source(
        on_ready=lambda y, d: received.append(("ok", y, d)),
        on_error=lambda y, e: received.append(("err", y, type(e).__name__)),
    )
    assert src.start() is True
    try:
        src._handle_error(2024, "network", "boom")
        assert received == [("err", 2024, "NetworkError")]
    finally:
        src.shutdown()


def test_shutdown_drops_late_signals(qapp):
    """shutdown 后到达的信号被丢弃（_worker 已置 None）。"""
    from desktop_calendar.infrastructure.network.qt_holiday_source import (
        make_qt_holiday_source,
    )

    received = []
    src = make_qt_holiday_source(
        on_ready=lambda y, d: received.append((y, d)),
        on_error=lambda y, e: received.append(("err", y)),
    )
    assert src.start() is True
    src.shutdown()

    src._handle_ready(2024, {})
    src._handle_error(2024, "network", "x")
    assert received == []