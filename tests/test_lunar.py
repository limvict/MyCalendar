# coding: utf-8
from datetime import date, datetime

import pytest

from desktop_calendar.core import lunar


class TestToDate:
    def test_date(self):
        assert lunar._to_date(date(2024, 1, 1)) == date(2024, 1, 1)

    def test_datetime(self):
        assert lunar._to_date(datetime(2024, 1, 1, 5)) == date(2024, 1, 1)

    def test_tuple(self):
        assert lunar._to_date((2024, 1, 1)) == date(2024, 1, 1)

    def test_list(self):
        assert lunar._to_date([2024, 1, 1]) == date(2024, 1, 1)

    def test_bool_rejected(self):
        with pytest.raises(TypeError):
            lunar._to_date(True)

    def test_invalid_type(self):
        with pytest.raises(TypeError):
            lunar._to_date("2024-01-01")


class TestFallbackHoliday:
    def test_weekend(self):
        # 2024-01-06 周六
        assert lunar._fallback_is_holiday(date(2024, 1, 6)) is True
        # 2024-01-07 周日
        assert lunar._fallback_is_holiday(date(2024, 1, 7)) is True

    def test_weekday(self):
        assert lunar._fallback_is_holiday(date(2024, 1, 1)) is False

    def test_workday(self):
        assert lunar._fallback_is_workday(date(2024, 1, 1)) is True
        assert lunar._fallback_is_workday(date(2024, 1, 6)) is False


class TestQDateToPyDate:
    def test_valid(self):
        class Fake:
            def year(self): return 2024
            def month(self): return 3
            def day(self): return 15
        assert lunar.qdate_to_pydate(Fake()) == date(2024, 3, 15)

    def test_none(self):
        with pytest.raises(TypeError):
            lunar.qdate_to_pydate(None)

    def test_invalid_type(self):
        with pytest.raises(TypeError):
            lunar.qdate_to_pydate(123)


CNLUNAR_AVAILABLE = lunar.HAS_CNLUNAR


@pytest.mark.skipif(not CNLUNAR_AVAILABLE, reason="需要 cnlunar")
class TestLunarToGregorian:
    def test_invalid_month(self):
        assert lunar.lunar_to_gregorian(2024, 0, 1) is None
        assert lunar.lunar_to_gregorian(2024, 13, 1) is None

    def test_invalid_day(self):
        assert lunar.lunar_to_gregorian(2024, 1, 0) is None
        assert lunar.lunar_to_gregorian(2024, 1, 31) is None

    def test_spring_festival_2024(self):
        # 2024 春节 = 2 月 10 日
        assert lunar.lunar_to_gregorian(2024, 1, 1) == date(2024, 2, 10)


@pytest.mark.skipif(not CNLUNAR_AVAILABLE, reason="需要 cnlunar")
class TestGetLunar:
    def test_basic(self):
        lunar_obj = lunar.get_lunar_by_datetime((2024, 2, 10))
        assert lunar_obj is not None
        assert lunar_obj.lunarMonth == 1
        assert lunar_obj.lunarDay == 1

    def test_invalid_input(self):
        assert lunar.get_lunar_by_datetime("bad") is None