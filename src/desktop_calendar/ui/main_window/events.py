# coding: utf-8
"""事件总线：订阅表、退订、payload 校验与各事件回调。"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QDialog,
)

from desktop_calendar.config.manager import config
from desktop_calendar.contracts.event_bus import EventType, event_bus
from desktop_calendar.ui.controllers import settings_controller
from desktop_calendar.ui.dialogs import (
    MemorialRemindDialog,
)
from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME

from .helpers import _DEFER_RESCHEDULE_THRESHOLD

logger = logging.getLogger(APP_LOGGER_NAME)


class MainWindowEventsMixin:
    """事件总线：订阅表、退订、payload 校验与各事件回调。"""

    def _event_subscriptions(self):
        return [
            (EventType.HOLIDAY_UPDATED, self._on_holiday_updated),
            (EventType.MEMORIAL_CHANGED, self._on_memorial_changed),
            (EventType.MEMORIAL_REMIND_TRIGGERED, self._on_memorial_remind_triggered),
            (EventType.WINDOW_SHOW, self._on_window_show),
            (EventType.WINDOW_HIDE, self._on_window_hide),
            (EventType.WINDOW_QUIT, self._on_window_quit),
            (EventType.OPEN_SETTINGS, self._on_open_settings),
            (EventType.BACKUP_MEMORIAL, self._on_backup_memorial),
            (EventType.RESTORE_MEMORIAL, self._on_restore_memorial),
            (EventType.UPDATE_AVAILABLE, self._on_update_available),
            (EventType.UPDATE_FAILED, self._on_update_failed),
            (EventType.UPDATE_READY, self._on_update_ready),
            (EventType.UPDATE_PROGRESS, self._on_update_progress),
            (EventType.ATTENDANCE_REMIND_TRIGGERED, self._on_attendance_remind),
        ]

    def _subscribe_events(self) -> None:
        self._wiring_subs = self._event_subscriptions()
        for evt, cb in self._wiring_subs:
            try:
                event_bus.subscribe(evt, cb)
            except Exception:
                logger.exception("订阅 %s 失败", evt)

    def _unwire(self) -> None:
        for evt, cb in getattr(self, "_wiring_subs", []):
            try:
                event_bus.unsubscribe(evt, cb)
            except Exception:
                logger.exception("退订 %s 失败", evt)
        self._wiring_subs = []

    def _as_dict(self, data, event_name: str):
        if data is not None and not isinstance(data, dict):
            logger.warning("%s 收到非 dict payload: %r", event_name, data)
            return None
        return data

    def _on_window_show(self, _data=None):
        self.show_normal()

    def _on_window_quit(self, _data=None):
        self.quit_app()

    def _on_open_settings(self, _data=None):
        settings_controller.open_settings_dialog(self)

    def _on_backup_memorial(self, _data=None):
        self.memorial_mgr.backup()

    def _on_restore_memorial(self, _data=None):
        self.memorial_mgr.restore()

    def _on_holiday_updated(self, data=None):
        data = self._as_dict(data, "HOLIDAY_UPDATED")
        if not isinstance(data, dict) or not isinstance(data.get("holiday_data"), dict):
            logger.warning("HOLIDAY_UPDATED 缺少 holiday_data dict: %r", data)
            return
        self.cal.set_net_holiday(data["holiday_data"])
        self._refresh_overview_views()

    def _on_memorial_changed(self, data=None):
        data = self._as_dict(data, "MEMORIAL_CHANGED")
        memorials = config.get("memorial_days", [])
        self.cal.set_memorial_list(memorials)
        self._refresh_overview_views()
        check_today = isinstance(data, dict) and bool(data.get("check_today", False))
        if len(memorials) > _DEFER_RESCHEDULE_THRESHOLD:
            QTimer.singleShot(0, lambda ct=check_today: self._deferred_reschedule(ct))
        else:
            self.reminder_mgr.reschedule(force=True, check_today=check_today)
        self._refresh_info_label()

    def _deferred_reschedule(self, check_today: bool) -> None:
        try:
            self.reminder_mgr.reschedule(force=True, check_today=check_today)
        except Exception:
            logger.exception("延迟重排提醒调度失败")

    def _on_memorial_remind_triggered(self, data=None):
        data = self._as_dict(data, "MEMORIAL_REMIND_TRIGGERED")
        if data is None:
            return
        hit_list = data.get("hit_list")
        today_str = data.get("today_str")
        if not (
            isinstance(hit_list, list) and hit_list and isinstance(today_str, str) and today_str
        ):
            try:
                self.reminder_mgr.discard_pending(reason="invalid_payload")
            except Exception:
                pass
            return
        if not self._show_remind_dialog(hit_list, today_str):
            try:
                self.reminder_mgr.abandon_reminder(today_str, reason="user_closed_or_error")
            except Exception:
                pass
            return
        try:
            self.reminder_mgr.acknowledge_reminder(today_str)
        except Exception:
            logger.exception("acknowledge_reminder 失败, today_str=%s", today_str)

    def _show_remind_dialog(self, hit_list, today_str):
        try:
            dlg = MemorialRemindDialog(hit_list, parent=self, bundle=self.theme_mgr.current)
            try:
                result = dlg.exec()
            finally:
                dlg.deleteLater()
            return result == QDialog.DialogCode.Accepted
        except Exception:
            logger.exception("纪念日提醒弹窗异常")
            return False

    def _on_update_available(self, data=None):
        self.update_ui.on_available(data)

    def _on_update_progress(self, data=None):
        self.update_ui.on_progress(data)

    def _on_update_failed(self, data=None):
        self.update_ui.on_failed(data)

    def _on_update_ready(self, installer: str = "", log_path: str = ""):
        logger.info("更新安装器已启动: %s，日志: %s", installer, log_path)
        self._quitting_for_update = True
        self.quit_app()
