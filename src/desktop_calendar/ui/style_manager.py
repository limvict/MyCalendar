# coding: utf-8
import os
from PyQt6.QtCore import QObject, QFileSystemWatcher, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from desktop_calendar.config.config import ConfigManager, get_resource_path, get_logger
from desktop_calendar.config.constants import DEFAULT_THEME, load_theme

logger = get_logger()


class StyleManager(QObject):
    """UI 样式统一管理：主题加载、文件监视、热更新、全控件刷新。"""

    # 主题重载完成；main 侧订阅后刷新窗口
    theme_reloaded = pyqtSignal(dict)

    _DEBOUNCE_MS = 300

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self.theme = load_theme() or DEFAULT_THEME.copy()
        self._theme_path = get_resource_path("theme.json")

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_dir_changed)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._DEBOUNCE_MS)
        self._debounce.timeout.connect(self._do_reload)

        self._install_watch()

    # ---------------- 文件监视 ----------------
    def _install_watch(self):
        # 监视文件本身 + 所在目录：编辑器"先删后写"会丢掉文件监听，
        # 目录变动可以把它补回来。
        if os.path.exists(self._theme_path):
            self._watcher.addPath(self._theme_path)
        parent = os.path.dirname(self._theme_path) or "."
        if os.path.isdir(parent):
            self._watcher.addPath(parent)

    def _on_file_changed(self, path: str):
        # Qt 在文件被删除时会自动移除监听，若文件已重建需重新加回。
        if path not in self._watcher.files() and os.path.exists(path):
            self._watcher.addPath(path)
        self._debounce.start()

    def _on_dir_changed(self, _path: str):
        if (os.path.exists(self._theme_path)
                and self._theme_path not in self._watcher.files()):
            self._watcher.addPath(self._theme_path)
        self._debounce.start()

    def _do_reload(self):
        new_theme = load_theme(self._theme_path)
        if new_theme == self.theme:
            return
        self.theme = new_theme
        logger.info("检测到 theme.json 变更，已重载主题")
        self.theme_reloaded.emit(new_theme)

    # ---------------- 已有方法 ----------------
    @staticmethod
    def build_styles(theme: dict) -> dict:
        """
        把主题转为 QSS 字符串字典。纯函数，不接触 QWidget，可单测。

        key 约定（与 MainWindow 的控件一一对应）：
          content_widget / calendar / nav_buttons / cal_title / info_label
        """
        th = theme
        btn_bg = th.get("btn_bg", "#b4c3b0")
        btn_hover = th.get("btn_hover", "#98aa93")
        btn_pressed = th.get("btn_pressed", "#82947d")
        btn_text = th.get("btn_text", "#ffffff")
        title_color = th.get("date_text_color", "#444444")
        info_color = th.get("date_text_color", "#444444")

        return {
            "content_widget": f"""
            QWidget#content_widget {{
                background-color:{th['bg_main']};
                border-radius:{th['corner_radius']}px;
            }}
            """,
            "calendar": f"""
            QCalendarWidget {{ background-color:{th["bg_main"]}; font-family:"{th["font_family"]}"; }}
            QCalendarWidget QTableView {{
                background-color:{th["bg_main"]};
                selection-background-color:transparent;
                selection-color:transparent;
                gridline-color:transparent;
            }}
            QCalendarWidget QTableView QHeaderView::section {{
                background-color:{th["calendar_header_bg"]};
                color:{th["calendar_header_text"]};
                border:none;
                padding:5px 0px;
                font-size:{th['week_header_font_size']}px;
            }}
            """,
            "nav_buttons": f"""
            QPushButton{{
                background:{btn_bg};color:{btn_text};border:none;border-radius:10px;
                padding:6px;font-size:13px;
            }}
            QPushButton:hover{{background:{btn_hover};}}
            QPushButton:pressed{{background:{btn_pressed};}}
            """,
            "cal_title": (
                f"font-size:15px;font-weight:500;"
                f"background:transparent;color:{title_color};"
            ),
            "info_label": (
                f"QLabel{{color:{info_color};font-size:12px;padding:4px;}}"
            ),
        }
    
    def refresh_all(self, window):
        styles = self.build_styles(self.theme)
        window.content_widget.setStyleSheet(styles["content_widget"])
        window.cal.setStyleSheet(styles["calendar"])
        for btn in (window.btn_prev, window.btn_next, window.btn_today):
            btn.setStyleSheet(styles["nav_buttons"])
        window.cal_title.setStyleSheet(styles["cal_title"])
        window.info_label.setStyleSheet(styles["info_label"])

        window.cal.update_theme(self.theme)
        window.cal.update()
    
    def get_global_font(self) -> QFont:
        th = self.theme
        font = QFont()
        font.setFamily(th["font_family"].split(",")[0].strip())
        font.setPointSize(th["font_size"])
        return font

    @property
    def current_theme(self) -> dict:
        return self.theme