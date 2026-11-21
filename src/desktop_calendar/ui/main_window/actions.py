# coding: utf-8
"""功能入口：日程增删、番茄钟、日程提醒与 QQ 音乐窗口。"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QInputDialog,
    QMessageBox,
)

from desktop_calendar.config.i18n import tr
from desktop_calendar.ui.dialogs import (
    PomodoroDialog,
    ScheduleDialog,
    ScheduleRemindDialog,
    msg_error,
)
from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME

logger = logging.getLogger(APP_LOGGER_NAME)


class MainWindowActionsMixin:
    """功能入口：日程增删、番茄钟、日程提醒与 QQ 音乐窗口。"""

    def _open_schedule_dialog(self):
        dialog = ScheduleDialog(
            self._schedule_mgr,
            self.cal.selectedDate().toPyDate(),
            self,
            bundle=self.theme_mgr.current,
        )
        dialog.changed.connect(self._refresh_schedule_ui)
        try:
            dialog.exec()
        finally:
            self._refresh_schedule_ui()
            dialog.deleteLater()

    def _quick_add_schedule(self) -> None:
        selected_date = self.cal.selectedDate().toPyDate()
        title, accepted = QInputDialog.getText(
            self,
            "快速添加日程",
            f"为 {selected_date.year:04d}年{selected_date.month:02d}月"
            f"{selected_date.day:02d}日 添加全天日程：",
        )
        if not accepted:
            return
        title = title.strip()
        if not title:
            QMessageBox.information(self, "快速添加日程", "请输入日程标题。")
            return
        try:
            self._schedule_mgr.add(
                title=title,
                date=selected_date.isoformat(),
            )
        except (OSError, ValueError, TypeError) as error:
            logger.exception("快速添加日程失败 date=%s", selected_date)
            msg_error(self, tr("msg.error"), f"无法添加日程：{error}")
            return
        self._refresh_schedule_ui()

    def _open_pomodoro_dialog(self, *_args) -> None:
        if self._pomodoro_dialog is not None:
            self._pomodoro_dialog.showNormal()
            self._pomodoro_dialog.raise_()
            self._pomodoro_dialog.activateWindow()
            return
        dialog = PomodoroDialog(self._pomodoro_timer, self, focus_log=self.focus_log)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(self._clear_pomodoro_dialog)
        self._pomodoro_dialog = dialog
        dialog.show()

    def _clear_pomodoro_dialog(self, *_args) -> None:
        self._pomodoro_dialog = None

    def _on_pomodoro_work_completed(
        self,
        _round_index: int,
        work_seconds: int,
    ) -> None:
        minutes = max(1, round(work_seconds / 60))
        try:
            self.focus_log.add(minutes, started_at=self._pomodoro_work_started_at)
        except Exception:
            logger.exception("写入专注记录失败")
        self._update_focus_label()

    def _on_pomodoro_phase_changed(self, phase: str) -> None:
        if phase == "work":
            self._pomodoro_work_started_at = datetime.now()
        else:
            self._pomodoro_work_started_at = None

    def _on_schedule_due(self, _schedule_id: str, title: str) -> None:
        self.sound_mgr.play("assets/alert.wav")
        dialog = ScheduleRemindDialog(title, parent=self, bundle=self.theme_mgr.current)
        try:
            dialog.exec()
            if dialog.snooze_minutes:
                if not self._schedule_reminder.snooze(_schedule_id, dialog.snooze_minutes):
                    msg_error(self, tr("msg.error"), "无法推迟日程提醒。")
        finally:
            dialog.deleteLater()

    def _open_qq_music(self) -> None:
        from desktop_calendar.ui.dialogs.qq_music import QQMusicDialog

        dialog = getattr(self, "_qq_music_dialog", None)
        if dialog is None:
            dialog = QQMusicDialog(self)
            self._qq_music_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
