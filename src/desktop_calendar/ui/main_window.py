# coding: utf-8
"""
主窗口：UI 容器 + 跨模块调度。

职责：
  - 窗口基础属性（无边框、透明、字体、DWM 修复）
  - UI 构建（顶栏、日历、info_label、阴影）
  - Qt 事件重写（paint / mouse / close / contextMenu）
  - 事件总线回调（薄委托：一行转发给管理器或控制器）
  - i18n / 主题刷新入口
  - 退出清理

业务逻辑全部下沉到 manager / controller。本类方法超过 ~15 行
通常说明有东西该抽出去。
"""
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QDate
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QPushButton, QMenu, QLabel,
    QGraphicsDropShadowEffect, QMessageBox, QProgressDialog,
)

from desktop_calendar.config.config import config, get_logger, get_resource_path
from desktop_calendar.config.i18n import (
    set_language, tr, on_language_changed, off_language_changed,
)
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.holiday_manager import HolidayManager
from desktop_calendar.core.lunar import get_lunar_by_datetime
from desktop_calendar.core.reminder_manager import ReminderManager
from desktop_calendar.infrastructure.audio import SoundManager
from desktop_calendar.infrastructure.network.qt_holiday_source import QtHolidaySource
from desktop_calendar.infrastructure.network.updater import UpdateManager
from desktop_calendar.infrastructure.platform import dwm
from desktop_calendar.ui import info_panel
from desktop_calendar.ui.calendar_widget import ClickLabel, LunarCalendarWidget
from desktop_calendar.ui.controllers import settings_controller
from desktop_calendar.ui.controllers.dependency_check import check_dependencies
from desktop_calendar.ui.controllers.memorial_data_manager import MemorialDataManager
from desktop_calendar.ui.controllers.window_state import WindowStateManager
from desktop_calendar.ui.dialogs import (
    MonthYearPickerDialog, MemorialRemindDialog, msg_error,
)
from desktop_calendar.ui.style_manager import StyleManager
from desktop_calendar.ui.tray_manager import TrayManager
from desktop_calendar.utils.helpers import init_config_defaults

logger = get_logger()


