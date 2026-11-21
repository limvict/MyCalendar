"""日程到点提醒：轮询 ScheduleManager，支持 snooze。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..config.constants import SCHEDULE_REMIND_CHECK_INTERVAL_MS
from ..utils.logging_setup import get_logger
from .schedule import ScheduleManager

logger = get_logger()


class ScheduleReminder(QObject):
    # (schedule_id, title) -> main_window 接弹窗
    due = pyqtSignal(str, str)

    def __init__(
        self,
        manager: ScheduleManager,
        interval_ms: int = SCHEDULE_REMIND_CHECK_INTERVAL_MS,
        parent=None,
    ):
        super().__init__(parent)
        self._mgr = manager
        self._fired: set[str] = set()
        self._last_day: date | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._check)
        self._timer.start()

    def _check(self) -> None:
        now = datetime.now()
        today = now.date()

        # 跨天清理，避免 _fired 无限增长
        if self._last_day != today:
            today_key = today.strftime("%Y%m%d")
            self._fired = {k for k in self._fired if k.endswith(today_key)}
            self._last_day = today

        for s in self._mgr.on(today):
            if not s.remind_minutes or s.done or not s.time:
                continue

            # 1) snooze 处理优先
            if s.snoozed_until:
                try:
                    snooze_until = datetime.fromisoformat(s.snoozed_until)
                    if snooze_until.tzinfo is not None:
                        snooze_until = snooze_until.astimezone().replace(tzinfo=None)
                except (TypeError, ValueError, OverflowError):
                    snooze_until = None
                if snooze_until is not None and now < snooze_until:
                    continue
                key = f"{s.id}:{today:%Y%m%d}"
                if key not in self._fired:
                    self._fired.add(key)
                    self._clear_snooze(s.id)
                    self.due.emit(s.id, s.title)
                continue

            # 2) 正常提醒窗口
            try:
                occurrence = datetime.strptime(f"{today.isoformat()} {s.time}", "%Y-%m-%d %H:%M")
            except ValueError:
                logger.warning("跳过无效日程时间 id=%s time=%r", s.id, s.time)
                continue
            due_at = occurrence - timedelta(minutes=s.remind_minutes)
            if due_at <= now < due_at + timedelta(minutes=1):
                key = f"{s.id}:{today:%Y%m%d}"
                if key not in self._fired:
                    self._fired.add(key)
                    self.due.emit(s.id, s.title)

    def snooze(self, schedule_id: str, minutes: int) -> bool:
        """把提醒延后 minutes 分钟。返回是否成功。"""
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
            return False
        until = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        try:
            if self._mgr.update(schedule_id, snoozed_until=until) is None:
                return False
        except Exception:
            logger.exception("设置日程 snooze 失败 id=%s", schedule_id)
            return False
        prefix = f"{schedule_id}:"
        self._fired = {key for key in self._fired if not key.startswith(prefix)}
        return True

    def _clear_snooze(self, schedule_id: str) -> None:
        try:
            self._mgr.update(schedule_id, snoozed_until="")
        except Exception:
            logger.exception("清除 snooze 失败 id=%s", schedule_id)

    def stop(self) -> None:
        self._timer.stop()
