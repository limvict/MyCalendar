# coding: utf-8
"""lunar：输入类型、fallback、qdate 转换、农历转公历、索引缓存隔离。"""
from datetime import date, datetime
import threading
import time
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

    def test_tuple_too_short_raises(self):
        with pytest.raises((ValueError, TypeError)):
            lunar._to_date((2024, 1))

    def test_none_raises(self):
        with pytest.raises(TypeError):
            lunar._to_date(None)


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

    def test_friday_is_workday(self):
        # 2024-01-05 周五
        assert lunar._fallback_is_holiday(date(2024, 1, 5)) is False
        assert lunar._fallback_is_workday(date(2024, 1, 5)) is True

    def test_saturday_not_workday(self):
        assert lunar._fallback_is_workday(date(2024, 1, 6)) is False

    def test_sunday_is_holiday(self):
        assert lunar._fallback_is_holiday(date(2024, 1, 7)) is True


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

    def test_mid_autumn_2024(self):
        # 2024 中秋 = 9 月 17 日
        assert lunar.lunar_to_gregorian(2024, 8, 15) == date(2024, 9, 17)

    def test_leap_month_out_of_range(self):
        assert lunar.lunar_to_gregorian(2024, 14, 1) is None


@pytest.mark.skipif(not CNLUNAR_AVAILABLE, reason="需要 cnlunar")
class TestGetLunar:
    def test_basic(self):
        lunar_obj = lunar.get_lunar_by_datetime((2024, 2, 10))
        assert lunar_obj is not None
        assert lunar_obj.lunarMonth == 1
        assert lunar_obj.lunarDay == 1

    def test_invalid_input(self):
        assert lunar.get_lunar_by_datetime("bad") is None


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


@pytest.mark.skipif(not CNLUNAR_AVAILABLE, reason="需要 cnlunar")
class TestLunarIndexSingleFlight:
    def test_single_flight_concurrent(self, monkeypatch):
        lunar.clear_lunar_caches()
        calls = []
        orig = lunar._compute_lunar_index

        def counting(year):
            calls.append(year)
            time.sleep(0.05)
            return orig(year)

        monkeypatch.setattr(lunar, "_compute_lunar_index", counting)

        results, errors = [], []

        def worker():
            try:
                results.append(lunar._build_lunar_index(2024))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert calls == [2024]
        assert all(r is results[0] for r in results)

    def test_clear_caches_does_not_break_locks(self):
        lunar.clear_lunar_caches()
        locks_before = dict(lunar._index_locks)
        lunar.clear_lunar_caches()
        assert lunar._index_locks == locks_before
