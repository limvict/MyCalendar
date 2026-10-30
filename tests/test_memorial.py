# coding: utf-8
from datetime import date, datetime

import pytest

from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core import memorial as M


class TestToPydate:
    def test_date(self):
        assert M._to_pydate(date(2024, 1, 1)) == date(2024, 1, 1)

    def test_datetime(self):
        assert M._to_pydate(datetime(2024, 1, 1, 12)) == date(2024, 1, 1)

    def test_qdate_like(self):
        class FakeQDate:
            def year(self): return 2024
            def month(self): return 3
            def day(self): return 15
        assert M._to_pydate(FakeQDate()) == date(2024, 3, 15)


class TestClampInt:
    @pytest.mark.parametrize("val,lo,hi,dft,expected", [
        (5, 1, 10, 1, 5),
        (-5, 1, 10, 1, 1),
        (20, 1, 10, 1, 10),
        (None, 1, 10, 7, 7),
        ("abc", 1, 10, 7, 7),
        ("5", 1, 10, 1, 5),
    ])
    def test_clamp(self, val, lo, hi, dft, expected):
        assert M._clamp_int(val, lo, hi, dft) == expected


class TestNormalizeMemorial:
    def test_empty_gets_defaults(self):
        result = M.normalize_memorial({})
        assert result["type"] == "solar"
        assert result["repeat_type"] == "year"
        assert result["month"] == 1
        assert result["day"] == 1
        assert result["enabled"] is True
        assert result["advance_days"] == 0
        assert result["isleap"] is False

    def test_lunar_month_and_day_clamped(self):
        result = M.normalize_memorial({"type": "lunar", "month": 13, "day": 40})
        assert result["month"] == 12
        assert result["day"] == 30

    def test_solar_day_clamped_to_month(self):
        # 2 月 30 日应统一收敛到 29（用 2024 闰年校验）
        result = M.normalize_memorial({"month": 2, "day": 30})
        assert result["day"] == 29

    def test_solar_day_31_in_april(self):
        result = M.normalize_memorial({"month": 4, "day": 31})
        assert result["day"] == 30

    def test_week_repeat_forces_solar(self):
        result = M.normalize_memorial({"repeat_type": "week", "type": "lunar"})
        assert result["type"] == "solar"
        assert result["isleap"] is False

    def test_week_day_clamped_to_7(self):
        result = M.normalize_memorial({"repeat_type": "week", "day": 10})
        assert result["day"] == 7

    def test_advance_days_clamped(self):
        result = M.normalize_memorial({"advance_days": 1000})
        assert result["advance_days"] == 365
        result = M.normalize_memorial({"advance_days": -5})
        assert result["advance_days"] == 0


class TestNormalizeMemorialDays:
    def test_non_list(self):
        assert M.normalize_memorial_days("abc") == ([], 0)
        assert M.normalize_memorial_days(None) == ([], 0)

    def test_filters_non_dict(self):
        result, skipped = M.normalize_memorial_days(
            [1, "x", {}, {"name": "a"}])
        assert skipped == 2
        assert len(result) == 2

    def test_count_returned(self):
        result, skipped = M.normalize_memorial_days([{"name": "a"}])
        assert skipped == 0
        assert len(result) == 1


class TestSolarMatching:
    def test_monthly_day_30_in_feb(self):
        # 2024-02-29 是月末，配置 30 号应在 29 号命中
        assert M._match_solar_monthly(date(2024, 2, 29), 30) is True

    def test_monthly_normal(self):
        assert M._match_solar_monthly(date(2024, 1, 15), 15) is True
        assert M._match_solar_monthly(date(2024, 1, 14), 15) is False

    def test_yearly(self):
        assert M._match_solar_yearly(date(2024, 3, 15), 3, 15) is True
        assert M._match_solar_yearly(date(2024, 4, 15), 3, 15) is False


class TestNextSolar:
    def test_next_monthly(self):
        assert M._next_solar_monthly(date(2024, 1, 15), 20) == date(2024, 1, 20)

    def test_monthly_rolls_over(self):
        assert M._next_solar_monthly(date(2024, 1, 25), 20) == date(2024, 2, 20)

    def test_monthly_december_rollover(self):
        assert M._next_solar_monthly(date(2024, 12, 25), 20) == date(2025, 1, 20)

    def test_yearly_same_year(self):
        assert M._next_solar_yearly(date(2024, 1, 1), 12, 31) == date(2024, 12, 31)

    def test_yearly_rollover(self):
        assert M._next_solar_yearly(date(2024, 12, 31), 1, 1) == date(2025, 1, 1)

    def test_yearly_day_clamped(self):
        assert M._next_solar_yearly(date(2024, 1, 1), 2, 30) == date(2024, 2, 29)


class TestNextWeek:
    def test_monday(self):
        # 2024-01-01 是周一，下一个周一 = 01-08
        assert M._next_week_date(date(2024, 1, 1), 1) == date(2024, 1, 8)

    def test_sunday(self):
        assert M._next_week_date(date(2024, 1, 1), 7) == date(2024, 1, 7)


class TestGetNextMemorialDate:
    def test_solar_yearly(self):
        mem = {"repeat_type": "year", "type": "solar",
               "month": 6, "day": 15, "enabled": True,
               "advance_days": 0, "isleap": False}
        assert M.get_next_memorial_date(mem, date(2024, 1, 1)) == date(2024, 6, 15)

    def test_solar_yearly_include_base(self):
        mem = {"repeat_type": "year", "type": "solar",
               "month": 1, "day": 1, "enabled": True,
               "advance_days": 0, "isleap": False}
        assert M.get_next_memorial_date(
            mem, date(2024, 1, 1), include_base=True) == date(2024, 1, 1)

    def test_weekly(self):
        mem = {"repeat_type": "week", "type": "solar",
               "month": 1, "day": 3, "enabled": True,
               "advance_days": 0, "isleap": False}
        assert M.get_next_memorial_date(mem, date(2024, 1, 1)) == date(2024, 1, 3)


class TestBuildMemorialIndex:
    def test_empty(self):
        idx = M.build_memorial_index([])
        assert idx["solar_year"] == {}

    def test_disabled_skipped(self):
        idx = M.build_memorial_index([{
            "enabled": False, "repeat_type": "year",
            "type": "solar", "month": 1, "day": 1,
        }])
        assert idx["solar_year"] == {}

    def test_solar_year(self):
        idx = M.build_memorial_index([{
            "enabled": True, "repeat_type": "year",
            "type": "solar", "month": 3, "day": 15,
        }])
        assert (3, 15) in idx["solar_year"]

    def test_non_list(self):
        idx = M.build_memorial_index("abc")
        assert idx["solar_year"] == {}


# ---- 依赖 cnlunar 的用例 ----
CNLUNAR_AVAILABLE = lunar_mod.HAS_CNLUNAR


@pytest.mark.skipif(not CNLUNAR_AVAILABLE, reason="需要 cnlunar")
class TestLunar:
    def test_lunar_yearly_2024_spring_festival(self):
        mem = {"repeat_type": "year", "type": "lunar",
               "month": 1, "day": 1, "enabled": True,
               "advance_days": 0, "isleap": False}
        # 2024 春节 = 2024-02-10
        assert M.get_next_memorial_date(mem, date(2024, 1, 1)) == date(2024, 2, 10)