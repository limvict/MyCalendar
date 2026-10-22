# coding: utf-8
"""配置管理器：统一读写、版本迁移、防抖保存、原子落盘。

路径 / 日志 / 布尔归一化工具已下沉到 utils/，本模块只保留：
  - ConfigManager 单例
  - JSON 原子写（_atomic_write_json）
  - 节假日缓存读写
  - 兼容性 re-export（保留旧 import 路径）
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
from threading import Timer
from typing import Any, Dict, Optional

from desktop_calendar.utils.paths import (
    get_app_data_dir as _get_app_data_dir,
    get_resource_path,
)
from desktop_calendar.utils.logging_setup import (
    get_logger,
    log_exception,
    TRACE_LEVEL,
)
from desktop_calendar.utils.coerce import to_bool

# 保留旧公开名：既有代码 `from config.config import get_resource_path`
# `from config.config import get_logger` 等路径不变。
__all__ = [
    "CONFIG_VERSION", "CONFIG_SAVE_DEBOUNCE_MS",
    "ConfigManager", "config",
    "get_logger", "log_exception", "get_resource_path", "to_bool",
    "TRACE_LEVEL",
    "get_config_path", "get_holiday_cache_path",
    "load_holiday_cache", "save_holiday_cache",
    "atomic_write_json",
]

CONFIG_VERSION = 2
CONFIG_SAVE_DEBOUNCE_MS = 500
_MUTABLE_TYPES = (dict, list, set, tuple)


def get_config_path() -> str:
    return os.path.join(_get_app_data_dir(), "config.json")


def get_holiday_cache_path() -> str:
    return os.path.join(_get_app_data_dir(), "holiday_cache.json")


def atomic_write_json(path: str, data: Any) -> None:
    """原子写入 JSON：临时文件 + fsync + os.replace。

    失败时抛异常，由调用方决定日志 / 降级。
    """
    target_dir = os.path.dirname(path) or "."
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
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


def save_holiday_cache(cache_data: dict) -> None:
    cache_path = get_holiday_cache_path()
    try:
        atomic_write_json(cache_path, cache_data)
    except Exception as e:
        get_logger().error(f"保存节假日缓存失败: {e}")


def load_holiday_cache() -> dict:
    cache_path = get_holiday_cache_path()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            get_logger().warning(f"读取节假日缓存失败: {e}")
    return {}


class ConfigManager:
    """配置管理器单例：统一读写、版本迁移、防抖保存、原子落盘。

    线程模型：
    - 所有对 self._cfg 的读写都持 self._lock（RLock，允许嵌套）。
    - _save_timer 的读写也在锁内，避免并发 save_debounced 互相覆盖。
    - 磁盘写通过"临时文件 + os.replace"保证原子性。

    可变值约定：get() / get_nested() 返回的容器仅供读取；外部如需
    修改嵌套结构，请用 snapshot()（深拷贝）或 update_nested()。
    """
    _instance: Optional["ConfigManager"] = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._lock = threading.RLock()
                    inst._save_timer = None
                    inst._flush_lock = threading.Lock()
                    inst._cfg = {}
                    inst._last_flush_ts = 0.0
                    inst._load()
                    cls._instance = inst
        return cls._instance

    def _load(self):
        data: Dict[str, Any] = {}
        try:
            cfg_path = get_config_path()
        except Exception as e:
            get_logger().warning(f"获取配置路径失败: {e}，使用空配置")
            with self._lock:
                self._cfg = data
                self._migrate()
            return

        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if not isinstance(raw, dict):
                    raise ValueError("配置文件根节点不是 dict")
                data = raw
            except Exception as e:
                get_logger().warning(f"读取配置失败: {e}")
                data = {}
        with self._lock:
            self._cfg = data
            self._migrate()

    def _migrate(self):
        with self._lock:
            cfg = self._cfg
            if not isinstance(cfg.get("memorial_days"), list):
                cfg["memorial_days"] = []

            mem_cfg = cfg.get("memorial_cfg")
            if not isinstance(mem_cfg, dict):
                mem_cfg = {}
            mem_cfg["enable_remind"] = to_bool(
                mem_cfg.get("enable_remind"), default=True)
            mem_cfg["sound_enable"] = to_bool(
                mem_cfg.get("sound_enable"), default=True)
            if not isinstance(mem_cfg.get("last_remind_date"), str):
                mem_cfg["last_remind_date"] = ""
            mem_cfg.setdefault("remind_start_hour", 8)
            mem_cfg.setdefault("remind_end_hour", 22)
            cfg["memorial_cfg"] = mem_cfg
            cfg["theme"] = cfg.get("theme") or None
            cfg["topmost"] = to_bool(cfg.get("topmost"), default=False)
            try:
                cfg["opacity"] = max(
                    0.0, min(1.0, float(cfg.get("opacity", 0.92))))
            except (TypeError, ValueError):
                cfg["opacity"] = 0.92
            if cfg.get("language") not in ("zh_CN", "en_US"):
                cfg["language"] = "zh_CN"
            cfg["config_version"] = CONFIG_VERSION
            if not isinstance(cfg.get("update_skipped_version"), str):
                cfg["update_skipped_version"] = ""

    def ensure_migrated(self) -> None:
        """确保配置字段按当前 CONFIG_VERSION 补齐 / 归一化。

        幂等：_migrate 内部自带 RLock，可安全重复调用。
        供启动流程、导入配置等外部调用方在"配置可能在运行期被改写"
        的场景兜底，避免直接访问私有 _migrate。
        """
        self._migrate()
    
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            val = self._cfg.get(key, default)
            if isinstance(val, _MUTABLE_TYPES):
                return copy.deepcopy(val)
            return val

    def get_nested(self, *keys: str, default: Any = None) -> Any:
        with self._lock:
            cur: Any = self._cfg
            for k in keys:
                if not isinstance(cur, dict):
                    cur = default
                    break
                cur = cur.get(k)
                if cur is None:
                    cur = default
                    break
            if isinstance(cur, _MUTABLE_TYPES):
                return copy.deepcopy(cur)
            return cur

    def get_bool_nested(self, *keys, default: bool) -> bool:
        return to_bool(
            self.get_nested(*keys, default=default), default=default)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._cfg)

    @property
    def raw(self) -> Dict[str, Any]:
        return self.snapshot()

    def set_nested(self, *keys_and_value: Any, save: bool = True):
        if len(keys_and_value) < 2:
            return
        *keys, value = keys_and_value
        with self._lock:
            cur = self._cfg
            for k in keys[:-1]:
                nxt = cur.get(k)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[k] = nxt
                cur = nxt
            cur[keys[-1]] = value
        if save:
            self.save_debounced()

    def update_nested(self, *keys: str, save: bool = True, **kwargs):
        with self._lock:
            cur = self._cfg
            for k in keys:
                nxt = cur.get(k)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[k] = nxt
                cur = nxt
            cur.update(kwargs)
        if save:
            self.save_debounced()

    def set(self, key: str, value: Any, save: bool = True):
        with self._lock:
            self._cfg[key] = value
        if save:
            self.save_debounced()

    def replace_all(self, data: Dict[str, Any], save: bool = True):
        if not isinstance(data, dict):
            get_logger().warning("replace_all 收到非 dict 参数，已忽略")
            return
        data = copy.deepcopy(data)
        with self._lock:
            self._cfg = data
            self._migrate()
        if save:
            self.save_debounced()

    def save_debounced(self):
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            timer = Timer(CONFIG_SAVE_DEBOUNCE_MS / 1000, self._flush_save)
            timer.daemon = True
            self._save_timer = timer
            timer.start()

    def _flush_save(self, force: bool = False):
        with self._flush_lock:
            try:
                cfg_path = get_config_path()
                with self._lock:
                    if self._save_timer is not None:
                        self._save_timer = None
                    data = copy.deepcopy(self._cfg)
                    snapshot_ts = time.monotonic()
                    if not force and snapshot_ts <= self._last_flush_ts:
                        return
                atomic_write_json(cfg_path, data)
                with self._lock:
                    if snapshot_ts > self._last_flush_ts:
                        self._last_flush_ts = snapshot_ts
            except Exception as e:
                get_logger().error(f"保存配置失败: {e}")

    def flush(self):
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
        self._flush_save(force=True)
        
# 全局单例
config = ConfigManager()