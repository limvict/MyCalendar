"""日程提醒弹窗：带 snooze 选项。"""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from desktop_calendar.config.constants import SCHEDULE_REMIND_SNOOZE_OPTIONS
from desktop_calendar.config.i18n import tr
from desktop_calendar.ui.theme import ThemeBundle


def _t(key: str, fallback: str) -> str:
    value = tr(key)
    return fallback if value == key else value


class ScheduleRemindDialog(QDialog):
    """用户选择 snooze 后，通过 self.snooze_minutes 取分钟数；0 = 不 snooze。"""

    def __init__(self, title: str, body: str = "", parent=None, bundle: ThemeBundle | None = None):
        super().__init__(parent)
        self.setWindowTitle(_t("schedule.remind_title", "日程提醒"))
        self.setModal(True)
        self.resize(360, 190)
        self.snooze_minutes = 0

        if bundle is not None:
            self.setStyleSheet(bundle.dialog.qss_standard)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title_label = QLabel(title, self)
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-weight: 700;")
        layout.addWidget(title_label)

        if body:
            body_label = QLabel(body, self)
            body_label.setWordWrap(True)
            layout.addWidget(body_label)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        for minutes in SCHEDULE_REMIND_SNOOZE_OPTIONS:
            btn = QPushButton(_t("schedule.snooze_n", "{n} 分钟后").format(n=minutes), self)
            btn.clicked.connect(lambda _=False, m=minutes: self._choose_snooze(m))
            buttons.addWidget(btn)
        layout.addLayout(buttons)

        dismiss = QPushButton(_t("schedule.dismiss", "知道了"), self)
        dismiss.clicked.connect(self.accept)
        layout.addWidget(dismiss)

    def _choose_snooze(self, minutes: int) -> None:
        self.snooze_minutes = minutes
        self.accept()
