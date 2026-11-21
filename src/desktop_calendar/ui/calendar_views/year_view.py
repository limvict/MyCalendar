# coding: utf-8
"""年视图：12 个月缩略图，可点月跳转。"""

from __future__ import annotations

from PyQt6.QtCore import QDate, QPointF, QRectF, QSizeF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QWidget

from desktop_calendar.ui.calendar_wallpaper import draw_wallpaper
from desktop_calendar.ui.calendar_widget import LunarCalendarWidget
from desktop_calendar.ui.theme import ThemeBundle
from desktop_calendar.ui.theme.bundle import LAYOUT
from desktop_calendar.utils.logging_setup import get_logger

from .common import _SCHEDULE_DEFAULT, _WEEKDAY_NAMES

logger = get_logger()


class CalendarYearView(QWidget):
    date_selected = pyqtSignal(QDate)
    month_selected = pyqtSignal(int, int)

    def __init__(
        self,
        calendar: LunarCalendarWidget,
        bundle: ThemeBundle,
        parent=None,
    ):
        super().__init__(parent)
        self._calendar = calendar
        self._bundle = bundle
        self._wallpaper = None
        self._wallpaper_overlay = 58
        self._legend_tooltip = "彩色圆点表示当天有日程；悬停日期查看节假日信息"
        self.setMinimumHeight(LAYOUT["year_view_min_height"])
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._legend_tooltip)

    def apply_theme(self, bundle: ThemeBundle) -> None:
        self._bundle = bundle
        self.update()

    def refresh(self) -> None:
        self.update()

    def set_wallpaper(self, pixmap, overlay_percent: int) -> None:
        self._wallpaper = pixmap
        self._wallpaper_overlay = overlay_percent
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = self._bundle.calendar_colors
        selected = self._calendar.selectedDate()
        today = QDate.currentDate()
        year = selected.year()
        margin = 4
        gap = 6
        month_width = max(1, (self.width() - margin * 2 - gap * 2) / 3)
        month_height = max(1, (self.height() - margin * 2 - gap * 3) / 4)
        title_height = min(18, month_height * 0.2)
        weekday_height = min(12, month_height * 0.14)
        day_height = (month_height - title_height - weekday_height) / 6
        if day_height <= 0 or self.width() <= 0 or self.height() <= 0:
            return

        for month in range(1, 13):
            row, col = divmod(month - 1, 3)
            left = margin + col * (month_width + gap)
            top = margin + row * (month_height + gap)
            month_rect = QRectF(left, top, month_width, month_height)
            if not draw_wallpaper(
                painter,
                month_rect,
                QSizeF(self.size()),
                self._wallpaper,
                QColor(colors["normal_cell_bg"]),
                self._wallpaper_overlay,
                radius=5,
            ):
                painter.setPen(QColor(self._bundle.resolver.color("border_color")))
                painter.setBrush(QColor(colors["normal_cell_bg"]))
                painter.drawRoundedRect(month_rect, 5, 5)
            painter.setPen(QColor(self._bundle.resolver.color("border_color")))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(month_rect, 5, 5)

            painter.setPen(QColor(self._bundle.resolver.color("date_text_color")))
            painter.setFont(self._font(11, bold=True))
            painter.drawText(
                QRectF(left, top + 1, month_width, title_height),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                f"{month}月",
            )

            day_width = max(1, (month_width - 8) / 7)
            grid_left = left + 4
            grid_top = top + title_height
            painter.setFont(self._font(9))
            painter.setPen(QColor(colors["normal_lunar_color"]))
            for weekday, name in enumerate(_WEEKDAY_NAMES):
                painter.drawText(
                    QRectF(grid_left + weekday * day_width, grid_top, day_width, weekday_height),
                    Qt.AlignmentFlag.AlignCenter,
                    name,
                )

            first = QDate(year, month, 1)
            offset = first.dayOfWeek() - 1
            for day in range(1, first.daysInMonth() + 1):
                index = offset + day - 1
                cell_row, cell_col = divmod(index, 7)
                cell_rect = QRectF(
                    grid_left + cell_col * day_width,
                    grid_top + weekday_height + cell_row * day_height,
                    day_width,
                    day_height,
                )
                current = QDate(year, month, day)
                is_today = current == today
                is_selected = current == selected
                cell = self._calendar.cell_data_for(current)
                if is_today or is_selected:
                    color_key = "today_bg" if is_today else "select_bg"
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(colors[color_key]))
                    diameter = min(cell_rect.width() - 1, cell_rect.height() - 1)
                    painter.drawEllipse(cell_rect.center(), diameter / 2, diameter / 2)
                text_key = (
                    "today_text_color"
                    if is_today
                    else "select_text_color"
                    if is_selected
                    else "festival_red"
                    if (cell.is_legal_hol or current.dayOfWeek() in (6, 7))
                    else "normal_num_color"
                )
                painter.setPen(QColor(colors[text_key]))
                painter.setFont(self._font(max(8, min(11, day_height * 0.72)), bold=is_today))
                painter.drawText(cell_rect, Qt.AlignmentFlag.AlignCenter, str(day))
                if cell.has_schedule and cell_rect.height() >= 5:
                    marker = QColor(cell.schedule_color or _SCHEDULE_DEFAULT)
                    if not marker.isValid():
                        marker = QColor(_SCHEDULE_DEFAULT)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(marker)
                    painter.drawEllipse(
                        QPointF(cell_rect.center().x(), cell_rect.bottom() - 1.5), 1.8, 1.8
                    )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            x, y = event.position().x(), event.position().y()
            month = self._month_at(x, y)
            if month is not None:
                self.month_selected.emit(self._calendar.selectedDate().year(), month)
                event.accept()
                return
            selected = self._date_at(x, y)
            if selected is not None:
                self.date_selected.emit(selected)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        selected = self._date_at(event.position().x(), event.position().y())
        self.setToolTip(self._tooltip_for(selected) if selected else self._legend_tooltip)
        super().mouseMoveEvent(event)

    def _tooltip_for(self, selected: QDate) -> str:
        cell = self._calendar.cell_data_for(selected)
        details = [selected.toString("yyyy-MM-dd")]
        if cell.lunar_text:
            details.append(cell.lunar_text)
        if cell.is_legal_hol:
            details.append("节假日")
        if cell.has_schedule:
            details.append("有日程")
        return "\n".join(details)

    def _month_at(self, x: float, y: float) -> int | None:
        margin = 4
        gap = 6
        month_width = max(1, (self.width() - margin * 2 - gap * 2) / 3)
        month_height = max(1, (self.height() - margin * 2 - gap * 3) / 4)
        title_height = min(18, month_height * 0.2)
        col = int((x - margin) / (month_width + gap))
        row = int((y - margin) / (month_height + gap))
        if not (0 <= col < 3 and 0 <= row < 4):
            return None
        local_x = x - (margin + col * (month_width + gap))
        local_y = y - (margin + row * (month_height + gap))
        if 0 <= local_x < month_width and 0 <= local_y < title_height:
            return row * 3 + col + 1
        return None

    def _date_at(self, x: float, y: float) -> QDate | None:
        margin = 4
        gap = 6
        month_width = max(1, (self.width() - margin * 2 - gap * 2) / 3)
        month_height = max(1, (self.height() - margin * 2 - gap * 3) / 4)
        title_height = min(18, month_height * 0.2)
        weekday_height = min(12, month_height * 0.14)
        day_height = (month_height - title_height - weekday_height) / 6
        if day_height <= 0 or self.width() <= 0 or self.height() <= 0:
            return None
        col = int((x - margin) / (month_width + gap))
        row = int((y - margin) / (month_height + gap))
        if not (0 <= col < 3 and 0 <= row < 4):
            return None
        local_x = x - (margin + col * (month_width + gap)) - 4
        local_y = y - (margin + row * (month_height + gap)) - title_height - weekday_height
        day_width = max(1, (month_width - 8) / 7)
        if local_x < 0 or local_y < 0 or local_x >= month_width - 8:
            return None
        day_col = int(local_x / day_width)
        day_row = int(local_y / day_height)
        month = row * 3 + col + 1
        first = QDate(self._calendar.selectedDate().year(), month, 1)
        day = day_row * 7 + day_col - (first.dayOfWeek() - 1) + 1
        if not 1 <= day <= first.daysInMonth():
            return None
        return QDate(first.year(), month, day)

    def _font(self, size: int, *, bold: bool = False) -> QFont:
        font = QFont(self._bundle.fonts.global_)
        font.setPointSizeF(max(8.0, size * self._bundle.scale_factor))
        font.setBold(bold)
        return font
