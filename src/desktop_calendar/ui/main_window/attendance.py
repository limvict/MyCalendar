# coding: utf-8
"""考勤交互：状态卡、上/下班双按钮、本周统计与自动打卡反馈。"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QToolTip

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
    """考勤交互：状态卡、上/下班双按钮、本周统计与自动打卡反馈。"""

    # ---------- 自动打卡反馈 ----------
    def _on_auto_punched(self, action: str, punched_at: str) -> None:
        self._update_attendance_ui()
        self.attendance_reminder.notify_punched(action)
        key = "attendance.auto_punch_in" if action == "in" else "attendance.auto_punch_out"
        message = tr(key).format(time=punched_at)
        if self.tray_mgr.show_message(tr("btn.attendance"), message):
            return
        anchor = self.btn_punch_in if action == "in" else self.btn_punch_out
        if self.isVisible():
            QToolTip.showText(
                anchor.mapToGlobal(anchor.rect().center()),
                message,
                anchor,
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

    # ---------- 按钮状态 ----------
    @staticmethod
    def _punch_states(rec: dict, now: datetime) -> tuple[dict, dict]:
        """返回 (上班按钮, 下班按钮) 的文案 / 可用状态 / tooltip。

        纯函数：不读控件，便于单测。规则与 AttendanceStore 保持一致：
        - 上班卡：未打过且在 11:00 前可用；已打过或过期 → 禁用；
        - 下班卡：打过上班卡（或已过上班卡截止时间，允许只记下班）可用；
          已打过下班卡时按钮变为「更新下班」。
        """
        in_time = rec.get("in")
        out_time = rec.get("out")
        allow_in = now.hour < PUNCH_IN_DEADLINE_HOUR
        deadline = f"{PUNCH_IN_DEADLINE_HOUR:02d}:00"

        if in_time:
            punch_in = {
                "text": tr("attendance.punch_in_done_btn").format(time=in_time),
                "enabled": False,
                "tip": tr("attendance.punch_in_done_tip").format(time=in_time),
            }
        elif allow_in:
            punch_in = {
                "text": tr("attendance.punch_in"),
                "enabled": True,
                "tip": tr("attendance.punch_in_tip").format(deadline=deadline),
            }
        else:
            punch_in = {
                "text": tr("attendance.punch_in"),
                "enabled": False,
                "tip": tr("attendance.punch_in_expired_tip").format(deadline=deadline),
            }

        can_punch_out = bool(in_time) or not allow_in
        if out_time:
            punch_out = {
                "text": tr("attendance.punch_out_update_short"),
                "enabled": can_punch_out,
                "tip": tr("attendance.punch_out_update_tip").format(time=out_time),
            }
        else:
            punch_out = {
                "text": tr("attendance.punch_out"),
                "enabled": can_punch_out,
                "tip": (
                    tr("attendance.punch_out_tip")
                    if can_punch_out
                    else tr("attendance.punch_out_need_in_tip")
                ),
            }

        return punch_in, punch_out

    def _update_attendance_ui(self) -> None:
        """刷新状态卡、两个按钮与本周统计摘要（每分钟 + 打卡后调用）。"""
        rec = self.attendance_store.get_record(QDate.currentDate().toPyDate())
        status = self._attendance_status_text(rec)

        punch_in, punch_out = self._punch_states(rec, datetime.now())
        for button, state in ((self.btn_punch_in, punch_in), (self.btn_punch_out, punch_out)):
            button.setText(state["text"])
            button.setEnabled(state["enabled"])
            button.setToolTip(state["tip"])

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
        self.attendance_status_label.setText(text)
        self.attendance_status_label.setToolTip(status)

        self.attendance_summary_label.setText(self._attendance_summary_text())

    def _attendance_summary_text(self) -> str:
        """本周出勤摘要，例如「本周 3 天 · 24.5h」；无记录时给占位文案。"""
        try:
            summary = self.attendance_store.week_summary(QDate.currentDate().toPyDate())
        except Exception:
            logger.exception("读取本周考勤统计失败")
            return tr("attendance.sidebar_week_empty")
        # 天数按「有打卡记录」计：只打了上班卡也算今天已打卡，工时此时为 0 不显示
        days = sum(1 for day in summary.days if day.in_time or day.out_time)
        if not days:
            return tr("attendance.sidebar_week_empty")
        if not summary.total_minutes:
            return tr("attendance.sidebar_week_days").format(days=days)
        hours = f"{summary.total_minutes / 60:.2f}".rstrip("0").rstrip(".")
        return tr("attendance.sidebar_week_summary").format(days=days, hours=hours)

    # ---------- 打卡 ----------
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
        """执行一次打卡。action: "in" / "out"。"""
        anchor = self.btn_punch_in if action == "in" else self.btn_punch_out
        now = datetime.now()

        if action == "in":
            rec = self.attendance_store.get_record(now.date())
            old_in = rec.get("in")
            if old_in:
                logger.warning("上班卡已打过，拒绝重复打卡")
                QToolTip.showText(
                    anchor.mapToGlobal(anchor.rect().center()),
                    _tr_fmt(
                        "attendance.punch_in_done_label", f"上班打卡（已 {old_in}）", time=old_in
                    ),
                    anchor,
                )
                return

            if now.hour >= PUNCH_IN_DEADLINE_HOUR:
                logger.warning("上班打卡已过截止时间，拒绝写入")
                QToolTip.showText(
                    anchor.mapToGlobal(anchor.rect().center()),
                    tr("attendance.punch_in_expired").format(deadline=self._punch_deadline_str()),
                    anchor,
                )
                return
        else:
            # 已有下班卡：更新前先确认，避免误触改掉时间
            rec = self.attendance_store.get_record(now.date())
            old_out = rec.get("out")
            if old_out and not self._confirm_overwrite(old_out):
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
            QToolTip.showText(anchor.mapToGlobal(anchor.rect().center()), tip, anchor)
            return
        except Exception as e:
            logger.exception("考勤打卡保存失败")
            msg_error(self, tr("msg.error"), tr("attendance.save_failed").format(error=e))
            return

        self._update_attendance_ui()
        self.attendance_reminder.notify_punched(action)
        self.attendance_auto_punch.reschedule()

        if action == "in":
            key = "attendance.punch_in_done"
        else:
            key = "attendance.punch_out_update" if updated else "attendance.punch_out_done"

        QToolTip.showText(
            anchor.mapToGlobal(anchor.rect().center()),
            _tr_fmt(key, "打卡成功", time=hm),
            anchor,
        )

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
            anchor = self.btn_punch_out
            QToolTip.showText(
                anchor.mapToGlobal(anchor.rect().topLeft()),
                f"{title}\n{body}",
                anchor,
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
