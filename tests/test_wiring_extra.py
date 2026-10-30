# coding: utf-8
"""wiring 订阅：事件集合精确断言（比 len 断言更严谨）。"""
from unittest.mock import MagicMock

from desktop_calendar import wiring
from desktop_calendar.contracts.events import EventType


def test_subscriptions_cover_expected_events():
    actual = {evt for evt, _ in wiring._subscriptions(MagicMock())}
    expected = {
        EventType.HOLIDAY_UPDATED,
        EventType.MEMORIAL_CHANGED,
        EventType.MEMORIAL_REMIND_TRIGGERED,
        EventType.WINDOW_SHOW,
        EventType.WINDOW_QUIT,
        EventType.WINDOW_TOGGLE_TOPMOST,
        EventType.OPEN_SETTINGS,
        EventType.BACKUP_MEMORIAL,
        EventType.RESTORE_MEMORIAL,
        EventType.UPDATE_AVAILABLE,
        EventType.UPDATE_FAILED,
        EventType.UPDATE_READY,
        EventType.UPDATE_PROGRESS,
    }
    assert actual == expected
    # SETTINGS_CHANGED 当前未订阅（注释说明保留备未来）
    assert EventType.SETTINGS_CHANGED not in actual