# coding: utf-8
"""考勤统计对话框：周 / 月切换 + 明细表 + 汇总 + CSV 导出。"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from typing import Optional, Sequence

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog,
)

from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import get_logger
from desktop_calendar.core.attendance import (
    AttendanceStore, DayStat,
    STATUS_OK, STATUS_INCOMPLETE, STATUS_ABNORMAL,
    STATUS_ABSENT, STATUS_REST, STATUS_PENDING,
)
from desktop_calendar.ui.theme import ThemeBundle

from .messages import msg_error, msg_info

__all__ = ["AttendanceDialog"]

logger = get_logger()

MODE_WEEK = "week"
MODE_MONTH = "month"

_STATUS_TEXT_KEY = {
    STATUS_OK: "attendance.status_ok",
    STATUS_INCOMPLETE: "attendance.status_incomplete",
    STATUS_ABNORMAL: "attendance.status_abnormal",
    STATUS_ABSENT: "attendance.status_absent",
    STATUS_REST: "attendance.status_rest",
    STATUS_PENDING: "attendance.status_pending",
}

_STATUS_COLOR_KEY = {
    STATUS_OK: "solar_term_text_color",
    STATUS_INCOMPLETE: "workday_orange",
    STATUS_ABNORMAL: "festival_red",
    STATUS_ABSENT: "festival_red",
    STATUS_REST: "normal_lunar_color",
    STATUS_PENDING: "normal_lunar_color",
}

_MARK_LATE = "attendance.mark_late"
_MARK_EARLY = "attendance.mark_early"


def _fmt_duration(minutes) -> str:
    if not minutes:
        return tr("attendance.none")
    h, m = divmod(int(minutes), 60)
    if h and m:
        return tr("attendance.duration_hm").format(h=h, m=m)
    if h:
        return tr("attendance.duration_h").format(h=h)
    return tr("attendance.duration_m").format(m=m)


def _fmt_hours(minutes: Optional[int]) -> str:
    """分钟 → 两位小数小时；None / 0 输出空串，便于 Excel 数值列保持干净。"""
    if not minutes:
        return ""
    return f"{minutes / 60:.2f}"


def _status_text(st: DayStat) -> str:
    """状态文案：迟到 / 早退会覆盖 STATUS_OK 的"正常"。"""
    if st.status == STATUS_OK:
        if st.is_late and st.is_early_leave:
            return tr("attendance.status_late_early")
        if st.is_late:
            return tr("attendance.status_late")
        if st.is_early_leave:
            return tr("attendance.status_early")
        return tr("attendance.status_ok")
    base = tr(_STATUS_TEXT_KEY.get(st.status, "attendance.none"))
    if st.status == STATUS_INCOMPLETE and (st.is_late or st.is_early_leave):
        marks = []
        if st.is_late:
            marks.append(tr(_MARK_LATE))
        if st.is_early_leave:
            marks.append(tr(_MARK_EARLY))
        return tr("attendance.status_with_mark").format(
            base=base, marks="/".join(marks))
    return base


def _status_color(st: DayStat, resolver) -> QColor:
    if st.status == STATUS_OK:
        if st.is_late or st.is_early_leave:
            return QColor(resolver.color("workday_orange"))
        return QColor(resolver.color("solar_term_text_color"))
    return QColor(resolver.color(
        _STATUS_COLOR_KEY.get(st.status, "dialog_text")))


class AttendanceDialog(QDialog):
    def __init__(self, store: AttendanceStore, parent=None,
                 bundle: ThemeBundle = None, mode: str = MODE_WEEK,
                 base_date: Optional[date] = None):
        super().__init__(parent)
        if bundle is None:
            raise ValueError("AttendanceDialog 需要 ThemeBundle")
        self._store = store
        self._r = bundle.resolver
        self._nav_w = bundle.window.nav_btn_width
        self._mode = mode if mode in (MODE_WEEK, MODE_MONTH) else MODE_WEEK
        self._anchor = base_date or QDate.currentDate().toPyDate()

        dlg = bundle.dialog
        self.setWindowTitle(tr("attendance.title"))
        self.resize(*dlg.manage_size)
        # qss_picker = dialog_base + buttons + inputs：本对话框有 QComboBox，
        # 必须带上 inputs 样式，否则深色主题下下拉框回退系统默认。
        # 表格样式内联拼，避免为单个对话框扩 ThemeBundle 的 QssSet 字段。
        self.setStyleSheet(dlg.qss_picker + self._table_qss())

        layout = QVBoxLayout(self)
        mw = dlg.margin_wide
        layout.setContentsMargins(mw, mw, mw, mw)
        layout.setSpacing(dlg.spacing_wide)

        top = QHBoxLayout()
        self.combo_mode = QComboBox()
        self.combo_mode.addItem(tr("attendance.mode_week"), MODE_WEEK)
        self.combo_mode.addItem(tr("attendance.mode_month"), MODE_MONTH)
        idx = self.combo_mode.findData(self._mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)

        # 用 objectName 覆盖 qss_picker 中 QPushButton 的 min-width，
        # 否则 "<" / ">" 会被撑成 75px 宽，与主窗口导航按钮不一致。
        self.btn_prev = QPushButton("<")
        self.btn_prev.setObjectName("att_nav_btn")
        self.btn_prev.setFixedWidth(self._nav_w)
        self.btn_prev.clicked.connect(lambda: self._shift(-1))
        self.btn_next = QPushButton(">")
        self.btn_next.setObjectName("att_nav_btn")
        self.btn_next.setFixedWidth(self._nav_w)
        self.btn_next.clicked.connect(lambda: self._shift(1))

        self.lbl_range = QLabel("")
        self.lbl_range.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top.addWidget(self.combo_mode)
        top.addWidget(self.btn_prev)
        top.addWidget(self.lbl_range, stretch=1)
        top.addWidget(self.btn_next)
        layout.addLayout(top)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            tr("attendance.col_date"),
            tr("attendance.col_weekday"),
            tr("attendance.col_in"),
            tr("attendance.col_out"),
            tr("attendance.col_hours"),
            tr("attendance.col_overtime"),
            tr("attendance.col_status"),
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        header.setHighlightSections(False)
        layout.addWidget(self.table, stretch=1)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setWordWrap(True)
        # 与表格视觉分离：顶部一条细边框 + 上内边距，比直接堆文字更清爽。
        self.lbl_summary.setStyleSheet(
            f"padding-top: 10px;"
            f"border-top: 1px solid {self._r.color('border_color')};"
            f"color: {self._r.color('dialog_text')};"
        )
        layout.addWidget(self.lbl_summary)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_export = QPushButton(tr("attendance.export"))
        self.btn_export.clicked.connect(self._export_csv)
        bottom.addWidget(self.btn_export)
        self.btn_close = QPushButton(tr("btn.close"))
        self.btn_close.clicked.connect(self.accept)
        bottom.addWidget(self.btn_close)
        layout.addLayout(bottom)

        self._refresh()

    # ---------- 样式 ----------
    def _table_qss(self) -> str:
        r = self._r
        nav_w = self._nav_w
        return f"""
        QTableWidget {{
            background: {r.color('bg_main')};
            alternate-background-color: {r.color('input_bg')};
            border: 1px solid {r.color('border_color')};
            border-radius: {r.px('btn_radius_small')};
            color: {r.color('dialog_text')};
        }}
        QHeaderView::section {{
            background: {r.color('bg_main')};
            color: {r.color('dialog_text')};
            border: none;
            border-bottom: 1px solid {r.color('border_color')};
            padding: 8px 4px;
        }}
        QTableWidget::item {{ padding: 4px; }}
        QTableWidget::item:selected {{
            background: {r.color('select_bg')};
            color: {r.color('select_text_color')};
        }}
        QPushButton#att_nav_btn {{
            min-width: {nav_w}px;
            max-width: {nav_w}px;
            padding: 4px 0;
            background: {r.color('btn_bg')};
            color: {r.color('btn_text')};
            border: none;
            border-radius: {r.px('btn_radius')};
        }}
        QPushButton#att_nav_btn:hover {{
            background: {r.color('btn_hover')};
        }}
        QPushButton#att_nav_btn:pressed {{
            background: {r.color('btn_pressed')};
        }}
        """

    # ---------- 交互 ----------
    def _on_mode_changed(self, _idx: int) -> None:
        new_mode = self.combo_mode.currentData() or MODE_WEEK
        if new_mode == self._mode:
            return
        self._mode = new_mode
        if self._mode == MODE_MONTH:
            self._anchor = date(self._anchor.year, self._anchor.month, 1)
        self._refresh()

    def _shift(self, delta: int) -> None:
        if self._mode == MODE_WEEK:
            self._anchor = self._anchor + timedelta(days=7 * delta)
        else:
            y, m = self._anchor.year, self._anchor.month + delta
            while m < 1:
                m += 12
                y -= 1
            while m > 12:
                m -= 12
                y += 1
            self._anchor = date(y, m, 1)
        self._refresh()

    # ---------- 渲染 ----------
    def _refresh(self) -> None:
        if self._mode == MODE_WEEK:
            summary = self._store.week_summary(self._anchor)
            self.lbl_range.setText(tr("attendance.week_range").format(
                start=summary.start.strftime("%Y-%m-%d"),
                end=summary.end.strftime("%Y-%m-%d")))
            self._fill(summary.days)
            line1 = tr("attendance.summary_week").format(
                attended=summary.attended_days,
                complete=summary.complete_days,
                total=_fmt_duration(summary.total_minutes),
                avg=_fmt_duration(summary.avg_minutes))
            line2 = self._abnormal_line(
                summary.total_overtime, summary.late_count,
                summary.early_count)
        else:
            summary = self._store.month_summary(
                self._anchor.year, self._anchor.month)
            self.lbl_range.setText(tr("attendance.month_range").format(
                year=self._anchor.year, month=self._anchor.month))
            self._fill(summary.days)
            line1 = tr("attendance.summary_month").format(
                attended=summary.attended_days,
                workdays=summary.workdays,
                complete=summary.complete_days,
                total=_fmt_duration(summary.total_minutes),
                avg=_fmt_duration(summary.avg_minutes))
            line2 = self._abnormal_line(
                summary.total_overtime, summary.late_count,
                summary.early_count)
        self.lbl_summary.setText(
            line1 if not line2 else f"{line1}\n{line2}")

    @staticmethod
    def _abnormal_line(overtime: int, late: int, early: int) -> str:
        parts = []
        if overtime:
            parts.append(tr("attendance.summary_overtime").format(
                total=_fmt_duration(overtime)))
        if late:
            parts.append(tr("attendance.summary_late").format(count=late))
        if early:
            parts.append(tr("attendance.summary_early").format(count=early))
        return " ｜ ".join(parts)

    def _fill(self, stats) -> None:
        today = date.today()
        self.table.setRowCount(len(stats))
        for row, st in enumerate(stats):
            self._fill_row(row, st, today)

    def _fill_row(self, row: int, st: DayStat, today: date) -> None:
        values = [
            st.day.strftime("%Y-%m-%d"),
            tr(f"weekday.short.{st.day.isoweekday()}"),
            st.in_time or tr("attendance.none"),
            st.out_time or tr("attendance.none"),
            _fmt_duration(st.minutes),
            _fmt_duration(st.overtime_minutes),
            _status_text(st),
        ]
        status_color = _status_color(st, self._r)
        overtime_color = QColor(self._r.color("workday_orange"))
        is_today = st.day == today
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if col == 5 and st.overtime_minutes:
                item.setForeground(overtime_color)
            if col == 6:
                item.setForeground(status_color)
            if is_today:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.table.setItem(row, col, item)

    # ---------- 导出 ----------
    def _export_csv(self) -> None:
        """导出当前视图（周 / 月）为 CSV，Excel 直接可打开。"""
        stats, default_name = self._export_scope()
        path, _ = QFileDialog.getSaveFileName(
            self, tr("attendance.export_title"), default_name,
            tr("attendance.export_filter"))
        if not path:
            return
        try:
            self._write_csv(path, stats)
        except Exception as e:
            logger.exception("导出考勤记录失败: %s", path)
            msg_error(self, tr("msg.error"),
                      tr("attendance.export_failed").format(error=e))
            return
        msg_info(self, tr("msg.success"),
                 tr("attendance.export_success").format(count=len(stats)))

    def _export_scope(self):
        """返回 (当前视图的 DayStat 序列, 默认文件名)。"""
        if self._mode == MODE_WEEK:
            summary = self._store.week_summary(self._anchor)
            default_name = tr("attendance.export_name_week").format(
                start=summary.start.strftime("%Y-%m-%d"),
                end=summary.end.strftime("%Y-%m-%d"))
            return summary.days, default_name
        summary = self._store.month_summary(
            self._anchor.year, self._anchor.month)
        default_name = tr("attendance.export_name_month").format(
            year=self._anchor.year, month=self._anchor.month)
        return summary.days, default_name

    @staticmethod
    def _write_csv(path: str, stats: Sequence[DayStat]) -> None:
        """utf-8-sig：带 BOM，Excel / WPS 双击打开中文不乱码。

        工时 / 加班写两位小数小时（8.50），而非"8小时30分"：
        数值列才能在 Excel 里 SUM/AVERAGE。状态列仍写中文可读文本。
        """
        header = [
            tr("attendance.col_date"),
            tr("attendance.col_weekday"),
            tr("attendance.col_in"),
            tr("attendance.col_out"),
            tr("attendance.csv_col_hours"),
            tr("attendance.csv_col_overtime"),
            tr("attendance.col_status"),
        ]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for st in stats:
                writer.writerow([
                    st.day.strftime("%Y-%m-%d"),
                    tr(f"weekday.short.{st.day.isoweekday()}"),
                    st.in_time or "",
                    st.out_time or "",
                    _fmt_hours(st.minutes),
                    _fmt_hours(st.overtime_minutes),
                    _status_text(st),
                ])