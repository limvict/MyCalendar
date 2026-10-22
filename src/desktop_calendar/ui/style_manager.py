# coding: utf-8
import json
import os
from typing import Optional
from PyQt6.QtCore import QObject, QFileSystemWatcher, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from desktop_calendar.config.manager import ConfigManager, get_resource_path, get_logger
from desktop_calendar.config.constants import DEFAULT_THEME

logger = get_logger()

def load_theme(theme_path: Optional[str] = None) -> dict:
    """加载主题配置：优先读取外部文件，失败则返回默认主题。

    从 config.constants 迁入。逻辑不变。
    """
    theme = dict(DEFAULT_THEME)

    if theme_path is None:
        try:
            theme_path = get_resource_path("theme.json")
        except Exception as e:
            logger.warning(f"获取默认主题路径失败，使用默认主题：{e}")
            return theme
    if not theme_path or not os.path.exists(theme_path):
        logger.warning(f"主题文件 {theme_path!r} 不存在，使用默认主题")
        return theme
    try:
        with open(theme_path, "r", encoding="utf-8") as f:
            custom_theme = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"主题文件读取或解析失败，使用默认主题：{e}")
        return theme
    except Exception as e:
        logger.warning(f"加载主题文件时发生未知错误，使用默认主题：{e}")
        return theme

    if not isinstance(custom_theme, dict):
        logger.warning(
            f"主题文件内容不是 JSON 对象（实际为 {type(custom_theme).__name__}），"
            f"使用默认主题")
        return theme

    unknown_keys = set(custom_theme) - set(DEFAULT_THEME)
    if unknown_keys:
        logger.warning(
            f"主题文件中存在未知配置项，已忽略：{', '.join(sorted(unknown_keys))}")

    for key, value in custom_theme.items():
        if key not in DEFAULT_THEME:
            continue
        if value is None:
            logger.warning(f"主题配置项 {key!r} 为 None，已保留默认值")
            continue
        coerced = _coerce_theme_value(key, value)
        if coerced is None:
            logger.warning(
                f"主题配置项 {key!r} 的值 {value!r} 类型不合法，已保留默认值")
            continue
        theme[key] = coerced
    return theme

def _coerce_theme_value(key: str, value):
    """按 DEFAULT_THEME[key] 的类型归一化。返回 None 表示保留默认。"""
    default = DEFAULT_THEME[key]
    if isinstance(default, bool):
        return value if isinstance(value, bool) else None
    if isinstance(default, int):
        if isinstance(value, bool):      # bool 是 int 子类，必须拦
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if isinstance(default, float):
        if isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(default, str):
        return value if isinstance(value, str) else None
    return value

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