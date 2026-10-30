# coding: utf-8
from desktop_calendar.contracts.events import EventType


class TestEventType:
    def test_strings_are_unique(self):
        values = [
            v for k, v in vars(EventType).items()
            if not k.startswith("_") and isinstance(v, str)
        ]
        assert len(values) == len(set(values))

    def test_known_events_exist(self):
        assert EventType.HOLIDAY_UPDATED == "holiday_updated"
        assert EventType.MEMORIAL_CHANGED == "memorial_changed"
        assert EventType.UPDATE_READY == "update_ready"