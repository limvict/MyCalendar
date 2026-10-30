# coding: utf-8
import time as _time
from collections import OrderedDict
from typing import Any

from PyQt6.QtCore import Qt, QDate, QLocale, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import QTextCharFormat, QPainter, QPen
from PyQt6.QtWidgets import QCalendarWidget, QLabel

from desktop_calendar.config.manager import log_exception, get_logger
from desktop_calendar.config.i18n import tr, get_language
from desktop_calendar.ui.cell_presenter import (
    CellPresenter, CELL_NORMAL, CELL_MEMORIAL, CELL_RED, UNSET,
)
from desktop_calendar.ui.theme import ThemeBundle
logger = get_logger()

_REPORTED_ERRORS_MAX = 2000
_WHEEL_STEP = 120


class ClickLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class LunarCalendarWidget(QCalendarWidget):
    """自定义农历日历控件：展示逻辑由 CellPresenter 提供。"""

    _CELL_CACHE_MAX = 3 * 42

    def __init__(self, parent, bundle: ThemeBundle, memorial_list):
        super().__init__(parent)
        self.setLocale(QLocale(get_language()))
        self._presenter = CellPresenter()
        self._presenter.set_memorial_list(memorial_list)
        self._reported_errors = set()
        self._reported_errors_limit_warned = False
        self._cell_cache = OrderedDict()
        self._wheel_accum = 0
        self._workday_tag_text = tr("cell.workday_tag")
        self.apply_theme(bundle)
        self.currentPageChanged.connect(self._on_page_changed)
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())

    def apply_theme(self, bundle: ThemeBundle) -> None:
        self._bundle = bundle
        self._day_font = bundle.fonts.calendar_day
        self._small_font = bundle.fonts.calendar_small
        self._colors = bundle.calendar_colors
        self._dot_size = bundle.calendar_metrics.dot_size
        self._tag_size = bundle.calendar_metrics.tag_size
        self._cell_radius = bundle.calendar_metrics.cell_radius
        self._no_pen = QPen(Qt.PenStyle.NoPen)
        self._fix_week_header_color()
        self.update()

    # ---------- Qt 事件 ----------
    def wheelEvent(self, event):
        """滚轮翻月：累计一格才翻，避免触控板飞页。"""
        self._wheel_accum += event.angleDelta().y()
        if self._wheel_accum >= _WHEEL_STEP:
            self._wheel_accum = 0
            self.showPreviousMonth()
        elif self._wheel_accum <= -_WHEEL_STEP:
            self._wheel_accum = 0
            self.showNextMonth()
        event.accept()

    # ---------- 数据注入 ----------
    def set_memorial_list(self, ml):
        self._presenter.set_memorial_list(
            list(ml) if isinstance(ml, (list, tuple)) else [])
        self._invalidate_cell_cache()
        self.update()

    def set_net_holiday(self, holiday_data):
        try:
            self._presenter.set_net_holiday(holiday_data)
            logger.info("加载网络节假日数据，共%d条", self._presenter.net_count)
            self._invalidate_cell_cache()
            self.update()
        except Exception as e:
            log_exception(f"set_net_holiday 加载节假日数据失败: {e}")

    def get_memorials_for_date(self, qdate: QDate):
        return self._presenter.memorials_for(qdate)
    
    def memorial_items_for(self, qdate: QDate):
        return self._presenter.memorial_items_for(qdate)
    
    def get_lunar_cell_text(self, qdate, lunar=UNSET, legal_raw=UNSET):
        return self._presenter.lunar_text_and_kind(
            qdate, lunar=lunar, legal_raw=legal_raw)

    # ---------- 主题 / 语言 ----------
    def retranslate_ui(self):
        self._workday_tag_text = tr("cell.workday_tag")
        self.setLocale(QLocale(get_language()))
        self._invalidate_cell_cache()
        self._fix_week_header_color()
        self.update()

    def _fix_week_header_color(self):
        red_fmt = QTextCharFormat()
        red_fmt.setForeground(self._colors["weekend_header_red"])
        normal_fmt = QTextCharFormat()
        normal_fmt.setForeground(self._colors["calendar_header_text"])
        for dow in (Qt.DayOfWeek.Monday, Qt.DayOfWeek.Tuesday,
                    Qt.DayOfWeek.Wednesday, Qt.DayOfWeek.Thursday,
                    Qt.DayOfWeek.Friday):
            self.setWeekdayTextFormat(dow, normal_fmt)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, red_fmt)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, red_fmt)

    # ---------- 单元格缓存 ----------
    def _on_page_changed(self, year: int, month: int):
        self._rebuild_cell_cache(year, month)

    def _put_cell_cache(self, key: int, cell: Any) -> Any:
        self._cell_cache[key] = cell
        self._cell_cache.move_to_end(key)
        while len(self._cell_cache) > self._CELL_CACHE_MAX:
            self._cell_cache.popitem(last=False)
        return cell

    def _rebuild_cell_cache(self, year: int, month: int):
        first = QDate(year, month, 1)
        for day in range(1, first.daysInMonth() + 1):
            d = QDate(year, month, day)
            key = d.toJulianDay()
            if key in self._cell_cache:
                self._cell_cache.move_to_end(key)
                continue
            self._put_cell_cache(key, self._presenter.compute(d))

    def _invalidate_cell_cache(self):
        self._cell_cache.clear()
        t0 = _time.monotonic()
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())
        elapsed_ms = (_time.monotonic() - t0) * 1000
        if elapsed_ms > 100:
            logger.warning(
                "日历缓存重建耗时 %.1fms（%d 项），可能存在主线程卡顿",
                elapsed_ms, len(self._cell_cache))

    def _cell_for(self, qdate: QDate):
        key = qdate.toJulianDay()
        if key in self._cell_cache:
            self._cell_cache.move_to_end(key)
            return self._cell_cache[key]
        return self._put_cell_cache(key, self._presenter.compute(qdate))

    # ---------- 绘制入口 ----------
    def paintCell(self, painter: QPainter, rect: QRect, qdate: QDate):
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            bg_rect = QRectF(rect.adjusted(2, 2, -2, -2))
            if not self._is_current_month(qdate):
                self._draw_adjacent_cell(painter, rect, bg_rect, qdate)
                return
            self._draw_current_cell(painter, rect, bg_rect, qdate)
        except Exception:
            date_str = qdate.toString('yyyy-MM-dd')
            self._log_exception_once(
                f"paintCell:{date_str}",
                f"paintCell单元格渲染异常 date={date_str}")
        finally:
            try:
                painter.restore()
            except RuntimeError:
                pass

    # ---------- 绘制子步骤 ----------
    def _is_current_month(self, qdate: QDate) -> bool:
        return (qdate.year() == self.yearShown()
                and qdate.month() == self.monthShown())

    def _draw_adjacent_cell(self, painter, rect, bg_rect, qdate):
        r = self._cell_radius
        painter.setBrush(self._colors["adjacent_cell_bg"])
        painter.setPen(self._no_pen)
        painter.drawRoundedRect(bg_rect, r, r)
        painter.setFont(self._day_font)
        painter.setPen(self._colors["adjacent_text_color"])
        painter.drawText(
            rect.adjusted(4, 3, -4, -9),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            str(qdate.day()))

    def _draw_current_cell(self, painter, rect, bg_rect, qdate):
        cell = self._cell_for(qdate)
        is_today = qdate == QDate.currentDate()
        is_selected = qdate == self.selectedDate()
        r = self._cell_radius
        bg_key = ("today_bg" if is_today
                  else "select_bg" if is_selected
                  else "normal_cell_bg")
        painter.setBrush(self._colors[bg_key])
        painter.setPen(self._no_pen)
        painter.drawRoundedRect(bg_rect, r, r)
        self._draw_texts(painter, rect, qdate, cell, is_today, is_selected)
        if cell.is_weekend_work:
            self._draw_workday_tag(painter, rect)
        self._draw_dot(painter, rect, cell)

    def _draw_texts(self, painter, rect, qdate, cell, is_today, is_selected):
        if is_today:
            day_color = self._colors["today_text_color"]
        elif is_selected:
            day_color = self._colors["select_text_color"]
        elif cell.is_legal_hol:
            day_color = self._colors["festival_red"]
        elif cell.is_weekend_work:
            day_color = self._colors["workday_orange"]
        else:
            day_color = self._colors["normal_num_color"]
        painter.setFont(self._day_font)
        painter.setPen(day_color)
        painter.drawText(
            rect.adjusted(4, 3, -4, -9),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            str(qdate.day()))

        if cell.kind == CELL_MEMORIAL:
            lunar_color = self._colors["memorial_orange"]
        elif cell.kind == CELL_RED:
            lunar_color = self._colors["festival_red"]
        elif cell.is_weekend_work:
            lunar_color = self._colors["workday_orange"]
        else:
            lunar_color = self._colors["normal_lunar_color"]
        painter.setFont(self._small_font)
        painter.setPen(lunar_color)
        painter.drawText(
            rect.adjusted(4, 9, -4, -2),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            cell.lunar_text)

    def _draw_workday_tag(self, painter, rect):
        tag_size = self._tag_size
        x = rect.right() - tag_size - 4
        y = rect.top() + 4
        painter.setBrush(self._colors["tag_bg"])
        painter.setPen(self._no_pen)
        painter.drawRoundedRect(x, y, tag_size, tag_size, 4, 4)
        painter.setFont(self._small_font)
        painter.setPen(self._colors["tag_text_color"])
        painter.drawText(
            QRectF(x, y, tag_size, tag_size),
            Qt.AlignmentFlag.AlignCenter, self._workday_tag_text)

    def _draw_dot(self, painter, rect, cell):
        if cell.kind == CELL_MEMORIAL:
            dot_color = self._colors["memorial_orange"]
        elif cell.kind == CELL_RED:
            dot_color = self._colors["festival_red"]
        else:
            return
        painter.setBrush(dot_color)
        painter.setPen(self._no_pen)
        x = (rect.left() + 4 if cell.is_weekend_work
             else rect.right() - self._dot_size - 4)
        painter.drawEllipse(x, rect.top() + 4, self._dot_size, self._dot_size)

    # ---------- 工具 ----------
    def _log_exception_once(self, key, message):
        if key in self._reported_errors:
            return
        if len(self._reported_errors) >= _REPORTED_ERRORS_MAX:
            self._reported_errors.clear()
            if not self._reported_errors_limit_warned:
                logger.warning("异常上报去重表已达上限，已清空")
                self._reported_errors_limit_warned = True
        self._reported_errors.add(key)
        log_exception(message)