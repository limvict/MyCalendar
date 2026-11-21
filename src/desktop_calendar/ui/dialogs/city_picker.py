# coding: utf-8
"""省份 / 城市选择对话框。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from desktop_calendar.config.constants import WEATHER_PROVINCES
from desktop_calendar.config.i18n import tr
from desktop_calendar.ui.theme import ThemeBundle

from .base import make_button_box

__all__ = ["CityPickerDialog"]


class CityPickerDialog(QDialog):
    city_selected = pyqtSignal(dict)
    search_requested = pyqtSignal()

    def __init__(self, source, parent=None, bundle: ThemeBundle = None):
        super().__init__(parent)
        self._source = source
        self._request_id = 0
        self._loading = False
        self._closed = False

        self.setWindowTitle(tr("weather.city_picker_title"))
        self.resize(360, 190)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        if bundle is not None:
            resolver = bundle.resolver
            self.setStyleSheet(
                bundle.dialog.qss_picker + f"\nQDialog {{ border: 1px solid "
                f"{resolver.color('border_color')}; "
                "background: "
                f"{resolver.color('bg_main')}; }}"
            )

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("weather.province")))
        self.province_combo = QComboBox(self)
        for name, adcode in WEATHER_PROVINCES:
            self.province_combo.addItem(name, adcode)
        layout.addWidget(self.province_combo)

        layout.addWidget(QLabel(tr("weather.city")))
        self.city_combo = QComboBox(self)
        self.city_combo.setEnabled(False)
        layout.addWidget(self.city_combo)

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        search_button = QPushButton(tr("weather.search_city"), self)
        search_button.clicked.connect(self._request_search)
        button_box = make_button_box(self)
        self._ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setEnabled(False)
        bottom_row = QHBoxLayout()
        bottom_row.addWidget(search_button)
        bottom_row.addStretch(1)
        bottom_row.addWidget(button_box)
        layout.addLayout(bottom_row)

        self.province_combo.currentIndexChanged.connect(self._load_selected_province)
        self.city_combo.currentIndexChanged.connect(
            lambda _index: self._ok_button.setEnabled(self.city_combo.currentIndex() >= 0)
        )
        self._load_selected_province()

    def _load_selected_province(self, _index=None) -> None:
        province_index = self.province_combo.currentIndex()
        province = self.province_combo.currentText()
        adcode = self.province_combo.currentData()
        self._request_id += 1
        request_id = self._request_id
        self._loading = True
        self.city_combo.clear()
        self.city_combo.setEnabled(False)
        self._ok_button.setEnabled(False)
        self.status_label.setText(tr("weather.city_loading"))

        list_cities = getattr(self._source, "list_cities", None)
        if province_index < 0 or not callable(list_cities):
            self._finish_error(request_id, tr("weather.city_list_unavailable"))
            return
        try:
            list_cities(
                province,
                adcode,
                lambda cities: self._on_cities_loaded(request_id, cities),
                lambda error: self._finish_error(request_id, error),
            )
        except (OSError, TypeError, ValueError) as error:
            self._finish_error(request_id, str(error))

    def _on_cities_loaded(self, request_id: int, cities: list[dict]) -> None:
        if request_id != self._request_id:
            return
        self._loading = False
        if self._closed:
            self.deleteLater()
            return
        self.city_combo.clear()
        for city in cities:
            if isinstance(city, dict) and isinstance(city.get("name"), str):
                self.city_combo.addItem(city["name"], dict(city))
        self.city_combo.setEnabled(self.city_combo.count() > 0)
        self._ok_button.setEnabled(self.city_combo.count() > 0)
        self.status_label.setText("" if self.city_combo.count() else tr("weather.city_list_empty"))

    def _finish_error(self, request_id: int, error: str) -> None:
        if request_id != self._request_id:
            return
        self._loading = False
        if self._closed:
            self.deleteLater()
            return
        self.city_combo.clear()
        self.city_combo.setEnabled(False)
        self._ok_button.setEnabled(False)
        self.status_label.setText(tr("weather.city_list_error").format(error=error))

    def _request_search(self) -> None:
        self.search_requested.emit()
        self.reject()

    def accept(self) -> None:
        city = self.city_combo.currentData()
        if not isinstance(city, dict):
            return
        self.city_selected.emit(dict(city))
        super().accept()

    def done(self, result: int) -> None:
        self._closed = True
        super().done(result)
        if not self._loading:
            self.deleteLater()
