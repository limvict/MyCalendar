"""Selected-day schedule management dialog."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QDate, Qt, QTime, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ...config.constants import SCHEDULE_COLOR_PRESETS
from ...config.i18n import tr
from ...core.schedule import REPEAT_CHOICES, ScheduleManager
from ...ui.theme import ThemeBundle
from .base import fit_dialog_to_screen


class _ColorSwatches(QWidget):
    def __init__(
        self,
        presets: tuple[str, ...],
        parent=None,
        bundle: ThemeBundle | None = None,
    ):
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._colors = ("",) + tuple(presets)
        self._buttons: list[QPushButton] = []
        border = bundle.resolver.color("today_bg") if bundle is not None else "#333333"
        empty_border = bundle.resolver.color("border_color") if bundle is not None else "#999999"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        scale = bundle.scale_factor if bundle is not None else 1.0
        swatch = max(12, round(22 * scale))
        for index, color in enumerate(self._colors):
            btn = QPushButton(self)
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedSize(swatch, swatch)
            if color:
                btn.setToolTip(color)
                btn.setStyleSheet(
                    f"QPushButton {{ background: {color}; "
                    "border: 2px solid transparent; border-radius: 4px; }"
                    f"QPushButton:checked {{ border-color: {border}; }}"
                )
            else:
                btn.setToolTip(tr("schedule.color_default"))
                btn.setStyleSheet(
                    "QPushButton { background: transparent; "
                    f"border: 2px dashed {empty_border}; "
                    "border-radius: 4px; }"
                    f"QPushButton:checked {{ border-color: {border}; "
                    "border-style: solid; }"
                )
            self._group.addButton(btn, index)
            self._buttons.append(btn)
            layout.addWidget(btn)
        layout.addStretch(1)
        self._buttons[0].setChecked(True)

    def selected_color(self) -> str:
        idx = self._group.checkedId()
        if idx <= 0 or idx >= len(self._colors):
            return ""
        return self._colors[idx]

    def reset(self) -> None:
        self._buttons[0].setChecked(True)

    def set_color(self, color: str) -> None:
        try:
            index = self._colors.index(color or "")
        except ValueError:
            index = 0
        self._buttons[index].setChecked(True)


class ScheduleDialog(QDialog):
    changed = pyqtSignal()

    def __init__(
        self,
        manager: ScheduleManager,
        selected_date: date,
        parent=None,
        *,
        bundle: ThemeBundle | None = None,
    ):
        super().__init__(parent)
        self._manager = manager
        self._date = selected_date
        self._editing_schedule_id: str | None = None
        self._refreshing = False
        self.setWindowTitle(f"日程管理 - {selected_date:%Y-%m-%d}")
        if bundle is not None:
            self.setStyleSheet(bundle.dialog.qss_picker)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(("●", "标题", "时间", "状态"))
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 28)
        self._table.setSortingEnabled(True)
        self._table.itemSelectionChanged.connect(self._update_done_enabled)
        self._table.itemChanged.connect(self._on_status_changed)
        self._table.cellDoubleClicked.connect(lambda *_args: self._edit_selected())

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("在所选日期内搜索标题或备注…")
        self._search.setToolTip("仅搜索下方所选日期的日程")
        self._scope_label = QLabel(f"列表与搜索范围：{selected_date:%Y-%m-%d} 当天", self)
        self._scope_label.setWordWrap(True)
        self._status_filter = QComboBox(self)
        self._status_filter.addItem("全部", "all")
        self._status_filter.addItem("未完成", "open")
        self._status_filter.addItem("已完成", "done")
        self._search.textChanged.connect(self._apply_filter)
        self._status_filter.currentIndexChanged.connect(self._apply_filter)

        self._title = QLineEdit(self)
        self._title.setPlaceholderText("日程标题")
        self._date_edit = QDateEdit(
            QDate(selected_date.year, selected_date.month, selected_date.day), self
        )
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        self._time = QTimeEdit(QTime(9, 0), self)
        self._time.setDisplayFormat("HH:mm")
        self._all_day = QCheckBox("全天", self)
        self._all_day.toggled.connect(self._time.setDisabled)
        self._repeat = QComboBox(self)
        for repeat, label in zip(
            REPEAT_CHOICES, ("不重复", "每天", "每周", "每月", "每年"), strict=True
        ):
            self._repeat.addItem(label, repeat)
        self._remind = QSpinBox(self)
        self._remind.setRange(0, 1440)
        self._remind.setSuffix(" 分钟前提醒")
        remind_width = round(128 * (bundle.scale_factor if bundle else 1.0))
        self._remind.setMinimumWidth(max(80, remind_width))
        self._note = QLineEdit(self)
        self._note.setPlaceholderText("备注（可选）")
        self._add_button = QPushButton("添加", self)
        self._save_edit_button = QPushButton("保存修改", self)
        self._cancel_edit_button = QPushButton("取消编辑", self)
        self._edit_button = QPushButton("编辑选中项", self)
        self._remove_button = QPushButton("删除选中项", self)
        self._done_button = QPushButton("切换完成状态", self)
        self._close_button = QPushButton("关闭", self)
        self._colors = _ColorSwatches(SCHEDULE_COLOR_PRESETS, self, bundle)

        form = QGridLayout()
        form.setColumnStretch(1, 1)
        form.setColumnStretch(2, 1)
        form.setColumnStretch(3, 1)
        form.setColumnStretch(4, 1)
        form.setColumnStretch(6, 1)
        form.setColumnStretch(7, 1)
        form.addWidget(QLabel("标题"), 0, 0)
        form.addWidget(self._title, 0, 1, 1, 4)
        form.addWidget(QLabel("日期"), 0, 5)
        form.addWidget(self._date_edit, 0, 6, 1, 2)
        form.addWidget(QLabel("时间"), 1, 0)
        form.addWidget(self._time, 1, 1)
        form.addWidget(self._all_day, 1, 2)
        form.addWidget(QLabel("重复"), 1, 3)
        form.addWidget(self._repeat, 1, 4)
        form.addWidget(QLabel("提醒"), 1, 5)
        form.addWidget(self._remind, 1, 6, 1, 2)
        form.addWidget(QLabel("备注"), 2, 0)
        form.addWidget(self._note, 2, 1, 1, 7)
        form.addWidget(self._add_button, 0, 8, 3, 1)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel(tr("schedule.color"), self))
        color_row.addWidget(self._colors, 1)

        actions = QHBoxLayout()
        actions.addWidget(self._remove_button)
        actions.addWidget(self._done_button)
        actions.addWidget(self._edit_button)
        actions.addStretch(1)
        actions.addWidget(self._close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._scope_label)
        search_row = QHBoxLayout()
        search_row.addWidget(self._search, 1)
        search_row.addWidget(self._status_filter)
        layout.addLayout(search_row)
        layout.addWidget(self._table, 1)
        layout.addLayout(form)
        layout.addLayout(color_row)
        self._save_edit_button.hide()
        self._cancel_edit_button.hide()
        edit_actions = QHBoxLayout()
        edit_actions.addWidget(self._save_edit_button)
        edit_actions.addWidget(self._cancel_edit_button)
        edit_actions.addStretch(1)
        layout.addLayout(edit_actions)
        layout.addLayout(actions)

        self._add_button.clicked.connect(self._add_schedule)
        self._save_edit_button.clicked.connect(self._save_edit)
        self._cancel_edit_button.clicked.connect(self._cancel_edit)
        self._edit_button.clicked.connect(self._edit_selected)
        self._remove_button.clicked.connect(self._remove_schedule)
        self._done_button.clicked.connect(self._toggle_done)
        self._close_button.clicked.connect(self.accept)
        self._done_button.setEnabled(False)
        self._refresh()
        fit_dialog_to_screen(self, (800, 560), minimum_size=(680, 480))

    def _refresh(self) -> None:
        schedules = self._manager.on(self._date)
        self._refreshing = True
        self._table.blockSignals(True)
        self._table.setSortingEnabled(False)
        try:
            self._table.setRowCount(len(schedules))
            for row, schedule in enumerate(schedules):
                color_item = QTableWidgetItem("●")
                color = QColor(schedule.color or "#4A90D9")
                color_item.setForeground(color if color.isValid() else QColor("#4A90D9"))
                self._table.setItem(row, 0, color_item)

                title = QTableWidgetItem(schedule.title)
                title.setData(Qt.ItemDataRole.UserRole, schedule.id)
                title.setData(Qt.ItemDataRole.UserRole + 1, schedule.repeat == "none")
                title.setToolTip(schedule.note)
                self._table.setItem(row, 1, title)
                self._table.setItem(row, 2, QTableWidgetItem(schedule.time or "全天"))
                status = QTableWidgetItem("已完成" if schedule.done else "未完成")
                status.setData(Qt.ItemDataRole.UserRole, schedule.id)
                if schedule.repeat == "none":
                    status.setFlags(status.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    status.setCheckState(
                        Qt.CheckState.Checked if schedule.done else Qt.CheckState.Unchecked
                    )
                self._table.setItem(row, 3, status)
        finally:
            self._table.setSortingEnabled(True)
            self._table.sortItems(2, Qt.SortOrder.AscendingOrder)
            self._table.blockSignals(False)
            self._refreshing = False
        self._apply_filter()
        self._update_done_enabled()

    def _update_done_enabled(self) -> None:
        row = self._table.currentRow()
        item = self._table.item(row, 1) if row >= 0 else None
        self._done_button.setEnabled(
            item is not None and bool(item.data(Qt.ItemDataRole.UserRole + 1))
        )
        self._edit_button.setEnabled(item is not None)
        self._done_button.setText("撤销完成" if self._selected_done() else "标记完成")

    def _selected_done(self) -> bool:
        row = self._table.currentRow()
        item = self._table.item(row, 3) if row >= 0 else None
        return bool(item and item.checkState() == Qt.CheckState.Checked)

    def _on_status_changed(self, item: QTableWidgetItem) -> None:
        if self._refreshing or item.column() != 3:
            return
        schedule_id = item.data(Qt.ItemDataRole.UserRole)
        if not schedule_id:
            return
        try:
            self._manager.toggle_done(schedule_id)
        except OSError as error:
            self._show_save_error(error)
        self._refresh()

    def _apply_filter(self, *_args) -> None:
        query = self._search.text().strip().casefold()
        status_filter = self._status_filter.currentData()
        for row in range(self._table.rowCount()):
            title = self._table.item(row, 1)
            status = self._table.item(row, 3)
            text = " ".join(
                (title.text() if title else "", title.toolTip() if title else "")
            ).casefold()
            done = bool(status and status.checkState() == Qt.CheckState.Checked)
            matches_status = (
                status_filter == "all"
                or status_filter == "done"
                and done
                or status_filter == "open"
                and not done
            )
            self._table.setRowHidden(row, not matches_status or bool(query and query not in text))

    def _edit_selected(self) -> None:
        schedule_id = self._selected_schedule_id()
        if schedule_id is None:
            return
        schedule = next((item for item in self._manager.all() if item.id == schedule_id), None)
        if schedule is None:
            return
        self._editing_schedule_id = schedule_id
        self._title.setText(schedule.title)
        self._date_edit.setDate(QDate.fromString(schedule.date, "yyyy-MM-dd"))
        self._all_day.setChecked(not schedule.time)
        if schedule.time:
            self._time.setTime(QTime.fromString(schedule.time, "HH:mm"))
        self._repeat.setCurrentIndex(self._repeat.findData(schedule.repeat))
        self._remind.setValue(schedule.remind_minutes)
        self._note.setText(schedule.note)
        self._colors.set_color(schedule.color)
        self._add_button.hide()
        self._save_edit_button.show()
        self._cancel_edit_button.show()

    def _save_edit(self) -> None:
        if self._editing_schedule_id is None:
            return
        title = self._title.text().strip()
        if not title:
            QMessageBox.warning(self, "提示", "请输入日程标题。")
            return
        try:
            self._manager.update(
                self._editing_schedule_id,
                title=title,
                date=self._date_edit.date().toString("yyyy-MM-dd"),
                time="" if self._all_day.isChecked() else self._time.time().toString("HH:mm"),
                repeat=self._repeat.currentData(),
                remind_minutes=self._remind.value(),
                note=self._note.text().strip(),
                color=self._colors.selected_color(),
            )
        except (OSError, ValueError, TypeError) as error:
            self._show_save_error(error)
            return
        self._cancel_edit()
        self._refresh()
        self.changed.emit()

    def _cancel_edit(self) -> None:
        self._editing_schedule_id = None
        self._title.clear()
        self._note.clear()
        self._colors.reset()
        self._date_edit.setDate(QDate(self._date.year, self._date.month, self._date.day))
        self._time.setTime(QTime(9, 0))
        self._all_day.setChecked(False)
        self._repeat.setCurrentIndex(0)
        self._remind.setValue(0)
        self._add_button.show()
        self._save_edit_button.hide()
        self._cancel_edit_button.hide()

    def _selected_schedule_id(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 1)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _show_save_error(self, error: Exception) -> None:
        QMessageBox.critical(self, "保存失败", f"无法保存日程：{error}")

    def _add_schedule(self) -> None:
        title = self._title.text().strip()
        if not title:
            QMessageBox.warning(self, "提示", "请输入日程标题。")
            return
        try:
            self._manager.add(
                title=title,
                date=self._date_edit.date().toString("yyyy-MM-dd"),
                time="" if self._all_day.isChecked() else self._time.time().toString("HH:mm"),
                repeat=self._repeat.currentData(),
                remind_minutes=self._remind.value(),
                note=self._note.text().strip(),
                color=self._colors.selected_color(),
            )
        except (OSError, ValueError, TypeError) as error:
            self._show_save_error(error)
            return
        self._title.clear()
        self._note.clear()
        self._colors.reset()
        self._refresh()
        self.changed.emit()

    def _remove_schedule(self) -> None:
        schedule_id = self._selected_schedule_id()
        if schedule_id is None:
            return
        try:
            self._manager.remove(schedule_id)
        except (OSError, ValueError, TypeError) as error:
            self._show_save_error(error)
            return
        self._refresh()
        self.changed.emit()

    def _toggle_done(self) -> None:
        schedule_id = self._selected_schedule_id()
        if schedule_id is None:
            return
        try:
            self._manager.toggle_done(schedule_id)
        except (OSError, ValueError, TypeError) as error:
            self._show_save_error(error)
            return
        self._refresh()
        self.changed.emit()
