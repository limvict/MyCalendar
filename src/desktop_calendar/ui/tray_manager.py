# coding: utf-8
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import ConfigManager, get_logger
from desktop_calendar.contracts.event_bus import EventType, event_bus
from desktop_calendar.infrastructure.platform import auto_start
from desktop_calendar.ui.icon_manager import IconManager
from desktop_calendar.ui.theme import ThemeBundle

logger = get_logger()


class TrayManager(QObject):
    """系统托盘管理：图标、菜单、交互事件。"""

    def __init__(
        self,
        parent,
        config: ConfigManager,
        get_resource_path,
        bundle: ThemeBundle,
        on_open_pomodoro=None,
        on_check_update=None,
    ):
        super().__init__(parent)
        self._bundle = bundle
        self.parent = parent
        self.config = config
        self._get_resource = get_resource_path
        self.tray_icon = None
        self._menu = None
        self._act_show = None
        self._act_settings = None
        self._act_pomodoro = None
        self._act_autostart = None
        self._act_check_update = None
        self._act_quit = None
        self._on_open_pomodoro_callback = on_open_pomodoro
        self._on_check_update_callback = on_check_update
        self._init_tray()

    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(self.parent)

        # 直接通过管理器获取当前主题的托盘图标
        self.tray_icon.setIcon(self._build_tray_icon())

        self._menu = QMenu(self.parent)
        self._menu.setStyleSheet(self._bundle.qss.menu)
        # 菜单每次弹出前同步状态，避免显示「恢复窗口」时窗口其实已经在前台
        self._menu.aboutToShow.connect(self._refresh_menu_state)

        # 具名方法便于调试；若未来改为 event_bus.subscribe，unsubscribe 也能匹配。
        self._act_show = QAction(tr("tray.show"), self)
        self._act_show.setToolTip(tr("tray.hint_body"))
        self._act_show.triggered.connect(self._on_show_toggle)
        show_font = self._act_show.font()
        show_font.setBold(True)
        self._act_show.setFont(show_font)

        self._act_autostart = QAction(tr("tray.autostart"), self)
        self._act_autostart.setCheckable(True)
        self._act_autostart.setChecked(self._safe_autostart_state())
        self._act_autostart.setEnabled(auto_start.is_supported())
        self._act_autostart.triggered.connect(self._on_toggle_autostart)

        self._act_settings = QAction(tr("tray.settings"), self)
        self._act_settings.triggered.connect(self._on_open_settings)

        if self._on_open_pomodoro_callback is not None:
            self._act_pomodoro = QAction(tr("tray.pomodoro"), self)
            self._act_pomodoro.triggered.connect(self._on_open_pomodoro_callback)

        if self._on_check_update_callback is not None:
            self._act_check_update = QAction(tr("tray.check_update"), self)
            self._act_check_update.triggered.connect(self._on_check_update)

        self._act_quit = QAction(tr("tray.quit"), self)
        self._act_quit.triggered.connect(self._on_quit)

        self._menu.addAction(self._act_show)
        if self._act_pomodoro is not None:
            self._menu.addAction(self._act_pomodoro)
        self._menu.addSeparator()
        self._menu.addAction(self._act_autostart)
        self._menu.addAction(self._act_settings)
        if self._act_check_update is not None:
            self._menu.addAction(self._act_check_update)
        self._menu.addSeparator()
        self._menu.addAction(self._act_quit)
        self.tray_icon.setContextMenu(self._menu)
        self.tray_icon.activated.connect(self._on_activated)
        self.tray_icon.messageClicked.connect(self._on_message_clicked)
        self.tray_icon.show()

    def _build_tray_icon(self) -> QIcon:
        """构建当前主题对应的托盘图标。"""
        return IconManager.get_tray_icon(self._bundle)

    def _window_visible(self) -> bool:
        window = self.parent
        return bool(window is not None and window.isVisible() and not window.isMinimized())

    def _refresh_menu_state(self) -> None:
        """菜单弹出前刷新文案与勾选状态。"""
        if self._act_show is not None:
            self._act_show.setText(tr("tray.hide") if self._window_visible() else tr("tray.show"))
        if self._act_autostart is not None:
            self._act_autostart.setChecked(self._safe_autostart_state())

    @staticmethod
    def _safe_autostart_state() -> bool:
        try:
            return bool(auto_start.is_enabled())
        except Exception:
            logger.debug("读取开机自启状态失败", exc_info=True)
            return False

    def _on_show_toggle(self):
        if self._window_visible():
            event_bus.publish(EventType.WINDOW_HIDE)
        else:
            event_bus.publish(EventType.WINDOW_SHOW)

    def _on_toggle_autostart(self, checked: bool) -> None:
        if not auto_start.is_supported():
            self._act_autostart.setChecked(False)
            self.show_message(tr("autostart.window_title_hint"), tr("autostart.windows_only"))
            return
        try:
            auto_start.set_enabled(checked)
        except auto_start.AutoStartError as error:
            # 失败回滚勾选，用气泡告知，避免托盘菜单里弹模态框
            self._act_autostart.setChecked(not checked)
            if error.reason == "permission":
                message = tr("autostart.permission_error")
            else:
                message = tr("autostart.failed").format(error=error)
            self.show_message(tr("autostart.window_title_error"), message)
            return
        self._act_autostart.setChecked(checked)
        self.show_message(
            tr("autostart.window_title_success"),
            tr("autostart.enabled") if checked else tr("autostart.disabled"),
        )

    def _on_open_settings(self):
        event_bus.publish(EventType.OPEN_SETTINGS)

    def _on_check_update(self):
        if self._on_check_update_callback is None:
            return
        try:
            self._on_check_update_callback()
        except Exception:
            logger.exception("托盘检查更新失败")

    def _on_quit(self):
        event_bus.publish(EventType.WINDOW_QUIT)

    def _on_activated(self, reason):
        # 左键单击 / 双击都调出窗口；隐藏只走菜单，避免误触
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            event_bus.publish(EventType.WINDOW_SHOW)

    def _on_message_clicked(self):
        # 气泡点击只调出主窗口，不直接弹考勤菜单（易误触）。
        event_bus.publish(EventType.WINDOW_SHOW)

    def show_message(self, title: str, body: str, *, timeout_ms: int = 5000) -> bool:
        """显示托盘气泡。返回 False 表示托盘不可用 / 调用失败。"""
        if self.tray_icon is None or not self.tray_icon.isVisible():
            return False
        try:
            self.tray_icon.showMessage(
                title, body, QSystemTrayIcon.MessageIcon.Information, timeout_ms
            )
            return True
        except Exception:
            logger.debug("托盘气泡通知失败", exc_info=True)
            return False

    def update_theme(self, bundle: ThemeBundle) -> None:
        if bundle is None:
            return
        self._bundle = bundle
        if self._menu is not None:
            self._menu.setStyleSheet(bundle.qss.menu)
        if self.tray_icon is not None:
            try:
                # 主题切换时，自动获取新主题的托盘图标
                self.tray_icon.setIcon(self._build_tray_icon())
            except Exception:
                logger.debug("更新托盘图标失败", exc_info=True)

    def hide(self):
        if self.tray_icon:
            self.tray_icon.hide()

    @property
    def available(self) -> bool:
        # 系统运行期禁用托盘时 isVisible() 会翻 False，
        # closeEvent 应走"真正退出"而非最小化，否则窗口会失联。
        return self.tray_icon is not None and self.tray_icon.isVisible()
