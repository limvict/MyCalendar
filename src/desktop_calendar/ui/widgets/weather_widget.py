"""Compact weather display with a saved city selector."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config.constants import (
    WEATHER_CITY_DEFAULT,
    WEATHER_ENABLED_DEFAULT,
    WEATHER_LAT_DEFAULT,
    WEATHER_LON_DEFAULT,
    WEATHER_REFRESH_MINUTES_DEFAULT,
)
from ...utils.logging_setup import get_logger
from ..dialogs.city_picker import CityPickerDialog
from ..info_panel import format_weather
from ..theme.bundle import LAYOUT
from .elided_label import ElidedLabel
from .weather_cities import MAX_CITIES, city_key, valid_city
from .weather_icons import weather_icon_for

logger = get_logger()


class WeatherWidget(QWidget):
    def __init__(self, source, cfg, parent=None):
        super().__init__(parent)
        self.setObjectName("weather_panel")
        # 普通 QWidget 必须显式开启，否则 #weather_panel 的背景/边框不绘制
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._source = source
        self._cfg = cfg
        self._pending: set[tuple[str, float, float]] = set()
        self._active_key: tuple[str, float, float] | None = None
        self._has_weather = False
        self._stopped = False
        self._adding_city = False
        self._bundle = None
        self._cities = self._load_cities()
        self._current_city_index = self._selected_city_index()
        self._swipe_start = None

        self._btn_previous = QPushButton("‹", self)
        self._btn_previous.setObjectName("weather_nav")
        self._btn_previous.setFixedWidth(LAYOUT["weather_nav_width"])
        self._btn_previous.setToolTip("上一个城市")

        self._city_name = ElidedLabel(self)
        self._city_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._city_name.setObjectName("weather_city_name")
        self._city_name.setToolTip("左右滑动或使用箭头切换城市")

        self._city_pages = QLabel(self)
        self._city_pages.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._city_pages.setObjectName("weather_city_pages")

        self._btn_next = QPushButton("›", self)
        self._btn_next.setObjectName("weather_nav")
        self._btn_next.setFixedWidth(LAYOUT["weather_nav_width"])
        self._btn_next.setToolTip("下一个城市")

        self._btn_add_city = QPushButton("+", self)
        self._btn_add_city.setObjectName("weather_add")
        self._btn_add_city.setFixedWidth(LAYOUT["weather_action_width"])
        self._btn_add_city.setToolTip("添加城市")

        self._btn_remove_city = QPushButton("−", self)
        self._btn_remove_city.setObjectName("weather_remove")
        self._btn_remove_city.setFixedWidth(LAYOUT["weather_action_width"])
        self._btn_remove_city.setToolTip("删除当前城市")

        city_row = QHBoxLayout()
        self._city_row = city_row
        city_row.setContentsMargins(0, 0, 0, 0)
        city_row.setSpacing(LAYOUT["weather_row_spacing"])
        city_row.addWidget(self._btn_previous)
        city_row.addWidget(self._city_name, stretch=1)
        city_row.addWidget(self._btn_next)
        city_row.addWidget(self._btn_add_city)
        city_row.addWidget(self._btn_remove_city)

        self._label = QLabel(self.tr("天气加载中…"), self)
        self._label.setObjectName("weather_status")
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setMinimumWidth(LAYOUT["weather_status_min_width"])
        self._label.setWordWrap(True)
        self._label.installEventFilter(self)

        self._details_label = QLabel(self)
        self._details_label.setObjectName("weather_details")
        self._details_label.setWordWrap(True)
        self._details_label.setTextFormat(Qt.TextFormat.PlainText)

        self._weather_icon = QLabel("…", self)
        self._weather_icon.setObjectName("weather_icon")
        self._weather_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._weather_icon.setFixedWidth(LAYOUT["weather_icon_width"])
        self._weather_icon.installEventFilter(self)

        weather_row = QHBoxLayout()
        self._weather_row = weather_row
        weather_row.setContentsMargins(0, 0, 0, 0)
        weather_row.setSpacing(LAYOUT["weather_row_spacing"])
        weather_row.addWidget(self._weather_icon)
        weather_row.addWidget(self._label, stretch=1)

        layout = QVBoxLayout(self)
        self._layout = layout
        margin = LAYOUT["weather_margin"]
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(LAYOUT["weather_layout_spacing"])
        layout.addLayout(city_row)
        layout.addWidget(self._city_pages)
        layout.addLayout(weather_row)
        layout.addWidget(self._details_label)

        self._populate_cities()
        self._btn_previous.clicked.connect(lambda: self._select_city(self._current_city_index - 1))
        self._btn_next.clicked.connect(lambda: self._select_city(self._current_city_index + 1))
        self._btn_add_city.clicked.connect(self._add_city)
        self._btn_remove_city.clicked.connect(self._remove_city)
        self.setMouseTracking(True)
        self.installEventFilter(self)
        self._update_remove_button()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._apply_interval()
        self.refresh()

    def apply_theme(self, bundle) -> None:
        self._bundle = bundle
        self.setStyleSheet(bundle.qss.weather_panel)
        self._apply_metrics(bundle.layout)

    def _apply_metrics(self, layout) -> None:
        """同步布局尺寸（已由 bundle 按 UI 缩放算好）。"""
        self._btn_previous.setFixedWidth(layout.weather_nav_width)
        self._btn_next.setFixedWidth(layout.weather_nav_width)
        self._btn_add_city.setFixedWidth(layout.weather_action_width)
        self._btn_remove_city.setFixedWidth(layout.weather_action_width)
        self._weather_icon.setFixedWidth(layout.weather_icon_width)
        self._label.setMinimumWidth(layout.weather_status_min_width)
        self._layout.setContentsMargins(
            layout.weather_margin,
            layout.weather_margin,
            layout.weather_margin,
            layout.weather_margin,
        )
        self._layout.setSpacing(layout.weather_layout_spacing)
        self._city_row.setSpacing(layout.weather_row_spacing)
        self._weather_row.setSpacing(layout.weather_row_spacing)

    def _cfg_get(self, key: str, default=None):
        return self._cfg.get(key, default)

    def _cfg_set(self, key: str, value) -> None:
        if isinstance(self._cfg, dict):
            self._cfg[key] = value
            return
        self._cfg.set(key, value, save=False)
        self._cfg.save_debounced()

    def _load_cities(self) -> list[dict]:
        raw = self._cfg_get("weather_cities", [])
        cities = []
        seen = set()
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                city = valid_city(item)
                if city is None:
                    continue
                key = city_key(city)
                if key not in seen:
                    seen.add(key)
                    cities.append(city)
        current = valid_city(
            {
                "name": self._cfg_get("weather_city", WEATHER_CITY_DEFAULT),
                "lat": self._cfg_get("weather_lat", WEATHER_LAT_DEFAULT),
                "lon": self._cfg_get("weather_lon", WEATHER_LON_DEFAULT),
            }
        )
        if current is None:
            current = {
                "name": WEATHER_CITY_DEFAULT,
                "lat": WEATHER_LAT_DEFAULT,
                "lon": WEATHER_LON_DEFAULT,
            }
        if city_key(current) not in seen:
            cities.insert(0, current)
        return cities

    def _selected_city_index(self) -> int:
        lat = self._cfg_get("weather_lat", WEATHER_LAT_DEFAULT)
        lon = self._cfg_get("weather_lon", WEATHER_LON_DEFAULT)
        try:
            selected = round(float(lat), 4), round(float(lon), 4)
        except (TypeError, ValueError, OverflowError):
            selected = round(WEATHER_LAT_DEFAULT, 4), round(WEATHER_LON_DEFAULT, 4)
        for index, city in enumerate(self._cities):
            if (round(city["lat"], 4), round(city["lon"], 4)) == selected:
                return index
        return 0

    def _populate_cities(self, selected: int | None = None) -> None:
        if selected is None:
            selected = self._selected_city_index()
        if not self._cities:
            return
        self._current_city_index = min(max(0, selected), len(self._cities) - 1)
        city = self._cities[self._current_city_index]
        self._city_name.setText(city["name"])
        self._city_name.setToolTip(city.get("label", city["name"]))
        self._city_pages.setText(f"●  {self._current_city_index + 1} / {len(self._cities)}")
        self._btn_previous.setEnabled(self._current_city_index > 0)
        self._btn_next.setEnabled(self._current_city_index < len(self._cities) - 1)
        self._update_remove_button()

    def _persist_cities(self, active: dict) -> None:
        self._cfg_set("weather_cities", [dict(city) for city in self._cities])
        self._cfg_set("weather_city", active["name"])
        self._cfg_set("weather_lat", active["lat"])
        self._cfg_set("weather_lon", active["lon"])

    def _apply_interval(self) -> None:
        minutes = self._cfg_get("weather_refresh_minutes", WEATHER_REFRESH_MINUTES_DEFAULT)
        interval = max(5, int(minutes)) * 60_000
        if self._timer.interval() != interval:
            self._timer.start(interval)

    def _on_city_changed(self, index: int) -> None:
        if not 0 <= index < len(self._cities):
            return
        self._current_city_index = index
        city = self._cities[index]
        self._populate_cities(index)
        self._persist_cities(city)
        self._has_weather = False
        self._weather_icon.setText("…")
        self._details_label.clear()
        self._label.setToolTip("")
        self.refresh()

    def _select_city(self, index: int) -> None:
        if 0 <= index < len(self._cities) and index != self._current_city_index:
            self._on_city_changed(index)

    def _update_remove_button(self) -> None:
        self._btn_remove_city.setEnabled(len(self._cities) > 1)

    def eventFilter(self, watched, event):
        if watched not in (self, self._label, self._weather_icon):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.MouseButtonPress:
            self._swipe_start = event.globalPosition().toPoint()
        elif event.type() == QEvent.Type.MouseButtonRelease and self._swipe_start is not None:
            delta = event.globalPosition().toPoint() - self._swipe_start
            self._swipe_start = None
            # 提高滑动阈值，降低误触
            if abs(delta.x()) >= 60 and abs(delta.x()) > abs(delta.y()) * 1.5:
                direction = 1 if delta.x() < 0 else -1
                self._select_city(self._current_city_index + direction)
        return super().eventFilter(watched, event)

    def _add_city(self) -> None:
        if len(self._cities) >= MAX_CITIES:
            QMessageBox.warning(self, "天气", f"最多可保存 {MAX_CITIES} 个城市。")
            return
        if self._adding_city:
            return
        self._adding_city = True
        dialog = CityPickerDialog(self._source, self, bundle=self._bundle)
        search_requested = []
        dialog.city_selected.connect(self._on_city_selected)
        dialog.search_requested.connect(lambda: search_requested.append(True))
        dialog.exec()
        self._adding_city = False
        if search_requested:
            self._search_city()

    def _on_city_selected(self, city: dict) -> None:
        self._on_city_resolved([city])

    def _search_city(self) -> None:
        if len(self._cities) >= MAX_CITIES:
            QMessageBox.warning(self, "天气", f"最多可保存 {MAX_CITIES} 个城市。")
            return
        if self._adding_city:
            return
        resolver = getattr(self._source, "resolve_city", None)
        if not callable(resolver):
            QMessageBox.warning(self, "天气", "当前天气服务不支持搜索城市。")
            return
        dialog = QInputDialog(self)
        dialog.setWindowTitle("添加城市")
        dialog.setLabelText("请输入城市名称：")
        dialog.setTextValue("")
        if self._bundle is not None:
            dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            dialog.setAutoFillBackground(True)
            resolver_color = self._bundle.resolver
            dialog.setStyleSheet(
                self._bundle.dialog.qss_picker + f"\nQDialog {{ border: 1px solid "
                f"{resolver_color.color('border_color')}; "
                "background: "
                f"{resolver_color.color('bg_main')}; }}"
            )
        accepted = dialog.exec()
        name = dialog.textValue().strip()
        dialog.deleteLater()
        if accepted != QInputDialog.DialogCode.Accepted:
            return
        if not name:
            QMessageBox.warning(self, "天气", "城市名称不能为空。")
            return
        self._adding_city = True
        self._btn_add_city.setEnabled(False)
        try:
            resolver(name, self._on_city_resolved, self._on_city_resolve_error)
        except (OSError, TypeError, ValueError) as error:
            self._on_city_resolve_error(str(error))

    def _on_city_resolved(self, matches: list[dict]) -> None:
        self._adding_city = False
        self._btn_add_city.setEnabled(True)
        if self._stopped:
            return
        if not matches:
            QMessageBox.warning(self, "天气", "没有找到匹配的城市。")
            return
        if len(matches) == 1:
            city = matches[0]
        else:
            labels = [str(item.get("label", item.get("name", ""))) for item in matches]
            dialog = QInputDialog(self)
            dialog.setWindowTitle("选择城市")
            dialog.setLabelText("找到多个匹配城市，请选择：")
            dialog.setComboBoxEditable(False)
            dialog.setComboBoxItems(labels)
            if self._bundle is not None:
                dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                dialog.setAutoFillBackground(True)
                resolver_color = self._bundle.resolver
                dialog.setStyleSheet(
                    self._bundle.dialog.qss_picker + f"\nQDialog {{ border: 1px solid "
                    f"{resolver_color.color('border_color')}; "
                    "background: "
                    f"{resolver_color.color('bg_main')}; }}"
                )
            accepted = dialog.exec()
            label = dialog.textValue()
            dialog.deleteLater()
            if accepted != QInputDialog.DialogCode.Accepted:
                return
            city = matches[labels.index(label)]
        city = valid_city(city)
        if city is None:
            QMessageBox.warning(self, "天气", "城市坐标无效，无法添加。")
            return
        key = city_key(city)
        for index, existing in enumerate(self._cities):
            if city_key(existing) == key:
                self._on_city_changed(index)
                return
        if len(self._cities) >= MAX_CITIES:
            QMessageBox.warning(self, "天气", f"最多可保存 {MAX_CITIES} 个城市。")
            return
        self._cities.append(city)
        self._on_city_changed(len(self._cities) - 1)

    def _on_city_resolve_error(self, error: str) -> None:
        self._adding_city = False
        self._btn_add_city.setEnabled(True)
        if not self._stopped:
            logger.warning("城市搜索失败: %s", error)
            QMessageBox.warning(self, "天气", f"城市搜索失败：{error}")

    def _remove_city(self) -> None:
        index = self._current_city_index
        if len(self._cities) <= 1 or not 0 <= index < len(self._cities):
            return
        self._cities.pop(index)
        selected = min(index, len(self._cities) - 1)
        self._populate_cities(selected)
        city = self._cities[selected]
        self._persist_cities(city)
        self._active_key = None
        self._has_weather = False
        self._weather_icon.setText("…")
        self._label.setToolTip("")
        self._details_label.clear()
        self.refresh()

    def refresh(self) -> None:
        if self._stopped:
            return
        self._apply_interval()
        if not self._cfg_get("weather_enabled", WEATHER_ENABLED_DEFAULT):
            self._active_key = None
            self._has_weather = False
            self._weather_icon.setText("—")
            self._label.setText(self.tr("天气未启用"))
            self._label.setToolTip("")
            self._details_label.clear()
            return
        city = (
            self._cities[self._current_city_index]
            if 0 <= self._current_city_index < len(self._cities)
            else None
        )
        if not isinstance(city, dict):
            return
        key = city_key(city)
        if self._active_key != key:
            self._active_key = key
            self._has_weather = False
            self._weather_icon.setText("…")
            get_cached = getattr(self._source, "get_cached", None)
            cached = (
                get_cached(city["name"], city["lat"], city["lon"]) if callable(get_cached) else None
            )
            if cached is not None:
                self._show_info(cached)
        if key in self._pending:
            return
        self._pending.add(key)
        if not self._has_weather:
            self._label.setText(self.tr("天气加载中…"))
        # adcode 只有从行政区选择器加进来的城市才有；无值时不下发，
        # 以兼容只实现五参数契约的数据源（含测试替身）。
        adcode = city.get("adcode")
        extra = {"adcode": adcode} if adcode else {}
        try:
            self._source.fetch(
                city["name"],
                city["lat"],
                city["lon"],
                lambda info, request_key=key: self._on_ok(info, request_key),
                lambda error, request_key=key: self._on_error(error, request_key),
                **extra,
            )
        except (OSError, TypeError, ValueError) as error:
            self._pending.discard(key)
            self._on_error(str(error), key)

    def _on_ok(self, info, key: tuple[str, float, float]) -> None:
        self._pending.discard(key)
        if self._stopped or key != self._active_key:
            return
        self._show_info(info)

    def _show_info(self, info) -> None:
        self._has_weather = True
        self._weather_icon.setText(weather_icon_for(info))
        self._label.setText(format_weather(info.city, info.temperature, info.description))
        details = []
        if info.humidity is not None:
            details.append(f"湿度 {info.humidity}%")
        self._label.setToolTip(" · ".join(details))
        self._details_label.setText(" · ".join(details))

    def _on_error(self, error: str, key: tuple[str, float, float]) -> None:
        self._pending.discard(key)
        logger.warning("天气更新失败: %s", error)
        if self._stopped or key != self._active_key:
            return
        if not self._has_weather:
            self._weather_icon.setText("⚠️")
            self._label.setText(self.tr("天气不可用"))

    def stop(self) -> None:
        self._stopped = True
        self._timer.stop()
