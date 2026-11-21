"""Automatic attendance punching at configured work-rule times."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from desktop_calendar.config.manager import get_logger, to_bool
from desktop_calendar.core.attendance import (
    PUNCH_IN_DEADLINE_HOUR,
    AttendanceStore,
    PunchRejected,
    WorkRule,
    _is_workday,
)

logger = get_logger()

_MAX_TIMER_MS = 24 * 60 * 60 * 1000
_LOOKAHEAD_DAYS = 15
_MAX_LATE = timedelta(minutes=15)
_EARLY_TOLERANCE = timedelta(seconds=2)


class AttendanceAutoPunchManager(QObject):
    """Schedule missing punches while the application is running.

    Missed start times are intentionally not backfilled on startup. A punch
    recorded by this manager uses the actual local time when the timer fires.
    """

    punched = pyqtSignal(str, str)
    failed = pyqtSignal(str, str)

    def __init__(self, parent, config, store: AttendanceStore):
        super().__init__(parent)
        self._config = config
        self._store = store
        self._rule = WorkRule.from_config(config)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_trigger)
        self._pending: tuple[datetime, str] | None = None
        self._shutting_down = False

    def _enabled(self) -> bool:
        return to_bool(
            self._config.get_nested("attendance_cfg", "enable_auto_punch", default=False),
            default=False,
        )

    @staticmethod
    def _target(day: date, minutes: int) -> datetime:
        hour, minute = divmod(int(minutes), 60)
        return datetime.combine(day, time(hour, minute))

    def _next_target(self, now: datetime) -> tuple[datetime, str] | None:
        today = now.date()
        for offset in range(_LOOKAHEAD_DAYS):
            day = today + timedelta(days=offset)
            if not _is_workday(day):
                continue
            record = self._store.get_record(day)
            start = self._target(day, self._rule.start)
            end = self._target(day, self._rule.end)
            if not record.get("in") and start > now and start.hour < PUNCH_IN_DEADLINE_HOUR:
                return start, "in"
            if record.get("in") and not record.get("out") and end > now:
                return end, "out"
        return None

    def reschedule(self) -> None:
        if self._shutting_down:
            return
        self._timer.stop()
        self._pending = None
        self._rule = WorkRule.from_config(self._config)
        if not self._enabled():
            return
        pending = self._next_target(datetime.now())
        if pending is None:
            return
        self._pending = pending
        delay_ms = int((pending[0] - datetime.now()).total_seconds() * 1000)
        self._timer.start(max(0, min(delay_ms, _MAX_TIMER_MS)))

    def _on_trigger(self) -> None:
        pending = self._pending
        self._pending = None
        if self._shutting_down or pending is None or not self._enabled():
            return
        target, action = pending
        now = datetime.now()
        if now + _EARLY_TOLERANCE < target:
            self.reschedule()
            return
        if now.date() != target.date() or not _is_workday(target.date()):
            self.reschedule()
            return
        if now - target > _MAX_LATE:
            logger.warning(
                "自动考勤触发过晚，跳过 action=%s target=%s now=%s",
                action,
                target.isoformat(),
                now.isoformat(timespec="seconds"),
            )
            self.reschedule()
            return

        record = self._store.get_record(target.date())
        if (action == "in" and record.get("in")) or (
            action == "out" and (not record.get("in") or record.get("out"))
        ):
            self.reschedule()
            return
        try:
            punched_at, _updated = self._store.punch(action, now=now)
        except PunchRejected as error:
            logger.warning("自动考勤未写入 action=%s code=%s", action, error.code)
        except Exception as error:
            logger.exception("自动考勤保存失败 action=%s", action)
            self.failed.emit(action, str(error))
        else:
            self.punched.emit(action, punched_at)
        finally:
            self.reschedule()

    def shutdown(self) -> None:
        self._shutting_down = True
        self._pending = None
        self._timer.stop()
