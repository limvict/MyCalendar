# coding: utf-8
"""主窗口：UI 容器 + 跨模块调度。"""
from PyQt6.QtCore import Qt, QTimer, QDate
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QMenu, QLabel, QGraphicsDropShadowEffect,
)

from desktop_calendar.config.manager import config, get_logger, get_resource_path
from datetime import date
from desktop_calendar.core.memorial import (
    normalize_memorial_days, get_next_memorial_date,
)
from desktop_calendar.config.i18n import (
    set_language, tr, on_language_changed, off_language_changed,
)
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.holiday_manager import HolidayManager
from desktop_calendar.core.lunar import get_lunar_by_datetime
from desktop_calendar.core.reminder_manager import ReminderManager
from desktop_calendar.infrastructure.audio import SoundManager
from desktop_calendar.infrastructure.network.qt_holiday_source import make_qt_holiday_source
from desktop_calendar.infrastructure.network.update_manager import UpdateManager
from desktop_calendar.infrastructure.platform import dwm
from desktop_calendar.ui import info_panel
from desktop_calendar.ui.calendar_widget import ClickLabel, LunarCalendarWidget
from desktop_calendar.ui.controllers import settings_controller
from desktop_calendar.ui.controllers.startup import check_dependencies
from desktop_calendar.ui.controllers.memorial_backup_ui import MemorialDataManager
from desktop_calendar.ui.controllers.window_state import WindowStateManager
from desktop_calendar.ui.dialogs import (
    MonthYearPickerDialog, MemorialRemindDialog, set_bundle_provider,
)
from desktop_calendar.ui.theme import ThemeManager, ThemeBundle
from desktop_calendar.ui.controllers.update_ui import UpdateUIController
from desktop_calendar.ui.tray_manager import TrayManager

logger = get_logger()


