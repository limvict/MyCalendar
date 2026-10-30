# coding: utf-8
"""纪念日相关对话框：
- AddMemorialDialog     : 新增 / 编辑单个纪念日
- MemorialDialog        : 纪念日列表管理
- MemorialRemindDialog  : 提醒弹窗
"""
import copy
import calendar
from datetime import date
from typing import Any
import time
from PyQt6.QtCore import Qt,QDate
from PyQt6.QtWidgets import (
    QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QCheckBox, QSpinBox, QListWidget, QListWidgetItem, QPushButton,
    QComboBox, QRadioButton, QButtonGroup,
)

from desktop_calendar.core.memorial import (
    REPEAT_YEAR, REPEAT_MONTH, REPEAT_WEEK, REPEAT_ONCE,
    normalize_memorial, get_next_memorial_date,
)
from desktop_calendar.config.i18n import tr
from desktop_calendar.config.constants import REFERENCE_LEAP_YEAR
from desktop_calendar.config.manager import get_logger
from desktop_calendar.ui.theme import ThemeBundle

from .messages import msg_info, msg_warn
from .base import (
    RetranslatableDialog, make_button_box, retranslate_button_box,
)

logger = get_logger()

__all__ = [
    "AddMemorialDialog", "MemorialDialog", "MemorialRemindDialog",
]

_NO_NEXT_DATE_RANK = 10**6


# ===================== 新增/编辑弹窗 =====================
class AddMemorialDialog(RetranslatableDialog, QDialog):
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
        layout.setContentsMargins(dlg.margin, dlg.margin, dlg.margin, dlg.margin)
        layout.setSpacing(dlg.spacing)

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText(tr("memorial.name_placeholder"))

        self.radio_solar = QRadioButton(tr("memorial.solar"))
        self.radio_lunar = QRadioButton(tr("memorial.lunar"))
        self.radio_solar.setChecked(True)
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self.radio_solar)
        self._type_group.addButton(self.radio_lunar)

        self.chk_leap = QCheckBox(tr("memorial.leap"))
        self.chk_leap.setEnabled(False)
        self.radio_solar.toggled.connect(self._on_type_changed)
        self.radio_lunar.toggled.connect(self._on_type_changed)

        self.combo_repeat = QComboBox()
        self.combo_repeat.addItem(tr("memorial.repeat_year"), REPEAT_YEAR)
        self.combo_repeat.addItem(tr("memorial.repeat_month"), REPEAT_MONTH)
        self.combo_repeat.addItem(tr("memorial.repeat_week"), REPEAT_WEEK)
        self.combo_repeat.addItem(tr("memorial.repeat_once"), REPEAT_ONCE)
        self.combo_repeat.currentIndexChanged.connect(self._update_day_range)

        self.spin_month = QSpinBox()
        self.spin_month.setRange(1, 12)
        self.spin_month.setValue(1)

        self.spin_day = QSpinBox()
        self.spin_day.setRange(1, 31)
        self.spin_day.setValue(1)

        self.spin_advance = QSpinBox()
        self.spin_advance.setRange(0, 30)
        self.spin_advance.setValue(3)

        self.chk_enabled = QCheckBox(tr("memorial.enabled"))
        self.chk_enabled.setChecked(True)

        self.lbl_name = QLabel(tr("memorial.name"))
        self.lbl_repeat = QLabel(tr("memorial.repeat"))
        self.lbl_month = QLabel(tr("memorial.month"))
        self.lbl_day = QLabel(tr("memorial.day"))
        self.lbl_advance = QLabel(tr("memorial.advance"))

        self.spin_year = QSpinBox()
        self.spin_year.setRange(1900, 2100)
        self.spin_year.setValue(QDate.currentDate().year())
        self.lbl_year = QLabel(tr("memorial.year"))

        for w in (self.lbl_name, self.edit_name, self.radio_solar,
                  self.radio_lunar, self.chk_leap, self.lbl_repeat,
                  self.combo_repeat, self.lbl_year, self.spin_year,
                  self.lbl_month, self.spin_month,
                  self.lbl_day, self.spin_day, self.lbl_advance,
                  self.spin_advance, self.chk_enabled):
            layout.addWidget(w)

        self._btn_box = make_button_box(self, on_accept=self._on_accept)
        layout.addWidget(self._btn_box)
        self._update_day_range()
        self.retranslate_ui()

    def retranslate_ui(self):
        self.setWindowTitle(tr("memorial.title_new"))
        self.edit_name.setPlaceholderText(tr("memorial.name_placeholder"))
        self.lbl_name.setText(tr("memorial.name"))
        self.radio_solar.setText(tr("memorial.solar"))
        self.radio_lunar.setText(tr("memorial.lunar"))
        self.chk_leap.setText(tr("memorial.leap"))
        self.lbl_repeat.setText(tr("memorial.repeat"))
        self.lbl_month.setText(tr("memorial.month"))
        self.lbl_day.setText(tr("memorial.day"))
        self.lbl_advance.setText(tr("memorial.advance"))
        self.chk_enabled.setText(tr("memorial.enabled"))

        for i, key in enumerate((
                "memorial.repeat_year", "memorial.repeat_month",
                "memorial.repeat_week", "memorial.repeat_once")):
            self.combo_repeat.setItemText(i, tr(key))
        self.lbl_year.setText(tr("memorial.year"))

        if self.combo_repeat.currentData() == REPEAT_WEEK:
            self.spin_day.setSuffix(tr("memorial.weekday_suffix"))
        else:
            self.spin_day.setSuffix("")
        retranslate_button_box(self._btn_box)

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
            self.spin_day.setMaximum(31)
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
            year, month, day = (self.spin_year.value(),
                                self.spin_month.value(),
                                self.spin_day.value())
            try:
                last_day = calendar.monthrange(year, month)[1]
            except Exception:
                last_day = 28
            if day > last_day:
                msg_warn(self, tr("msg.hint"),
                         tr("memorial.warn_once_date").format(
                             year=year, month=month, day=day,
                             max_day=last_day))
                return
        
        elif repeat_type == REPEAT_YEAR:
            month, day = self.spin_month.value(), self.spin_day.value()
            if is_solar:
                _, last_day = calendar.monthrange(REFERENCE_LEAP_YEAR, month)
                if day > last_day:
                    msg_warn(self, tr("msg.hint"),
                             tr("memorial.warn_solar_day").format(
                                 month=month, day=day, max_day=last_day))
                    return
            else:
                if day > 30:
                    msg_warn(self, tr("msg.hint"), tr("memorial.warn_lunar_day_max"))
                    return
                if self.chk_leap.isChecked():
                    reply = QMessageBox.question(
                        self, tr("msg.hint"), tr("memorial.warn_leap_rare"),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes)
                    if reply != QMessageBox.StandardButton.Yes:
                        return
        elif repeat_type == REPEAT_MONTH:
            day = self.spin_day.value()
            if is_solar:
                if day > 28:
                    reply = QMessageBox.question(
                        self, tr("msg.hint"),
                        tr("memorial.warn_day_overflow").format(day=day),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes)
                    if reply != QMessageBox.StandardButton.Yes:
                        return
            elif day > 30:
                msg_warn(self, tr("msg.hint"),
                         tr("memorial.warn_lunar_day_max_short"))
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
            self.chk_leap.setChecked(
                bool(data.get("isleap", False)) if typ == "lunar" else False)
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


