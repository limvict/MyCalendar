# coding: utf-8
"""图标统一管理模块。

根据当前主题 (dark/light/sakura) 自动从对应的子文件夹加载图标。
"""

import os

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from desktop_calendar.config.manager import get_resource_path
from desktop_calendar.ui.theme import ThemeBundle


class IconManager:
    """统一管理应用图标的加载和主题适配。"""

    # 映射主题名称到文件夹和主图片文件名 (根据您的目录结构定制)
    THEME_ICON_MAP = {
        "dark": {"dir": "dark", "file": "icon_dark.png"},
        "light": {"dir": "light", "file": "icon_light.png"},
        "sakura": {"dir": "sakura", "file": "sakura.png"},
    }

    @classmethod
    def _get_theme_info(cls, bundle: ThemeBundle) -> tuple[str, str]:
        """获取当前主题的目录名和图片文件名。"""
        # 假设 bundle.name 就是 'dark', 'light' 或 'sakura'
        theme_name = getattr(bundle, "name", "").lower()

        # 如果 bundle.name 不在映射中，默认降级为 light
        info = cls.THEME_ICON_MAP.get(theme_name, cls.THEME_ICON_MAP["light"])
        return info["dir"], info["file"]

    @classmethod
    def get_app_icon(cls, bundle: ThemeBundle) -> QIcon:
        """获取主程序图标。"""
        theme_dir, png_file = cls._get_theme_info(bundle)

        # 优先级 1: 主题目录下的 256x256 ico (适合任务栏和标题栏)
        ico_path = get_resource_path(f"assets/{theme_dir}/theme_256x256.ico")
        if os.path.exists(ico_path):
            return QIcon(ico_path)

        # 优先级 2: 主题目录下的 png (适合高分辨率缩放)
        png_path = get_resource_path(f"assets/{theme_dir}/{png_file}")
        if os.path.exists(png_path):
            return QIcon(png_path)

        # 优先级 3: 终极兜底方案 (根目录的 app.ico)
        fallback_path = get_resource_path("assets/app.ico")
        return QIcon(fallback_path)

    @classmethod
    def apply_global_icon(cls, bundle: ThemeBundle) -> None:
        """应用全局图标 (影响 Windows 任务栏、所有弹窗)。"""
        icon = cls.get_app_icon(bundle)

        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)

    @classmethod
    def get_tray_icon(cls, bundle: ThemeBundle) -> QIcon:
        """获取系统托盘图标（与主程序共用同一套匹配逻辑）。"""
        return cls.get_app_icon(bundle)
