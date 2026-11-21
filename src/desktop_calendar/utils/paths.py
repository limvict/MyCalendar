# coding: utf-8
"""平台相关的路径解析。

本模块只依赖标准库，不依赖 desktop_calendar 内其它模块。
"""

from __future__ import annotations

import os
import stat
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
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    return os.path.join(project_root, relative_path)


def ensure_writable_dir(path: str) -> None:
    """创建目录并校验可写；不可写抛 OSError 供调用方降级。

    makedirs(exist_ok=True) 成功只说明目录存在或能创建，不说明当前
    用户有写权限（例如目录由 root 创建、权限 755）。用 os.access
    显式检查，否则降级逻辑永远走不到，直到真正写文件时才失败。

    供 get_app_data_dir / logging_setup 等"写盘前先探路"的场景共用，
    保证数据目录与日志目录的可写性判定标准一致。
    """
    os.makedirs(path, exist_ok=True)
    if not os.access(path, os.W_OK):
        raise PermissionError(f"目录不可写: {path!r}")


def get_app_data_dir() -> str:
    """返回可写的应用数据目录；都不可写时降级到临时目录。

    降级路径的提示直接 print 到 stderr：本模块被 logging_setup 在
    logging 初始化前 import（循环依赖），不能用 logger。stderr 由
    logging_setup 的 fallback 也使用，一致。
    """
    data_dir = os.path.join(get_base_dir(), "MyCalendarApp")
    try:
        ensure_writable_dir(data_dir)
        return data_dir
    except OSError as e:
        print(
            f"[MyCalendarApp] 主数据目录不可写 ({data_dir!r}: {e})，"
            f"降级到临时目录；配置可能在系统清理临时文件时丢失",
            file=sys.stderr,
        )

    fallback = os.path.join(tempfile.gettempdir(), "MyCalendarApp")
    try:
        ensure_writable_dir(fallback)
        print(f"[MyCalendarApp] 临时数据目录: {fallback!r}", file=sys.stderr)
        return fallback
    except OSError as e2:
        print(
            f"[MyCalendarApp] 临时目录也不可写 ({fallback!r}: {e2})，配置将无法持久化",
            file=sys.stderr,
        )
        return data_dir


def clear_readonly(path: str) -> None:
    """清掉只读属性（Windows 的 FILE_ATTRIBUTE_READONLY，POSIX 的 0444）。

    写盘前必须先清：Windows 上 os.replace 覆盖只读目标会直接
    PermissionError；POSIX 上写 0444 文件同样会被拒。
    """
    try:
        if os.path.exists(path):
            os.chmod(path, 0o644)
    except OSError:
        # 清不掉就让后续写入按真实权限失败，调用方本来就要处理 OSError
        pass


def mark_readonly(path: str) -> None:
    """把文件标记为只读（应用数据文件默认对用户不可改）。"""
    try:
        os.chmod(path, 0o444)
    except OSError:
        pass


def is_readonly(path: str) -> bool:
    """判断文件是否只读（跨平台：Windows 看文件属性，POSIX 看 owner 写位）。"""
    info = os.stat(path)
    attributes = getattr(info, "st_file_attributes", None)
    if attributes is not None:
        # Windows：FILE_ATTRIBUTE_READONLY；Linux 上结构体没有该字段
        return bool(attributes & stat.FILE_ATTRIBUTE_READONLY)
    return not bool(info.st_mode & stat.S_IWUSR)


__all__ = [
    "get_base_dir",
    "get_log_dir",
    "get_resource_path",
    "get_app_data_dir",
    "ensure_writable_dir",
    "clear_readonly",
    "mark_readonly",
    "is_readonly",
]
