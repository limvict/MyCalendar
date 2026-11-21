# coding: utf-8
"""快捷侧栏：显隐切换、宽度重算与入口按钮分发。"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QApplication,
)

from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME

from .helpers import _screen_ui_scale

logger = logging.getLogger(APP_LOGGER_NAME)


class MainWindowSidebarMixin:
    """快捷侧栏：显隐切换、宽度重算与入口按钮分发。"""

    def _toggle_sidebar(self, visible: bool) -> None:
        self._sidebar_visible = visible
        self.sidebar.setVisible(visible)
        self.btn_sidebar.setToolTip("关闭快捷侧边栏" if visible else "打开快捷侧边栏")
        screen = self.windowHandle().screen() if self.windowHandle() is not None else None
        if screen is None:
            screen = QApplication.screenAt(self.frameGeometry().center())
        self.theme_mgr.set_ui_scale(_screen_ui_scale(screen, sidebar_visible=visible))
        self._apply_theme_geometry(self.theme_mgr.current)
        self._refresh_styles(self.theme_mgr.current)
        if visible:
            self.sidebar_services_widget.refresh()
        if screen is not None:
            available = screen.availableGeometry()
            right = max(available.left(), available.right() - self.width() + 1)
            self.move(
                max(available.left(), min(self.x(), right)),
                max(available.top(), min(self.y(), available.bottom() - self.height() + 1)),
            )

    def _run_sidebar_action(self, action) -> None:
        if self._sidebar_visible:
            self.btn_sidebar.setChecked(False)
        action()
