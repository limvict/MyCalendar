# coding: utf-8
"""主窗口：UI 容器 + 跨模块调度。"""
import logging
from datetime import date, datetime

from PyQt6.QtCore import Qt, QTimer, QDate
from PyQt6.QtGui import QColor, QKeySequence, QShortcut, QFont
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QMenu, QLabel, QGraphicsDropShadowEffect,
    QToolTip, QMessageBox,
)

from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import config, get_resource_path
from desktop_calendar.contracts.event_bus import event_bus, EventType
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.attendance import (
    AttendanceStore, PUNCH_IN_DEADLINE_HOUR,
)
from desktop_calendar.core.holiday_manager import HolidayManager
from desktop_calendar.core.lunar import get_lunar_by_datetime
from desktop_calendar.core.memorial import (
    normalize_memorial_days, get_next_memorial_date,
)
from desktop_calendar.core.reminder_manager import ReminderManager
from desktop_calendar.infrastructure.audio import SoundManager
from desktop_calendar.infrastructure.network.qt_holiday_source import (
    make_qt_holiday_source,
)
from desktop_calendar.infrastructure.network.update_manager import UpdateManager
from desktop_calendar.infrastructure.platform import dwm
from desktop_calendar.ui import info_panel
from desktop_calendar.ui.calendar_widget import ClickLabel, LunarCalendarWidget
from desktop_calendar.ui.controllers import settings_controller
from desktop_calendar.ui.controllers.memorial_backup_ui import MemorialDataManager
from desktop_calendar.ui.controllers.startup import check_dependencies
from desktop_calendar.ui.controllers.update_ui import UpdateUIController
from desktop_calendar.ui.controllers.window_state import WindowStateManager
from desktop_calendar.ui.dialogs import (
    AttendanceDialog, MemorialRemindDialog, MonthYearPickerDialog,
    msg_error, set_bundle_provider,
)
from desktop_calendar.ui.theme import ThemeBundle, ThemeManager
from desktop_calendar.ui.theme_icon import (
    resolve_icon_color, standard_fallback_icon, tinted_icon,
)
from desktop_calendar.ui.tray_manager import TrayManager
from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME
from desktop_calendar.core.attendance_reminder import AttendanceReminderManager

logger = logging.getLogger(APP_LOGGER_NAME)

_DEFER_RESCHEDULE_THRESHOLD = 100

# 布局节奏：顶栏 / 日历 / 底栏共用同一套边距与间距，
# 保证按钮与日历左缘、底栏 label 与按钮文字左缘精确对齐。
_LAYOUT_MARGIN = 14
_SECTION_SPACING = 8
_ROW_SPACING = 8


