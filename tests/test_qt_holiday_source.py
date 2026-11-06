# coding: utf-8
"""qt_holiday_source：P0 回调强引用回归 + JSON 多格式解析归一。"""
import json

import pytest

from desktop_calendar.infrastructure.network.qt_holiday_source import (
    HolidayNetWorker, make_qt_holiday_source,
)


# ===================== P0 回归：on_ready / on_error 必须是强引用 =====================
# 历史 bug：曾用 weakref.ref(bound_method)，bound method 每次属性访问
# 都新建临时对象，weakref 立即失效，回调永远拿不到，节假日永远不更新。
def test_handle_ready_calls_on_ready(qapp):
    """P0 回归：_handle_ready 必须调到 on_ready，不得 AttributeError。"""
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


# ===================== JSON 解析：多格式归一 =====================
class TestKindFromOff:
    def test_true(self):
        assert HolidayNetWorker._kind_from_off(True) == "holiday"

    def test_false(self):
        assert HolidayNetWorker._kind_from_off(False) == "workday"

    def test_missing_defaults_to_workday(self):
        assert HolidayNetWorker._kind_from_off(None) == "workday"

    def test_string(self):
        assert HolidayNetWorker._kind_from_off("true") == "holiday"
        assert HolidayNetWorker._kind_from_off("false") == "workday"


class TestIsDateLike:
    def test_valid(self):
        assert HolidayNetWorker._is_date_like("2024-01-01") is True

    def test_invalid(self):
        assert HolidayNetWorker._is_date_like("2024/01/01") is False
        assert HolidayNetWorker._is_date_like("20240101") is False
        assert HolidayNetWorker._is_date_like("") is False


class TestParseDayItems:
    def test_basic(self):
        items = [
            {"date": "2024-01-01", "isOffDay": True},
            {"date": "2024-01-02", "isOffDay": False},
        ]
        result = HolidayNetWorker._parse_day_items(items)
        assert result == {
            "2024-01-01": "holiday",
            "2024-01-02": "workday",
        }

    def test_missing_isoff_treated_as_workday(self):
        result = HolidayNetWorker._parse_day_items([{"date": "2024-01-01"}])
        assert result == {"2024-01-01": "workday"}

    def test_non_dict_skipped(self):
        items = ["x", {"date": "2024-01-01", "isOffDay": True}]
        assert HolidayNetWorker._parse_day_items(items) == {
            "2024-01-01": "holiday"
        }

    def test_missing_date_skipped(self):
        items = [{"isOffDay": True}, {"date": "", "isOffDay": True}]
        assert HolidayNetWorker._parse_day_items(items) == {}


class TestParseDayMap:
    def test_basic(self):
        result = HolidayNetWorker._parse_day_map(
            {"2024-01-01": True, "2024-01-02": False},
            date_keys_only=True)
        assert result == {
            "2024-01-01": "holiday",
            "2024-01-02": "workday",
        }

    def test_metadata_keys_filtered(self):
        result = HolidayNetWorker._parse_day_map(
            {"2024-01-01": True, "version": "1"},
            date_keys_only=True)
        assert result == {"2024-01-01": "holiday"}

    def test_metadata_keys_kept(self):
        result = HolidayNetWorker._parse_day_map(
            {"2024-01-01": True, "version": "1"},
            date_keys_only=False)
        assert "2024-01-01" in result


class TestParseHolidayJson:
    def test_natescarlet(self):
        raw = json.dumps({
            "year": 2024,
            "days": [
                {"date": "2024-01-01", "isOffDay": True},
                {"date": "2024-02-04", "isOffDay": False},
            ]
        })
        result = HolidayNetWorker._parse_holiday_json(raw, 2024)
        assert result == {
            "2024-01-01": "holiday",
            "2024-02-04": "workday",
        }

    def test_chinese_days_nested(self):
        raw = json.dumps({
            "days": {"2024-01-01": True, "2024-01-02": False}
        })
        result = HolidayNetWorker._parse_holiday_json(raw, 2024)
        assert result == {
            "2024-01-01": "holiday",
            "2024-01-02": "workday",
        }

    def test_top_level_date_map(self):
        raw = json.dumps({
            "2024-01-01": True,
            "2024-01-02": False,
            "version": "1.0",
        })
        result = HolidayNetWorker._parse_holiday_json(raw, 2024)
        assert result == {
            "2024-01-01": "holiday",
            "2024-01-02": "workday",
        }

    def test_list_format(self):
        raw = json.dumps([{"date": "2024-01-01", "isOffDay": True}])
        assert HolidayNetWorker._parse_holiday_json(raw, 2024) == {
            "2024-01-01": "holiday"
        }

    def test_unrecognized(self):
        with pytest.raises(ValueError):
            HolidayNetWorker._parse_holiday_json('"just a string"', 2024)

    def test_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            HolidayNetWorker._parse_holiday_json("{invalid", 2024)