class MainWindow(QWidget):
    """UI 容器：只做布局装配与事件转发，业务逻辑在 manager / controller。"""

    def __init__(self, wiring=None):
        super().__init__()
        # 幂等退出守卫：托盘退出 / closeEvent / UPDATE_READY 可能重复触发
        self._quitting = False
        self._update_progress_dlg: Optional[QProgressDialog] = None
        # 用户主动关掉进度框后置位：同一次下载内不再自动弹回来
        self._update_progress_dismissed = False
        init_config_defaults(config)
        set_language(config.get("language", "zh_CN"))

        self.style_mgr = StyleManager(config)
        self.sound_mgr = SoundManager(self, get_resource_path)
        self.window_state = WindowStateManager(self, config)
        self.holiday_mgr = HolidayManager(config, source_factory=QtHolidaySource)
        self.memorial_mgr = MemorialDataManager(self, config)
        self.reminder_mgr = ReminderManager(self, config, self.sound_mgr)
        self.tray_mgr = TrayManager(self, config, get_resource_path)
        self.update_mgr = UpdateManager(self)
        self.style_mgr.theme_reloaded.connect(self._on_theme_reloaded)

        self._setup_window()
        self.build_ui()
        self.style_mgr.refresh_all(self)
        self._wiring = wiring
        if wiring is not None:
            wiring.connect(self)

        self._lang_cb = self._on_language_changed
        on_language_changed(self._lang_cb)
        self.destroyed.connect(self._detach_main_lang_listener)

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
        self.on_calendar_select_changed()

        # 首次构建约 400+ 天扫描，放到事件循环下一轮做，避免首屏卡顿
        QTimer.singleShot(0, self._warmup_lunar_cache)
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(5000)
        self._update_timer.timeout.connect(self._check_update_on_start)
        self._update_timer.start()

    # ===== 启动预热 =====
    def _warmup_lunar_cache(self):
        try:
            if not lunar_mod.HAS_CNLUNAR:
                return
            today = QDate.currentDate()
            # 农历年与公历年大致重合，预取当年与次年覆盖绝大多数范围
            lunar_mod.warmup_lunar_index(
                [today.year(), today.year() + 1])
        except Exception:
            logger.warning("农历索引预热失败", exc_info=True)

    # ===== 窗口基础属性 =====
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

    # ===== UI 构建 =====
    def build_ui(self):
        th = self.style_mgr.current_theme
        layout_main = QVBoxLayout(self)

        shadow_size = th["shadow_size"]
        margin = shadow_size if shadow_size > 0 else 1
        layout_main.setContentsMargins(margin, margin, margin, margin)
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

        self.calendar = LunarCalendarWidget(
            self, th, config.get("memorial_days", []))
        self.cal = self.calendar
        self.cal.currentPageChanged.connect(self.update_calendar_title)
        self.cal.selectionChanged.connect(self.on_calendar_select_changed)
        self.cal.setGridVisible(False)
        self.cal.setNavigationBarVisible(False)
        self.cal.setVerticalHeaderFormat(
            self.cal.VerticalHeaderFormat.NoVerticalHeader)
        cal_vl.addWidget(self.cal)

        self.info_label = QLabel()
        self.info_label.setObjectName("info_label")
        self.info_label.setFixedHeight(40)
        self.info_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setWordWrap(True)
        cal_vl.addWidget(self.info_label)

        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(10)
        self.btn_today = QPushButton(tr("btn.today"))
        self.btn_today.clicked.connect(self.goto_today)
        row2_layout.addStretch(1)
        row2_layout.addWidget(self.btn_today)
        cal_vl.addLayout(row2_layout)

        self.stack.addWidget(self.calendar_container)
        content_layout.addWidget(self.stack)
        layout_main.addWidget(self.content_widget)

        if shadow_size > 0:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(shadow_size)
            shadow.setColor(QColor(th["shadow_color"]))
            shadow.setOffset(0, 0)
            self.content_widget.setGraphicsEffect(shadow)
        else:
            self.content_widget.setGraphicsEffect(None)
            
        self._setup_shortcuts()

    def paintEvent(self, event):
        # WA_TranslucentBackground 已处理透明背景，无需额外 fillRect
        super().paintEvent(event)

    # ===== 事件总线回调（薄委托） =====
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
        if not isinstance(data, dict) or "data" not in data:
            logger.warning("HOLIDAY_UPDATED 收到非法 payload: %r", data)
            return
        self.cal.set_net_holiday(data["data"])

    def _on_memorial_changed(self, data: dict = None):
        self.cal.set_memorial_list(config.get("memorial_days", []))
        # payload 带 check_today=True 表示用户显式动作（如恢复数据），
        # 需要立即检查今日命中；普通刷新走静默重排。
        check_today = (isinstance(data, dict)
                       and bool(data.get("check_today", False)))
        self.reminder_mgr.reschedule(force=True, check_today=check_today)

    def _on_memorial_remind_triggered(self, data: dict = None):
        """提醒到点：由 presentation 负责弹窗，关闭后回写确认。"""
        if not isinstance(data, dict):
            return
        hit_list = data.get("hit_list") or []
        today_str = data.get("today_str") or ""
        if not hit_list or not today_str:
            logger.warning(
                "MEMORIAL_REMIND_TRIGGERED 收到非法 payload: %r", data)
            return
        try:
            dlg = MemorialRemindDialog(
                hit_list, self.style_mgr.current_theme, self)
            dlg.exec()
            dlg.deleteLater()
        except Exception:
            logger.exception("纪念日提醒弹窗异常，本次提醒放弃")
            return
        # 弹窗正常关闭（OK / Esc / 叉）均视为“用户已看到”，
        # 只有构造/exec 抛异常才不确认 —— 与用户选择一致。
        self.reminder_mgr.acknowledge_reminder(today_str)
    
    def _on_toggle_topmost(self, data=None):
        if not isinstance(data, dict) or "enable" not in data:
            logger.warning("WINDOW_TOGGLE_TOPMOST 收到非法 payload: %r", data)
            return
        enable = bool(data["enable"])
        self.window_state.set_topmost(enable)
        config.set("topmost", enable, save=True)
        self.tray_mgr.update_topmost_check(enable)

    # ===== Qt 事件重写 =====
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
        # 每次显示都新建 QMenu / QAction，tr() 天然跟随当前语言。
        # 色值与 dialogs/ 下对话框保持一致，不跟随主窗口主题。
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu{background-color:#f7f3ed;border:1px solid #d8d2c5;border-radius:12px;padding:6px;}
            QMenu::item{padding:6px 20px;background:transparent;border-radius:8px;color:#444;}
            QMenu::item:selected{background:#d9e2d6;}
        """)
        act_min    = menu.addAction(tr("ctxmenu.minimize"))
        act_backup = menu.addAction(tr("ctxmenu.backup"))
        act_restore= menu.addAction(tr("ctxmenu.restore"))
        act_set    = menu.addAction(tr("ctxmenu.settings"))
        act_exit   = menu.addAction(tr("ctxmenu.quit"))
        action = menu.exec(event.globalPos())

        if action == act_min:
            # 无托盘时 hide() 会导致窗口失联，改为最小化
            if self.tray_mgr.available:
                self.hide()
            else:
                self.showMinimized()
        elif action == act_backup:
            self.memorial_mgr.backup()
        elif action == act_restore:
            self.memorial_mgr.restore()
        elif action == act_set:
            settings_controller.open_settings_dialog(self)
        elif action == act_exit:
            self.quit_app()
  
    # ===== 月份导航 =====
    def goto_today(self):
        t = QDate.currentDate()
        self.cal.setSelectedDate(t)
        self.cal.showSelectedDate()
        self.update_calendar_title()

    def prev_month(self):
        self.cal.showPreviousMonth()
        self.update_calendar_title()

    def next_month(self):
        self.cal.showNextMonth()
        self.update_calendar_title()

    def open_month_picker(self):
        dlg = MonthYearPickerDialog(
            self.cal.yearShown(), self.cal.monthShown(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        year, month = dlg.get_year_month()
        # setCurrentPage 触发 currentPageChanged → 自动重建缓存
        self.cal.setCurrentPage(year, month)
        self.update_calendar_title()

    def update_calendar_title(self, *_args):
           """刷新标题。*_args 用于兼容 currentPageChanged 的 (year, month)。"""
           self.cal_title.setText(tr("cal.title_format").format(
               year=self.cal.yearShown(),
               month=self.cal.monthShown(),
           ))

    # ===== 选中日详情 =====
    def on_calendar_select_changed(self):
        self._refresh_info_label()

    def _refresh_info_label(self):
        """按当前选中日重建 info_label。不改变任何选中态。"""
        sel_date = self.cal.selectedDate()
        memorial_names = self.cal.get_memorials_for_date(sel_date)
        lunar = get_lunar_by_datetime(
            (sel_date.year(), sel_date.month(), sel_date.day()))

        parts = info_panel.build_info_parts(
            sel_date=sel_date,
            memorial_names=memorial_names,
            lunar_obj=lunar,
            has_cnlunar=lunar_mod.HAS_CNLUNAR,
        )
        html_text = info_panel.render_html(
            parts, theme=self.style_mgr.current_theme)
        if html_text is None:
            self.info_label.setTextFormat(Qt.TextFormat.PlainText)
            self.info_label.setText(tr(info_panel.placeholder_key(parts)))
            return
        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.info_label.setText(html_text)

    # ===== 主题 / 语言 =====
    def _on_theme_reloaded(self, _theme: dict):
        """主题热更新：只刷 QSS + 重绘，不重建 UI（避免闪烁和状态丢失）。"""
        try:
            self.setFont(self.style_mgr.get_global_font())
            self.style_mgr.refresh_all(self)
            logger.info("主题已应用")
        except Exception:
            logger.exception("主题热更新失败")

    def _on_language_changed(self, _lang: str):
        try:
            self.retranslate_ui()
        except Exception:
            logger.exception("语言切换后刷新主窗口 UI 失败")
            
    def _detach_main_lang_listener(self, _obj=None):
        """窗口析构时卸载语言监听。幂等。"""
        try:
            off_language_changed(self._lang_cb)
        except Exception:
            logger.debug("窗口销毁时卸载语言监听失败", exc_info=True)

    def retranslate_ui(self):
        """刷新所有依赖 tr() 的静态文本。不改变任何控件状态。"""
        self.setWindowTitle(tr("app.title"))
        self.btn_today.setText(tr("btn.today"))
        self.update_calendar_title()
        # info_label 的 HTML 由 tr 拼接，需要按新语言重建
        self._refresh_info_label()
        self.cal.retranslate_ui()
        self.cal.update()
        # tray_manager.py 未同步更新时静默跳过（getattr 防御）
        tray_retranslate = getattr(self.tray_mgr, "retranslate_ui", None)
        if callable(tray_retranslate):
            tray_retranslate()

    # ===== 其他 =====
    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _check_update_on_start(self):
        if self._quitting:
            return
        # 先处理上次更新遗留的失败标记：同步阻塞弹窗，
        # 用户处理完（或点忽略）后才继续自动检查新版本。
        retry_ver = ""
        try:
            retry_ver = self._handle_pending_update_failure()
        except Exception:
            logger.exception("处理上次更新失败标记异常")
        if self._quitting:
            return
        try:
            started = self.update_mgr.check_async(retry_version=retry_ver)
            if retry_ver and not started:
                # 用户在重试时，检查却发不出去（非打包 / 占位符 URL /
                # 已有检查在跑），必须明确告知，不能静默。
                msg_error(
                    self, tr("update.title"),
                    tr("update.failed").format(
                        error=tr("update.cannot_start")))
        except Exception:
            logger.exception("启动时检查更新失败")

    def _handle_pending_update_failure(self) -> str:
        """
        返回用户选择重试的版本号；空串表示无重试请求。
        """
        state = self.update_mgr.consume_pending_failure()
        if not state:
            return ""

        version = state.get("version") or "?"
        reason_key = {
            "backup_failed":         "update.reason.backup_failed",
            "install_failed":        "update.reason.install_failed",
            "probe_failed":          "update.reason.probe_failed",
            "rollback_failed":       "update.reason.rollback_failed",
            "probe_rollback_failed": "update.reason.probe_rollback_failed",
        }.get(state.get("reason", ""))
        reason_text = tr(reason_key) if reason_key else (state.get("reason") or "?")
        log_path = state.get("log_path") or "-"

        box = QMessageBox(self)
        box.setWindowTitle(tr("update.title"))
        box.setText(tr("update.prev_failed").format(version=version))
        box.setInformativeText(tr("update.prev_failed_detail").format(
            reason=reason_text, log=log_path))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Ignore)
        box.button(QMessageBox.StandardButton.Retry).setText(tr("update.retry"))
        box.button(QMessageBox.StandardButton.Ignore).setText(
            tr("update.ignore_version"))

        choice = box.exec()
        if choice == QMessageBox.StandardButton.Ignore:
            config.set("update_skipped_version", version, save=True)
            logger.info(f"用户忽略版本 {version} 的失败提示")
            return ""
        logger.info(f"用户选择重试版本 {version} 的更新")
        return version

    # ===== 自动更新 =====
    def _on_update_available(self, data: dict = None):
        if not isinstance(data, dict):
            return
        info = data.get("info") or {}
        version = info.get("version", "?")
        notes = info.get("release_notes", "")

        box = QMessageBox(self)
        box.setWindowTitle(tr("update.title"))
        box.setText(tr("update.available").format(version=version))
        if notes:
            box.setInformativeText(notes)
        box.setIcon(QMessageBox.Icon.Information)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText(
            tr("update.download"))
        box.button(QMessageBox.StandardButton.No).setText(
            tr("update.later"))

        if box.exec() == QMessageBox.StandardButton.Yes:
            started = self.update_mgr.download_and_apply_async()
            if not started:
                msg_error(
                    self, tr("update.title"),
                    tr("update.failed").format(
                        error=tr("update.cannot_start")))

    def _on_update_progress(self, data: dict = None):
        """下载进度：首次到达时创建 QProgressDialog，之后更新数值。"""
        if not isinstance(data, dict):
            return
        try:
            pct = int(data.get("percent", -1))
        except (TypeError, ValueError, OverflowError):
            return
        if pct < 0:
            return

        if self._update_progress_dlg is None:
            # 用户已经手动关过一次 → 本次下载不再弹回来打扰
            if self._update_progress_dismissed:
                return
            dlg = QProgressDialog(self)
            dlg.setWindowTitle(tr("update.title"))
            dlg.setLabelText(tr("update.downloading"))
            dlg.setRange(0, 100)
            dlg.setValue(0)
            dlg.setCancelButton(None)         # 不加取消按钮，避免用户误解
            dlg.setMinimumDuration(0)
            dlg.setWindowModality(Qt.WindowModality.WindowModal)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            dlg.canceled.connect(self._on_update_progress_canceled)
            self._update_progress_dlg = dlg
            dlg.show()
        self._update_progress_dlg.setValue(min(100, max(0, pct)))

    def _on_update_progress_canceled(self):
        """
        用户 Esc / 点了窗口关闭按钮：仅隐藏进度框，不中断后台下载。

        QProgressDialog 的 canceled 信号在用户主动关闭时发出（不是
        程序调用 close()）。先清引用再 close()，即使 Qt 再发一次
        canceled 也会因为 _update_progress_dlg 已是 None 而早退。
        """
        dlg = self._update_progress_dlg
        self._update_progress_dlg = None
        self._update_progress_dismissed = True
        if dlg is not None:
            try:
                dlg.close()
            except Exception:
                pass

    def _close_update_progress(self):
        # 先摘引用，避免 close() 触发 canceled 时二次进入
        dlg = self._update_progress_dlg
        self._update_progress_dlg = None
        # 程序主动关闭（下载完成/失败/退出）：复位 dismissed，
        # 让下一次“立即更新”重新弹出进度条。
        self._update_progress_dismissed = False
        if dlg is not None:
            try:
                dlg.close()
            except Exception:
                pass

    def _on_update_failed(self, data: dict = None):
        data = data or {}
        err = data.get("error", "")
        logger.warning(f"更新失败: {err}")
        self._close_update_progress()
        if data.get("stage") == "download":
            msg_error(self, tr("update.title"),
                      tr("update.failed").format(error=err))

    def _on_update_ready(self, _data=None):
        # 已在退出流程则不再弹窗（此时窗口可能已 hide）
        if self._quitting:
            return
        self._close_update_progress()
        # 下载完成，替换脚本已启动。先让用户知道即将重启，
        # 然后退出主程序，把舞台交给 bat。
        QMessageBox.information(
            self,
            tr("update.title"),
            tr("update.applying"),
        )
        self.quit_app()
   
    def _setup_shortcuts(self):
        """
        窗口级快捷键。

        用 QShortcut 而非 keyPressEvent：前者不受焦点位置影响，日历
        控件吃掉按键也不会导致快捷键失效。上下文默认 WindowShortcut，
        模态对话框弹出时主窗口不是活动窗口，不会误触发。
        """
        for seq, slot in (
            ("Ctrl+T", self.goto_today),
            ("Ctrl+,", lambda: settings_controller.open_settings_dialog(self)),
            ("Ctrl+Q", self.quit_app),
            ("Esc",     self._on_escape),
        ):
            QShortcut(QKeySequence(seq), self).activated.connect(slot)

    def _on_escape(self):
        """Esc：隐藏到托盘。无托盘时不动作，避免窗口失联。"""
        if self.tray_mgr.available:
            self.hide()     
    # ===== 退出 =====
    def quit_app(self):
        # 幂等：托盘退出 / closeEvent / UPDATE_READY 可能重复触发。
        # 首次进入后立即置位，后续调用直接返回，防止
        # holiday_mgr.shutdown / update_mgr.shutdown 被重复执行。
        if self._quitting:
            return
        self._quitting = True

        # 停掉启动检查更新定时器（若 5 秒还没到就退出）
        try:
            if getattr(self, "_update_timer", None) is not None:
                self._update_timer.stop()
        except Exception:
            pass

        # 关掉下载进度对话框（若有）；独立成块，不与 timer 耦合
        try:
            self._close_update_progress()
        except Exception:
            pass
        try:
            if self._wiring is not None:
                self._wiring.disconnect(self)
        except Exception as e:
            logger.warning("解除事件订阅失败: %s", e, exc_info=True)
        try:
            off_language_changed(self._lang_cb)
        except Exception as e:
            logger.warning("解除语言切换监听失败: %s", e)
        self.window_state.save_position()
        try:
            self.holiday_mgr.shutdown()
        except Exception as e:
            logger.warning("关闭节假日线程失败: %s", e)
        # 关闭更新线程：否则退出时可能报
        # "QThread: Destroyed while thread is still running"
        try:
            self.update_mgr.shutdown()
        except Exception as e:
            logger.warning("关闭更新线程失败: %s", e)
        # 强制同步落盘：避免防抖定时器未触发就退出导致配置丢失/半写
        try:
            config.flush()
        except Exception as e:
            logger.warning("刷写配置失败: %s", e)
        QTimer.singleShot(0, QApplication.quit)