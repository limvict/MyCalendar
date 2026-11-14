# coding: utf-8
"""应用日志初始化。

线程模型：`get_logger()` 是进程级单例，第一次调用时初始化，
之后加锁 double-check。日志文件写失败时降级到 stderr。

日志级别通过环境变量 MYCALENDAR_LOG_LEVEL 控制（DEBUG / TRACE /
WARNING 等，大小写不敏感），默认 INFO。TRACE 是本项目自定义
级别（logging.DEBUG - 1），可捕获逐条纪念日诊断等高频日志。
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from typing import Optional

from desktop_calendar.utils.paths import get_log_dir, ensure_writable_dir

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
APP_LOGGER_NAME = "MyCalendarApp"

_logger: Optional[logging.Logger] = None
_logger_lock = threading.Lock()

# TRACE 级别低于 DEBUG，用于"逐条纪念日诊断"等高频日志。
TRACE_LEVEL = logging.DEBUG - 1
logging.addLevelName(TRACE_LEVEL, "TRACE")


def _resolve_level() -> int:
    """从环境变量解析日志级别，失败回退 INFO。

    TRACE 是自定义级别，logging 模块没有 TRACE 属性，需特判。
    """
    raw = (os.getenv("MYCALENDAR_LOG_LEVEL") or "INFO").strip().upper()
    if raw == "TRACE":
        return TRACE_LEVEL
    level = getattr(logging, raw, None)
    return level if isinstance(level, int) else logging.INFO


def _init_logger() -> logging.Logger:
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.propagate = False

    if logger.handlers:
        # 已初始化：保留调用方可能已设置的 level（测试常用 DEBUG）。
        # 但若调用方只挂了 handler 没 setLevel，logger.level 仍是
        # NOTSET 会继承 root 的 WARNING，导致 INFO/DEBUG/TRACE 全被
        # 过滤。这里补一次兜底，只在未显式设级时生效。
        if logger.level == logging.NOTSET:
            logger.setLevel(_resolve_level())
        return logger

    logger.setLevel(_resolve_level())

    _FMT = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s")

    def _attach_fallback(reason: str):
        h = logging.StreamHandler()
        h.setFormatter(_FMT)
        logger.addHandler(h)
        print(f"[{APP_LOGGER_NAME}] {reason}，日志将输出到 stderr",
              file=sys.stderr)

    log_dir = get_log_dir()
    try:
        # 与 get_app_data_dir 共用同一套可写性判定：makedirs 成功
        # 不代表可写（目录可能由 root 创建、权限 755），RotatingFileHandler
        # 要到真正打开文件时才抛 OSError。提前用 access 探路，让降级
        # 发生在更早、更明确的位置，文案也能区分"目录不可用"和
        # "文件打不开"。
        ensure_writable_dir(log_dir)
    except OSError as e:
        _attach_fallback(f"日志目录不可用 {log_dir!r}: {e}")
        return logger

    log_path = os.path.join(log_dir, "calendar_log.txt")
    try:
        handler = RotatingFileHandler(
            log_path, maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    except OSError as e:
        _attach_fallback(f"无法打开日志文件 {log_path!r}: {e}")
        return logger

    handler.setFormatter(_FMT)
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                _logger = _init_logger()
    return _logger


def log_exception(msg: str) -> None:
    """仅在真实异常上下文存在时打印 traceback，避免 NoneType: None 噪音。"""
    logger = get_logger()
    if sys.exc_info()[0] is not None:
        logger.exception(msg)
    else:
        logger.error(msg)


def _logger_trace(self, msg, *args, **kwargs):
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, msg, args, **kwargs)


logging.Logger.trace = _logger_trace


__all__ = [
    "get_logger", "log_exception", "TRACE_LEVEL", "APP_LOGGER_NAME",
]