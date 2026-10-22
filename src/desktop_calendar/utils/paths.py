# coding: utf-8
"""平台相关的路径解析。

本模块只依赖标准库，不依赖 desktop_calendar 内其它模块。
"""
from __future__ import annotations

import os
import sys
import tempfile


def get_base_dir() -> str:
    """按平台返回标准数据目录（不含应用名）。"""
    if sys.platform == "win32":
        return os.getenv("APPDATA") or os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    return os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def get_log_dir() -> str:
    override = os.getenv("MYCALENDAR_LOG_DIR")
    return override or os.path.join(get_base_dir(), "MyCalendarApp")


def get_resource_path(relative_path: str) -> str:
    """获取资源文件路径（兼容打包后环境）。

    打包后：_MEIPASS 根。
    源码运行：项目根（main.py 所在目录），而不是 CWD ——
    否则从任意目录 `python -m` 启动都找不到资源。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return os.path.join(meipass, relative_path)
    # utils/paths.py → 上四级 = 项目根（src/desktop_calendar/utils → 项目根）
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(project_root, relative_path)


def get_app_data_dir() -> str:
    """返回可写的应用数据目录；都不可写时降级到临时目录。

    降级原因通过返回值表示（调用方自行决定是否记录日志），
    本模块不 import logging，避免循环。
    """
    data_dir = os.path.join(get_base_dir(), "MyCalendarApp")
    try:
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    except OSError:
        fallback = os.path.join(tempfile.gettempdir(), "MyCalendarApp")
        try:
            os.makedirs(fallback, exist_ok=True)
            return fallback
        except OSError:
            return data_dir   # 交给调用方处理异常


__all__ = [
    "get_base_dir", "get_log_dir", "get_resource_path", "get_app_data_dir",
]