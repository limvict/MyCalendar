# coding: utf-8
"""lunar 补充：更多输入类型、索引缓存隔离。"""
from datetime import date, datetime

import pytest

from desktop_calendar.core import lunar


class TestToDateMore:
    def test_tuple_too_short_raises(self):
        with pytest.raises((ValueError, TypeError)):
            lunar._to_date((2024, 1))

    def test_none_raises(self):
        with pytest.raises(TypeError):
            lunar._to_date(None)


class TestFallbackMore:
    def test_friday_is_workday(self):
        # 2024-01-05 周五
        assert lunar._fallback_is_holiday(date(2024, 1, 5)) is False
        assert lunar._fallback_is_workday(date(2024, 1, 5)) is True

    def test_saturday_not_workday(self):
        assert lunar._fallback_is_workday(date(2024, 1, 6)) is False

    def test_sunday_is_holiday(self):
        assert lunar._fallback_is_holiday(date(2024, 1, 7)) is True


CNLUNAR_AVAILABLE = lunar.HAS_CNLUNAR


@pytest.mark.skipif(not CNLUNAR_AVAILABLE, reason="需要 cnlunar")
class TestLunarToGregorianMore:
    def test_mid_autumn_2024(self):
        # 2024 中秋 = 9 月 17 日
        assert lunar.lunar_to_gregorian(2024, 8, 15) == date(2024, 9, 17)

    def test_leap_month_out_of_range(self):
        assert lunar.lunar_to_gregorian(2024, 14, 1) is None


@pytest.mark.skipif(not CNLUNAR_AVAILABLE, reason="需要 cnlunar")
class TestLunarIndexIsolation:
    def test_two_years_different_objects(self):
        lunar.clear_lunar_caches()
        a = lunar._build_lunar_index(2023)
        b = lunar._build_lunar_index(2024)
        assert a is not b

    def test_same_year_cached(self):
        lunar.clear_lunar_caches()
        a = lunar._build_lunar_index(2024)
        b = lunar._build_lunar_index(2024)
        assert a is b