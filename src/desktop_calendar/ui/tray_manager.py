# coding: utf-8
from typing import Optional
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu

from desktop_calendar.config.manager import ConfigManager, get_logger
from desktop_calendar.contracts.event_bus import EventType, event_bus
from desktop_calendar.config.i18n import tr
from desktop_calendar.ui.theme import ThemeBundle
from desktop_calendar.ui.theme_icon import (
    resolve_icon_color, standard_fallback_icon, tinted_icon,
)
logger = get_logger()


class TrayManager(QObject):
    """系统托盘管理：图标、菜单、交互事件。"""

    def __init__(self, parent, config: ConfigManager, get_resource_path,
                 bundle: ThemeBundle):
        super().__init__(parent)
        self._bundle = bundle
        self.parent = parent
        self.config = config
        self._get_resource = get_resource_path
        self.tray_icon = None
        self._menu = None
        self._icon_path = self._get_resource("assets/app.ico")
        self._fallback_icon = standard_fallback_icon()
        self._act_show = None
        self._act_backup = None
        self._act_restore = None
        self._act_settings = None
        self._act_quit = None
        self._init_tray()

    def _init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(self.parent)
        self.tray_icon.setIcon(self._build_tray_icon())

        self._menu = QMenu(self.parent)
        self._menu.setStyleSheet(self._bundle.qss.menu)

        # 具名方法而非 lambda：便于断点调试，与 main.py 的订阅风格一致，
        # 未来若搬到 event_bus.subscribe 时 unsubscribe 才不会失效。
        self._act_show = QAction(tr("tray.show"), self)
        self._act_show.triggered.connect(self._on_show)

        self._act_backup = QAction(tr("tray.backup"), self)
        self._act_backup.triggered.connect(self._on_backup)

        self._act_restore = QAction(tr("tray.restore"), self)
        self._act_restore.triggered.connect(self._on_restore)

        self._act_settings = QAction(tr("tray.settings"), self)
        self._act_settings.triggered.connect(self._on_open_settings)

        self._act_quit = QAction(tr("tray.quit"), self)
        self._act_quit.triggered.connect(self._on_quit)

        self._menu.addAction(self._act_show)
        self._menu.addSeparator()
        self._menu.addAction(self._act_backup)
        self._menu.addAction(self._act_restore)
        self._menu.addSeparator()
        self._menu.addAction(self._act_settings)
        self._menu.addAction(self._act_quit)
        self.tray_icon.setContextMenu(self._menu)
        self.tray_icon.activated.connect(self._on_activated)
        self.tray_icon.messageClicked.connect(self._on_message_clicked)
        self.tray_icon.show()

    def _build_tray_icon(self) -> QIcon:
        return tinted_icon(
            self._icon_path,
            resolve_icon_color(self._bundle),
            fallback=self._fallback_icon,
        )
    
    def _on_show(self):
        event_bus.publish(EventType.WINDOW_SHOW)

    def _on_backup(self):
        event_bus.publish(EventType.BACKUP_MEMORIAL)

    def _on_restore(self):
        event_bus.publish(EventType.RESTORE_MEMORIAL)

    def _on_open_settings(self):
        event_bus.publish(EventType.OPEN_SETTINGS)

    def _on_quit(self):
        event_bus.publish(EventType.WINDOW_QUIT)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            event_bus.publish(EventType.WINDOW_SHOW)

    def _on_message_clicked(self):
        # 气泡被点击：把主窗口调出来，用户自己点"考勤"按钮打卡。
        # 不直接弹考勤菜单——气泡点击是系统级交互，弹菜单容易误触。
        event_bus.publish(EventType.WINDOW_SHOW)

    def show_message(self, title: str, body: str,
                     *, timeout_ms: int = 5000) -> bool:
        """显示托盘气泡。返回 False 表示托盘不可用 / 调用失败。

        调用方（主窗口）据此决定回退到窗口内 tooltip。
        """
        if self.tray_icon is None or not self.tray_icon.isVisible():
            return False
        try:
            self.tray_icon.showMessage(
                title, body,
                QSystemTrayIcon.MessageIcon.Information, timeout_ms)
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
                self.tray_icon.setIcon(self._build_tray_icon())
            except Exception:
                logger.debug("更新托盘图标失败", exc_info=True)

    def hide(self):
        if self.tray_icon:
            self.tray_icon.hide()

    @property
    def available(self) -> bool:
        # 若系统在运行期禁用了托盘（Linux 下可由用户/桌面环境动态改），
        # isVisible() 会翻 False，此时主窗口 closeEvent 应走"真正退出"
        # 分支而不是最小化到托盘 —— 否则窗口会失联。
        return self.tray_icon is not None and self.tray_icon.isVisible()