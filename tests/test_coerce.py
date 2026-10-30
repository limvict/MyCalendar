# coding: utf-8
import pytest

from desktop_calendar.utils.coerce import to_bool, to_holiday_kind


class TestToBool:
    @pytest.mark.parametrize("val,expected", [
        (True, True), (False, False),
        (1, True), (0, False), (-1, True),
        (1.5, True), (0.0, False),
        ("true", True), ("True", True), ("TRUE", True),
        ("yes", True), ("1", True), ("on", True),
        ("false", False), ("False", False), ("no", False),
        ("0", False), ("off", False),
    ])
    def test_known_values(self, val, expected):
        assert to_bool(val) is expected

    def test_unknown_string_uses_default(self):
        assert to_bool("maybe", default=False) is False
        assert to_bool("maybe", default=True) is True

    def test_none_uses_default(self):
        assert to_bool(None, default=True) is True
        assert to_bool(None, default=False) is False

    def test_container_uses_default(self):
        assert to_bool([], default=True) is True
        assert to_bool([1], default=False) is False

    def test_string_whitespace(self):
        assert to_bool("  true  ") is True
        assert to_bool("\tno\n") is False


class TestToHolidayKind:
    @pytest.mark.parametrize("val,expected", [
        ("holiday", "holiday"), ("workday", "workday"),
        ("HOLIDAY", "holiday"),
        ("true", "holiday"), ("false", "workday"),
        (True, "holiday"), (False, "workday"),
        (1, "holiday"), (0, "workday"),
        (2.5, "holiday"),
    ])
    def test_valid(self, val, expected):
        assert to_holiday_kind(val) == expected

    @pytest.mark.parametrize("val", ["maybe", None, [], {}, "holi", object()])
    def test_invalid(self, val):
        assert to_holiday_kind(val) is None
        
def test_to_bool_nan_returns_default():
    """P2 回归：NaN 视为无效，返回 default 而非 True。"""
    from desktop_calendar.utils.coerce import to_bool

    nan = float("nan")
    assert to_bool(nan, default=False) is False
    assert to_bool(nan, default=True) is True
    # 非 NaN 的正常浮点保持"非零即 True"
    assert to_bool(0.0) is False
    assert to_bool(1.5) is True
    assert to_bool(float("inf")) is True
    assert to_bool(float("-inf")) is True


def test_to_holiday_kind_nan_returns_none():
    """P2 回归：NaN 无法判定 → None，调用方丢弃。"""
    from desktop_calendar.utils.coerce import to_holiday_kind

    assert to_holiday_kind(float("nan")) is None
    # 回归
    assert to_holiday_kind(1) == "holiday"
    assert to_holiday_kind(0) == "workday"
    assert to_holiday_kind(True) == "holiday"
    assert to_holiday_kind("holiday") == "holiday"
    assert to_holiday_kind("unknown") is None