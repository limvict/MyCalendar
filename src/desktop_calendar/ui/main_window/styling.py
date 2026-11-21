# coding: utf-8
"""主题刷新：把 ThemeBundle 里的 QSS/字体/图标套到各控件上。"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QApplication,
)

from desktop_calendar.ui.calendar_wallpaper import load_wallpaper
from desktop_calendar.ui.theme import ThemeBundle, qss
from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME

logger = logging.getLogger(APP_LOGGER_NAME)


class MainWindowStylingMixin:
    """主题刷新：把 ThemeBundle 里的 QSS/字体/图标套到各控件上。"""

    def _refresh_styles(self, b: ThemeBundle):
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(b.qss.tooltip)
        self.view_selector.setStyleSheet(b.qss.header_combo)
        self.content_widget.setStyleSheet(
            b.qss.content_widget_sidebar if self._sidebar_visible else b.qss.content_widget
        )
        self.sidebar.setStyleSheet(
            b.qss.sidebar_panel if self._sidebar_visible else b.qss.sidebar_panel_flat
        )
        self.btn_sidebar_close.setStyleSheet(b.qss.sidebar_close)
        # 侧边栏的滚动条也要套主题 QSS，否则会回落到系统原生滑块
        self.sidebar_scroll.setStyleSheet(qss.TRANSPARENT_SCROLL_AREA + b.qss.scrollbar)
        viewport = self.sidebar_scroll.viewport()
        viewport.setObjectName("sidebar_viewport")
        viewport.setStyleSheet(qss.transparent_widget("sidebar_viewport"))
        self.sidebar_content.setObjectName("sidebar_content")
        self.sidebar_content.setStyleSheet(qss.transparent_widget("sidebar_content"))
        self.weather_widget.apply_theme(b)
        self.sidebar_services_widget.apply_theme(b)
        self.cal.setStyleSheet(b.qss.calendar)
        for btn in (self.btn_prev, self.btn_next, self.btn_mood, self.btn_sidebar):
            btn.setStyleSheet(b.qss.nav_buttons)
        for btn in (self.btn_minimize, self.btn_close):
            btn.setStyleSheet(b.qss.window_buttons)
        self.header_sep.setStyleSheet(b.qss.header_separator)
        for button in self._sidebar_buttons:
            button.setStyleSheet(b.qss.sidebar_action)
        # 打卡双按钮用居中样式，覆盖上面「常用」网格的左对齐样式
        for button in (self.btn_punch_in, self.btn_punch_out):
            button.setStyleSheet(b.qss.attendance_punch)
        self.btn_attendance_stats.setStyleSheet(b.qss.attendance_stats)
        self.attendance_summary_label.setStyleSheet(b.qss.sidebar_subtitle)
        for label in (
            self.sidebar_weather_title,
            self.sidebar_attendance_title,
            self.sidebar_focus_title,
            self.sidebar_actions_title,
        ):
            label.setStyleSheet(b.qss.sidebar_section_title)
        for label in (self.attendance_status_label, self.focus_status_label):
            label.setStyleSheet(b.qss.sidebar_status)
        self.sidebar_title.setStyleSheet(b.qss.sidebar_title)
        self.sidebar_subtitle.setStyleSheet(b.qss.sidebar_subtitle)
        self.btn_today.setStyleSheet(b.qss.today_button)
        self.cal_title.setStyleSheet(b.qss.cal_title)
        self.info_label.setStyleSheet(b.qss.info_label)

    def apply_theme(self, bundle):
        steps = (
            ("setFont", lambda: self.setFont(bundle.fonts.global_)),
            ("window_icon", lambda: self._apply_window_icon(bundle)),
            ("layout_metrics", lambda: self._apply_layout_metrics(bundle)),
            ("geometry", lambda: self._apply_theme_geometry(bundle)),
            ("styles", lambda: self._refresh_styles(bundle)),
            ("row_heights", self._sync_row_heights),
            ("calendar", lambda: self.cal.apply_theme(bundle)),
            ("calendar_views", lambda: self._apply_overview_themes(bundle)),
            ("tray", lambda: self.tray_mgr.update_theme(bundle)),
            ("info", lambda: self._refresh_info_label(bundle.resolver)),
            ("repaint", self.update),
        )
        failed = []
        for step_name, fn in steps:
            try:
                fn()
            except Exception:
                failed.append(step_name)
                logger.exception("主题应用步骤 %s 失败 bundle=%s", step_name, bundle.name)
        if failed:
            logger.warning("主题 %s 部分步骤失败: %s", bundle.name, ",".join(failed))
        else:
            logger.info("主题已应用: %s", bundle.name)

    def set_calendar_wallpaper(
        self,
        path: str,
        overlay_percent: int,
    ) -> None:
        """给月/周/年三个视图同时换壁纸（设置对话框与启动流程共用）。"""
        pixmap = load_wallpaper(path)
        if path and pixmap is None:
            logger.warning("无法读取日历壁纸: %s", path)
        overlay_percent = max(20, min(90, int(overlay_percent)))
        self.cal.set_wallpaper(pixmap, overlay_percent)
        self.week_view.set_wallpaper(pixmap, overlay_percent)
        self.year_view.set_wallpaper(pixmap, overlay_percent)
        self._refresh_overview_views()

    def _apply_overview_themes(self, bundle) -> None:
        self.week_view.apply_theme(bundle)
        self.year_view.apply_theme(bundle)
