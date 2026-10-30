# coding: utf-8
"""配置管理器：统一读写、版本迁移、防抖保存、原子落盘。

路径 / 日志 / 布尔归一化工具已下沉到 utils/，本模块只保留：
  - ConfigManager 单例
  - JSON 原子写（atomic_write_json）
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
    get_logger, log_exception, TRACE_LEVEL,
)
from desktop_calendar.utils.coerce import to_bool
from desktop_calendar.config.constants import (
    THEME_LIGHT, THEME_PRESETS,
)
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
    """原子写入 JSON：临时文件 + fsync + os.replace。失败时抛异常由调用方处理。

    用 NamedTemporaryFile 而非 mkstemp + fdopen：前者内部管理 fd
    生命周期，任何异常路径（包括 fdopen 本身抛）都会关闭 fd，
    不会泄漏。
    """
    target_dir = os.path.dirname(path) or "."
    os.makedirs(target_dir, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", dir=target_dir, suffix=".tmp",
                encoding="utf-8", delete=False) as f:
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
                get_logger().warning(
                    "损坏配置备份同名冲突超过 10 次，使用 %s", backup)
                break
        os.replace(cfg_path, backup)
        get_logger().warning(f"损坏的配置文件已备份到 {backup}")
    except OSError:
        get_logger().debug("备份损坏配置失败", exc_info=True)


def save_holiday_cache(cache_data: dict) -> None:
    try:
        atomic_write_json(get_holiday_cache_path(), cache_data)
    except Exception:
        # 用 exception 而非 error：写入失败的堆栈（磁盘满 / 权限 /
        # 路径）对诊断至关重要，error 只记一句话会丢上下文。
        get_logger().exception("保存节假日缓存失败")


def load_holiday_cache() -> dict:
    cache_path = get_holiday_cache_path()
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        get_logger().warning(f"读取节假日缓存失败: {e}")
        return {}
    if isinstance(data, dict):
        return data
    get_logger().warning("节假日缓存格式异常（非 dict），已忽略")
    return {}


def _clamp_hour(val, *, default: int, lo: int, hi: int) -> int:
    """把配置里的小时值归一化到 [lo, hi]；非法值返回 default。

    与 ReminderManager._get_int_cfg 的边界保持一致：
    remind_start_hour ∈ [0, 23]，remind_end_hour ∈ [0, 24]
    （24 表示"到当天结束"）。bool 是 int 子类，必须先拦截，
    否则 True 会被当作 1、False 被当作 0。
    """
    if isinstance(val, bool):
        return default
    try:
        v = int(val)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, v))


def normalize_config(cfg: dict) -> dict:
    """把 cfg 归一化为当前 CONFIG_VERSION 的合法形态。

    与 ConfigManager._migrate 共用同一份逻辑，但独立成模块级函数，
    供非单例场景（如 SettingDialog 导入配置时校验）复用。
    不修改入参，返回新 dict。
    """
    cfg = dict(cfg)
    if not isinstance(cfg.get("memorial_days"), list):
        cfg["memorial_days"] = []

    mem_cfg = cfg.get("memorial_cfg")
    if not isinstance(mem_cfg, dict):
        mem_cfg = {}
    mem_cfg["enable_remind"] = to_bool(mem_cfg.get("enable_remind"), default=True)
    mem_cfg["sound_enable"] = to_bool(mem_cfg.get("sound_enable"), default=True)
    if not isinstance(mem_cfg.get("last_remind_date"), str):
        mem_cfg["last_remind_date"] = ""
    if not isinstance(mem_cfg.get("last_remind_sig"), str):
        mem_cfg["last_remind_sig"] = ""    
    
    start_h = _clamp_hour(
        mem_cfg.get("remind_start_hour"), default=8, lo=0, hi=23)
    end_h = _clamp_hour(
        mem_cfg.get("remind_end_hour"), default=22, lo=0, hi=24)
    # start >= end 是非法时段：check_memorial 的 `start <= h < end`
    # 对任意 h 恒为 False，会导致永久静默不提醒。回退默认 8~22。
    #
    # 不自动交换（min/max）：交换会掩盖用户配置错误，且 start=22/
    # end=8 的意图通常是"跨天提醒"，而 check_memorial 当前用的是
    # `start <= h < end` 单区间判断，不支持跨天。交换成 8~22 语义
    # 与用户意图完全相反。回退默认 + warning 是最安全的选择。
    if start_h >= end_h:
        get_logger().warning(
            "配置 remind 时段非法 start=%s >= end=%s，回退默认 8~22",
            start_h, end_h)
        start_h, end_h = 8, 22
    mem_cfg["remind_start_hour"] = start_h
    mem_cfg["remind_end_hour"] = end_h
    cfg["memorial_cfg"] = mem_cfg

    cfg["topmost"] = to_bool(cfg.get("topmost"), default=False)
    try:
        cfg["opacity"] = max(0.0, min(1.0, float(cfg.get("opacity", 0.92))))
    except (TypeError, ValueError):
        cfg["opacity"] = 0.92
    if cfg.get("language") not in ("zh_CN", "en_US"):
        cfg["language"] = "zh_CN"
    cfg["config_version"] = CONFIG_VERSION
    if not isinstance(cfg.get("update_skipped_version"), str):
        cfg["update_skipped_version"] = ""
    theme_name = cfg.get("theme_name")
    if not isinstance(theme_name, str) or theme_name not in THEME_PRESETS:
        cfg["theme_name"] = THEME_LIGHT
    return cfg

class ConfigManager:
    """配置管理器单例：统一读写、版本迁移、防抖保存、原子落盘。

    线程模型：
    - 所有对 self._cfg 的读写都持 self._lock（RLock，允许嵌套）。
    - _save_timer 的读写也在锁内，避免并发 save_debounced 互相覆盖。
    - 磁盘写通过"临时文件 + os.replace"保证原子性。
    - _flush_save 在 threading.Timer 的独立线程中执行，与主线程的
      set/save_debounced 并发；_last_flush_ts 保证旧快照不会覆盖新快照。

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
            self._migrate_with_fallback()
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
                # FileNotFoundError 不备份：exists 之后文件消失属竞态，
                # 无内容可留；其余异常（JSONDecodeError / OSError /
                # 根节点非 dict）都把损坏文件改名，避免下次 save 覆盖。
                if not isinstance(e, FileNotFoundError):
                    _backup_corrupt_config(cfg_path)
                data = {}

        with self._lock:
            self._cfg = data
        self._migrate_with_fallback()

    def _migrate_with_fallback(self) -> None:
        """安全执行 _migrate。失败时降级为空配置重新迁移。

        _migrate 里任何一步抛异常，都会沿 _load → __new__ 传播，
        导致 ConfigManager 单例初始化失败——此后所有 config.get()
        调用全部 AttributeError，程序永久无法启动（即使配置文件
        本身是合法 JSON，只是某字段类型不对）。

        这里用两级兜底：
          1. 首次失败：记录原异常，清空 _cfg 后重试 _migrate。
             大部分字段在空配置下走默认值分支，能正常完成。
          2. 再次失败：记录，保持空配置。后续 get(key, default)
             返回调用方默认值，程序可启动，用户可通过设置页恢复。
        """
        try:
            self._migrate()
            return
        except Exception:
            get_logger().exception(
                "配置迁移失败，降级为空配置重新迁移")
        with self._lock:
            self._cfg = {}
        try:
            self._migrate()
        except Exception:
            get_logger().exception(
                "默认配置迁移也失败，保持空配置（后续读走默认值）")

    def _migrate(self):
        with self._lock:
            self._cfg = normalize_config(self._cfg)

    def ensure_migrated(self) -> None:
        """确保配置按当前 CONFIG_VERSION 补齐 / 归一化。幂等。

        与 _load 路径共用 _migrate_with_fallback：对外入口若因数据
        异常抛异常，调用方（main_window._init_config_on_start）会
        连锁失败。降级行为与启动期一致。
        """
        self._migrate_with_fallback()

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
        return to_bool(self.get_nested(*keys, default=default), default=default)

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
        self._migrate_with_fallback()
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

    def _flush_save(self, force: bool = False,
                    raise_on_error: bool = False):
        """落盘。snapshot_ts 与 _last_flush_ts 的比较保证：

        - 同一快照不会被重复写盘（timer 与 flush 可能并发）；
        - 后发起的快照一定覆盖先发起的，不会因调度顺序倒挂。

        注意 threading.Timer 的回调在本线程（独立线程）执行，与
        主线程的 set / save_debounced 并发；_lock 保护 _cfg 快照，
        _flush_lock 串行化磁盘写，_last_flush_ts 保证旧快照不覆盖新快照。

        raise_on_error=True：磁盘写失败时抛异常，供数据安全场景
        （如纪念日恢复）感知"是否真的存下去了"。默认 False 保持
        "尽力而为"语义（窗口位置保存失败不阻断退出）。
        """
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
                if raise_on_error:
                    raise

    def flush(self, raise_on_error: bool = False):
        """立即落盘。

        raise_on_error=True：磁盘写失败时抛异常。默认 False 保持
        "尽力而为"语义（窗口位置保存失败不阻断退出）。
        数据安全场景（restore_from）必须用 True，否则会在内存已
        更新但磁盘写失败时误报成功，用户重启后丢数据。
        """
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
        self._flush_save(force=True, raise_on_error=raise_on_error)


    
# 全局单例
config = ConfigManager()