# coding: utf-8
import json

import pytest

from desktop_calendar.infrastructure.network.qt_holiday_source import (
    HolidayNetWorker,
)


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