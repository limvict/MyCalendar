# coding: utf-8
"""提醒规则：配置读取、下次时间戳、命中收集与去重签名。

全部是不依赖 ReminderManager 实例状态的纯逻辑（只读 config、只用
传入的参数），便于单测；调度与 pending 状态机仍留在 reminder_manager。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from PyQt6.QtCore import QDate

from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import get_logger, to_bool
from desktop_calendar.core.memorial import get_next_memorial_date

logger = get_logger()


@dataclass(frozen=True)
class RemindCfg:
    """提醒时段与开关（已按配置归一化、做过合法性兜底）。"""

    enable: bool
    start_hour: int
    end_hour: int
    sound_enable: bool


_REQUIRED_MEMORIAL_FIELDS = ("repeat_type", "type")

# 参与“下次提醒时间”计算的标量字段。新增此类字段时必须在此登记，
# 否则 memorial_cache_key 会漏算，导致不同纪念日命中同一缓存键、
# 提醒时间错误（旧实现“跳过不可 hash 字段”正是这种静默错误的来源）。
_CACHE_KEY_FIELDS = (
    "repeat_type",
    "type",
    "month",
    "day",
    "year",
    "isleap",
    "advance_days",
)


# ---------- 配置读取 ----------
def read_int_cfg(cfg, *keys, default: int, lo: int | None = None, hi: int | None = None):
    val = cfg.get_nested(*keys, default=default)
    if isinstance(val, bool):  # bool 是 int 子类，须先拦截
        return default
    try:
        v = int(val)
    except (TypeError, ValueError, OverflowError):
        return default
    if lo is not None and v < lo:
        return lo
    if hi is not None and v > hi:
        return hi
    return v


def read_bool_cfg(cfg, *keys, default: bool):
    return to_bool(cfg.get_nested(*keys, default=default), default=default)


def read_remind_cfg(config) -> RemindCfg:
    start = read_int_cfg(config, "memorial_cfg", "remind_start_hour", default=8, lo=0, hi=23)
    end = read_int_cfg(config, "memorial_cfg", "remind_end_hour", default=22, lo=0, hi=24)
    # start >= end 兜底：normalize_config 已在落盘时修正，但运行期
    # config.set_nested / update_nested 可写入未归一化值，而
    # check_memorial 的 `start <= h < end` 在 start >= end 时恒为
    # False，会导致永久静默不提醒。此处与 normalize_config 保持
    # 一致的"回退默认 8~22"策略，不自动交换（理由见 normalize_config）。
    if start >= end:
        logger.warning("remind 时段非法 start=%s >= end=%s，回退默认 8~22", start, end)
        start, end = 8, 22
    return RemindCfg(
        enable=read_bool_cfg(config, "memorial_cfg", "enable_remind", default=True),
        start_hour=start,
        end_hour=end,
        sound_enable=read_bool_cfg(config, "memorial_cfg", "sound_enable", default=True),
    )


def memorial_cache_key(mem: dict, remind_h: int) -> tuple:
    """缓存键：日期相关标量字段 + remind_h。

    用白名单而非“遍历所有可哈希字段”：后者在新增不可 hash 字段
    时会静默跳过，导致两条不同纪念日命中同一缓存键。白名单漏登记
    会立即表现为“改了字段不生效”，比静默错误可诊断。
    """
    parts = []
    for k in _CACHE_KEY_FIELDS:
        v = mem.get(k)
        try:
            hash(v)
        except TypeError:
            v = repr(v)
        parts.append((k, v))
    parts.append(("__remind_h__", remind_h))
    return tuple(parts)


def first_future_remind_ts(
    first_alert_qd: QDate, target_qd: QDate, remind_h: int, now_dt: datetime
) -> int | None:
    now_ms = int(now_dt.timestamp() * 1000)
    today_qd = QDate(now_dt.year, now_dt.month, now_dt.day)
    start = first_alert_qd if first_alert_qd > today_qd else today_qd
    if start == today_qd:
        today_remind = datetime(now_dt.year, now_dt.month, now_dt.day, remind_h, 0, 0)
        if int(today_remind.timestamp() * 1000) <= now_ms:
            start = start.addDays(1)
    if start > target_qd:
        return None
    dt = datetime(start.year(), start.month(), start.day(), remind_h, 0, 0)
    ts = int(dt.timestamp() * 1000)
    return ts if ts > now_ms else None


# ---------- 命中签名 ----------
def hits_signature(hit_list: list) -> str:
    """命中列表的稳定签名。

    - 排序后拼接：集合相同则签名相同（顺序无关）。
    - sha256 而非 md5：FIPS 模式下 md5 可能抛 ValueError。
    - 截断 16 位：碰撞概率可忽略（用于本地区分提醒批次，非安全用途）。
    """
    raw = "\x00".join(sorted(hit_list)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def collect_hits(all_mem: list, today: QDate) -> list:
    hit_list = []
    for mem in all_mem:
        target_date = get_next_memorial_date(mem, today, include_base=True, normalized=True)
        if target_date is None:
            continue
        target = QDate(target_date.year, target_date.month, target_date.day)
        diff = today.daysTo(target)
        # advance_days 已在 _enabled_memorials 中归一化为非负 int，
        # 这里直接比较安全。
        if 0 <= diff <= mem.get("advance_days", 0):
            hit_list.append(format_hit_text(mem, diff))
    return hit_list


def format_hit_text(mem: dict, diff: int) -> str:
    name = mem.get("name") or tr("memorial.default_name")
    if diff == 0:
        return name
    if diff == 1:
        return tr("memorial.remind.hit_fmt_one").format(name=name)
    return tr("memorial.remind.hit_fmt").format(name=name, days=diff)
