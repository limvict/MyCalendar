# coding: utf-8
"""考勤规则子对话框：编辑 attendance_cfg.work_rule。"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QGridLayout, QLabel,
    QSpinBox, QTimeEdit, QVBoxLayout,
)

from desktop_calendar.config.i18n import tr
from desktop_calendar.ui.theme import ThemeBundle

from .base import make_button_box
from .messages import msg_warn

__all__ = ["AttendanceRuleDialog"]

_FMT = "HH:mm"


def _to_time(value, default: QTime) -> QTime:
    if isinstance(value, str):
        t = QTime.fromString(value, _FMT)
        if t.isValid():
            return t
    return default


class AttendanceRuleDialog(QDialog):
    """编辑考勤规则。get_rule() 返回可直接写入 work_rule 的 dict。"""

    def __init__(self, work_rule: Optional[dict], parent=None,
                 bundle: ThemeBundle = None):
        super().__init__(parent)
        if bundle is None:
            raise ValueError("AttendanceRuleDialog 需要 ThemeBundle")
        self._bundle = bundle
        dlg = bundle.dialog
        r = bundle.resolver

        self.setWindowTitle(tr("setting.attendance_rule_title"))
        self.setFixedSize(*dlg.new_size)
        self.setStyleSheet(dlg.qss_picker + f"""
        QTimeEdit {{
            background: {r.color('input_bg')};
            color: {r.color('dialog_text')};
            border: 1px solid {r.color('border_color')};
            border-radius: {r.px('input_radius')};
            padding: 3px 6px;
        }}
        """)

        cfg = work_rule if isinstance(work_rule, dict) else {}

        self.time_start = QTimeEdit()
        self.time_start.setDisplayFormat(_FMT)
        self.time_start.setTime(_to_time(cfg.get("work_start"), QTime(8, 0)))

        self.time_end = QTimeEdit()
        self.time_end.setDisplayFormat(_FMT)
        self.time_end.setTime(_to_time(cfg.get("work_end"), QTime(17, 0)))

        self.chk_lunch = QCheckBox(tr("setting.lunch_enable"))
        self.chk_lunch.setChecked(
            isinstance(cfg.get("lunch_start"), str)
            and isinstance(cfg.get("lunch_end"), str))

        self.time_lunch_start = QTimeEdit()
        self.time_lunch_start.setDisplayFormat(_FMT)
        self.time_lunch_start.setTime(
            _to_time(cfg.get("lunch_start"), QTime(12, 0)))

        self.time_lunch_end = QTimeEdit()
        self.time_lunch_end.setDisplayFormat(_FMT)
        self.time_lunch_end.setTime(
            _to_time(cfg.get("lunch_end"), QTime(13, 0)))

        self.spin_hours = QDoubleSpinBox()
        self.spin_hours.setRange(1.0, 24.0)
        self.spin_hours.setSingleStep(0.5)
        self.spin_hours.setDecimals(1)
        try:
            hours = float(cfg.get("standard_minutes", 480)) / 60.0
        except (TypeError, ValueError):
            hours = 8.0
        self.spin_hours.setValue(max(1.0, min(24.0, hours)))

        self.spin_grace = QSpinBox()
        self.spin_grace.setRange(0, 60)
        try:
            self.spin_grace.setValue(int(cfg.get("late_grace", 0) or 0))
        except (TypeError, ValueError):
            self.spin_grace.setValue(0)

        self.spin_gran = QSpinBox()
        self.spin_gran.setRange(0, 60)
        self.spin_gran.setToolTip(tr("setting.overtime_granularity_tip"))
        try:
            self.spin_gran.setValue(
                int(cfg.get("overtime_granularity", 0) or 0))
        except (TypeError, ValueError):
            self.spin_gran.setValue(0)

        form = QGridLayout()
        form.setSpacing(dlg.spacing)
        rows = (
            (tr("setting.work_start"), self.time_start),
            (tr("setting.work_end"), self.time_end),
        )
        for row, (label, widget) in enumerate(rows):
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(widget, row, 1)

        row = len(rows)
        form.addWidget(self.chk_lunch, row, 0, 1, 2)

        for label, widget in (
            (tr("setting.lunch_start"), self.time_lunch_start),
            (tr("setting.lunch_end"), self.time_lunch_end),
            (tr("setting.standard_hours"), self.spin_hours),
            (tr("setting.late_grace"), self.spin_grace),
            (tr("setting.overtime_granularity"), self.spin_gran),
        ):
            row += 1
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(widget, row, 1)

        self.chk_lunch.toggled.connect(self._sync_lunch_enabled)
        self._sync_lunch_enabled(self.chk_lunch.isChecked())

        self._btn_box = make_button_box(self, on_accept=self._on_accept)

        layout = QVBoxLayout(self)
        mw = dlg.margin_wide
        layout.setContentsMargins(mw, mw, mw, mw)
        layout.setSpacing(dlg.spacing_wide)
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addWidget(self._btn_box)

    def _sync_lunch_enabled(self, on: bool) -> None:
        self.time_lunch_start.setEnabled(on)
        self.time_lunch_end.setEnabled(on)

    def _on_accept(self) -> None:
        if self.time_start.time() >= self.time_end.time():
            msg_warn(self, tr("msg.hint"), tr("setting.rule_invalid"))
            return
        if (self.chk_lunch.isChecked()
                and self.time_lunch_start.time() >= self.time_lunch_end.time()):
            msg_warn(self, tr("msg.hint"), tr("setting.rule_invalid"))
            return
        self.accept()

    def get_rule(self) -> dict:
        lunch_on = self.chk_lunch.isChecked()
        return {
            "work_start": self.time_start.time().toString(_FMT),
            "work_end": self.time_end.time().toString(_FMT),
            "lunch_start": (self.time_lunch_start.time().toString(_FMT)
                            if lunch_on else None),
            "lunch_end": (self.time_lunch_end.time().toString(_FMT)
                          if lunch_on else None),
            "standard_minutes": int(round(self.spin_hours.value() * 60)),
            "late_grace": self.spin_grace.value(),
            "overtime_granularity": self.spin_gran.value(),
        }