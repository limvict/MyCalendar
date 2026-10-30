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
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return os.path.join(meipass, relative_path)
    # 4 层 dirname：src/desktop_calendar/utils/paths.py → 仓库根
    # （不是 src/desktop_calendar/，assets/ 等运行时资源放在仓库根）。
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(project_root, relative_path)


def get_app_data_dir() -> str:
    """返回可写的应用数据目录；都不可写时降级到临时目录。

    降级路径的提示直接 print 到 stderr：本模块被 logging_setup 在
    logging 初始化前 import（循环依赖），不能用 logger。stderr 由
    logging_setup 的 fallback 也使用，一致。
    """
    data_dir = os.path.join(get_base_dir(), "MyCalendarApp")
    try:
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    except OSError as e:
        print(
            f"[MyCalendarApp] 主数据目录不可写 ({data_dir!r}: {e})，"
            f"降级到临时目录；配置可能在系统清理临时文件时丢失",
            file=sys.stderr)

    fallback = os.path.join(tempfile.gettempdir(), "MyCalendarApp")
    try:
        os.makedirs(fallback, exist_ok=True)
        print(f"[MyCalendarApp] 临时数据目录: {fallback!r}", file=sys.stderr)
        return fallback
    except OSError as e2:
        print(
            f"[MyCalendarApp] 临时目录也不可写 ({fallback!r}: {e2})，"
            f"配置将无法持久化",
            file=sys.stderr)
        return data_dir


__all__ = [
    "get_base_dir", "get_log_dir", "get_resource_path", "get_app_data_dir",
]