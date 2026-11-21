# coding: utf-8
import time as _time
from collections import OrderedDict
from typing import Any

from PyQt6.QtCore import QDate, QLocale, QRect, QRectF, QSizeF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QTextCharFormat,
)
from PyQt6.QtWidgets import QCalendarWidget

from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import get_logger, log_exception
from desktop_calendar.ui.calendar_wallpaper import draw_wallpaper
from desktop_calendar.ui.cell_presenter import (
    CELL_MEMORIAL,
    CELL_RED,
    UNSET,
    CellPresenter,
)
from desktop_calendar.ui.theme import ThemeBundle

logger = get_logger()

_REPORTED_ERRORS_MAX = 2000
_WHEEL_STEP = 120


class LunarCalendarWidget(QCalendarWidget):
    """农历日历控件：展示规则由 CellPresenter 提供。"""

    _CELL_CACHE_MAX = 5 * 42

    def __init__(self, parent, bundle: ThemeBundle, memorial_list):
        super().__init__(parent)
        self._apply_locale()
        self._presenter = CellPresenter()
        self._presenter.set_memorial_list(memorial_list)
        self._reported_errors = set()
        self._reported_errors_limit_warned = False
        self._cell_cache = OrderedDict()
        self._wheel_accum = 0
        self._warmed_years: set[int] = set()
        self._wallpaper = None
        self._wallpaper_overlay = 58
        self._workday_tag_text = tr("cell.workday_tag")
        self.apply_theme(bundle)
        self.currentPageChanged.connect(self._on_page_changed)
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())
        # __init__ 不走 _on_page_changed，首屏需手动预热
        self._warmup_adjacent_years(self.yearShown())

    def _apply_locale(self) -> None:
        self.setLocale(QLocale("zh_CN"))
        self.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)

    def apply_theme(self, bundle: ThemeBundle) -> None:
        self._bundle = bundle
        self._day_font = bundle.fonts.calendar_day
        self._small_font = bundle.fonts.calendar_small
        self._colors = bundle.calendar_colors
        self._dot_size = bundle.calendar_metrics.dot_size
        self._tag_size = bundle.calendar_metrics.tag_size
        self._cell_radius = bundle.calendar_metrics.cell_radius
        # 格子里的边距同样要跟缩放走：写死像素在 0.8 倍缩放或矮格子里
        # 会把公历数字和农历挤到一起
        scale = bundle.scale_factor
        self._cell_inset = max(1, round(2 * scale))
        self._text_pad_x = max(2, round(4 * scale))
        self._text_pad_top = max(2, round(3 * scale))
        self._text_pad_bottom = max(1, round(2 * scale))
        self._gap = max(2, round(4 * scale))
        metrics_day = QFontMetrics(self._day_font)
        metrics_small = QFontMetrics(self._small_font)
        self._day_text_h = metrics_day.height()
        self._small_text_h = metrics_small.height()
        self._day_pt = self._day_font.pointSizeF()
        self._small_pt = self._small_font.pointSizeF()
        self._no_pen = QPen(Qt.PenStyle.NoPen)
        self._fix_week_header_color()
        self.update()

    def _inner_rect(self, rect: QRect) -> QRect:
        return rect.adjusted(
            self._text_pad_x, self._text_pad_top, -self._text_pad_x, -self._text_pad_bottom
        )

    def _fitted_fonts(self, height: int) -> tuple[QFont, QFont, int, int]:
        """格子矮时按比例缩字号，保证公历与农历两行都放得下。"""
        need = self._day_text_h + self._small_text_h
        if height >= need or need <= 0:
            return (self._day_font, self._small_font, self._day_text_h, self._small_text_h)
        ratio = max(0.62, (height - 1) / need)
        day_font = QFont(self._day_font)
        day_font.setPointSizeF(max(6.0, self._day_pt * ratio))
        small_font = QFont(self._small_font)
        small_font.setPointSizeF(max(5.0, self._small_pt * ratio))
        # 取整后的实际行高可能仍差 1~2px，逐次微缩直到两行都塞得下
        for _ in range(4):
            day_h = QFontMetrics(day_font).height()
            small_h = QFontMetrics(small_font).height()
            if day_h + small_h <= height:
                break
            day_font.setPointSizeF(max(6.0, day_font.pointSizeF() * 0.92))
            small_font.setPointSizeF(max(5.0, small_font.pointSizeF() * 0.92))
        return (
            day_font,
            small_font,
            QFontMetrics(day_font).height(),
            QFontMetrics(small_font).height(),
        )

    def _text_bands(
        self,
        rect: QRect,
        day_h: int,
        small_h: int,
    ) -> tuple[QRect, QRect]:
        """按字体实际行高把格子切成「公历数字 / 农历」两段。"""
        inner = self._inner_rect(rect)
        if inner.width() <= 0 or inner.height() <= 1:
            return QRect(), QRect()
        split = inner.bottom() + 1 - max(1, small_h)
        split = max(inner.top() + 1, min(split, inner.bottom()))
        return (
            QRect(inner.left(), inner.top(), inner.width(), split - inner.top()),
            QRect(inner.left(), split, inner.width(), inner.bottom() - split + 1),
        )

    def set_wallpaper(self, pixmap, overlay_percent: int) -> None:
        self._wallpaper = pixmap
        self._wallpaper_overlay = overlay_percent
        self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y() * 3
        self._wheel_accum += delta
        while self._wheel_accum >= _WHEEL_STEP:
            self._wheel_accum -= _WHEEL_STEP
            self.showPreviousMonth()
        while self._wheel_accum <= -_WHEEL_STEP:
            self._wheel_accum += _WHEEL_STEP
            self.showNextMonth()
        event.accept()

    def set_memorial_list(self, ml):
        self._presenter.set_memorial_list(list(ml) if isinstance(ml, (list, tuple)) else [])
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

    def set_schedule_dates(self, dates) -> None:
        self.set_schedule_markers({value: "" for value in dates if isinstance(value, str)})

    def set_schedule_markers(self, markers: dict[str, str]) -> None:
        self._presenter.set_schedule_markers(markers)
        self._invalidate_cell_cache()
        self.update()

    def get_memorials_for_date(self, qdate: QDate):
        return self._presenter.memorials_for(qdate)

    def cell_data_for(self, qdate: QDate):
        return self._cell_for(qdate)

    def memorial_items_for(self, qdate: QDate):
        return self._presenter.memorial_items_for(qdate)

    def get_lunar_cell_text(self, qdate, lunar=UNSET, legal_raw=UNSET):
        return self._presenter.lunar_text_and_kind(qdate, lunar=lunar, legal_raw=legal_raw)

    def _fix_week_header_color(self):
        red_fmt = QTextCharFormat()
        red_fmt.setForeground(self._colors["weekend_header_red"])
        red_fmt.setFont(self._day_font)

        normal_fmt = QTextCharFormat()
        normal_fmt.setForeground(self._colors["calendar_header_text"])
        normal_fmt.setFont(self._day_font)

        for dow in (
            Qt.DayOfWeek.Monday,
            Qt.DayOfWeek.Tuesday,
            Qt.DayOfWeek.Wednesday,
            Qt.DayOfWeek.Thursday,
            Qt.DayOfWeek.Friday,
        ):
            self.setWeekdayTextFormat(dow, normal_fmt)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, red_fmt)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, red_fmt)

    def _on_page_changed(self, year: int, month: int):
        self._rebuild_cell_cache(year, month)
        self._warmup_adjacent_years(year)

    def _warmup_adjacent_years(self, year: int) -> None:
        new_years = [y for y in (year - 1, year, year + 1) if y not in self._warmed_years]
        if not new_years:
            return
        self._warmed_years.update(new_years)
        self._presenter.warmup_for_years(new_years)

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
                elapsed_ms,
                len(self._cell_cache),
            )

    def _cell_for(self, qdate: QDate):
        key = qdate.toJulianDay()
        if key in self._cell_cache:
            self._cell_cache.move_to_end(key)
            return self._cell_cache[key]
        return self._put_cell_cache(key, self._presenter.compute(qdate))

    def paintCell(self, painter: QPainter, rect: QRect, qdate: QDate):
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            inset = self._cell_inset
            bg_rect = QRectF(rect).adjusted(inset, inset, -inset, -inset)
            if not self._is_current_month(qdate):
                self._draw_adjacent_cell(painter, rect, bg_rect, qdate)
                return
            self._draw_current_cell(painter, rect, bg_rect, qdate)
        except Exception:
            date_str = qdate.toString("yyyy-MM-dd")
            self._log_exception_once(
                f"paintCell:{date_str}", f"paintCell单元格渲染异常 date={date_str}"
            )
        finally:
            try:
                painter.restore()
            except RuntimeError:
                pass

    def _is_current_month(self, qdate: QDate) -> bool:
        return qdate.year() == self.yearShown() and qdate.month() == self.monthShown()

    def _draw_adjacent_cell(self, painter, rect, bg_rect, qdate):
        r = self._cell_radius
        if not draw_wallpaper(
            painter,
            bg_rect,
            QSizeF(self.size()),
            self._wallpaper,
            self._colors["adjacent_cell_bg"],
            self._wallpaper_overlay,
            radius=r,
        ):
            painter.setBrush(self._colors["adjacent_cell_bg"])
            painter.setPen(self._no_pen)
            painter.drawRoundedRect(bg_rect, r, r)
        inner = self._inner_rect(rect)
        if inner.isEmpty():
            return
        day_font, _small, _day_h, _small_h = self._fitted_fonts(inner.height())
        painter.setFont(day_font)
        painter.setPen(self._colors["adjacent_text_color"])
        painter.drawText(
            inner, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, str(qdate.day())
        )

    def _draw_current_cell(self, painter, rect, bg_rect, qdate):
        cell = self._cell_for(qdate)
        is_today = qdate == QDate.currentDate()
        is_selected = qdate == self.selectedDate()
        r = self._cell_radius
        bg_key = "today_bg" if is_today else "select_bg" if is_selected else "normal_cell_bg"
        overlay = (
            min(90, self._wallpaper_overlay + 14)
            if (is_today or is_selected)
            else self._wallpaper_overlay
        )
        if not draw_wallpaper(
            painter,
            bg_rect,
            QSizeF(self.size()),
            self._wallpaper,
            self._colors[bg_key],
            overlay,
            radius=r,
        ):
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
        inner = self._inner_rect(rect)
        if inner.isEmpty():
            return
        day_font, small_font, day_h, small_h = self._fitted_fonts(inner.height())
        number_rect, lunar_rect = self._text_bands(rect, day_h, small_h)
        if number_rect.isEmpty():
            return
        painter.setFont(day_font)
        painter.setPen(day_color)
        painter.drawText(
            number_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            str(qdate.day()),
        )

        # 今日/选中背景特殊，农历必须用对应文字色，否则深色主题不可见
        if is_today:
            lunar_color = self._colors["today_text_color"]
        elif is_selected:
            lunar_color = self._colors["select_text_color"]
        elif cell.kind == CELL_MEMORIAL:
            lunar_color = self._colors["memorial_orange"]
        elif cell.kind == CELL_RED:
            lunar_color = self._colors["festival_red"]
        elif cell.is_weekend_work:
            lunar_color = self._colors["workday_orange"]
        else:
            lunar_color = self._colors["normal_lunar_color"]
        painter.setFont(small_font)
        painter.setPen(lunar_color)
        if lunar_rect.isEmpty() or lunar_rect.height() < small_h:
            return
        painter.drawText(
            lunar_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            cell.lunar_text,
        )

    def _draw_workday_tag(self, painter, rect):
        tag_size = self._tag_size
        gap = self._gap
        x = rect.right() - tag_size - gap
        y = rect.top() + gap
        painter.setBrush(self._colors["tag_bg"])
        painter.setPen(self._no_pen)
        painter.drawRoundedRect(x, y, tag_size, tag_size, 4, 4)
        painter.setFont(self._small_font)
        painter.setPen(self._colors["tag_text_color"])
        painter.drawText(
            QRectF(x, y, tag_size, tag_size), Qt.AlignmentFlag.AlignCenter, self._workday_tag_text
        )

    def _draw_dot(self, painter, rect, cell):
        dots = []
        if cell.kind == CELL_MEMORIAL:
            side = "left" if cell.is_weekend_work else "right"
            dots.append((self._colors["memorial_orange"], side))
        elif cell.kind == CELL_RED:
            side = "left" if cell.is_weekend_work else "right"
            dots.append((self._colors["festival_red"], side))
        if cell.has_schedule:
            color = QColor(cell.schedule_color or "#4A90D9")
            if not color.isValid():
                color = QColor("#4A90D9")
            dots.append((color, "left"))
        for color, side in dots:
            painter.setBrush(color)
            painter.setPen(self._no_pen)
            gap = self._gap
            x = rect.left() + gap if side == "left" else rect.right() - self._dot_size - gap
            y = rect.top() + gap
            if side == "left" and cell.is_weekend_work and cell.has_schedule:
                y += self._dot_size + max(1, gap // 2)
            painter.drawEllipse(x, y, self._dot_size, self._dot_size)

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
