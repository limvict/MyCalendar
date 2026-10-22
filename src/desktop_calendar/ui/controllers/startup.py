# coding: utf-8
"""启动期一次性 UI 包装：开机自启 + 依赖检查。

合并自 auto_start_ui.py / dependency_check.py。两者都是"启动时
调用一次、失败静默或弹窗"的薄包装，放同一文件便于审查启动路径。
"""
import weakref

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from desktop_calendar.config.i18n import tr
from desktop_calendar.infrastructure.platform import auto_start
from desktop_calendar.ui.dialogs import msg_warn

__all__ = [
    "check_auto_start", "apply_auto_start",
    "check_dependencies",
]


# ===================== 开机自启 =====================
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
            QMessageBox.critical(
                parent_widget, tr("autostart.window_title_error"),
                tr("autostart.failed").format(error=e))
        return
    QMessageBox.information(
        parent_widget, tr("autostart.window_title_success"),
        tr("autostart.enabled") if enable else tr("autostart.disabled"))


# ===================== 依赖检查 =====================
def check_dependencies(
    parent_widget,
    has_cnlunar: bool,
    has_chinese_cal: bool,
    delay_ms: int = 100,
) -> None:
    """无缺失时静默；有缺失时延迟弹窗。"""
    warn_msgs = []
    if not has_cnlunar:
        warn_msgs.append(tr("dep.missing_cnlunar"))
    if not has_chinese_cal:
        warn_msgs.append(tr("dep.missing_chinese_cal"))
    if not warn_msgs:
        return

    ref = weakref.ref(parent_widget)

    def _fire():
        w = ref()
        if w is not None:
            _show_warning(w, warn_msgs)

    QTimer.singleShot(delay_ms, _fire)


def _show_warning(parent_widget, warn_msgs) -> None:
    msg_warn(
        parent_widget, tr("dep.missing_title"),
        "\n".join(warn_msgs) + "\n" + tr("dep.install_hint"))