class MainWindow(QWidget):
    """UI 容器：只做布局装配与事件转发，业务逻辑在 manager / controller。"""

    # ==================== 1. 初始化 ====================
    def __init__(self):
        super().__init__()
        self._quitting = False
        # 更新流程专用退出标志：让 closeEvent 放行，避免托盘模式下
        # event.ignore() 把安装器的关闭请求吞掉。
        self._quitting_for_update = False
        self._shadow_effect = None
        self._shortcuts: list = []
        self._init_config_on_start()
        self.attendance_store = AttendanceStore(config=config)

        self.theme_mgr = ThemeManager(config)
        self.theme_mgr.theme_changed.connect(self.apply_theme)
        self.setFont(self.theme_mgr.current.fonts.global_)
        set_bundle_provider(lambda: self.theme_mgr.current)
        self.sound_mgr = SoundManager(self, get_resource_path)
        self.window_state = WindowStateManager(self, config)
        self.holiday_mgr = HolidayManager(config, source_factory=make_qt_holiday_source)
        self.memorial_mgr = MemorialDataManager(self, config)
        self.reminder_mgr = ReminderManager(self, config, self.sound_mgr)
        self.attendance_reminder = AttendanceReminderManager(
            self, config, self.attendance_store, self.sound_mgr)
        self.tray_mgr = TrayManager(
            self, config, get_resource_path,
            bundle=self.theme_mgr.current)
        self.update_mgr = UpdateManager(self)
        self.update_ui = UpdateUIController(
            parent_widget=self, update_mgr=self.update_mgr,
            window_quit_cb=self.quit_app)

        self._setup_window()
        self.build_ui()

        self._subscribe_events()

        self.destroyed.connect(self._on_destroyed_cleanup)
        self._startup()

    def _event_subscriptions(self):
        return [
            (EventType.HOLIDAY_UPDATED,       self._on_holiday_updated),
            (EventType.MEMORIAL_CHANGED,      self._on_memorial_changed),
            (EventType.MEMORIAL_REMIND_TRIGGERED, self._on_memorial_remind_triggered),
            (EventType.WINDOW_SHOW,           self._on_window_show),
            (EventType.WINDOW_QUIT,           self._on_window_quit),
            (EventType.OPEN_SETTINGS,         self._on_open_settings),
            (EventType.BACKUP_MEMORIAL,       self._on_backup_memorial),
            (EventType.RESTORE_MEMORIAL,      self._on_restore_memorial),
            (EventType.UPDATE_AVAILABLE,      self._on_update_available),
            (EventType.UPDATE_FAILED,         self._on_update_failed),
            (EventType.UPDATE_READY,          self._on_update_ready),
            (EventType.UPDATE_PROGRESS,       self._on_update_progress),
            (EventType.ATTENDANCE_REMIND_TRIGGERED, self._on_attendance_remind),
        ]

    def _subscribe_events(self) -> None:
        self._wiring_subs = self._event_subscriptions()
        for evt, cb in self._wiring_subs:
            try:
                event_bus.subscribe(evt, cb)
            except Exception:
                logger.exception("订阅 %s 失败", evt)

    def _unwire(self) -> None:
        for evt, cb in getattr(self, "_wiring_subs", []):
            try:
                event_bus.unsubscribe(evt, cb)
            except Exception:
                logger.exception("退订 %s 失败", evt)
        self._wiring_subs = []

    # ==================== 2. 启动流程 ====================
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
        check_dependencies(
            self,
            has_cnlunar=lunar_mod.HAS_CNLUNAR,
            has_chinese_cal=lunar_mod.HAS_CHINESE_CAL)
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

    # ==================== 3. 窗口基础属性 ====================
    def _setup_window(self):
        b = self.theme_mgr.current
        self.setFixedSize(b.window.width, b.window.height)
        flags = (
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowSystemMenuHint)
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setObjectName("MainWindow")
        self.setStyleSheet("#MainWindow { background: transparent; }")
        # 用 bg_main 亮度判断深色，避免主题名不是 "dark" 时 DWM 误走浅色分支。
        bg = QColor(b.theme.get("bg_main", "#ffffff"))
        is_dark = bg.isValid() and bg.lightness() < 128
        dwm.apply_dwm_fix(self, dark_mode=is_dark)
        self.setFont(b.fonts.global_)

        self._icon_path = get_resource_path("assets/app.ico")
        self._fallback_icon = standard_fallback_icon()
        self._apply_window_icon(b)

    def _apply_window_icon(self, bundle: ThemeBundle) -> None:
        """窗口 / 任务栏图标跟随主题色。"""
        path = getattr(self, "_icon_path", None) or get_resource_path(
            "assets/app.ico")
        fallback = getattr(self, "_fallback_icon", None) \
            or standard_fallback_icon()
        icon = tinted_icon(path, resolve_icon_color(bundle), fallback=fallback)
        self.setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)

    # ==================== 4. UI 构建 ====================
    def build_ui(self):
        b = self.theme_mgr.current
        layout_main = QVBoxLayout(self)
        layout_main.setSpacing(0)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("content_widget")
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(
            _LAYOUT_MARGIN, _LAYOUT_MARGIN, _LAYOUT_MARGIN, _LAYOUT_MARGIN)
        content_layout.setSpacing(_SECTION_SPACING)

        self.stack = QStackedWidget()
        self.calendar_container = QWidget()
        cal_vl = QVBoxLayout(self.calendar_container)
        cal_vl.setContentsMargins(0, 0, 0, 0)
        cal_vl.setSpacing(_SECTION_SPACING)

        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        # 去掉额外 4px margin，让顶栏按钮与日历网格左缘对齐。
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(_ROW_SPACING)
        self.btn_prev = QPushButton("<")
        self.btn_prev.setFixedWidth(b.window.nav_btn_width)
        self.btn_prev.clicked.connect(self.prev_month)
        self.cal_title = ClickLabel("")
        self.cal_title.setObjectName("cal_title")
        self.cal_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cal_title.clicked.connect(self.open_month_picker)
        self.btn_next = QPushButton(">")
        self.btn_next.setFixedWidth(b.window.nav_btn_width)
        self.btn_next.clicked.connect(self.next_month)
        top_layout.addWidget(self.btn_prev)
        top_layout.addWidget(self.cal_title, stretch=1)
        top_layout.addWidget(self.btn_next)
        cal_vl.addWidget(top_bar)

        self.calendar = LunarCalendarWidget(
            self, b, config.get("memorial_days", []))
        self.cal = self.calendar
        self.cal.currentPageChanged.connect(self.update_calendar_title)
        self.cal.selectionChanged.connect(self.on_calendar_select_changed)
        self.cal.setGridVisible(False)
        self.cal.setNavigationBarVisible(False)
        self.cal.setVerticalHeaderFormat(self.cal.VerticalHeaderFormat.NoVerticalHeader)
        cal_vl.addWidget(self.cal, stretch=1)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(_ROW_SPACING)
        bottom_row.setContentsMargins(0, 0, 0, 0)

        self.info_label = QLabel()
        self.info_label.setObjectName("info_label")
        font = self.info_label.font()
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.info_label.setFont(font)
        # 固定高度：信息过多时裁切而不是撑高布局、挤压日历。
        # 完整信息通过 setToolTip 悬停查看。
        self.info_label.setFixedHeight(b.window.info_label_height)
        self.info_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setWordWrap(True)
        bottom_row.addWidget(self.info_label, stretch=1)

        self.btn_attendance = QPushButton(tr("btn.attendance"))
        self.btn_attendance.clicked.connect(self.open_attendance_menu)
        bottom_row.addWidget(
            self.btn_attendance, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.btn_today = QPushButton(tr("btn.today"))
        self.btn_today.setObjectName("today_btn")
        self.btn_today.clicked.connect(self.goto_today)
        bottom_row.addWidget(
            self.btn_today, alignment=Qt.AlignmentFlag.AlignVCenter)

        cal_vl.addLayout(bottom_row)

        self.stack.addWidget(self.calendar_container)
        content_layout.addWidget(self.stack, stretch=1)
        layout_main.addWidget(self.content_widget)
        self._apply_theme_geometry(b)
        self._setup_shortcuts()
        self._refresh_styles(b)
        self._sync_row_heights()
        self._update_attendance_button()

    def _setup_shortcuts(self):
        for seq, slot in (
            ("Ctrl+T", self.goto_today),
            ("Ctrl+,", lambda: settings_controller.open_settings_dialog(self)),
            ("Ctrl+Q", self.quit_app),
            ("Esc", self._on_escape),
        ):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

    def _on_escape(self):
        if self.tray_mgr.available:
            self.hide()

    # ==================== 5. 主题装配 ====================
    def _apply_theme_geometry(self, b: ThemeBundle):
        self.setFixedSize(b.window.width, b.window.height)
        self.info_label.setFixedHeight(b.window.info_label_height)
        margin = b.window.shadow_size if b.window.shadow_size > 0 else 1
        if (lay := self.layout()) is not None:
            lay.setContentsMargins(margin, margin, margin, margin)
        if b.window.shadow_size > 0:
            if self._shadow_effect is None:
                eff = QGraphicsDropShadowEffect(self)
                eff.setOffset(0, 0)
                self.content_widget.setGraphicsEffect(eff)
                self._shadow_effect = eff
            self._shadow_effect.setBlurRadius(b.window.shadow_size)
            self._shadow_effect.setColor(b.window.shadow_color)
        elif self._shadow_effect is not None:
            self.content_widget.setGraphicsEffect(None)
            self._shadow_effect = None

    def _refresh_styles(self, b: ThemeBundle):
        self.content_widget.setStyleSheet(b.qss.content_widget)
        self.cal.setStyleSheet(b.qss.calendar)

        for btn in (self.btn_prev, self.btn_next, self.btn_attendance):
            btn.setStyleSheet(b.qss.nav_buttons)

        self.btn_today.setStyleSheet(b.qss.today_button)

        self.cal_title.setStyleSheet(b.qss.cal_title)
        self.info_label.setStyleSheet(b.qss.info_label)

    def _sync_row_heights(self) -> None:
        """统一顶栏三件套 / 底部功能按钮的行高与行宽。

        必须在 _refresh_styles 之后调用：QSS 的 padding / min-height
        会改变 sizeHint，先算后套样式会得到过时尺寸。
        """
        nav_h = max(self.btn_prev.sizeHint().height(),
                    self.btn_next.sizeHint().height(),
                    self.cal_title.sizeHint().height())
        for w in (self.btn_prev, self.btn_next, self.cal_title):
            w.setFixedHeight(nav_h)

        fn_btn_h = max(self.btn_attendance.sizeHint().height(),
                       self.btn_today.sizeHint().height())
        # 底栏两个功能按钮等宽：文字长度与 QSS padding 不同，
        # 不统一会一宽一窄显得零散。
        fn_btn_w = max(self.btn_attendance.sizeHint().width(),
                       self.btn_today.sizeHint().width())
        for btn in (self.btn_attendance, self.btn_today):
            btn.setFixedHeight(fn_btn_h)
            btn.setMinimumWidth(fn_btn_w)

    # ==================== 6. 主题刷新 ====================
    def apply_theme(self, bundle):
        """theme_changed 槽：一次刷完所有主题相关资源。

        每步独立 try/except：某一步失败不阻断其余步骤，也不让 emit
        抛异常（否则调用方会误判"切换失败"并回滚 theme_name）。
        """
        steps = (
            ("setFont", lambda: self.setFont(bundle.fonts.global_)),
            ("window_icon", lambda: self._apply_window_icon(bundle)),
            ("geometry", lambda: self._apply_theme_geometry(bundle)),
            ("styles", lambda: self._refresh_styles(bundle)),
            # 放在 styles 之后：确保按新 QSS 的 sizeHint 重算行高。
            ("row_heights", self._sync_row_heights),
            ("calendar", lambda: self.cal.apply_theme(bundle)),
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
                logger.exception(
                    "主题应用步骤 %s 失败 bundle=%s",
                    step_name, bundle.name)
        if failed:
            logger.warning(
                "主题 %s 部分步骤失败: %s（UI 可能不一致，下次切换或重启恢复）",
                bundle.name, ",".join(failed))
        else:
            logger.info("主题已应用: %s", bundle.name)

    def _on_destroyed_cleanup(self, _obj=None):
        try:
            set_bundle_provider(None)
        except Exception:
            logger.debug("destroyed 清理 bundle_provider 失败", exc_info=True)

    # ==================== 7. 事件总线回调 ====================
    def _as_dict(self, data, event_name: str):
        if data is not None and not isinstance(data, dict):
            logger.warning("%s 收到非 dict payload: %r", event_name, data)
            return None
        return data

    def _on_window_show(self, _data=None):
        self.show_normal()

    def _on_window_quit(self, _data=None):
        self.quit_app()

    def _on_open_settings(self, _data=None):
        settings_controller.open_settings_dialog(self)

    def _on_backup_memorial(self, _data=None):
        self.memorial_mgr.backup()

    def _on_restore_memorial(self, _data=None):
        self.memorial_mgr.restore()

    def _on_holiday_updated(self, data=None):
        data = self._as_dict(data, "HOLIDAY_UPDATED")
        if not isinstance(data, dict) or not isinstance(
                data.get("holiday_data"), dict):
            logger.warning("HOLIDAY_UPDATED 缺少 holiday_data dict: %r", data)
            return
        self.cal.set_net_holiday(data["holiday_data"])

    def _on_memorial_changed(self, data=None):
        data = self._as_dict(data, "MEMORIAL_CHANGED")
        memorials = config.get("memorial_days", [])
        self.cal.set_memorial_list(memorials)
        check_today = isinstance(data, dict) and bool(data.get("check_today", False))
        if len(memorials) > _DEFER_RESCHEDULE_THRESHOLD:
            logger.info(
                "纪念日数 %d 超过阈值 %d，延迟重排提醒调度",
                len(memorials), _DEFER_RESCHEDULE_THRESHOLD)
            QTimer.singleShot(
                0, lambda ct=check_today: self._deferred_reschedule(ct))
        else:
            self.reminder_mgr.reschedule(force=True, check_today=check_today)
        self._refresh_info_label()

    def _deferred_reschedule(self, check_today: bool) -> None:
        try:
            self.reminder_mgr.reschedule(
                force=True, check_today=check_today)
        except Exception:
            logger.exception("延迟重排提醒调度失败")

    def _on_memorial_remind_triggered(self, data=None):
        data = self._as_dict(data, "MEMORIAL_REMIND_TRIGGERED")
        if data is None:
            return
        hit_list = data.get("hit_list")
        today_str = data.get("today_str")
        if not (isinstance(hit_list, list) and hit_list
                and isinstance(today_str, str) and today_str):
            logger.warning(
                "MEMORIAL_REMIND_TRIGGERED 收到非法 payload: %r", data)
            # payload 非法时丢弃 pending，避免当日永久静默。
            try:
                self.reminder_mgr.discard_pending(reason="invalid_payload")
            except Exception:
                logger.exception("discard_pending 失败")
            return
        if not self._show_remind_dialog(hit_list, today_str):
            try:
                self.reminder_mgr.abandon_reminder(
                    today_str, reason="user_closed_or_error")
            except Exception:
                logger.exception("abandon_reminder 失败")
            return
        try:
            self.reminder_mgr.acknowledge_reminder(today_str)
        except Exception:
            logger.exception(
                "acknowledge_reminder 失败, today_str=%s", today_str)

    def _show_remind_dialog(self, hit_list, today_str):
        # 策略 A：打开时快照 current。弹窗模态期间用户无法改主题。
        try:
            dlg = MemorialRemindDialog(
                hit_list, parent=self, bundle=self.theme_mgr.current)
            try:
                result = dlg.exec()
            finally:
                dlg.deleteLater()
            return result == QDialog.DialogCode.Accepted
        except Exception:
            logger.exception("纪念日提醒弹窗异常，本次提醒放弃")
            return False

    def _on_update_available(self, data=None):
        self.update_ui.on_available(data)

    def _on_update_progress(self, data=None):
        self.update_ui.on_progress(data)

    def _on_update_failed(self, data=None):
        self.update_ui.on_failed(data)

    def _on_update_ready(self, installer: str = "", log_path: str = ""):
        """安装器已启动，主程序需要尽快退出。

        走 quit_app() 而不是 QApplication.quit()：前者会刷写配置、
        停止提醒/考勤/节假日/更新线程并解除事件订阅。安装器带
        CloseApplications=force 兜底，但主动退出能把配置丢失窗口
        压到最小。

        _quitting_for_update 让 closeEvent 放行：托盘模式下普通
        关闭会被 event.ignore() 吞掉，更新退出不能走那条路径。
        """
        logger.info("更新安装器已启动: %s，日志: %s", installer, log_path)
        self._quitting_for_update = True
        self.quit_app()

    # ==================== 8. Qt 事件重写 ====================
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
        # 主动退出（托盘退出 / 更新退出）时放行；否则托盘模式下
        # window_state.close_event 会 event.ignore() + hide()。
        if self._quitting or self._quitting_for_update:
            event.accept()
            return
        if not self.tray_mgr.available:
            self.quit_app()
            event.accept()
            return
        self.window_state.close_event(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        handler = None
        try:
            # 运行时读 current：菜单即时弹出，切主题后再弹会拿最新 QSS。
            menu.setStyleSheet(self.theme_mgr.current.qss.menu)
            handlers = {
                menu.addAction(tr("ctxmenu.minimize")): self._hide_or_minimize,
                menu.addAction(tr("ctxmenu.backup")): self.memorial_mgr.backup,
                menu.addAction(tr("ctxmenu.restore")): self.memorial_mgr.restore,
                menu.addAction(tr("ctxmenu.attendance")):
                    lambda: self.open_attendance_dialog("week"),
                menu.addAction(tr("ctxmenu.settings")):
                    lambda: settings_controller.open_settings_dialog(self),
                menu.addAction(tr("ctxmenu.quit")): self.quit_app,
            }
            handler = handlers.get(menu.exec(event.globalPos()))
        finally:
            menu.deleteLater()
        if handler is not None:
            handler()

    def _hide_or_minimize(self):
        if self.tray_mgr.available:
            self.hide()
        else:
            self.showMinimized()

    # ==================== 9. 月份导航 ====================
    def goto_today(self):
        t = QDate.currentDate()
        self.cal.setSelectedDate(t)
        self.cal.showSelectedDate()
        self.update_calendar_title()

    def prev_month(self):
        self.cal.showPreviousMonth()

    def next_month(self):
        self.cal.showNextMonth()
        self.update_calendar_title()

    def open_month_picker(self):
        dlg = MonthYearPickerDialog(
            self.cal.yearShown(), self.cal.monthShown(), self,
            bundle=self.theme_mgr.current)
        try:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            year, month = dlg.get_year_month()
        finally:
            dlg.deleteLater()
        self.cal.setCurrentPage(year, month)
        self.update_calendar_title()

    def update_calendar_title(self, *_args):
        self.cal_title.setText(tr("cal.title_format").format(
            year=self.cal.yearShown(), month=self.cal.monthShown()))

    # ==================== 10. 选中日详情 ====================
    def on_calendar_select_changed(self):
        self._refresh_info_label()

    def _refresh_info_label(self, resolver=None):
        """刷新详情面板。

        resolver 参数用于 apply_theme 路径：强制用"传入 bundle 的
        resolver"而非重新读 current，保证主题信号分发期间数据源与
        正在应用的 bundle 严格一致。

        完整信息挂到 toolTip：info_label 固定高度，内容过多时裁切，
        悬停可见全文。
        """
        sel_date = self.cal.selectedDate()
        today = QDate.currentDate()
        today_py = date(today.year(), today.month(), today.day())
        items = self.cal.memorial_items_for(sel_date)

        names = []
        countdowns = []
        for mem in items:
            name = mem.get("name") or tr("memorial.default_name")
            names.append(name)
            try:
                nxt = get_next_memorial_date(
                    mem, today_py, include_base=True, normalized=False)
            except Exception:
                logger.debug("详情面板计算下次纪念日失败: %r", mem, exc_info=True)
                nxt = None
            countdowns.append(
                (name, None if nxt is None else (nxt - today_py).days))

        parts = info_panel.build_info_parts(
            memorial_names=names,
            lunar_obj=get_lunar_by_datetime(
                (sel_date.year(), sel_date.month(), sel_date.day())),
            has_cnlunar=lunar_mod.HAS_CNLUNAR,
            memorial_next=tuple(countdowns),
            solar_date=date(sel_date.year(), sel_date.month(), sel_date.day()),
        )
        r = resolver if resolver is not None else self.theme_mgr.current.resolver
        html_text = info_panel.render_html(parts, resolver=r)
        if html_text is None:
            self.info_label.setTextFormat(Qt.TextFormat.PlainText)
            self.info_label.setText(tr(info_panel.placeholder_key(parts)))
            self.info_label.setToolTip("")
            return
        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.info_label.setText(html_text)
        self.info_label.setToolTip(html_text)

    # ==================== 11. 考勤打卡 ====================
    def open_attendance_menu(self):
        try:
            rec = self.attendance_store.get_record(
                QDate.currentDate().toPyDate())
        except Exception:
            logger.exception("读取今日考勤记录失败，按未打卡处理")
            rec = {}

        in_time = rec.get("in")
        out_time = rec.get("out")
        allow_punch_in = datetime.now().hour < PUNCH_IN_DEADLINE_HOUR

        menu = QMenu(self)
        # 全部 action 预置 None：try 内任意一步抛异常时后续判定不会
        # NameError，也不会因 None is None 误触发打卡分支。
        act_in = act_out = act_week = act_month = None
        chosen = None
        try:
            menu.setStyleSheet(self.theme_mgr.current.qss.menu)
            head = menu.addAction(self._attendance_status_text(rec))
            head.setEnabled(False)
            menu.addSeparator()

            if in_time:
                act_in = menu.addAction(
                    tr("attendance.punch_in_done_label").format(time=in_time))
            elif not allow_punch_in:
                act_in = menu.addAction(
                    tr("attendance.punch_in_expired").format(
                        deadline=self._punch_deadline_str()))
            else:
                act_in = menu.addAction(tr("attendance.punch_in"))
            if not allow_punch_in:
                act_in.setEnabled(False)

            act_out = menu.addAction(
                tr("attendance.punch_out_done_label").format(time=out_time)
                if out_time else tr("attendance.punch_out"))

            menu.addSeparator()
            act_week = menu.addAction(tr("attendance.stats_week"))
            act_month = menu.addAction(tr("attendance.stats_month"))
            chosen = menu.exec(self.btn_attendance.mapToGlobal(
                self.btn_attendance.rect().bottomLeft()))
        finally:
            menu.deleteLater()

        if chosen is not None and chosen is act_in:
            if self._confirm_overwrite("in", in_time):
                self._do_punch("in")
        elif chosen is not None and chosen is act_out:
            if self._confirm_overwrite("out", out_time):
                self._do_punch("out")
        elif chosen is not None and chosen is act_week:
            self.open_attendance_dialog("week")
        elif chosen is not None and chosen is act_month:
            self.open_attendance_dialog("month")

    @staticmethod
    def _punch_deadline_str() -> str:
        return f"{PUNCH_IN_DEADLINE_HOUR:02d}:00"

    def _confirm_overwrite(self, action: str, old_time) -> bool:
        if not old_time:
            return True
        now_hm = datetime.now().strftime("%H:%M")
        key = ("attendance.punch_in_update_confirm" if action == "in"
               else "attendance.punch_out_update_confirm")
        reply = QMessageBox.question(
            self, tr("msg.confirm"),
            tr(key).format(old=old_time, new=now_hm),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)   # 默认"否"，防回车误覆盖
        return reply == QMessageBox.StandardButton.Yes

    def _do_punch(self, action: str) -> None:
        # 数据层防御：即使 UI 层有 bug 也不允许 11:00 后写入上班卡。
        now = datetime.now()
        if action == "in" and now.hour >= PUNCH_IN_DEADLINE_HOUR:
            logger.warning(
                "上班打卡已过截止时间 %s（当前 %s），拒绝写入 action=%r",
                self._punch_deadline_str(), now.strftime("%H:%M"), action)
            QToolTip.showText(
                self.btn_attendance.mapToGlobal(
                    self.btn_attendance.rect().center()),
                tr("attendance.punch_in_expired").format(
                    deadline=self._punch_deadline_str()),
                self.btn_attendance)
            return
        try:
            hm, updated = self.attendance_store.punch(action)
        except Exception as e:
            logger.exception("考勤打卡保存失败")
            msg_error(self, tr("msg.error"),
                      tr("attendance.save_failed").format(error=e))
            return
        if action == "in":
            key = ("attendance.punch_in_update" if updated
                   else "attendance.punch_in_done")
        else:
            key = ("attendance.punch_out_update" if updated
                   else "attendance.punch_out_done")
        self._update_attendance_button()
        self.attendance_reminder.notify_punched(action)
        QToolTip.showText(
            self.btn_attendance.mapToGlobal(
                self.btn_attendance.rect().center()),
            tr(key).format(time=hm), self.btn_attendance)

    def _update_attendance_button(self) -> None:
        rec = self.attendance_store.get_record(
            QDate.currentDate().toPyDate())
        self.btn_attendance.setToolTip(self._attendance_status_text(rec))

    def open_attendance_dialog(self, mode: str = "week") -> None:
        dlg = AttendanceDialog(
            self.attendance_store, self,
            bundle=self.theme_mgr.current, mode=mode)
        try:
            dlg.exec()
        finally:
            dlg.deleteLater()

    def _on_attendance_remind(self, data=None):
        data = self._as_dict(data, "ATTENDANCE_REMIND_TRIGGERED")
        if not isinstance(data, dict):
            return
        kind = data.get("kind")
        if kind == "start":
            title = tr("attendance.remind_start_title")
            body = tr("attendance.remind_start_body")
        elif kind == "end":
            title = tr("attendance.remind_end_title")
            body = tr("attendance.remind_end_body")
        else:
            logger.warning("未知考勤提醒 kind: %r", kind)
            return
        if self.tray_mgr.show_message(title, body):
            return
        if self.isVisible():
            QToolTip.showText(
                self.btn_attendance.mapToGlobal(
                    self.btn_attendance.rect().topLeft()),
                f"{title}\n{body}", self.btn_attendance,
                msecShowTime=8000)
            return
        logger.info("考勤提醒（无托盘且窗口不可见，仅记录）: %s / %s",
                    title, body)

    @staticmethod
    def _attendance_status_text(rec: dict) -> str:
        in_t = rec.get("in") if rec else None
        out_t = rec.get("out") if rec else None
        if not in_t and not out_t:
            return tr("attendance.menu_status_none")
        if in_t and out_t:
            return tr("attendance.menu_status_done").format(
                in_time=in_t, out_time=out_t)
        if in_t:
            return tr("attendance.menu_status_in").format(time=in_t)
        return tr("attendance.menu_status_out").format(time=out_t)

    # ==================== 12. 显示 / 退出 ====================
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

        for fn, name in (
            (self.update_ui.close_progress, "关闭进度对话框"),
            (self.reminder_mgr.shutdown, "关闭提醒线程"),
            (self.attendance_reminder.shutdown, "关闭考勤提醒"),
            (self._unwire, "解除事件订阅"),
            (self.window_state.save_position, "保存窗口位置"),
            (self.holiday_mgr.shutdown, "关闭节假日线程"),
            (self.update_mgr.shutdown, "关闭更新线程"),
            (self._flush_config, "刷写配置"),
            (self._disconnect_theme_signal, "解除主题信号")
        ):
            try:
                fn()
            except Exception as e:
                logger.warning("%s失败: %s", name, e)

        QTimer.singleShot(0, QApplication.quit)
        try:
            self.tray_mgr.hide()
        except Exception:
            pass
        try:
            set_bundle_provider(None)
        except Exception:
            pass

    def _flush_config(self):
        config.flush()

    def _disconnect_theme_signal(self):
        try:
            self.theme_mgr.theme_changed.disconnect(self.apply_theme)
        except (TypeError, RuntimeError):
            pass