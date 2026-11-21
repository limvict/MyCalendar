# coding: utf-8
"""新增 / 编辑单个纪念日的对话框。"""

from __future__ import annotations

import calendar

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from desktop_calendar.config.constants import REFERENCE_LEAP_YEAR
from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import get_logger
from desktop_calendar.core.memorial import (
    REPEAT_MONTH,
    REPEAT_ONCE,
    REPEAT_WEEK,
    REPEAT_YEAR,
    normalize_memorial,
)
from desktop_calendar.ui.theme import ThemeBundle

from ..base import (
    make_button_box,
)
from ..messages import msg_warn

logger = get_logger()


# ===================== 新增/编辑弹窗 =====================
class AddMemorialDialog(QDialog):
    def __init__(self, parent=None, bundle: ThemeBundle = None):
        super().__init__(parent)
        if bundle is None:
            raise ValueError("AddMemorialDialog 需要 ThemeBundle")
        self._bundle = bundle
        self._saved_type_lunar = False
        self._saved_isleap = False
        self._last_repeat_type = None

        dlg = self._bundle.dialog
        self.setWindowTitle(tr("memorial.title_new"))
        self.resize(*dlg.new_size)
        self.setStyleSheet(dlg.qss_standard)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            dlg.margin_wide, dlg.margin_wide, dlg.margin_wide, dlg.margin_wide
        )
        layout.setSpacing(dlg.spacing_wide)

        group_main = QGroupBox(tr("memorial.details"), self)
        form_main = QFormLayout(group_main)
        form_main.setSpacing(dlg.spacing)
        self.edit_name = QLineEdit(group_main)
        self.edit_name.setPlaceholderText(tr("memorial.name_placeholder"))
        form_main.addRow(tr("memorial.name"), self.edit_name)

        self.radio_solar = QRadioButton(tr("memorial.solar"))
        self.radio_lunar = QRadioButton(tr("memorial.lunar"))
        self.radio_solar.setChecked(True)
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self.radio_solar)
        self._type_group.addButton(self.radio_lunar)

        self.chk_leap = QCheckBox(tr("memorial.leap"), group_main)
        self.chk_leap.setEnabled(False)
        self.radio_solar.toggled.connect(self._on_type_changed)
        self.radio_lunar.toggled.connect(self._on_type_changed)

        self.combo_repeat = QComboBox(group_main)
        self.combo_repeat.addItem(tr("memorial.repeat_year"), REPEAT_YEAR)
        self.combo_repeat.addItem(tr("memorial.repeat_month"), REPEAT_MONTH)
        self.combo_repeat.addItem(tr("memorial.repeat_week"), REPEAT_WEEK)
        self.combo_repeat.addItem(tr("memorial.repeat_once"), REPEAT_ONCE)
        self.combo_repeat.currentIndexChanged.connect(self._update_day_range)

        self.spin_month = QSpinBox(group_main)
        self.spin_month.setRange(1, 12)
        self.spin_month.setValue(1)

        self.spin_day = QSpinBox(group_main)
        self.spin_day.setRange(1, 31)
        self.spin_day.setValue(1)

        self.spin_advance = QSpinBox(group_main)
        self.spin_advance.setRange(0, 30)
        self.spin_advance.setValue(3)

        self.chk_enabled = QCheckBox(tr("memorial.enabled"), self)
        self.chk_enabled.setChecked(True)

        self.lbl_repeat = QLabel(tr("memorial.repeat"), group_main)
        self.lbl_month = QLabel(tr("memorial.month"), group_main)
        self.lbl_day = QLabel(tr("memorial.day"), group_main)
        self.lbl_advance = QLabel(tr("memorial.advance"))

        self.spin_year = QSpinBox(group_main)
        self.spin_year.setRange(1900, 2100)
        self.spin_year.setValue(QDate.currentDate().year())
        self.lbl_year = QLabel(tr("memorial.year"), group_main)

        type_row = QHBoxLayout()
        type_row.addWidget(self.radio_solar)
        type_row.addWidget(self.radio_lunar)
        type_row.addWidget(self.chk_leap)
        type_row.addStretch(1)
        type_widget = QWidget(group_main)
        type_widget.setLayout(type_row)
        form_main.addRow(tr("memorial.type"), type_widget)
        form_main.addRow(self.lbl_repeat, self.combo_repeat)

        self.date_row = QWidget(group_main)
        date_layout = QHBoxLayout(self.date_row)
        date_layout.setContentsMargins(0, 0, 0, 0)
        date_layout.setSpacing(dlg.spacing)
        for label, control in (
            (self.lbl_year, self.spin_year),
            (self.lbl_month, self.spin_month),
            (self.lbl_day, self.spin_day),
        ):
            date_layout.addWidget(label)
            date_layout.addWidget(control)
        date_layout.addStretch(1)
        form_main.addRow(tr("memorial.date"), self.date_row)
        layout.addWidget(group_main)

        group_reminder = QGroupBox(tr("memorial.reminder_settings"), self)
        reminder_layout = QFormLayout(group_reminder)
        reminder_layout.setSpacing(dlg.spacing)
        reminder_layout.addRow(self.lbl_advance, self.spin_advance)
        reminder_layout.addRow(self.chk_enabled)
        layout.addWidget(group_reminder)

        self._btn_box = make_button_box(self, on_accept=self._on_accept)
        layout.addWidget(self._btn_box)
        self._update_day_range()

    def _on_type_changed(self):
        is_solar = self.radio_solar.isChecked()
        self.chk_leap.setEnabled(not is_solar)
        self._update_day_range()

    def _update_day_range(self, _idx: int = None):
        repeat_type = self.combo_repeat.currentData()
        was_week = self._last_repeat_type == REPEAT_WEEK
        is_week = repeat_type == REPEAT_WEEK
        is_once = repeat_type == REPEAT_ONCE

        if is_week and not was_week:
            self._saved_type_lunar = self.radio_lunar.isChecked()
            self._saved_isleap = self.chk_leap.isChecked()

        if is_week:
            self.spin_day.setMinimum(1)
            self.spin_day.setMaximum(7)
            self.spin_day.setSuffix(tr("memorial.weekday_suffix"))
            self.spin_month.setEnabled(False)
            self.spin_year.setVisible(False)
            self.lbl_year.setVisible(False)

            self.radio_solar.blockSignals(True)
            self.radio_lunar.blockSignals(True)
            try:
                self.radio_solar.setChecked(True)
            finally:
                self.radio_solar.blockSignals(False)
                self.radio_lunar.blockSignals(False)
            self.radio_lunar.setEnabled(False)
            self.chk_leap.setEnabled(False)
            self.chk_leap.setChecked(False)
        else:
            self.spin_day.setMinimum(1)
            # lunar 上限 30、solar 上限 31；once 已强制 solar，不受影响。
            # 切到 lunar 时若当前值 > 30，Qt 会自动截断到 30。
            is_lunar = self.radio_lunar.isChecked()
            self.spin_day.setMaximum(30 if is_lunar else 31)
            self.spin_day.setSuffix("")
            self.spin_month.setEnabled(repeat_type in (REPEAT_YEAR, REPEAT_ONCE))
            self.spin_year.setVisible(is_once)
            self.lbl_year.setVisible(is_once)
            self.spin_year.setEnabled(is_once)
            self.radio_lunar.setEnabled(not is_once)

            if is_once:
                # once 强制公历；blockSignals 避免触发 _on_type_changed
                self.radio_solar.blockSignals(True)
                try:
                    self.radio_solar.setChecked(True)
                finally:
                    self.radio_solar.blockSignals(False)
                self.chk_leap.setEnabled(False)
                self.chk_leap.setChecked(False)
            else:
                if was_week and self._saved_type_lunar:
                    self.radio_lunar.blockSignals(True)
                    try:
                        self.radio_lunar.setChecked(True)
                    finally:
                        self.radio_lunar.blockSignals(False)
                if was_week and self.radio_lunar.isChecked() and self._saved_isleap:
                    self.chk_leap.setChecked(True)
                self.chk_leap.setEnabled(self.radio_lunar.isChecked())

        self._last_repeat_type = repeat_type

    def _on_accept(self):
        if not self.edit_name.text().strip():
            msg_warn(self, tr("msg.hint"), tr("msg.name_empty"))
            return

        repeat_type = self.combo_repeat.currentData()
        is_solar = self.radio_solar.isChecked()

        if repeat_type == REPEAT_ONCE:
            year, month, day = (
                self.spin_year.value(),
                self.spin_month.value(),
                self.spin_day.value(),
            )
            try:
                last_day = calendar.monthrange(year, month)[1]
            except Exception:
                last_day = 28
            if day > last_day:
                msg_warn(
                    self,
                    tr("msg.hint"),
                    tr("memorial.warn_once_date").format(
                        year=year, month=month, day=day, max_day=last_day
                    ),
                )
                return

        elif repeat_type == REPEAT_YEAR:
            month, day = self.spin_month.value(), self.spin_day.value()
            if is_solar:
                _, last_day = calendar.monthrange(REFERENCE_LEAP_YEAR, month)
                if day > last_day:
                    msg_warn(
                        self,
                        tr("msg.hint"),
                        tr("memorial.warn_solar_day").format(
                            month=month, day=day, max_day=last_day
                        ),
                    )
                    return
            else:
                if day > 30:
                    msg_warn(self, tr("msg.hint"), tr("memorial.warn_lunar_day_max"))
                    return
                if self.chk_leap.isChecked():
                    reply = QMessageBox.question(
                        self,
                        tr("msg.hint"),
                        tr("memorial.warn_leap_rare"),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return
        elif repeat_type == REPEAT_MONTH:
            day = self.spin_day.value()
            if is_solar:
                if day > 28:
                    reply = QMessageBox.question(
                        self,
                        tr("msg.hint"),
                        tr("memorial.warn_day_overflow").format(day=day),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return
            elif day > 30:
                msg_warn(self, tr("msg.hint"), tr("memorial.warn_lunar_day_max_short"))
                return
        self.accept()

    def load_data(self, data: dict):
        frozen = (self.radio_solar, self.radio_lunar, self.combo_repeat)
        for w in frozen:
            w.blockSignals(True)
        try:
            self.edit_name.setText(data.get("name", ""))
            typ = data.get("type", "solar")
            if typ == "solar":
                self.radio_solar.setChecked(True)
            else:
                self.radio_lunar.setChecked(True)
            self.chk_leap.setChecked(bool(data.get("isleap", False)) if typ == "lunar" else False)
            idx = self.combo_repeat.findData(data.get("repeat_type", REPEAT_YEAR))
            if idx >= 0:
                self.combo_repeat.setCurrentIndex(idx)
            self.spin_month.setValue(data.get("month", 1))
            self.spin_day.setValue(data.get("day", 1))
            self.spin_advance.setValue(data.get("advance_days", 0))
            self.chk_enabled.setChecked(data.get("enabled", True))
            try:
                year_val = int(data.get("year") or QDate.currentDate().year())
            except (TypeError, ValueError):
                year_val = QDate.currentDate().year()
            self.spin_year.setValue(year_val)
        finally:
            for w in frozen:
                w.blockSignals(False)
        self._last_repeat_type = None
        self._update_day_range()

    def get_data(self) -> dict:
        typ = "solar" if self.radio_solar.isChecked() else "lunar"
        repeat_type = self.combo_repeat.currentData()
        if repeat_type == REPEAT_WEEK:
            typ = "solar"
        raw = {
            "name": self.edit_name.text().strip(),
            "type": typ,
            "month": self.spin_month.value(),
            "day": self.spin_day.value(),
            "isleap": self.chk_leap.isChecked() if typ == "lunar" else False,
            "advance_days": self.spin_advance.value(),
            "enabled": self.chk_enabled.isChecked(),
            "repeat_type": repeat_type,
        }
        if repeat_type == REPEAT_ONCE:
            raw["year"] = self.spin_year.value()
        return normalize_memorial(raw)
