# coding: utf-8
"""年 / 月快速跳转对话框。"""
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QSpinBox,
)

from desktop_calendar.config.i18n import tr
from desktop_calendar.ui.theme import ThemeBundle

from .base import (
    RetranslatableDialog, make_button_box, retranslate_button_box,
)

__all__ = ["MonthYearPickerDialog"]


class MonthYearPickerDialog(RetranslatableDialog, QDialog):
    YEAR_SPAN = 50

    def __init__(self, current_year: int, current_month: int,
                 parent=None, bundle: ThemeBundle = None):
        super().__init__(parent)
        if bundle is None:
            raise ValueError("MonthYearPickerDialog 需要 ThemeBundle")
        self._bundle = bundle

        dlg = self._bundle.dialog
        self.setWindowTitle(tr("btn.pick_month"))
        self.setFixedSize(*dlg.picker_size)
        self.setStyleSheet(dlg.qss_picker)

        today = QDate.currentDate()
        lo = today.year() - self.YEAR_SPAN
        hi = today.year() + self.YEAR_SPAN

        self.spin_year = QSpinBox()
        self.spin_year.setRange(lo, hi)
        self.spin_year.setValue(max(lo, min(hi, int(current_year))))

        self.spin_month = QSpinBox()
        self.spin_month.setRange(1, 12)
        self.spin_month.setValue(max(1, min(12, int(current_month))))

        self.lbl_year = QLabel(tr("setting.year_label"))
        self.lbl_month = QLabel(tr("setting.month_label"))

        form = QGridLayout()
        form.setSpacing(dlg.spacing)
        form.addWidget(self.lbl_year, 0, 0)
        form.addWidget(self.spin_year, 0, 1)
        form.addWidget(self.lbl_month, 1, 0)
        form.addWidget(self.spin_month, 1, 1)

        self._btn_box = make_button_box(self)

        layout = QVBoxLayout(self)
        mw = dlg.margin_wide
        layout.setContentsMargins(mw, mw, mw, mw)
        layout.setSpacing(dlg.spacing_wide)
        layout.addLayout(form)
        layout.addWidget(self._btn_box)

        self.spin_year.setFocus()
        self.spin_year.selectAll()
        self.retranslate_ui()

    def retranslate_ui(self):
        self.setWindowTitle(tr("btn.pick_month"))
        self.lbl_year.setText(tr("setting.year_label"))
        self.lbl_month.setText(tr("setting.month_label"))
        retranslate_button_box(self._btn_box)

    def get_year_month(self) -> tuple:
        return self.spin_year.value(), self.spin_month.value()