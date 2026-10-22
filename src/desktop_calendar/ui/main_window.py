# coding: utf-8
"""
主窗口：UI 容器 + 跨模块调度。
"""
from PyQt6.QtCore import Qt, QTimer, QDate
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QMenu, QLabel, QGraphicsDropShadowEffect,
)

from desktop_calendar.config.manager import config, get_logger, get_resource_path
from desktop_calendar.core.memorial import normalize_memorial_days
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
from desktop_calendar.ui.dialogs import MonthYearPickerDialog, MemorialRemindDialog
from desktop_calendar.ui.style_manager import StyleManager
from desktop_calendar.ui.tray_manager import TrayManager
from desktop_calendar.ui.controllers.update_ui import UpdateUIController

logger = get_logger()


class MainWindow(QWidget):
    """UI 容器：只做布局装配与事件转发，业务逻辑在 manager / controller。"""

    # ==================== 1. 初始化 ====================
    def __init__(self, wiring=None):
        super().__init__()
        self._quitting = False
        self._shadow_effect = None
        self._init_config_on_start()
        set_language(config.get("language", "zh_CN"))

        self.style_mgr = StyleManager(config)
        self.sound_mgr = SoundManager(self, get_resource_path)
        self.window_state = WindowStateManager(self, config)
        self.holiday_mgr = HolidayManager(config, source_factory=make_qt_holiday_source)
        self.memorial_mgr = MemorialDataManager(self, config)
        self.reminder_mgr = ReminderManager(self, config, self.sound_mgr)
        self.tray_mgr = TrayManager(self, config, get_resource_path)
        self.update_mgr = UpdateManager(self)
        self.update_ui = UpdateUIController(
            parent_widget=self, update_mgr=self.update_mgr, window_quit_cb=self.quit_app)

        self._setup_window()
        self.build_ui()
        self.style_mgr.refresh_all(self)

        self._wiring = wiring
        if wiring is not None:
            wiring.connect(self)

        self._lang_cb = self._on_language_changed
        on_language_changed(self._lang_cb)
        self.destroyed.connect(self._detach_lang_listener)

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
            has_chinese_cal=lunar_mod.HAS_CHINESE_CAL,
        )
        self.holiday_mgr.fetch_current_year()
        self.update_calendar_title()
        self._refresh_info_label()

        # 农历索引预热放到后台 daemon 线程；singleShot 延后到事件循环
        # 首轮启动，让窗口先完成 show() / 首帧绘制再启动线程，避免
        # 线程启动抢占 GIL 拖慢首屏。
        QTimer.singleShot(0, self._warmup_lunar_cache)
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(5000)
        self._update_timer.timeout.connect(self.update_ui.check_on_start)
        self._update_timer.start()

    def _warmup_lunar_cache(self):
        # 预热本身在后台 daemon 线程跑；此处仅做参数准备与异常兜底。
        # 失败静默——预热只是优化，正式路径有完整降级。
        if not lunar_mod.HAS_CNLUNAR:
            return
        try:
            y = QDate.currentDate().year()
            lunar_mod.warmup_lunar_index_async([y, y + 1])
        except Exception:
            logger.warning("农历索引异步预热启动失败", exc_info=True)

    # ==================== 3. 窗口基础属性 ====================
    def _setup_window(self):
        th = self.style_mgr.current_theme
        self.setFixedSize(th["window_width"], th["window_height"])
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowSystemMenuHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setObjectName("MainWindow")
        self.setStyleSheet("#MainWindow { background: transparent; }")
        dwm.apply_dwm_fix(self)
        self.setFont(self.style_mgr.get_global_font())

    # ==================== 4. UI 构建 ====================
    def build_ui(self):
        th = self.style_mgr.current_theme
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
        self.btn_prev.setFixedWidth(36)
        self.btn_prev.clicked.connect(self.prev_month)
        self.cal_title = ClickLabel("")
        self.cal_title.setObjectName("cal_title")
        self.cal_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cal_title.clicked.connect(self.open_month_picker)
        self.btn_next = QPushButton(">")
        self.btn_next.setFixedWidth(36)
        self.btn_next.clicked.connect(self.next_month)
        top_layout.addWidget(self.btn_prev)
        top_layout.addWidget(self.cal_title, stretch=1)
        top_layout.addWidget(self.btn_next)
        cal_vl.addWidget(top_bar)

        self.calendar = LunarCalendarWidget(self, th, config.get("memorial_days", []))
        self.cal = self.calendar
        self.cal.currentPageChanged.connect(self.update_calendar_title)
        self.cal.selectionChanged.connect(self.on_calendar_select_changed)
        self.cal.setGridVisible(False)
        self.cal.setNavigationBarVisible(False)
        self.cal.setVerticalHeaderFormat(self.cal.VerticalHeaderFormat.NoVerticalHeader)
        cal_vl.addWidget(self.cal)

        self.info_label = QLabel()
        self.info_label.setObjectName("info_label")
        self.info_label.setFixedHeight(40)
        self.info_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setWordWrap(True)
        cal_vl.addWidget(self.info_label)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.btn_today = QPushButton(tr("btn.today"))
        self.btn_today.clicked.connect(self.goto_today)
        row2.addStretch(1)
        row2.addWidget(self.btn_today)
        cal_vl.addLayout(row2)

        self.stack.addWidget(self.calendar_container)
        content_layout.addWidget(self.stack)
        layout_main.addWidget(self.content_widget)
        self._apply_theme_geometry(th)
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """窗口级快捷键，避免日历控件吞键；模态对话框弹出时不会误触发。"""
        for seq, slot in (
            ("Ctrl+T", self.goto_today),
            ("Ctrl+,", lambda: settings_controller.open_settings_dialog(self)),
            ("Ctrl+Q", self.quit_app),
            ("Esc", self._on_escape),
        ):
            QShortcut(QKeySequence(seq), self).activated.connect(slot)

    def _on_escape(self):
        if self.tray_mgr.available:
            self.hide()

    # ==================== 5. 主题装配（启动与热更新共用） ====================
    def _apply_theme_geometry(self, th: dict):
        self.setFixedSize(th["window_width"], th["window_height"])
        shadow_size = th["shadow_size"]
        margin = shadow_size if shadow_size > 0 else 1
        if (main_layout := self.layout()) is not None:
            main_layout.setContentsMargins(margin, margin, margin, margin)
        self._apply_shadow(th)   # 内部自己读 shadow_size，不再传参
        try:
            self.cal.update_theme(th)
        except Exception:
            logger.exception("日历主题刷新失败")

    def _apply_shadow(self, th: dict):
        shadow_size = th["shadow_size"]
        if shadow_size > 0:
            if self._shadow_effect is None:
                effect = QGraphicsDropShadowEffect(self)
                effect.setOffset(0, 0)
                self.content_widget.setGraphicsEffect(effect)
                self._shadow_effect = effect
            self._shadow_effect.setBlurRadius(shadow_size)
            self._shadow_effect.setColor(QColor(th["shadow_color"]))
        elif self._shadow_effect is not None:
            # setGraphicsEffect(None) 由 Qt 接管删除旧 effect，勿再 deleteLater
            self.content_widget.setGraphicsEffect(None)
            self._shadow_effect = None

    # ==================== 6. 主题 / 语言刷新 ====================
    def _on_theme_reloaded(self, theme: dict):
        try:
            self.setFont(self.style_mgr.get_global_font())
            self._apply_theme_geometry(theme)
            self.style_mgr.refresh_all(self)
            self.update()
            logger.info("主题已应用: %s", theme.get("name", "?"))
        except Exception:
            logger.exception("主题热更新失败")

    def _on_language_changed(self, _lang: str):
        try:
            self.retranslate_ui()
        except Exception:
            logger.exception("语言切换后刷新主窗口 UI 失败")

    def retranslate_ui(self):
        """刷新所有依赖 tr() 的静态文本，不改变控件状态。"""
        self.setWindowTitle(tr("app.title"))
        self.btn_today.setText(tr("btn.today"))
        self.update_calendar_title()
        self._refresh_info_label()
        self.cal.retranslate_ui()
        self.cal.update()
        if callable(rt := getattr(self.tray_mgr, "retranslate_ui", None)):
            rt()

    def _detach_lang_listener(self, _obj=None):
        try:
            off_language_changed(self._lang_cb)
        except Exception:
            logger.debug("窗口销毁时卸载语言监听失败", exc_info=True)

    # ==================== 7. 事件总线回调（薄委托） ====================
    def _as_dict(self, data, event_name: str):
        """事件 payload 的类型归一：None / dict 直接返回，其余告警后返回 None。

        五个事件回调（HOLIDAY_UPDATED / MEMORIAL_CHANGED /
        MEMORIAL_REMIND_TRIGGERED / WINDOW_TOGGLE_TOPMOST /
        MEMORIAL_REMIND_TRIGGERED）都做同样的防御检查。
        """
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
        # payload 带 check_today=True 表示用户显式动作，需要立即命中今日
        check_today = isinstance(data, dict) and bool(data.get("check_today", False))
        self.reminder_mgr.reschedule(force=True, check_today=check_today)

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
            return
        try:
            self.reminder_mgr.acknowledge_reminder(today_str)
        except Exception:
            logger.exception("acknowledge_reminder 失败, today_str=%s", today_str)

    def _show_remind_dialog(self, hit_list: list, today_str: str) -> bool:
        """弹提醒框；异常时 abandon 并返回 False。"""
        try:
            dlg = MemorialRemindDialog(hit_list, self.style_mgr.current_theme, self)
            try:
                dlg.exec()
            finally:
                dlg.deleteLater()
            return True
        except Exception as e:
            logger.exception("纪念日提醒弹窗异常，本次提醒放弃")
            try:
                self.reminder_mgr.abandon_reminder(
                    today_str, reason=f"{type(e).__name__}: {e}")
            except Exception:
                logger.exception("异常路径 abandon_reminder 也失败")
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
        # 每次新建 QMenu，tr() 天然跟随当前语言
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu{background-color:#f7f3ed;border:1px solid #d8d2c5;border-radius:12px;padding:6px;}
            QMenu::item{padding:6px 20px;background:transparent;border-radius:8px;color:#444;}
            QMenu::item:selected{background:#d9e2d6;}
        """)
        handlers = {
            menu.addAction(tr("ctxmenu.minimize")): self._hide_or_minimize,
            menu.addAction(tr("ctxmenu.backup")): self.memorial_mgr.backup,
            menu.addAction(tr("ctxmenu.restore")): self.memorial_mgr.restore,
            menu.addAction(tr("ctxmenu.settings")): lambda: settings_controller.open_settings_dialog(self),
            menu.addAction(tr("ctxmenu.quit")): self.quit_app,
        }
        handler = handlers.get(menu.exec(event.globalPos()))
        if handler is not None:
            handler()

    def _hide_or_minimize(self):
        # 无托盘时 hide() 会导致窗口失联，改为最小化
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
        dlg = MonthYearPickerDialog(self.cal.yearShown(), self.cal.monthShown(), self)
        try:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            year, month = dlg.get_year_month()
        finally:
            dlg.deleteLater()
        self.cal.setCurrentPage(year, month)
        self.update_calendar_title()

    def update_calendar_title(self, *_args):
        """刷新标题。*_args 兼容 currentPageChanged 的 (year, month)。"""
        self.cal_title.setText(tr("cal.title_format").format(
            year=self.cal.yearShown(), month=self.cal.monthShown()))

    # ==================== 10. 选中日详情 ====================
    def on_calendar_select_changed(self):
        self._refresh_info_label()

    def _refresh_info_label(self):
        sel_date = self.cal.selectedDate()
        parts = info_panel.build_info_parts(
            sel_date=sel_date,
            memorial_names=self.cal.get_memorials_for_date(sel_date),
            lunar_obj=get_lunar_by_datetime(
                (sel_date.year(), sel_date.month(), sel_date.day())),
            has_cnlunar=lunar_mod.HAS_CNLUNAR,
        )
        html_text = info_panel.render_html(parts, theme=self.style_mgr.current_theme)
        if html_text is None:
            self.info_label.setTextFormat(Qt.TextFormat.PlainText)
            self.info_label.setText(tr(info_panel.placeholder_key(parts)))
            return
        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.info_label.setText(html_text)

    # ==================== 11. 窗口显示 ====================
    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ==================== 12. 退出 ====================
    def quit_app(self):
        # 幂等：托盘 / closeEvent / UPDATE_READY 可能重复触发
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
            (self._unwire, "解除事件订阅"),
            (lambda: off_language_changed(self._lang_cb), "解除语言监听"),
            (self.window_state.save_position, "保存窗口位置"),
            (self.holiday_mgr.shutdown, "关闭节假日线程"),
            (self.update_mgr.shutdown, "关闭更新线程"),
            (lambda: config.flush(), "刷写配置"),
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

    def _unwire(self):
        if self._wiring is not None:
            self._wiring.disconnect(self)