# ===================== 管理弹窗 =====================
class MemorialDialog(RetranslatableDialog, QDialog):
    def __init__(self, memorial_list, parent=None, bundle: ThemeBundle = None):
        super().__init__(parent)
        if bundle is None:
            raise ValueError("MemorialDialog 需要 ThemeBundle")
        self._bundle = bundle
        self.memorial_list = copy.deepcopy(memorial_list)

        dlg = self._bundle.dialog
        self.setWindowTitle(tr("memorial.title_manage"))
        self.resize(*dlg.manage_size)
        self.setStyleSheet(dlg.qss_manage)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(dlg.margin, dlg.margin, dlg.margin, dlg.margin)
        layout.setSpacing(dlg.spacing)

        self.list_widget = QListWidget()
        self.refresh_list()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton(tr("btn.add"))
        self.btn_edit = QPushButton(tr("btn.edit"))
        self.btn_del = QPushButton(tr("btn.delete"))
        self.btn_all_enable = QPushButton(tr("btn.all_enable"))
        self.btn_all_disable = QPushButton(tr("btn.all_disable"))
        for b in (self.btn_add, self.btn_edit, self.btn_del,
                  self.btn_all_enable, self.btn_all_disable):
            btn_layout.addWidget(b)
        layout.addLayout(btn_layout)

        self._btn_box = make_button_box(self)
        layout.addWidget(self._btn_box)

        self.btn_add.clicked.connect(self.add_item)
        self.btn_edit.clicked.connect(self.edit_item)
        self.btn_del.clicked.connect(self.del_item)
        self.btn_all_enable.clicked.connect(self.batch_enable_all)
        self.btn_all_disable.clicked.connect(self.batch_disable_all)
        self.retranslate_ui()

    def retranslate_ui(self):
        self.setWindowTitle(tr("memorial.title_manage"))
        self.btn_add.setText(tr("btn.add"))
        self.btn_edit.setText(tr("btn.edit"))
        self.btn_del.setText(tr("btn.delete"))
        self.btn_all_enable.setText(tr("btn.all_enable"))
        self.btn_all_disable.setText(tr("btn.all_disable"))
        retranslate_button_box(self._btn_box)

        if self.list_widget.count() != len(self.memorial_list):
            row = self.list_widget.currentRow()
            self.refresh_list()
            if 0 <= row < self.list_widget.count():
                self.list_widget.setCurrentRow(row)
            return
        repeat_name_map = self._build_repeat_name_map()
        for row, item in enumerate(self.memorial_list):
            widget_item = self.list_widget.item(row)
            if widget_item is not None:
                widget_item.setText(self._format_item_text(item, repeat_name_map))

    def _sort_by_date(self):
        """按"启用优先 + 下次发生日期最近优先"排序。

        每条纪念日调一次 get_next_memorial_date；农历纪念日会触发
        _build_lunar_index(ly)，首次打开对话框且 LRU 未预热时可能慢。
        耗时超 500ms 记 warning（根因在主窗口预热范围，本轮不改）；
        单条失败（数据损坏 / cnlunar 异常）排到末尾并记 warning，
        不让一条坏数据阻断整个管理对话框打开。

        normalized=False 是有意为之：本方法在 UI 边界，memorial_list
        可能被外部工具写入未归一化数据（缺 repeat_type 等字段）。
        normalize_memorial 开销微秒级，安全 > 微优化。
        """
        today = date.today()
        t0 = time.monotonic()
        failed_names = []

        def _sort_key(item: dict):
            disabled_rank = 0 if item.get("enabled", True) else 1
            try:
                target = get_next_memorial_date(
                    item, today, include_base=True, normalized=False)
            except Exception:
                failed_names.append(item.get("name") or "<unnamed>")
                logger.debug(
                    "纪念日排序时计算下次日期失败: %r", item, exc_info=True)
                target = None
            if target is None:
                return (disabled_rank, _NO_NEXT_DATE_RANK)
            return (disabled_rank, (target - today).days)

        self.memorial_list.sort(key=_sort_key)

        elapsed_ms = (time.monotonic() - t0) * 1000
        if elapsed_ms > 500:
            logger.warning(
                "纪念日排序耗时 %.1fms（%d 条），农历索引可能未预热",
                elapsed_ms, len(self.memorial_list))
        if failed_names:
            logger.warning(
                "纪念日排序时 %d 条无法计算下次日期（已排到末尾）: %s",
                len(failed_names), ", ".join(failed_names[:5]))

    @staticmethod
    def _clamp_weekday(day: Any) -> int:
        try:
            return max(1, min(7, int(day)))
        except (TypeError, ValueError):
            return 1

    def _format_item_text(self, item: dict, repeat_name_map: dict) -> str:
        tname = (tr("memorial.manage.type_solar")
                 if item.get("type") == "solar"
                 else tr("memorial.manage.type_lunar"))
        leap = tr("memorial.manage.leap_prefix") if item.get("isleap", False) else ""
        advance = item.get("advance_days", 0)
        status_text = (tr("memorial.manage.status_enabled")
                       if item.get("enabled", True)
                       else tr("memorial.manage.status_disabled"))
        repeat = repeat_name_map.get(
            item.get("repeat_type", REPEAT_YEAR),
            tr("memorial.manage.repeat_prefix_year"))

        if item.get("repeat_type") == REPEAT_WEEK:
            wd = self._clamp_weekday(item.get("day", 1))
            week_key = f"weekday.short.{wd}"
            week_text = tr(week_key)
            if week_text == week_key:
                week_text = str(wd)
            date_text = tr("memorial.manage.week_fmt").format(week=week_text)
        elif item.get("repeat_type") == REPEAT_ONCE:
            date_text = tr("memorial.manage.once_date_fmt").format(
                year=item.get("year", REFERENCE_LEAP_YEAR),
                month=item.get("month", 1),
                day=item.get("day", 1))
        else:
            date_text = tr("memorial.manage.date_fmt").format(
                month=item.get("month", 1), day=item.get("day", 1))

        # 类型 + 闰月前缀 + 日期由语言模板拼装：不同语言对空格 /
        # 分隔符的需求不同（中文零间距、英文需空格），硬拼会得到
        # "LunarLeap4/15" 这种粘连结果。
        type_date = tr("memorial.manage.type_date_fmt").format(
            type=tname, leap=leap, date=date_text)

        display_name = item.get("name") or tr("memorial.default_name")
        return (
            f"{status_text} | {display_name} | {repeat} | "
            f"{type_date} | "
            f"{tr('memorial.manage.advance_fmt').format(advance=advance)}")

    def _find_row_by_item(self, target: dict) -> int | None:
        for row, item in enumerate(self.memorial_list):
            if item == target:
                return row
        return None

    @staticmethod
    def _build_repeat_name_map() -> dict:
        return {
            REPEAT_YEAR: tr("memorial.manage.repeat_prefix_year"),
            REPEAT_MONTH: tr("memorial.manage.repeat_prefix_month"),
            REPEAT_WEEK: tr("memorial.manage.repeat_prefix_week"),
            REPEAT_ONCE: tr("memorial.manage.repeat_prefix_once"),
        }

    def refresh_list(self):
        self.list_widget.clear()
        self.memorial_list = [
            m for m in self.memorial_list if isinstance(m, dict)]
        self._sort_by_date()
        repeat_name_map = self._build_repeat_name_map()
        for item in self.memorial_list:
            QListWidgetItem(
                self._format_item_text(item, repeat_name_map), self.list_widget)

    def add_item(self):
        dlg = AddMemorialDialog(self, bundle=self._bundle)
        try:
            if not dlg.exec():
                return
            new_item = dlg.get_data()
        finally:
            dlg.deleteLater()
        self.memorial_list.append(new_item)
        self.refresh_list()
        row = self._find_row_by_item(new_item)
        if row is not None:
            self.list_widget.setCurrentRow(row)

    def edit_item(self):
        row = self.list_widget.currentRow()
        if row < 0:
            msg_info(self, tr("msg.hint"), tr("memorial.manage.select_first"))
            return
        dlg = AddMemorialDialog(self, bundle=self._bundle)
        try:
            dlg.load_data(self.memorial_list[row])
            if not dlg.exec():
                return
            edited = dlg.get_data()
        finally:
            dlg.deleteLater()
        self.memorial_list[row] = edited
        self.refresh_list()
        new_row = self._find_row_by_item(edited)
        if new_row is not None:
            self.list_widget.setCurrentRow(new_row)

    def del_item(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        reply = QMessageBox.question(
            self, tr("memorial.manage.confirm_delete_title"),
            tr("memorial.confirm_delete"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
           return
        del self.memorial_list[row]
        self.refresh_list()
        # refresh_list 会重排序，原 row 位置不一定还是同一条。这里选择
        # "选中原索引位置（或新的最后一条）"——与文件管理器等常见列表
        # 的删除行为一致：用户连按删除时焦点不会跳到列表顶部。
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(
                min(row, self.list_widget.count() - 1))

    def batch_enable_all(self):
        if not self.memorial_list:
            msg_info(self, tr("msg.hint"), tr("memorial.manage.empty"))
            return
        reply = QMessageBox.question(
            self, tr("msg.confirm"), tr("memorial.manage.confirm_enable_all"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            for item in self.memorial_list:
                item["enabled"] = True
            self.refresh_list()

    def batch_disable_all(self):
        if not self.memorial_list:
            msg_info(self, tr("msg.hint"), tr("memorial.manage.empty"))
            return
        reply = QMessageBox.question(
            self, tr("msg.confirm"), tr("memorial.manage.confirm_disable_all"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            for item in self.memorial_list:
                item["enabled"] = False
            self.refresh_list()

    def get_result(self):
        return self.memorial_list


# ===================== 提醒弹窗 =====================
class MemorialRemindDialog(RetranslatableDialog, QDialog):
    def __init__(self, memorial_list, parent=None, bundle: ThemeBundle = None):
        super().__init__(parent)
        if bundle is None:
            raise ValueError("MemorialRemindDialog 需要 ThemeBundle")
        self._bundle = bundle

        dlg = self._bundle.dialog
        r = self._bundle.resolver

        self.setWindowTitle(tr("memorial.remind_title"))
        self.resize(*dlg.remind_size)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(dlg.qss_remind)

        layout = QVBoxLayout(self)
        mw = dlg.margin_wide
        layout.setContentsMargins(mw, mw - 2, mw, mw - 2)
        layout.setSpacing(dlg.spacing_wide)

        self.title_label = QLabel(tr("memorial.remind_heading"))
        self.title_label.setStyleSheet(
            f"font-size:{dlg.title_font_size}px;"
            f"font-weight:bold;color:{r.color('dialog_text')};")
        layout.addWidget(self.title_label)

        content_text = "\n".join(f"• {line}" for line in memorial_list)
        orange = r.color("memorial_orange")
        self.content_label = QLabel(content_text)
        # 内容含用户自由输入的纪念日名称，必须禁 HTML 解析：
        # 否则名称里的 <b>/<img> 会被 QLabel 当富文本渲染。
        self.content_label.setTextFormat(Qt.TextFormat.PlainText)
        self.content_label.setStyleSheet(
            f"font-size:{dlg.content_font_size}px;"
            f"color:{orange};background:transparent;")
        self.content_label.setWordWrap(True)
        layout.addWidget(self.content_label)
        layout.addStretch(1)

        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton(tr("memorial.remind_ok"))
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)
        self.retranslate_ui()

    def retranslate_ui(self):
        self.setWindowTitle(tr("memorial.remind_title"))
        self.title_label.setText(tr("memorial.remind_heading"))
        self.btn_ok.setText(tr("memorial.remind_ok"))