"""Dialog for recording the selected day's mood."""

from __future__ import annotations

from datetime import date

from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from desktop_calendar.config.i18n import tr
from desktop_calendar.core.mood import MOOD_CHOICES, MoodStore
from desktop_calendar.ui.theme import ThemeBundle

from .base import make_button_box
from .messages import msg_error, msg_warn


class MoodDialog(QDialog):
    def __init__(
        self, store: MoodStore, selected_date: date, parent=None, bundle: ThemeBundle = None
    ):
        super().__init__(parent)
        if bundle is None:
            raise ValueError("MoodDialog 需要 ThemeBundle")
        self._store = store
        self._date = selected_date
        self._record = store.get(selected_date)

        self.setWindowTitle(tr("mood.title").format(date=selected_date.isoformat()))
        self.resize(380, 250)
        self.setStyleSheet(bundle.dialog.qss_standard)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            bundle.dialog.margin, bundle.dialog.margin, bundle.dialog.margin, bundle.dialog.margin
        )
        layout.setSpacing(bundle.dialog.spacing)
        layout.addWidget(QLabel(tr("mood.prompt"), self))

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        mood_grid = QGridLayout()
        mood_grid.setSpacing(6)
        self._buttons: dict[str, QPushButton] = {}
        for index, mood in enumerate(MOOD_CHOICES):
            button = QPushButton(tr(f"mood.option.{mood}"), self)
            button.setCheckable(True)
            self._group.addButton(button)
            self._buttons[mood] = button
            mood_grid.addWidget(button, index // 3, index % 3)
            if self._record.get("mood") == mood:
                button.setChecked(True)
        layout.addLayout(mood_grid)

        self._note = QLineEdit(self)
        self._note.setMaxLength(200)
        self._note.setPlaceholderText(tr("mood.note_placeholder"))
        self._note.setText(self._record.get("note", ""))
        self._note.setClearButtonEnabled(True)
        layout.addWidget(self._note)

        actions = QHBoxLayout()
        self._delete_button = QPushButton(tr("mood.delete"), self)
        self._delete_button.setEnabled(bool(self._record))
        self._delete_button.clicked.connect(self._delete)
        actions.addWidget(self._delete_button)
        actions.addStretch(1)
        self._button_box = make_button_box(self, self._save)
        actions.addWidget(self._button_box)
        layout.addLayout(actions)

    def _save(self) -> None:
        selected = self._group.checkedButton()
        if selected is None:
            msg_warn(
                self, tr("mood.title").format(date=self._date.isoformat()), tr("mood.choose_first")
            )
            return
        mood = next(key for key, button in self._buttons.items() if button is selected)
        try:
            self._store.save(self._date, mood, self._note.text())
        except (OSError, ValueError, TypeError) as error:
            msg_error(self, tr("msg.error"), tr("mood.save_failed").format(error=error))
            return
        self.accept()

    def _delete(self) -> None:
        try:
            self._store.delete(self._date)
        except (OSError, ValueError, TypeError) as error:
            msg_error(self, tr("msg.error"), tr("mood.save_failed").format(error=error))
            return
        self.accept()
