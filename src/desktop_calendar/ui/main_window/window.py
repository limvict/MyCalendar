# coding: utf-8
"""主窗口：组装各功能 mixin，负责生命周期与窗口级行为。

能力分散在同级模块中，按界面区域划分：

- `layout`     ：控件搭建、快捷键、尺寸与阴影
- `styling`    ：主题与 QSS 刷新
- `screen`     ：多屏与缩放适配
- `sidebar`    ：快捷侧栏
- `navigation` ：日历导航与标题
- `status`     ：信息栏与日程/心情/专注状态
- `attendance` ：考勤菜单与打卡
- `actions`    ：日程、番茄钟、音乐等入口
- `events`     ：事件总线订阅与分发
- `helpers`    ：共用常量与纯函数
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from datetime import datetime

from PyQt6.QtCore import QDate, QTimer
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
)

from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import config, get_resource_path
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.attendance import (
    AttendanceStore,
)
from desktop_calendar.core.attendance_auto_punch import AttendanceAutoPunchManager
from desktop_calendar.core.attendance_reminder import AttendanceReminderManager
from desktop_calendar.core.focus_log import FocusLog
from desktop_calendar.core.holiday_manager import HolidayManager
from desktop_calendar.core.memorial import (
    normalize_memorial_days,
)
from desktop_calendar.core.mood import MoodStore
from desktop_calendar.core.pomodoro import PomodoroTimer
from desktop_calendar.core.reminder_manager import ReminderManager
from desktop_calendar.core.schedule import ScheduleManager
from desktop_calendar.core.schedule_reminder import ScheduleReminder
from desktop_calendar.infrastructure.audio import SoundManager
from desktop_calendar.infrastructure.network.qt_holiday_source import make_qt_holiday_source
from desktop_calendar.infrastructure.network.sidebar_services import SidebarServices
from desktop_calendar.infrastructure.network.update_manager import UpdateManager
from desktop_calendar.infrastructure.network.weather_source import OpenMeteoSource
from desktop_calendar.ui.controllers.memorial_backup_ui import MemorialDataManager
from desktop_calendar.ui.controllers.startup import check_dependencies
from desktop_calendar.ui.controllers.update_ui import UpdateUIController
from desktop_calendar.ui.controllers.window_state import WindowStateManager
from desktop_calendar.ui.dialogs import (
    set_bundle_provider,
)
from desktop_calendar.ui.theme import ThemeManager
from desktop_calendar.ui.tray_manager import TrayManager
from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME

from .actions import MainWindowActionsMixin
from .attendance import MainWindowAttendanceMixin
from .events import MainWindowEventsMixin
from .helpers import _screen_ui_scale
from .layout import MainWindowLayoutMixin
from .navigation import MainWindowNavigationMixin
from .screen import MainWindowScreenMixin
from .sidebar import MainWindowSidebarMixin
from .status import MainWindowStatusMixin
from .styling import MainWindowStylingMixin

logger = logging.getLogger(APP_LOGGER_NAME)


class MainWindow(
    MainWindowLayoutMixin,
    MainWindowStylingMixin,
    MainWindowScreenMixin,
    MainWindowSidebarMixin,
    MainWindowNavigationMixin,
    MainWindowStatusMixin,
    MainWindowAttendanceMixin,
    MainWindowActionsMixin,
    MainWindowEventsMixin,
    QWidget,
):
    """桌面日历主窗口。"""

    def __init__(self):
        super().__init__()
        if sys.platform == "win32":
            self._app_mutex = ctypes.windll.kernel32.CreateMutexW(
                None, False, "DesktopCalendar_App_Mutex"
            )
        self._quitting = False
        self._quitting_for_update = False
        self._shadow_effect = None
        self._shortcuts: list = []
        self._sidebar_visible = False
        self._watched_screen: QScreen | None = None
        self._screen_change_connected = False
        self._init_config_on_start()
        self.attendance_store = AttendanceStore(config=config)

        self.theme_mgr = ThemeManager(
            config, ui_scale=_screen_ui_scale(QApplication.primaryScreen())
        )
        self.theme_mgr.theme_changed.connect(self.apply_theme)
        self.setFont(self.theme_mgr.current.fonts.global_)
        set_bundle_provider(lambda: self.theme_mgr.current)
        self.sound_mgr = SoundManager(self, get_resource_path)
        self.window_state = WindowStateManager(self, config)
        self.holiday_mgr = HolidayManager(config, source_factory=make_qt_holiday_source)
        self.memorial_mgr = MemorialDataManager(self, config)
        self.reminder_mgr = ReminderManager(self, config, self.sound_mgr)
        self.attendance_reminder = AttendanceReminderManager(
            self, config, self.attendance_store, self.sound_mgr
        )
        self.attendance_auto_punch = AttendanceAutoPunchManager(self, config, self.attendance_store)
        self.attendance_auto_punch.punched.connect(self._on_auto_punched)
        self.attendance_auto_punch.failed.connect(self._on_auto_punch_failed)
        self.mood_store = MoodStore()
        self.focus_log = FocusLog()
        self._pomodoro_timer = PomodoroTimer(parent=self)
        self._pomodoro_work_started_at: datetime | None = None
        self._pomodoro_timer.round_finished.connect(
            lambda _round: self.sound_mgr.play("assets/alert.wav")
        )
        self._pomodoro_timer.phase_changed.connect(self._on_pomodoro_phase_changed)
        self._pomodoro_timer.work_completed.connect(self._on_pomodoro_work_completed)
        self._pomodoro_dialog = None
        self.tray_mgr = TrayManager(
            self,
            config,
            get_resource_path,
            bundle=self.theme_mgr.current,
            on_open_pomodoro=self._open_pomodoro_dialog,
            # 延迟取 update_ui：它在本方法稍后才创建
            on_check_update=lambda: self.update_ui.check_now(),
        )
        self.update_mgr = UpdateManager(self)
        self.update_ui = UpdateUIController(
            parent_widget=self, update_mgr=self.update_mgr, window_quit_cb=self.quit_app
        )

        self._schedule_mgr = ScheduleManager()
        self._schedule_reminder = ScheduleReminder(self._schedule_mgr, parent=self)
        self._schedule_reminder.due.connect(self._on_schedule_due)
        self.weather_source = OpenMeteoSource(self)
        self.sidebar_services_source = SidebarServices(self)

        self._setup_window()
        self.build_ui()
        self._subscribe_events()

        self.destroyed.connect(self._on_destroyed_cleanup)
        self._startup()

    def _init_config_on_start(self):
        before = config.snapshot()
        config.ensure_migrated()
        try:
            raw = config.get("memorial_days", [])
            normalized, _ = normalize_memorial_days(raw)
            if normalized != raw:
                config.set("memorial_days", normalized, save=False)
        except Exception:
            logger.warning("启动时 memorial_days 归一化失败", exc_info=True)
        if config.snapshot() != before:
            if callable(save := getattr(config, "save_debounced", None)):
                save()

    def _startup(self):
        self.setWindowTitle(tr("app.title"))
        self.cal.set_net_holiday(self.holiday_mgr.apply_cached())
        self.cal.set_memorial_list(config.get("memorial_days", []))
        self.reminder_mgr.reschedule(check_today=True)
        self.attendance_reminder.reschedule()
        self.attendance_auto_punch.reschedule()
        check_dependencies(
            self, has_cnlunar=lunar_mod.HAS_CNLUNAR, has_chinese_cal=lunar_mod.HAS_CHINESE_CAL
        )
        self.holiday_mgr.fetch_current_year()
        self.update_calendar_title()
        self._refresh_info_label()

        QTimer.singleShot(0, self._warmup_lunar_cache)
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(5000)
        self._update_timer.timeout.connect(self.update_ui.check_on_start)
        self._update_timer.start()

    def _warmup_lunar_cache(self):
        if not lunar_mod.HAS_CNLUNAR:
            return
        try:
            y = QDate.currentDate().year()
            lunar_mod.warmup_lunar_index_async([y])
        except Exception:
            logger.warning("农历索引异步预热启动失败", exc_info=True)

    def _on_destroyed_cleanup(self, _obj=None):
        try:
            set_bundle_provider(None)
        except Exception:
            logger.debug("destroyed 清理 bundle_provider 失败", exc_info=True)

    def _on_escape(self):
        # 以前 Esc 直接把窗口藏进托盘，用户会以为程序退出了；
        # 现在先收侧栏，再退化成"最小化到任务栏"这种可见的动作。
        if getattr(self, "_sidebar_visible", False):
            self.btn_sidebar.setChecked(False)
            return
        self.showMinimized()

    def mousePressEvent(self, event):
        self.window_state.mouse_press_event(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.window_state.mouse_move_event(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.window_state.mouse_release_event(event)
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        if self._quitting or self._quitting_for_update:
            event.accept()
            return
        if not self.tray_mgr.available:
            self.quit_app()
            event.accept()
            return
        event.ignore()
        self._on_window_hide()

    def contextMenuEvent(self, event):
        event.accept()

    def _on_window_hide(self, _data=None):
        """收起窗口到托盘，并在首次收起时提示一次「还在后台运行」。"""
        if not self.tray_mgr.available:
            self.showMinimized()
            return
        self.hide()
        self._show_tray_hint_once()

    def _show_tray_hint_once(self) -> None:
        try:
            if config.get("tray_hint_shown", False):
                return
        except Exception:
            logger.debug("读取托盘提示状态失败", exc_info=True)
        if not self.tray_mgr.show_message(tr("tray.hint_title"), tr("tray.hint_body")):
            return
        try:
            config.set("tray_hint_shown", True, save=False)
            config.save_debounced()
        except Exception:
            logger.debug("写入托盘提示状态失败", exc_info=True)

    def _hide_or_minimize(self):
        """「最小化」统一入口：收进任务栏，而不是无声藏进托盘。

        以前托盘可用时这里直接 hide()，用户会以为程序退出了；收进托盘
        现在只由标题栏的关闭按钮（×）负责，并会弹一次托盘气泡说明。
        """
        self.showMinimized()

    # ---------- 显示 / 退出 ----------
    def show_normal(self):
        self.showNormal()
        try:
            self.window_state.ensure_on_screen()
        except Exception:
            logger.exception("重置窗口位置失败")
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        if self._quitting:
            return
        self._quitting = True

        if (timer := getattr(self, "_update_timer", None)) is not None:
            try:
                timer.stop()
            except Exception:
                pass

        hard_exit = self._quitting_for_update

        for fn, name in (
            (self._attendance_status_timer.stop, "关闭考勤状态刷新"),
            (self.update_ui.close_progress, "关闭进度对话框"),
            (self.reminder_mgr.shutdown, "关闭提醒线程"),
            (self.attendance_reminder.shutdown, "关闭考勤提醒"),
            (self.attendance_auto_punch.shutdown, "关闭自动考勤"),
            (self._schedule_reminder.stop, "关闭日程提醒"),
            (self._pomodoro_timer.stop, "关闭番茄钟"),
            (self.weather_widget.stop, "关闭天气刷新"),
            (self.sidebar_services_widget.stop, "关闭侧栏信息服务"),
            (self._unwire, "解除事件订阅"),
            (self.window_state.save_position, "保存窗口位置"),
            (self.holiday_mgr.shutdown, "关闭节假日线程"),
            (self.update_mgr.shutdown, "关闭更新线程"),
            (self._flush_config, "刷写配置"),
            (self._disconnect_theme_signal, "解除主题信号"),
        ):
            try:
                fn()
            except Exception as e:
                logger.warning("%s失败: %s", name, e)

        try:
            self.tray_mgr.hide()
        except Exception:
            pass
        try:
            set_bundle_provider(None)
        except Exception:
            pass

        if hard_exit:
            logger.info("更新场景：强制结束主进程以释放文件句柄")
            try:
                logging.shutdown()  # 先 flush 再硬退出，保证最后日志落盘
            except Exception:
                pass
            os._exit(0)

        logger.info("正常退出：请求 Qt 事件循环结束")
        QApplication.quit()

    def _flush_config(self):
        config.flush()

    def _disconnect_theme_signal(self):
        try:
            self.theme_mgr.theme_changed.disconnect(self.apply_theme)
        except (TypeError, RuntimeError):
            pass
