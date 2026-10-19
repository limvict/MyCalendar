# coding: utf-8
from collections import OrderedDict
from typing import Any

from PyQt6.QtCore import Qt, QDate, QLocale, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QPainter, QPen
from PyQt6.QtWidgets import QCalendarWidget, QLabel

from desktop_calendar.config.config import log_exception, get_logger
from desktop_calendar.config.i18n import tr, get_language
from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.application.cell_presenter import (
    CellPresenter, CELL_NORMAL, CELL_MEMORIAL, CELL_RED, _UNSET,
)

logger = get_logger()

# 异常上报去重表上限
_REPORTED_ERRORS_MAX = 2000

_COLOR_KEYS = (
    "weekend_header_red", "calendar_header_text",
    "adjacent_cell_bg", "adjacent_text_color",
    "today_bg", "select_bg", "normal_cell_bg",
    "today_text_color", "select_text_color",
    "festival_red", "workday_orange",
    "normal_num_color", "memorial_orange",
    "normal_lunar_color", "tag_bg", "tag_text_color",
)
_COLOR_DEFAULTS = {k: DEFAULT_THEME[k] for k in _COLOR_KEYS}


class ClickLabel(QLabel):
    clicked = pyqtSignal()

    def __init__(self, text: str = ""):
        super().__init__(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class LunarCalendarWidget(QCalendarWidget):
    """自定义农历日历控件：展示逻辑由 CellPresenter 提供。"""

    _CELL_CACHE_MAX = 3 * 42

    def __init__(self, parent, theme: dict, memorial_list):
        super().__init__(parent)
        self.setLocale(QLocale(get_language()))
        self._theme = theme
        self._presenter = CellPresenter()
        self._presenter.set_memorial_list(memorial_list)

        self._reported_errors = set()
        self._reported_errors_limit_warned = False
        self._cell_cache: "OrderedDict[int, Any]" = OrderedDict()
        self._apply_theme(theme)
        self._fix_week_header_color()
        self.currentPageChanged.connect(self._on_page_changed)
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())
        self._wheel_accum = 0

    def wheelEvent(self, event):
        """滚轮翻月：累计一格（120）才翻，避免触控板飞页。"""
        self._wheel_accum += event.angleDelta().y()
        threshold = 120
        if self._wheel_accum >= threshold:
            self._wheel_accum = 0
            self.showPreviousMonth()
        elif self._wheel_accum <= -threshold:
            self._wheel_accum = 0
            self.showNextMonth()
        event.accept()

    # ---------------- 主题 / 字体 / 颜色 ----------------
    def _apply_theme(self, theme: dict):
        font_family = theme.get("font_family", "微软雅黑").split(",")[0].strip()
        font_size = theme.get("font_size", 13)
        small_font_size = theme.get("small_font_size", 9)

        self._day_font = QFont(font_family)
        self._day_font.setPointSize(font_size)
        self._small_font = QFont(font_family)
        self._small_font.setPointSize(small_font_size)

        self.dot_size = int(theme.get("dot_size", 6))
        self.tag_size = int(theme.get("tag_size", 14))
        self.cell_radius = int(theme.get("cell_corner_radius", 8))

        self._colors = {
            k: QColor(theme.get(k, v)) for k, v in _COLOR_DEFAULTS.items()
        }
        self._no_pen = QPen(Qt.PenStyle.NoPen)

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

    def _log_exception_once(self, key, message):
        if key in self._reported_errors:
            return
        if len(self._reported_errors) >= _REPORTED_ERRORS_MAX:
            if not self._reported_errors_limit_warned:
                logger.warning("异常上报去重表已达上限")
                self._reported_errors_limit_warned = True
            return
        self._reported_errors.add(key)
        log_exception(message)

    def _on_page_changed(self, year: int, month: int):
        self._rebuild_cell_cache(year, month)

    # ---------------- 单元格缓存 ----------------
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
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())

    # ---------------- 数据注入 ----------------
    def set_memorial_list(self, ml):
        self._presenter.set_memorial_list(
            list(ml) if isinstance(ml, (list, tuple)) else [])
        self._invalidate_cell_cache()
        self.update()

    def set_net_holiday(self, holiday_data):
        try:
            self._presenter.set_net_holiday(holiday_data)
            logger.info("加载网络节假日数据，共%d条",
                        self._presenter.net_count)
            self._invalidate_cell_cache()
            self.update()
        except Exception as e:
            log_exception(f"set_net_holiday 加载节假日数据失败: {e}")

    def get_memorials_for_date(self, qdate: QDate):
        return self._presenter.memorials_for(qdate)

    def get_lunar_cell_text(self, qdate, lunar=_UNSET, legal_raw=_UNSET):
        """兼容旧调用点：委托给 presenter，保留参数语义。"""
        return self._presenter.lunar_text_and_kind(
                qdate, lunar=lunar, legal_raw=legal_raw)

    def update_theme(self, new_theme: dict):
        self._theme = new_theme
        self._apply_theme(new_theme)
        self._fix_week_header_color()
        self.update()

    def retranslate_ui(self):
        """语言切换后刷新周几表头 + 缓存文本。"""
        self.setLocale(QLocale(get_language()))
        self._invalidate_cell_cache()
        self._fix_week_header_color()
        self.update()

    # ---------------- 绘制 ----------------
    def paintCell(self, painter: QPainter, rect: QRect, qdate: QDate):
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            is_current_month = (qdate.year() == self.yearShown()
                                and qdate.month() == self.monthShown())
            r = self.cell_radius
            bg_rect = QRectF(rect.adjusted(2, 2, -2, -2))

            if not is_current_month:
                painter.setBrush(self._colors["adjacent_cell_bg"])
                painter.setPen(self._no_pen)
                painter.drawRoundedRect(bg_rect, r, r)
                painter.setFont(self._day_font)
                painter.setPen(self._colors["adjacent_text_color"])
                painter.drawText(
                    rect.adjusted(4, 3, -4, -9),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    str(qdate.day()))
                return

            is_selected = (qdate == self.selectedDate())
            is_today = (qdate == QDate.currentDate())
            key = qdate.toJulianDay()
            cell = self._cell_cache.get(key)
            if cell is None:
                cell = self._put_cell_cache(key, self._presenter.compute(qdate))

            kind = cell.kind
            is_hol = cell.is_hol
            is_weekend_work = cell.is_weekend_work
            is_legal_hol = cell.is_legal_hol
            lunar_text = cell.lunar_text

            if is_today:
                bg = self._colors["today_bg"]
            elif is_selected:
                bg = self._colors["select_bg"]
            else:
                bg = self._colors["normal_cell_bg"]
            painter.setBrush(bg)
            painter.setPen(self._no_pen)
            painter.drawRoundedRect(bg_rect, r, r)

            painter.setFont(self._day_font)
            day_rect = rect.adjusted(4, 3, -4, -9)
            if is_today:
                painter.setPen(self._colors["today_text_color"])
            elif is_selected:
                painter.setPen(self._colors["select_text_color"])
            elif is_hol:
                painter.setPen(self._colors["festival_red"])
            elif is_weekend_work:
                painter.setPen(self._colors["workday_orange"])
            else:
                painter.setPen(self._colors["normal_num_color"])
            painter.drawText(
                day_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                str(qdate.day()))

            painter.setFont(self._small_font)
            if kind == CELL_MEMORIAL:
                painter.setPen(self._colors["memorial_orange"])
            elif kind == CELL_RED:
                painter.setPen(self._colors["festival_red"])
            elif is_weekend_work:
                painter.setPen(self._colors["workday_orange"])
            else:
                painter.setPen(self._colors["normal_lunar_color"])
            painter.drawText(
                rect.adjusted(4, 9, -4, -2),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                lunar_text)

            if is_weekend_work:
                tag_size = self.tag_size
                x = rect.right() - tag_size - 4
                y = rect.top() + 4
                painter.setBrush(self._colors["tag_bg"])
                painter.setPen(self._no_pen)
                painter.drawRoundedRect(x, y, tag_size, tag_size, 4, 4)
                painter.setFont(self._small_font)
                painter.setPen(self._colors["tag_text_color"])
                painter.drawText(
                    QRectF(x, y, tag_size, tag_size),
                    Qt.AlignmentFlag.AlignCenter,
                    tr("cell.workday_tag"))

            dot_color = None
            if kind == CELL_MEMORIAL:
                dot_color = self._colors["memorial_orange"]
            elif kind == CELL_RED or is_legal_hol:
                dot_color = self._colors["festival_red"]
            if dot_color is not None:
                painter.setBrush(dot_color)
                painter.setPen(self._no_pen)
                x = (rect.left() + 4 if is_weekend_work
                     else rect.right() - self.dot_size - 4)
                painter.drawEllipse(x, rect.top() + 4,
                                    self.dot_size, self.dot_size)
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