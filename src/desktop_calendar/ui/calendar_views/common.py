# coding: utf-8
"""周/年视图共用的常量与日期计算。"""

from __future__ import annotations

from PyQt6.QtCore import QDate

from desktop_calendar.config.i18n import tr

_WEEKDAY_NAMES = tuple(tr(f"weekday.short.{day}") for day in range(1, 8))
_SCHEDULE_DEFAULT = "#4A90D9"


_WEEKDAY_NAMES = tuple(tr(f"weekday.short.{day}") for day in range(1, 8))


_SCHEDULE_DEFAULT = "#4A90D9"


def week_start(value: QDate) -> QDate:
    return value.addDays(1 - value.dayOfWeek())
