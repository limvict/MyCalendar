# coding: utf-8
"""开机自启的 UI 包装：调用 platform 层，把结果映射为弹窗。"""
from PyQt6.QtWidgets import QMessageBox

from desktop_calendar.config.i18n import tr
from desktop_calendar.infrastructure.platform import auto_start


def check_auto_start() -> bool:
    return auto_start.is_enabled()


def apply_auto_start(parent_widget, enable: bool) -> None:
    if not auto_start.is_supported():
        QMessageBox.information(
            parent_widget, tr("autostart.window_title_hint"),
            tr("autostart.windows_only"))
        return
    try:
        auto_start.set_enabled(enable)
    except auto_start.AutoStartError as e:
        if e.reason == "permission":
            QMessageBox.critical(
                parent_widget, tr("autostart.window_title_permission"),
                tr("autostart.permission_error"))
        else:
            # path_missing / unknown 统一走通用错误
            QMessageBox.critical(
                parent_widget, tr("autostart.window_title_error"),
                tr("autostart.failed").format(error=e))
        return
    QMessageBox.information(
        parent_widget, tr("autostart.window_title_success"),
        
        tr("autostart.enabled") if enable else tr("autostart.disabled"))