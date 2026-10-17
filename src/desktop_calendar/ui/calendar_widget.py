# coding: utf-8
from collections import OrderedDict
from typing import Dict, Tuple, List, Any, Optional

from PyQt6.QtCore import Qt, QDate, QLocale, QRect, QRectF, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QPainter, QPen
from PyQt6.QtWidgets import QCalendarWidget, QLabel
from desktop_calendar.config.config import log_exception, get_logger
from desktop_calendar.config.i18n import tr, get_language

from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.lunar import (
    get_lunar_by_datetime, is_holiday, is_workday, qdate_to_pydate,
)
from desktop_calendar.core.memorial import (
    normalize_memorial, REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK,
)
from desktop_calendar.config.constants import (
    LUNAR_FESTIVALS, SOLAR_FESTIVALS, FESTIVAL_NAME_MAP,
    RED_TEXT_SET, MONTH_CN, NUM_CN_MAP, DEFAULT_THEME,
)

logger = get_logger()

_CELL_NORMAL = "normal"
_CELL_MEMORIAL = "memorial"
_CELL_RED = "red"

# 区分"尚未查询"与"确实无法定节日"。
_UNSET = object()

# 异常上报去重表上限。达到后拒绝新增 key，避免无限增长；
# 不清空，否则旧 key 会被重新上报、刷屏日志。
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
    """自定义农历日历控件：月份数据预计算缓存。"""

    _CELL_CACHE_MAX = 3 * 42 

    def __init__(
        self, parent, theme: Dict[str, Any], memorial_list: List[Dict[str, Any]]
    ):
        super().__init__(parent)
        self.setLocale(QLocale(get_language()))
        self._theme = theme
        self.memorial_list = (
            list(memorial_list) if isinstance(memorial_list, (list, tuple)) else []
        )
        self._memorial_index = self._build_memorial_index(self.memorial_list)
        self.net_holiday_data: Dict[str, bool] = {}

        self._reported_errors = set()
        self._reported_errors_limit_warned = False
        self._cell_cache: "OrderedDict[int, dict]" = OrderedDict()
        self._apply_theme(theme)
        self._fix_week_header_color()
        self.currentPageChanged.connect(self._on_page_changed)
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())
        self._wheel_accum = 0
        
    def wheelEvent(self, event):
        """
        滚轮翻月。

        累加 delta 而不是"有 delta 就翻"：触控板双指滑动会连续产生
        小 delta，直接翻页会飞页；鼠标滚轮一格是 120，累计到一格才翻。
        """
        self._wheel_accum += event.angleDelta().y()
        threshold = 120
        if self._wheel_accum >= threshold:
            self._wheel_accum = 0
            self.showPreviousMonth()
        elif self._wheel_accum <= -threshold:
            self._wheel_accum = 0
            self.showNextMonth()
        # 无论是否翻页都吞掉：避免向上冒泡到父窗口做无意义处理
        event.accept()
        
    # ---------------- 纪念日索引 ----------------
    def _build_memorial_index(
        self, memorial_list: List[Dict[str, Any]]
    ) -> Dict[str, Dict[Any, List[Dict[str, Any]]]]:
        """
        把"逐日遍历整表"（42×N）降为"逐日 O(1) 查表"。

        索引结构：
          solar_year[(month, day)]           → [...]   # 公历每年
          solar_month[day]                   → [...]   # 公历每月
          solar_week[weekday 1..7]           → [...]   # 每周（强制公历）
          lunar_year[(month, day, isleap)]   → [...]   # 农历每年
          lunar_month[(day, isleap)]         → [...]   # 农历每月

        桶内保留输入顺序；同日命中多个时 get_lunar_cell_text 取首条，
        get_memorials_for_date 取全部。
        """
        idx: Dict[str, Dict[Any, List[Dict[str, Any]]]] = {
            "solar_year": {}, "solar_month": {}, "solar_week": {},
            "lunar_year": {}, "lunar_month": {},
        }
        if not isinstance(memorial_list, (list, tuple)):
            return idx

        for mem in memorial_list:
            if not isinstance(mem, dict):
                continue
            try:
                m = normalize_memorial(mem)
            except Exception:
                continue
            if not m.get("enabled", True):
                continue
            rep, typ = m["repeat_type"], m["type"]
            if rep == REPEAT_WEEK:
                idx["solar_week"].setdefault(m["day"], []).append(m)
            elif typ == "solar":
                if rep == REPEAT_YEAR:
                    idx["solar_year"].setdefault(
                        (m["month"], m["day"]), []).append(m)
                else:
                    idx["solar_month"].setdefault(m["day"], []).append(m)
            else:
                leap = bool(m.get("isleap", False))
                if rep == REPEAT_YEAR:
                    idx["lunar_year"].setdefault(
                        (m["month"], m["day"], leap), []).append(m)
                else:
                    idx["lunar_month"].setdefault(
                        (m["day"], leap), []).append(m)
        return idx

    # ---------------- 主题 / 字体 / 颜色 ----------------
    def _apply_theme(self, theme: dict):
        """
        font_size / small_font_size 按 pointSize 解释，与
        StyleManager.get_global_font 保持一致（setPixelSize 会在高 DPI
        下把视觉尺寸缩水）。
        """
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

        self._colors: Dict[str, QColor] = {
            k: QColor(theme.get(k, v)) for k, v in _COLOR_DEFAULTS.items()
        }
        self._no_pen = QPen(Qt.PenStyle.NoPen)

    def _log_exception_once(self, key, message):
        if key in self._reported_errors:
            return
        if len(self._reported_errors) >= _REPORTED_ERRORS_MAX:
            if not self._reported_errors_limit_warned:
                logger.warning("异常上报去重表已达上限，后续不同 key 将不再记录")
                self._reported_errors_limit_warned = True
            return
        self._reported_errors.add(key)
        log_exception(message)

    def _on_page_changed(self, year: int, month: int):
        self._rebuild_cell_cache(year, month)

    # ---------------- 单元格缓存 ----------------
    def _put_cell_cache(self, key: int, cell: dict) -> dict:
        """
        写入/更新单元格缓存，刷新 LRU 位置，超限时淘汰最旧条目。

        所有写入路径（_rebuild_cell_cache、paintCell 补算）共用本方法，
        保证"写入 + move_to_end + 驱逐"不会在某处漏掉。
        返回值即入参 cell，便于 paintCell 一行完成"补算 → 写入 → 使用"。
        """
        self._cell_cache[key] = cell
        self._cell_cache.move_to_end(key)
        while len(self._cell_cache) > self._CELL_CACHE_MAX:
            self._cell_cache.popitem(last=False)
        return cell

    def _rebuild_cell_cache(self, year: int, month: int):
        """确保某月缓存存在；命中仅刷新 LRU，未命中才补算。"""
        first = QDate(year, month, 1)
        for day in range(1, first.daysInMonth() + 1):
            d = QDate(year, month, day)
            key = d.toJulianDay()
            if key in self._cell_cache:
                self._cell_cache.move_to_end(key)
                continue
            self._put_cell_cache(key, self._calc_cell_data(d))

    # ---------------- 法定节日提取 ----------------
    @staticmethod
    def _first_legal_holiday_raw(lunar) -> Optional[str]:
        if lunar is None:
            return None
        try:
            f_list = lunar.get_legalHolidays()
        except Exception:
            return None
        if not f_list:
            return None
        raw = f_list[0] if isinstance(f_list, (list, tuple)) else f_list
        if not raw or raw == "无":
            return None
        return raw

    def _calc_cell_data(self, qdate: QDate) -> dict:
        date_str = qdate.toString("yyyy-MM-dd")
        try:
            lunar = self.get_day_lunar_obj(qdate)
            legal_raw = self._first_legal_holiday_raw(lunar)
            lunar_text, kind = self.get_lunar_cell_text(
                qdate, lunar=lunar, legal_raw=legal_raw)
            return {
                "lunar_text": lunar_text,
                "kind": kind,
                "is_hol": self.is_date_holiday(qdate, date_str=date_str),
                "is_weekend_work": self.is_weekend_workday(
                qdate, date_str=date_str),
                "is_legal_hol": self._is_legal_holiday(
                qdate, lunar=lunar, legal_raw=legal_raw, date_str=date_str),
            }
        except Exception:
            self._log_exception_once(
                f"_calc_cell_data:{date_str}",
                f"预计算单元格数据失败 date={date_str}")
            return {"lunar_text": "", "kind": _CELL_NORMAL, "is_hol": False,
                    "is_weekend_work": False, "is_legal_hol": False}

    def set_memorial_list(self, ml: List[Dict[str, Any]]):
        # 拷贝：防止把 config.get("memorial_days") 拿到的内部引用直接
        # 挂到 self 上，将来任何原地修改都会污染配置。
        self.memorial_list = list(ml) if isinstance(ml, (list, tuple)) else []
        self._memorial_index = self._build_memorial_index(self.memorial_list)
        self._invalidate_cell_cache()
        self.update()

    def update_theme(self, new_theme: dict):
        """只更新绘制属性，不重算农历 / 纪念日缓存。"""
        self._theme = new_theme
        self._apply_theme(new_theme)
        self._fix_week_header_color()
        self.update()

    def _fix_week_header_color(self):
        """周一~周五用 calendar_header_text，周六~周日用 weekend_header_red。"""
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

    def get_day_lunar_obj(self, qdate: QDate) -> Optional[Any]:
        if not lunar_mod.HAS_CNLUNAR:
            return None
        try:
            return get_lunar_by_datetime(
                (qdate.year(), qdate.month(), qdate.day()))
        except Exception:
            logger.debug(
                f"实时农历转换失败 date={qdate.toString('yyyy-MM-dd')}",
                exc_info=True)
            return None

    # ---------------- 农历文本解析 ----------------
    def _lookup_solar_memorial_name(self, qdate: QDate) -> Optional[str]:
        """依次查 公历年 / 公历周 / 公历月 三个桶，顺序即优先级。"""
        for bucket_key, key in (
            ("solar_year",  (qdate.month(), qdate.day())),
            ("solar_week",  qdate.dayOfWeek()),
            ("solar_month", qdate.day()),
        ):
            mems = self._memorial_index[bucket_key].get(key)
            if mems:
                return mems[0].get("name") or tr("memorial.default_name")
        return None

    def _lookup_lunar_memorial_name(
        self, lunar_month: int, lunar_day: int, is_leap: bool
    ) -> Optional[str]:
        """依次查 农历年 / 农历月 两个桶，顺序即优先级。"""
        for bucket_key, key in (
            ("lunar_year",  (lunar_month, lunar_day, is_leap)),
            ("lunar_month", (lunar_day, is_leap)),
        ):
            mems = self._memorial_index[bucket_key].get(key)
            if mems:
                return mems[0].get("name") or tr("memorial.default_name")
        return None

    def _is_new_year_eve(
        self, qdate: QDate, lunar_month: int, is_leap: bool
    ) -> bool:
        """除夕：腊月最后一天，且次日为正月初一。闰月不算。"""
        if is_leap or lunar_month != 12:
            return False
        next_lunar = self.get_day_lunar_obj(qdate.addDays(1))
        return (next_lunar is not None
                and getattr(next_lunar, "lunarMonth", None) == 1
                and not bool(getattr(next_lunar, "isLunarLeapMonth", False))
                and getattr(next_lunar, "lunarDay", None) == 1
        )

    def _resolve_after_memorial(
        self, qdate: QDate, lunar, lunar_month: int, lunar_day: int,
        is_leap: bool, legal_raw,
    ) -> Tuple[str, str]:
        """
        纪念日未命中后的优先级链：
          除夕 → 法定节日 → 农历传统节日 → 公历节日 → 节气 → 农历日期。

        cnlunar 的 get_legalHolidays() 通常会覆盖春节 / 端午 / 中秋等，
        因此 LUNAR_FESTIVALS 分支在 cnlunar 数据正常时只在"农历节日但无
        对应法定名"的项上生效（如元宵、七夕、重阳）；只有当 cnlunar
        数据滞后、未把该日列为 legal_holiday 时，LUNAR_FESTIVALS 才会
        兜底给出正确的节日名与红色样式。
        """
        if self._is_new_year_eve(qdate, lunar_month, is_leap):
            return tr("cell.new_year_eve"), _CELL_RED

        if legal_raw is _UNSET:
            legal_raw = self._first_legal_holiday_raw(lunar)
        if legal_raw is not None:
            name = FESTIVAL_NAME_MAP.get(legal_raw, legal_raw)
            return name, (_CELL_RED if name in RED_TEXT_SET
                          else _CELL_NORMAL)

        if not is_leap and (lunar_month, lunar_day) in LUNAR_FESTIVALS:
            return LUNAR_FESTIVALS[(lunar_month, lunar_day)], _CELL_RED

        if (qdate.month(), qdate.day()) in SOLAR_FESTIVALS:
            return (SOLAR_FESTIVALS[(qdate.month(), qdate.day())],
                    _CELL_NORMAL)

        term_name = getattr(lunar, "todaySolarTerms", "")
        if isinstance(term_name, list) and term_name:
            term_name = term_name[0]
        if term_name and term_name != "无":
            return term_name, _CELL_NORMAL

        if lunar_day == 1:
            prefix = tr("cell.leap_prefix") if is_leap else ""
            return f"{prefix}{MONTH_CN[lunar_month]}", _CELL_NORMAL
        return NUM_CN_MAP.get(str(lunar_day), str(lunar_day)), _CELL_NORMAL

    def get_lunar_cell_text(self, qdate: QDate, lunar=None,
                            legal_raw=_UNSET) -> Tuple[str, str]:
        """
        返回 (显示文本, 单元格类型)。

        命中优先级：公历纪念日 → 农历纪念日 → 除夕 → 法定节日 →
        农历传统节日 → 公历节日 → 节气 → 农历日期。

        公历纪念日匹配放在最前，不依赖 cnlunar，保证无农历库时纯公历
        纪念日仍能显示。lunar / legal_raw 可由 _calc_cell_data 预取
        传入以避免重复查询。
        """
        try:
            name = self._lookup_solar_memorial_name(qdate)
            if name is not None:
                return name, _CELL_MEMORIAL

            if not lunar_mod.HAS_CNLUNAR:
                return self._solar_festival_fallback(qdate)

            if lunar is None:
                lunar = self.get_day_lunar_obj(qdate)
            if not lunar:
                return self._solar_festival_fallback(qdate)

            lunar_month = getattr(lunar, 'lunarMonth', 0)
            lunar_day = getattr(lunar, 'lunarDay', 0)
            is_leap = bool(getattr(lunar, 'isLunarLeapMonth', False))

            name = self._lookup_lunar_memorial_name(
                lunar_month, lunar_day, is_leap)
            if name is not None:
                return name, _CELL_MEMORIAL

            return self._resolve_after_memorial(
                qdate, lunar, lunar_month, lunar_day, is_leap, legal_raw)
        except Exception:
            date_str = qdate.toString('yyyy-MM-dd')
            self._log_exception_once(
                f"get_lunar_cell_text:{date_str}",
                f"解析农历文本失败 date={date_str}")
            return "", _CELL_NORMAL

    @staticmethod
    def _solar_festival_fallback(qdate: QDate) -> Tuple[str, str]:
        solar = SOLAR_FESTIVALS.get((qdate.month(), qdate.day()))
        return (solar, _CELL_NORMAL) if solar else ("", _CELL_NORMAL)

    def get_memorials_for_date(self, qdate: QDate) -> List[str]:
        """
        返回指定日期命中的所有纪念日名称，用于 info_label 全量展示。
        与 get_lunar_cell_text 的区别：后者只取桶内首条用于单元格显示。
        """
        names: List[str] = []

        def _collect(bucket):
            for m in bucket:
                name = m.get("name", "")
                if name:
                    names.append(name)

        _collect(self._memorial_index["solar_year"].get(
            (qdate.month(), qdate.day()), ()))
        _collect(self._memorial_index["solar_week"].get(
            qdate.dayOfWeek(), ()))
        _collect(self._memorial_index["solar_month"].get(qdate.day(), ()))

        if lunar_mod.HAS_CNLUNAR:
            lunar = self.get_day_lunar_obj(qdate)
            if lunar is not None:
                lm = getattr(lunar, "lunarMonth", 0)
                ld = getattr(lunar, "lunarDay", 0)
                is_leap = bool(getattr(lunar, "isLunarLeapMonth", False))
                _collect(self._memorial_index["lunar_year"].get(
                    (lm, ld, is_leap), ()))
                _collect(self._memorial_index["lunar_month"].get(
                    (ld, is_leap), ()))
        return names

    # ---------------- 节假日判断 ----------------

    def is_date_holiday(
        self, qdate: QDate, date_str: Optional[str] = None
    ) -> bool:
        """网络数据优先，其次 chinese_calendar，降级周末判断。"""
        try:
            s_key = date_str or qdate.toString("yyyy-MM-dd")
            if s_key in self.net_holiday_data:
                return self.net_holiday_data[s_key]
            if lunar_mod.HAS_CHINESE_CAL:
                return is_holiday(qdate_to_pydate(qdate))
            return qdate_to_pydate(qdate).weekday() >= 5
        except Exception:
            logger.debug(
                f"is_holiday 查询降级 "
                f"date={date_str or qdate.toString('yyyy-MM-dd')}",
                exc_info=True)
            return False

    def is_weekend_workday(
        self, qdate: QDate, date_str: Optional[str] = None
    ) -> bool:
        """判断是否周末调休工作日。非周末直接 False，防止被误标"班"。"""
        try:
            if qdate.dayOfWeek() not in (6, 7):
                return False
            s_key = date_str or qdate.toString("yyyy-MM-dd")
            if s_key in self.net_holiday_data:
                return self.net_holiday_data[s_key] is False
            if lunar_mod.HAS_CHINESE_CAL:
                return is_workday(qdate_to_pydate(qdate))
            return False
        except Exception:
            logger.debug(
                f"is_workday 查询降级 "
                f"date={date_str or qdate.toString('yyyy-MM-dd')}",
                exc_info=True)
            return False

    def _is_legal_holiday(
        self, qdate: QDate, lunar=None,
        legal_raw=_UNSET, date_str: Optional[str] = None,
    ) -> bool:
        s_key = date_str or qdate.toString("yyyy-MM-dd")
        if s_key in self.net_holiday_data:
            return self.net_holiday_data[s_key]
        if not lunar_mod.HAS_CNLUNAR:
            return False
        if legal_raw is _UNSET:
            if lunar is None:
                lunar = self.get_day_lunar_obj(qdate)
            legal_raw = self._first_legal_holiday_raw(lunar)
        return legal_raw is not None
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
                # 缓存缺失：只补当前这一天，避免在 paint 中遍历整月
                cell = self._put_cell_cache(key, self._calc_cell_data(qdate))

            kind = cell["kind"]
            is_hol = cell["is_hol"]
            is_weekend_work = cell["is_weekend_work"]
            is_legal_hol = cell["is_legal_hol"]
            lunar_text = cell["lunar_text"]

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
            if kind == _CELL_MEMORIAL:
                painter.setPen(self._colors["memorial_orange"])
            elif kind == _CELL_RED:
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
            if kind == _CELL_MEMORIAL:
                dot_color = self._colors["memorial_orange"]
            elif kind == _CELL_RED or is_legal_hol:
                # kind == _CELL_RED：cnlunar 给出节日名（数字也标红）
                # is_legal_hol：网络数据明确节假日，但 cnlunar 无节日名
                #   （典型：cnlunar 数据滞后 / 未安装，靠网络数据兜底）
                dot_color = self._colors["festival_red"]
            if dot_color is not None:
                painter.setBrush(dot_color)
                painter.setPen(self._no_pen)
                # 画了班标签时圆点让位到左上角
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

    def set_net_holiday(self, holiday_data: Dict[str, bool]):
        try:
            # 防御：None / 非 dict 一律按空数据处理，避免污染 self.net_holiday_data
            self.net_holiday_data = (
                holiday_data if isinstance(holiday_data, dict) else {}
            )
            logger.info(f"加载网络节假日数据，共{len(self.net_holiday_data)}条")
            self._invalidate_cell_cache()
            self.update()
        except Exception as e:
            log_exception(f"set_net_holiday 加载节假日数据失败: {e}")

    def _invalidate_cell_cache(self):
        """
        数据变更后作废缓存并重建当前月。

        任何改变 _calc_cell_data 结果的入口（纪念日 / 网络节假日 /
        语言切换 / 未来新增的覆盖规则）都必须调用本方法，而不是直接
        _rebuild_cell_cache —— 后者对已存在的 key 视为"命中"只刷新
        LRU，不会用新数据覆盖旧值。
        """
        self._cell_cache.clear()
        self._rebuild_cell_cache(self.yearShown(), self.monthShown())

    def retranslate_ui(self):
        """语言切换后刷新周几表头 + 缓存文本（lunar_text 含 tr() 结果）。"""
        self.setLocale(QLocale(get_language()))
        self._invalidate_cell_cache()
        self._fix_week_header_color()
        self.update()