class MainWindow(QWidget):
    """UI 容器：只做布局装配与事件转发，业务逻辑在 manager / controller。"""

    # ==================== 1. 初始化 ====================
    def __init__(self, wiring=None):
        super().__init__()
        self._quitting = False
        self._shadow_effect = None
        self._shortcuts: list = []
        self._init_config_on_start()
        set_language(config.get("language", "zh_CN"))

        self.theme_mgr = ThemeManager(config)
        self.theme_mgr.theme_changed.connect(self.apply_theme)
        self.setFont(self.theme_mgr.current.fonts.global_)
        set_bundle_provider(lambda: self.theme_mgr.current)
        self.sound_mgr = SoundManager(self, get_resource_path)
        self.window_state = WindowStateManager(self, config)
        self.holiday_mgr = HolidayManager(config, source_factory=make_qt_holiday_source)
        self.memorial_mgr = MemorialDataManager(self, config)
        self.reminder_mgr = ReminderManager(self, config, self.sound_mgr)
        self.tray_mgr = TrayManager(
            self, config, get_resource_path,
            bundle=self.theme_mgr.current)
        self.update_mgr = UpdateManager(self)
        self.update_ui = UpdateUIController(
            parent_widget=self, update_mgr=self.update_mgr,
            window_quit_cb=self.quit_app)

        self._setup_window()
        self.build_ui()

        self._wiring = wiring
        if wiring is not None:
            wiring.connect(self)

        self._lang_cb = self._on_language_changed
        on_language_changed(self._lang_cb)
        self.destroyed.connect(self._detach_lang_listener)
        self.destroyed.connect(self._on_destroyed_cleanup)
        self._startup()

    # ==================== 2. 启动流程 ====================
    def _init_config_on_start(self):
        config.ensure_migrated()
        try:
            raw = config.get("memorial_days", [])
            normalized, _ = normalize_memorial_days(raw)
            if normalized != raw:
                config.set("memorial_days", normalized, save=False)
        except Exception:
            logger.warning("启动时 memorial_days 归一化失败", exc_info=True)
        if callable(save := getattr(config, "save_debounced", None)):
            save()

    def _startup(self):
        self.setWindowTitle(tr("app.title"))
        self.cal.set_net_holiday(self.holiday_mgr.apply_cached())
        self.cal.set_memorial_list(config.get("memorial_days", []))
        self.reminder_mgr.reschedule(check_today=True)
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
        # 从配置恢复置顶：WindowStateManager 在本方法之前构造，其
        # set_topmost 写入的 WindowStaysOnTopHint 会被下面的
        # setWindowFlags 整体覆盖，导致重启后置顶静默失效。
        if config.get("topmost", False):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setObjectName("MainWindow")
        self.setStyleSheet("#MainWindow { background: transparent; }")
        # 用 bg_main 亮度判断深色，避免主题名不是 "dark" 但实际是深色
        # 时 DWM 标题栏仍走浅色分支。
        bg = QColor(b.theme.get("bg_main", "#ffffff"))
        is_dark = bg.isValid() and bg.lightness() < 128
        dwm.apply_dwm_fix(self, dark_mode=is_dark)
        self.setFont(b.fonts.global_)

    # ==================== 4. UI 构建 ====================
    def build_ui(self):
        b = self.theme_mgr.current
        layout_main = QVBoxLayout(self)
        layout_main.setSpacing(0)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("content_widget")
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(8)

        self.stack = QStackedWidget()
        self.calendar_container = QWidget()
        cal_vl = QVBoxLayout(self.calendar_container)
        cal_vl.setContentsMargins(0, 0, 0, 0)
        cal_vl.setSpacing(8)

        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(4, 4, 4, 4)
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
        cal_vl.addWidget(self.cal)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)
        bottom_row.setContentsMargins(0, 0, 0, 0)

        self.info_label = QLabel()
        self.info_label.setObjectName("info_label")
        self.info_label.setFixedHeight(b.window.info_label_height)
        self.info_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setWordWrap(True)
        bottom_row.addWidget(self.info_label, stretch=1)

        self.btn_today = QPushButton(tr("btn.today"))
        self.btn_today.clicked.connect(self.goto_today)
        bottom_row.addWidget(
            self.btn_today, alignment=Qt.AlignmentFlag.AlignVCenter)

        cal_vl.addLayout(bottom_row)

        self.stack.addWidget(self.calendar_container)
        content_layout.addWidget(self.stack)
        layout_main.addWidget(self.content_widget)
        self._apply_theme_geometry(b)
        self._setup_shortcuts()
        self._refresh_styles(b)

    def _setup_shortcuts(self):
        """窗口级快捷键，避免日历控件吞键；模态对话框弹出时不会误触发。"""
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
        for btn in (self.btn_prev, self.btn_next, self.btn_today):
            btn.setStyleSheet(b.qss.nav_buttons)
        self.cal_title.setStyleSheet(b.qss.cal_title)
        self.info_label.setStyleSheet(b.qss.info_label)

    # ==================== 6. 主题 / 语言刷新 ====================
    def apply_theme(self, bundle):
        steps = (
            ("setFont", lambda: self.setFont(bundle.fonts.global_)),
            ("geometry", lambda: self._apply_theme_geometry(bundle)),
            ("styles", lambda: self._refresh_styles(bundle)),
            ("calendar", lambda: self.cal.apply_theme(bundle)),
            ("tray", lambda: self.tray_mgr.update_theme(bundle)),
            ("info", self._refresh_info_label),
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

    def _on_language_changed(self, _lang: str):
        try:
            self.retranslate_ui()
        except Exception:
            logger.exception("语言切换后刷新主窗口 UI 失败")

    def retranslate_ui(self):
        self.setWindowTitle(tr("app.title"))
        self.btn_today.setText(tr("btn.today"))
        self.update_calendar_title()
        self._refresh_info_label()
        self.cal.retranslate_ui()
        if callable(rt := getattr(self.tray_mgr, "retranslate_ui", None)):
            rt()

    def _detach_lang_listener(self, _obj=None):
        try:
            off_language_changed(self._lang_cb)
        except Exception:
            logger.debug("窗口销毁时卸载语言监听失败", exc_info=True)

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
        self.cal.set_memorial_list(config.get("memorial_days", []))
        check_today = isinstance(data, dict) and bool(data.get("check_today", False))
        self.reminder_mgr.reschedule(force=True, check_today=check_today)
        self._refresh_info_label()

    def _on_memorial_remind_triggered(self, data=None):
        data = self._as_dict(data, "MEMORIAL_REMIND_TRIGGERED")
        if data is None:
            return
        hit_list = data.get("hit_list")
        today_str = data.get("today_str")
        if not (isinstance(hit_list, list) and hit_list
                and isinstance(today_str, str) and today_str):
            logger.warning("MEMORIAL_REMIND_TRIGGERED 收到非法 payload: %r", data)
            return
        if not self._show_remind_dialog(hit_list, today_str):
            # 用户主动关闭或异常，视为放弃本次提醒，解除 pending 锁。
            # 异常路径不在 _show_remind_dialog 内调用 abandon_reminder，
            # 避免双重解锁。
            try:
                self.reminder_mgr.abandon_reminder(
                    today_str, reason="user_closed_or_error")
            except Exception:
                logger.exception("abandon_reminder 失败")
            return
        try:
            self.reminder_mgr.acknowledge_reminder(today_str)
        except Exception:
            logger.exception("acknowledge_reminder 失败, today_str=%s", today_str)

    def _show_remind_dialog(self, hit_list, today_str):
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

    def _on_toggle_topmost(self, data=None):
        data = self._as_dict(data, "WINDOW_TOGGLE_TOPMOST")
        if data is None or "enable" not in data:
            logger.warning("WINDOW_TOGGLE_TOPMOST 缺少 enable: %r", data)
            return
        enable = bool(data["enable"])
        self.window_state.set_topmost(enable)
        config.set("topmost", enable, save=True)
        self.tray_mgr.update_topmost_check(enable)

    def _on_update_available(self, data=None):
        self.update_ui.on_available(data)

    def _on_update_progress(self, data=None):
        self.update_ui.on_progress(data)

    def _on_update_failed(self, data=None):
        self.update_ui.on_failed(data)

    def _on_update_ready(self, _data=None):
        if not self._quitting:
            self.update_ui.on_ready(_data)

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
        if not self.tray_mgr.available:
            self.quit_app()
            event.accept()
            return
        self.window_state.close_event(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        handler = None
        try:
            menu.setStyleSheet(self.theme_mgr.current.qss.menu)
            handlers = {
                menu.addAction(tr("ctxmenu.minimize")): self._hide_or_minimize,
                menu.addAction(tr("ctxmenu.backup")): self.memorial_mgr.backup,
                menu.addAction(tr("ctxmenu.restore")): self.memorial_mgr.restore,
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

    def _refresh_info_label(self):
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
        html_text = info_panel.render_html(
            parts, resolver=self.theme_mgr.current.resolver)
        if html_text is None:
            self.info_label.setTextFormat(Qt.TextFormat.PlainText)
            self.info_label.setText(tr(info_panel.placeholder_key(parts)))
            self.info_label.setToolTip("")
            return
        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.info_label.setText(html_text)

    # ==================== 11. 显示 / 退出 ====================
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
            (self._unwire, "解除事件订阅"),
            (self._detach_lang_listener, "解除语言监听"),
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

    def _unwire(self):
        if self._wiring is not None:
            self._wiring.disconnect(self)