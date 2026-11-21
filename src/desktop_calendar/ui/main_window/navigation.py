# coding: utf-8
"""日历导航：月/周/年视图切换、上下页、标题与年月跳转。"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QDialog,
)

from desktop_calendar.config.i18n import tr
from desktop_calendar.ui.calendar_views import (
    week_start,
)
from desktop_calendar.ui.dialogs import (
    MonthYearPickerDialog,
)
from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME

logger = logging.getLogger(APP_LOGGER_NAME)


class MainWindowNavigationMixin:
    """日历导航：月/周/年视图切换、上下页、标题与年月跳转。"""

    def goto_today(self):
        t = QDate.currentDate()
        self.cal.setSelectedDate(t)
        self.cal.showSelectedDate()
        self.update_calendar_title()
        self._refresh_overview_views()

    def prev_month(self):
        self._navigate_calendar(-1)

    def next_month(self):
        self._navigate_calendar(1)

    def _navigate_calendar(self, amount: int) -> None:
        mode = self.view_selector.currentData()
        if mode == "month":
            (self.cal.showPreviousMonth if amount < 0 else self.cal.showNextMonth)()
        elif mode == "week":
            self.cal.setSelectedDate(self.cal.selectedDate().addDays(7 * amount))
            self.cal.showSelectedDate()
            self._refresh_overview_views()
        else:
            current = self.cal.selectedDate()
            year = current.year() + amount
            month_start = QDate(year, current.month(), 1)
            selected = QDate(year, current.month(), min(current.day(), month_start.daysInMonth()))
            self.cal.setSelectedDate(selected)
            self.cal.setCurrentPage(year, selected.month())
            self._refresh_schedule_markers()
            self.update_calendar_title()

    def set_calendar_view(self, mode: str) -> None:
        views = {
            "month": self.cal,
            "week": self.week_view,
            "year": self.year_view,
        }
        if mode not in views:
            raise ValueError(f"Unknown calendar view: {mode!r}")
        index = self.view_selector.findData(mode)
        if self.view_selector.currentIndex() != index:
            self.view_selector.setCurrentIndex(index)
            return
        self.calendar_views.setCurrentWidget(views[mode])
        self.btn_prev.setToolTip(
            {"month": "上个月（PageUp）", "week": "上一周（PageUp）", "year": "上一年（PageUp）"}[
                mode
            ]
        )
        self.btn_prev.setAccessibleName(
            {"month": "上个月", "week": "上一周", "year": "上一年"}[mode]
        )
        self.btn_next.setToolTip(
            {
                "month": "下个月（PageDown）",
                "week": "下一周（PageDown）",
                "year": "下一年（PageDown）",
            }[mode]
        )
        self.btn_next.setAccessibleName(
            {"month": "下个月", "week": "下一周", "year": "下一年"}[mode]
        )
        self._refresh_schedule_markers()
        self.update_calendar_title()

    def _select_week_date(self, selected: QDate) -> None:
        self.cal.setSelectedDate(selected)
        self.cal.showSelectedDate()

    def _select_year_date(self, selected: QDate) -> None:
        self.cal.setSelectedDate(selected)
        self.cal.setCurrentPage(selected.year(), selected.month())
        self.set_calendar_view("month")

    def _select_year_month(self, year: int, month: int) -> None:
        current = self.cal.selectedDate()
        month_start = QDate(year, month, 1)
        selected = QDate(year, month, min(current.day(), month_start.daysInMonth()))
        self.cal.setSelectedDate(selected)
        self.cal.setCurrentPage(year, month)
        self.set_calendar_view("month")

    def update_calendar_title(self, *_args):
        mode = self.view_selector.currentData()
        selected = self.cal.selectedDate()
        if mode == "week":
            start = week_start(selected)
            end = start.addDays(6)
            end_year = f"{end.year()}年" if end.year() != start.year() else ""
            title = (
                f"{start.year()}年{start.month()}月{start.day()}日 - "
                f"{end_year}{end.month()}月{end.day()}日"
            )
        elif mode == "year":
            title = f"{selected.year()}年"
        else:
            title = tr("cal.title_format").format(
                year=self.cal.yearShown(), month=self.cal.monthShown()
            )
        self.cal_title.setText(title)

    def _open_month_picker(self) -> None:
        """点击标题 → 快速跳到指定年月（周/年视图下跳回月视图）。"""
        current = self.cal.selectedDate()
        try:
            dialog = MonthYearPickerDialog(
                current.year(), current.month(), self, bundle=self.theme_mgr.current
            )
        except Exception:
            logger.exception("打开年月跳转失败")
            return
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            if not accepted:
                return
            year, month = dialog.get_year_month()
        finally:
            dialog.deleteLater()
        index = self.view_selector.findData("month")
        if index >= 0 and self.view_selector.currentIndex() != index:
            self.view_selector.setCurrentIndex(index)
        self.cal.setCurrentPage(year, month)
