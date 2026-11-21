# coding: utf-8
"""考勤交互：状态文案、打卡菜单、写入与自动打卡反馈。"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QMenu,
    QToolTip,
)

from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import config
from desktop_calendar.core.attendance import (
    PUNCH_IN_DEADLINE_HOUR,
    PunchRejected,
)
from desktop_calendar.ui.dialogs import (
    AttendanceDialog,
    msg_error,
    msg_question,
)
from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME

from .helpers import _tr_fmt

logger = logging.getLogger(APP_LOGGER_NAME)


class MainWindowAttendanceMixin:
    """考勤交互：状态文案、打卡菜单、写入与自动打卡反馈。"""

    def _on_auto_punched(self, action: str, punched_at: str) -> None:
        self._update_attendance_button()
        self.attendance_reminder.notify_punched(action)
        key = "attendance.auto_punch_in" if action == "in" else "attendance.auto_punch_out"
        message = tr(key).format(time=punched_at)
        if self.tray_mgr.show_message(tr("btn.attendance"), message):
            return
        if self.isVisible():
            QToolTip.showText(
                self.btn_attendance.mapToGlobal(self.btn_attendance.rect().center()),
                message,
                self.btn_attendance,
            )
        else:
            logger.info("%s", message)

    def _on_auto_punch_failed(self, action: str, error: str) -> None:
        message = tr("attendance.auto_punch_failed").format(error=error)
        logger.error("自动考勤保存失败 action=%s: %s", action, error)
        if self.tray_mgr.show_message(tr("msg.error"), message):
            return
        if self.isVisible():
            msg_error(self, tr("msg.error"), message)

    def open_attendance_menu(self):
        try:
            rec = self.attendance_store.get_record(QDate.currentDate().toPyDate())
        except Exception:
            logger.exception("读取今日考勤记录失败，按未打卡处理")
            rec = {}

        in_time = rec.get("in")
        out_time = rec.get("out")
        allow_punch_in = datetime.now().hour < PUNCH_IN_DEADLINE_HOUR

        menu = QMenu(self)
        act_main = act_week = act_month = None
        chosen = None
        try:
            menu.setStyleSheet(self.theme_mgr.current.qss.menu)
            head = menu.addAction(self._attendance_status_text(rec))
            head.setEnabled(False)
            menu.addSeparator()

            if out_time:
                update_text = tr("attendance.punch_out_update_action")
                if update_text.startswith("attendance."):
                    update_text = tr("attendance.punch_out")
                act_main = menu.addAction(update_text)
            elif in_time:
                act_main = menu.addAction(tr("attendance.punch_out"))
            elif allow_punch_in:
                act_main = menu.addAction(tr("attendance.punch_in"))
            else:
                act_main = menu.addAction(tr("attendance.punch_out"))

            menu.addSeparator()
            act_week = menu.addAction(tr("attendance.stats_week"))
            act_month = menu.addAction(tr("attendance.stats_month"))
            chosen = menu.exec(
                self.btn_attendance.mapToGlobal(self.btn_attendance.rect().bottomLeft())
            )
        finally:
            menu.deleteLater()

        if chosen is not None and chosen is act_main:
            if out_time:
                if self._confirm_overwrite(out_time):
                    self._do_punch("out")
            elif in_time:
                self._do_punch("out")
            elif allow_punch_in:
                self._do_punch("in")
            else:
                self._do_punch("out")
        elif chosen is not None and chosen is act_week:
            self.open_attendance_dialog("week")
        elif chosen is not None and chosen is act_month:
            self.open_attendance_dialog("month")

    @staticmethod
    def _punch_deadline_str() -> str:
        return f"{PUNCH_IN_DEADLINE_HOUR:02d}:00"

    def _confirm_overwrite(self, old_time) -> bool:
        if not old_time:
            return True
        try:
            msg = tr("attendance.punch_out_update_confirm").format(
                old=old_time, new=datetime.now().strftime("%H:%M")
            )
        except (KeyError, IndexError, ValueError):
            msg = f"您今天已经打过下班卡了（{old_time}），确定要更新为现在的时间吗？"
        try:
            return bool(
                msg_question(self, tr("msg.confirm"), msg, yes=tr("btn.ok"), no=tr("btn.cancel"))
            )
        except Exception:
            logger.exception("打卡确认框显示失败，按取消处理")
            return False

    def _do_punch(self, action: str) -> None:
        now = datetime.now()

        if action == "in":
            rec = self.attendance_store.get_record(now.date())
            old_in = rec.get("in")
            if old_in:
                logger.warning("上班卡已打过，拒绝重复打卡")
                QToolTip.showText(
                    self.btn_attendance.mapToGlobal(self.btn_attendance.rect().center()),
                    _tr_fmt(
                        "attendance.punch_in_done_label", f"上班打卡（已 {old_in}）", time=old_in
                    ),
                    self.btn_attendance,
                )
                return

            if now.hour >= PUNCH_IN_DEADLINE_HOUR:
                logger.warning("上班打卡已过截止时间，拒绝写入")
                QToolTip.showText(
                    self.btn_attendance.mapToGlobal(self.btn_attendance.rect().center()),
                    tr("attendance.punch_in_expired").format(deadline=self._punch_deadline_str()),
                    self.btn_attendance,
                )
                return

        try:
            hm, updated = self.attendance_store.punch(action)
        except PunchRejected as e:
            # 逻辑层兜底拒绝（如跨午夜、系统时间跳变绕过上面的预检查）：
            # 不弹错误框，用 tooltip 与预检查保持一致的轻提示。
            logger.warning("打卡被逻辑层拒绝: code=%s", e.code)
            if e.code == "already_punched_in":
                cur = self.attendance_store.get_record(datetime.now().date()).get("in")
                tip = _tr_fmt("attendance.punch_in_done_label", f"上班打卡（已 {cur}）", time=cur)
            else:
                tip = tr("attendance.punch_in_expired").format(deadline=self._punch_deadline_str())
            QToolTip.showText(
                self.btn_attendance.mapToGlobal(self.btn_attendance.rect().center()),
                tip,
                self.btn_attendance,
            )
            return
        except Exception as e:
            logger.exception("考勤打卡保存失败")
            msg_error(self, tr("msg.error"), tr("attendance.save_failed").format(error=e))
            return

        self._update_attendance_button()
        self.attendance_reminder.notify_punched(action)
        self.attendance_auto_punch.reschedule()

        if action == "in":
            key = "attendance.punch_in_done"
        else:
            key = "attendance.punch_out_update" if updated else "attendance.punch_out_done"

        QToolTip.showText(
            self.btn_attendance.mapToGlobal(self.btn_attendance.rect().center()),
            _tr_fmt(key, "打卡成功", time=hm),
            self.btn_attendance,
        )

    def _update_attendance_button(self) -> None:
        rec = self.attendance_store.get_record(QDate.currentDate().toPyDate())
        status = self._attendance_status_text(rec)
        self.btn_attendance.setText(self._attendance_button_text(rec))
        auto_enabled = config.get_nested("attendance_cfg", "enable_auto_punch", default=False)
        auto_status = tr(
            "attendance.sidebar_auto_on" if auto_enabled else "attendance.sidebar_auto_off"
        )
        text = "\n".join(
            (
                tr("attendance.sidebar_in").format(time=rec.get("in") or tr("attendance.none")),
                tr("attendance.sidebar_out").format(time=rec.get("out") or tr("attendance.none")),
                auto_status,
            )
        )
        self.btn_attendance.setToolTip(status)
        self.attendance_status_label.setText(text)
        self.attendance_status_label.setToolTip(status)

    @staticmethod
    def _attendance_button_text(rec: dict) -> str:
        if rec.get("out"):
            return tr("btn.attendance")
        return tr("attendance.punch_out" if rec.get("in") else "attendance.punch_in")

    def open_attendance_dialog(self, mode: str = "week") -> None:
        dlg = AttendanceDialog(
            self.attendance_store, self, bundle=self.theme_mgr.current, mode=mode
        )
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()

    def _on_attendance_remind(self, data=None):
        data = self._as_dict(data, "ATTENDANCE_REMIND_TRIGGERED")
        if not isinstance(data, dict):
            return
        kind = data.get("kind")
        if kind == "start":
            title = tr("attendance.remind_start_title")
            body = tr("attendance.remind_start_body")
        elif kind == "end":
            title = tr("attendance.remind_end_title")
            body = tr("attendance.remind_end_body")
        else:
            return

        if self.tray_mgr.show_message(title, body):
            return
        if self.isVisible():
            QToolTip.showText(
                self.btn_attendance.mapToGlobal(self.btn_attendance.rect().topLeft()),
                f"{title}\n{body}",
                self.btn_attendance,
                msecShowTime=8000,
            )
            return
        logger.info("考勤提醒（无托盘且窗口不可见，仅记录）: %s / %s", title, body)

    @staticmethod
    def _attendance_status_text(rec: dict) -> str:
        in_t = rec.get("in") if rec else None
        out_t = rec.get("out") if rec else None

        if not in_t and not out_t:
            return tr("attendance.menu_status_none")
        if in_t and out_t:
            return _tr_fmt(
                "attendance.menu_status_done", "今日已打卡", in_time=in_t, out_time=out_t
            )
        if in_t:
            return _tr_fmt("attendance.menu_status_in", "已打上班卡", time=in_t)
        return _tr_fmt("attendance.menu_status_out", "已打下班卡", time=out_t)
