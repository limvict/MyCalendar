# coding: utf-8
"""配置落盘：路径解析、JSON 原子写与节假日缓存读写。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

from desktop_calendar.utils.logging_setup import get_logger
from desktop_calendar.utils.paths import clear_readonly, mark_readonly
from desktop_calendar.utils.paths import get_app_data_dir as _get_app_data_dir

logger = get_logger()


CONFIG_VERSION = 3


def get_config_path() -> str:
    return os.path.join(_get_app_data_dir(), "config.json")


def get_holiday_cache_path() -> str:
    return os.path.join(_get_app_data_dir(), "holiday_cache.json")


def atomic_write_json(path: str, data: Any, *, protect: bool = False) -> None:
    """原子写入 JSON：临时文件 + fsync + os.replace。失败时抛异常由调用方处理。

    用 NamedTemporaryFile 而非 mkstemp + fdopen：前者内部管理 fd
    生命周期，任何异常路径（包括 fdopen 本身抛）都会关闭 fd，
    不会泄漏。

    protect=True 时写完后把目标置为只读：应用数据文件（config /
    schedules / attendance / moods / focus_log / *_cache）用它对用户
    隐藏写入能力，程序自己下次写入前会自动解锁。对用户可编辑的导出
    路径（设置导出、纪念日备份）保持 protect=False。
    """
    target_dir = os.path.dirname(path) or "."
    os.makedirs(target_dir, exist_ok=True)
    # 目标可能是上次写入留下的只读文件：Windows 上 os.replace 覆盖只读
    # 目标会 PermissionError，必须先解锁。
    clear_readonly(path)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=target_dir, suffix=".tmp", encoding="utf-8", delete=False
        ) as f:
            tmp_path = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    if protect:
        mark_readonly(path)


def _backup_corrupt_config(cfg_path: str) -> None:
    """损坏的 config.json 先改名备份，避免下次 save 覆盖用户数据。

    同一秒内两次损坏会产生同名 backup，导致第二次覆盖第一次。
    这里用 `_1` / `_2` 后缀消歧，上限 10 次（极端场景兜底，
    避免死循环）。
    """
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = f"{cfg_path}.corrupt-{ts}"
        backup = base
        n = 1
        while os.path.exists(backup):
            backup = f"{base}_{n}"
            n += 1
            if n > 10:
                get_logger().warning("损坏配置备份同名冲突超过 10 次，使用 %s", backup)
                break
        os.replace(cfg_path, backup)
        get_logger().warning(f"损坏的配置文件已备份到 {backup}")
    except OSError:
        get_logger().debug("备份损坏配置失败", exc_info=True)


def save_holiday_cache(cache_data: dict) -> None:
    try:
        atomic_write_json(get_holiday_cache_path(), cache_data, protect=True)
    except Exception:
        # 用 exception 而非 error：写入失败的堆栈（磁盘满 / 权限 /
        # 路径）对诊断至关重要，error 只记一句话会丢上下文。
        get_logger().exception("保存节假日缓存失败")


def load_holiday_cache() -> dict:
    cache_path = get_holiday_cache_path()
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        get_logger().warning(f"读取节假日缓存失败: {e}")
        return {}
    if isinstance(data, dict):
        return data
    get_logger().warning("节假日缓存格式异常（非 dict），已忽略")
    return {}
