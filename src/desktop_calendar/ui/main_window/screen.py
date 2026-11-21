# coding: utf-8
"""屏幕适配：跟随窗口所在屏幕的可用区域与 DPI 重新缩放。"""

from __future__ import annotations

import logging

from PyQt6.QtGui import QScreen

from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME

from .helpers import _screen_ui_scale

logger = logging.getLogger(APP_LOGGER_NAME)


class MainWindowScreenMixin:
    """屏幕适配：跟随窗口所在屏幕的可用区域与 DPI 重新缩放。"""

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is None:
            return
        if not self._screen_change_connected:
            handle.screenChanged.connect(self._on_window_screen_changed)
            self._screen_change_connected = True
        self._watch_screen(handle.screen())

    def _on_window_screen_changed(self, screen: QScreen | None) -> None:
        self._watch_screen(screen)

    def _watch_screen(self, screen: QScreen | None) -> None:
        if screen is self._watched_screen:
            return
        if self._watched_screen is not None:
            for signal in (
                self._watched_screen.availableGeometryChanged,
                self._watched_screen.logicalDotsPerInchChanged,
            ):
                try:
                    signal.disconnect(self._on_screen_metrics_changed)
                except (TypeError, RuntimeError):
                    logger.debug("解除旧屏幕信号失败", exc_info=True)
        self._watched_screen = screen
        if screen is None:
            return
        screen.availableGeometryChanged.connect(self._on_screen_metrics_changed)
        screen.logicalDotsPerInchChanged.connect(self._on_screen_metrics_changed)
        self._apply_screen_scale(screen)

    def _on_screen_metrics_changed(self, *_args) -> None:
        if self._watched_screen is not None:
            self._apply_screen_scale(self._watched_screen)

    def _apply_screen_scale(self, screen: QScreen) -> None:
        self.theme_mgr.set_ui_scale(_screen_ui_scale(screen, sidebar_visible=self._sidebar_visible))
        self._apply_theme_geometry(self.theme_mgr.current)
        available = screen.availableGeometry()
        right = max(available.left(), available.right() - self.width() + 1)
        bottom = max(available.top(), available.bottom() - self.height() + 1)
        self.move(
            max(available.left(), min(self.x(), right)),
            max(available.top(), min(self.y(), bottom)),
        )
