# coding: utf-8
"""配置层：读写、版本迁移、防抖保存、原子落盘。

原 `config.manager` 单文件按职责拆成三个模块：

- `storage`  ：路径解析、JSON 原子写、节假日缓存
- `normalize`：把磁盘上的任意 dict 收敛成合法配置（纯函数）
- `manager`  ：ConfigManager 单例

本文件保留原有的导出面（含从 utils 再导出的日志/布尔/路径工具），
`from desktop_calendar.config.manager import ...` 的调用方无需改动。
"""

from __future__ import annotations

from desktop_calendar.utils.coerce import to_bool
from desktop_calendar.utils.logging_setup import (
    TRACE_LEVEL,
    get_logger,
    log_exception,
)
from desktop_calendar.utils.paths import get_resource_path

from .manager import CONFIG_SAVE_DEBOUNCE_MS, ConfigManager, config
from .normalize import normalize_config
from .storage import (
    CONFIG_VERSION,
    atomic_write_json,
    get_config_path,
    get_holiday_cache_path,
    load_holiday_cache,
    save_holiday_cache,
)

__all__ = [
    "CONFIG_VERSION",
    "CONFIG_SAVE_DEBOUNCE_MS",
    "ConfigManager",
    "config",
    "get_logger",
    "log_exception",
    "get_resource_path",
    "to_bool",
    "TRACE_LEVEL",
    "get_config_path",
    "get_holiday_cache_path",
    "load_holiday_cache",
    "save_holiday_cache",
    "atomic_write_json",
    "normalize_config",
]
