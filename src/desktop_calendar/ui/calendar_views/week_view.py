# coding: utf-8
"""周视图：一屏 7 天，带日程圆点。"""

from __future__ import annotations

from PyQt6.QtCore import QDate, QPointF, QRectF, QSizeF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QWidget

from desktop_calendar.core.schedule import ScheduleManager
from desktop_calendar.ui.calendar_wallpaper import draw_wallpaper
from desktop_calendar.ui.calendar_widget import LunarCalendarWidget
from desktop_calendar.ui.theme import ThemeBundle
from desktop_calendar.ui.theme.bundle import LAYOUT
from desktop_calendar.utils.logging_setup import get_logger

from .common import _SCHEDULE_DEFAULT, _WEEKDAY_NAMES, week_start

logger = get_logger()


class CalendarWeekView(QWidget):
    date_selected = pyqtSignal(QDate)

    def __init__(
        self,
        calendar: LunarCalendarWidget,
        schedule_manager: ScheduleManager,
        bundle: ThemeBundle,
        parent=None,
    ):
        super().__init__(parent)
        self._calendar = calendar
        self._schedule_manager = schedule_manager
        self._bundle = bundle
        self._wallpaper = None
        self._wallpaper_overlay = 58
        self.setMinimumHeight(LAYOUT["week_view_min_height"])
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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
        selected = self._calendar.selectedDate()
        start = week_start(selected)
        colors = self._bundle.calendar_colors
        width = self.width() / 7
        header_height = min(84, max(68, self.height() // 5))
        today = QDate.currentDate()

        for index in range(7):
            current = start.addDays(index)
            rect = QRectF(index * width + 2, 2, width - 4, self.height() - 4)
            is_today = current == today
            is_selected = current == selected
            bg_key = "today_bg" if is_today else "select_bg" if is_selected else "normal_cell_bg"
            overlay = (
                min(90, self._wallpaper_overlay + 14)
                if (is_today or is_selected)
                else self._wallpaper_overlay
            )
            if not draw_wallpaper(
                painter,
                rect,
                QSizeF(self.size()),
                self._wallpaper,
                QColor(colors[bg_key]),
                overlay,
                radius=8,
            ):
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(colors[bg_key]))
                painter.drawRoundedRect(rect, 8, 8)

            cell = self._calendar.cell_data_for(current)
            header_color = colors[
                "today_text_color"
                if is_today
                else "select_text_color"
                if is_selected
                else "calendar_header_text"
            ]
            painter.setPen(QColor(header_color))
            painter.setFont(self._font(10, bold=True))
            painter.drawText(
                QRectF(rect.left(), rect.top() + 6, rect.width(), 15),
                Qt.AlignmentFlag.AlignHCenter,
                _WEEKDAY_NAMES[index],
            )
            painter.setFont(self._font(14, bold=True))
            painter.drawText(
                QRectF(rect.left(), rect.top() + 21, rect.width(), 21),
                Qt.AlignmentFlag.AlignHCenter,
                str(current.day()),
            )

            lunar_color = (
                header_color
                if (is_today or is_selected)
                else (colors["festival_red"] if cell.is_legal_hol else colors["normal_lunar_color"])
            )
            painter.setPen(QColor(lunar_color))
            painter.setFont(self._font(9))
            painter.drawText(
                QRectF(rect.left() + 2, rect.top() + 43, rect.width() - 4, 14),
                Qt.AlignmentFlag.AlignHCenter,
                cell.lunar_text,
            )

            if rect.height() > header_height:
                painter.setPen(QColor(self._bundle.resolver.color("border_color")))
                painter.drawLine(
                    QPointF(rect.left() + 4, rect.top() + header_height),
                    QPointF(rect.right() - 4, rect.top() + header_height),
                )
                self._draw_schedules(painter, rect, current, header_height, colors)

    def _draw_schedules(self, painter, rect, current, header_height, colors):
        try:
            schedules = self._schedule_manager.on(current.toPyDate())
        except (OSError, ValueError, TypeError):
            logger.exception("读取周视图日程失败 date=%s", current.toString("yyyy-MM-dd"))
            return

        top = rect.top() + header_height + 6
        line_height = max(22, min(30, (rect.bottom() - top - 4) / 2))
        available = max(0, int((rect.bottom() - top - 4) / line_height))
        painter.save()
        painter.setClipRect(QRectF(rect.left() + 3, top, rect.width() - 6, rect.bottom() - top))
        if not schedules:
            painter.setPen(QColor(colors["normal_lunar_color"]))
            painter.setFont(self._font(9))
            painter.drawText(
                QRectF(rect.left() + 4, top, rect.width() - 8, 24),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                "暂无日程",
            )
        else:
            for index, schedule in enumerate(schedules[:available]):
                y = top + index * line_height
                color = QColor(schedule.color or _SCHEDULE_DEFAULT)
                if not color.isValid():
                    color = QColor(_SCHEDULE_DEFAULT)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(QRectF(rect.left() + 4, y + 3, 4, line_height - 6), 2, 2)
                painter.setPen(QColor(colors["normal_num_color"]))
                painter.setFont(self._font(9))
                painter.drawText(
                    QRectF(rect.left() + 12, y, rect.width() - 16, line_height),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    painter.fontMetrics().elidedText(
                        schedule.title, Qt.TextElideMode.ElideRight, max(0, int(rect.width() - 16))
                    ),
                )
            if len(schedules) > available and available > 0:
                painter.setPen(QColor(colors["normal_lunar_color"]))
                painter.drawText(
                    QRectF(rect.left() + 8, top + available * line_height, rect.width() - 12, 20),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"+{len(schedules) - available}",
                )
        painter.restore()

    def mouseMoveEvent(self, event) -> None:
        if self.width() > 0:
            index = min(6, max(0, int(event.position().x() * 7 / self.width())))
            current = week_start(self._calendar.selectedDate()).addDays(index)
            self.setToolTip(self._tooltip_for(current))
        super().mouseMoveEvent(event)

    def _tooltip_for(self, current: QDate) -> str:
        label = current.toString("yyyy-MM-dd")
        try:
            schedules = self._schedule_manager.on(current.toPyDate())
        except (OSError, ValueError, TypeError):
            logger.exception("读取周视图提示日程失败 date=%s", current.toString("yyyy-MM-dd"))
            return label
        if not schedules:
            return f"{label}\n暂无日程"
        details = [f"{item.time or '全天'}  {item.title}" for item in schedules]
        return f"{label}\n" + "\n".join(details)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.width() > 0:
            index = min(6, max(0, int(event.position().x() * 7 / self.width())))
            self.date_selected.emit(week_start(self._calendar.selectedDate()).addDays(index))
            event.accept()
            return
        super().mousePressEvent(event)

    def _font(self, size: int, *, bold: bool = False) -> QFont:
        font = QFont(self._bundle.fonts.global_)
        font.setPointSizeF(max(7.0, size * self._bundle.scale_factor))
        font.setBold(bold)
        return font
