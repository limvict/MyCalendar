"""Selected-day schedule list shown beneath the calendar."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.schedule import ScheduleManager
from ..theme.bundle import LAYOUT

_DEFAULT_DOT = "#4A90D9"
_WEEKDAY_NAMES = ("一", "二", "三", "四", "五", "六", "日")
# 面板最多展开到几行，超过后交给滚动条（计数，不随 UI 缩放）
_MAX_VISIBLE_ROWS = 3


def _weekday_name(value: date) -> str:
    return _WEEKDAY_NAMES[value.weekday()]


def _color_icon(color: str) -> QIcon:
    pixmap = QPixmap(4, 14)
    pixmap.fill(QColor(color or _DEFAULT_DOT))
    return QIcon(pixmap)


class SchedulePanel(QWidget):
    manage_requested = pyqtSignal()
    quick_add_requested = pyqtSignal()
    changed = pyqtSignal()
    save_failed = pyqtSignal(str)

    def __init__(self, manager: ScheduleManager, parent=None):
        super().__init__(parent)
        self.setObjectName("schedule_panel")
        # 普通 QWidget 必须显式开启，否则 #schedule_panel 的背景/边框不绘制
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._manager = manager
        self._date = date.today()
        self._refreshing = False
        self._date_label = QLabel(self)
        self._date_label.setObjectName("schedule_date")
        self._list = QListWidget(self)
        self._list.setMaximumHeight(LAYOUT["schedule_list_max_height"])
        self._list.setMinimumHeight(LAYOUT["schedule_list_min_height"])
        self._list.setIconSize(QSize(*LAYOUT["schedule_list_icon"]))
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setWordWrap(True)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.itemDoubleClicked.connect(lambda _item: self.manage_requested.emit())
        self._manage = QPushButton("管理", self)
        self._manage.setObjectName("manage_schedule")
        self._manage.setToolTip("管理所选日期的日程")
        self._manage.clicked.connect(self.manage_requested)
        self._quick_add = QPushButton("＋", self)
        self._quick_add.setObjectName("quick_add_schedule")
        self._quick_add.setToolTip("快速添加所选日期的全天日程")
        self._quick_add.clicked.connect(self.quick_add_requested)

        header = QHBoxLayout()
        header.addWidget(self._date_label)
        header.addStretch(1)
        header.addWidget(self._quick_add)
        header.addWidget(self._manage)
        layout = QVBoxLayout(self)
        margin_h = LAYOUT["schedule_margin_h"]
        margin_v = LAYOUT["schedule_margin_v"]
        layout.setContentsMargins(margin_h, margin_v, margin_h, margin_v)
        layout.setSpacing(LAYOUT["schedule_panel_spacing"])
        layout.addLayout(header)
        layout.addWidget(self._list)
        self._layout = layout
        self._list_min_h = LAYOUT["schedule_list_min_height"]
        self._list_max_h = LAYOUT["schedule_list_max_height"]
        self.refresh(self._date)

    def apply_theme(self, bundle) -> None:
        self._bundle = bundle
        metrics = bundle.layout
        margin_h = metrics.schedule_margin_h
        margin_v = metrics.schedule_margin_v
        self._layout.setContentsMargins(margin_h, margin_v, margin_h, margin_v)
        self._layout.setSpacing(metrics.schedule_panel_spacing)
        self._list.setIconSize(QSize(*metrics.schedule_list_icon))
        self._list_min_h = metrics.schedule_list_min_height
        self._list_max_h = max(self._list_min_h, metrics.schedule_list_max_height)
        self.setStyleSheet(bundle.qss.schedule_panel)
        self._fit_list_height()

    def _fit_list_height(self) -> None:
        """按实际条目数定高：1 条就一行高，多到上限后交给滚动条。"""
        count = self._list.count()
        if count <= 0:
            self._list.setFixedHeight(self._list_min_h)
            return
        rows = min(count, _MAX_VISIBLE_ROWS)
        needed = 0
        for row in range(rows):
            needed += max(1, self._list.sizeHintForRow(row))
        needed += 2 * self._list.frameWidth() + 2
        self._list.setFixedHeight(max(self._list_min_h, min(self._list_max_h, needed)))

    def refresh(self, selected_date: date) -> None:
        self._date = selected_date
        self._refreshing = True
        self._list.clear()
        try:
            schedules = self._manager.on(selected_date)
        except (OSError, ValueError, TypeError) as error:
            self._date_label.setText(
                f"{selected_date.month:02d}月{selected_date.day:02d}日 "
                f"星期{_weekday_name(selected_date)}"
            )
            self._list.setVisible(True)
            self._list.addItem(f"日程读取失败：{error}")
            self._manage.setEnabled(False)
            self._refreshing = False
            self._fit_list_height()
            return
        self._manage.setEnabled(True)
        count = len(schedules)
        suffix = "暂无日程" if count == 0 else f"{count} 项日程"
        self._date_label.setText(
            f"{selected_date.month:02d}月{selected_date.day:02d}日 "
            f"星期{_weekday_name(selected_date)} · {suffix}"
        )
        self._list.setVisible(bool(schedules))
        if not schedules:
            self._refreshing = False
            return
        for schedule in schedules:
            time_text = schedule.time or "全天"
            item = QListWidgetItem(f"{time_text}  {schedule.title}")
            item.setIcon(_color_icon(schedule.color))
            item.setToolTip(schedule.note or schedule.title)
            item.setData(Qt.ItemDataRole.UserRole, schedule.id)
            if schedule.repeat == "none":
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if schedule.done else Qt.CheckState.Unchecked
                )
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            if schedule.done:
                font = QFont(item.font())
                font.setStrikeOut(True)
                item.setFont(font)
                item.setForeground(QColor(self._bundle.resolver.color("normal_lunar_color")))
            self._list.addItem(item)
        self._refreshing = False
        self._fit_list_height()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self._refreshing:
            return
        schedule_id = item.data(Qt.ItemDataRole.UserRole)
        if not schedule_id:
            return
        try:
            self._manager.toggle_done(schedule_id)
        except OSError as error:
            self.refresh(self._date)
            self.save_failed.emit(str(error))
            return
        self.changed.emit()
