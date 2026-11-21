# coding: utf-8
"""配置归一化：把磁盘上的任意 dict 收敛成合法配置（纯函数）。"""

from __future__ import annotations

import copy
import math

from desktop_calendar.config.constants import (
    THEME_LIGHT,
    THEME_PRESETS,
    WEATHER_CITY_DEFAULT,
    WEATHER_ENABLED_DEFAULT,
    WEATHER_LAT_DEFAULT,
    WEATHER_LON_DEFAULT,
    WEATHER_PROVIDER_DEFAULT,
    WEATHER_REFRESH_MINUTES_DEFAULT,
)
from desktop_calendar.utils.coerce import to_bool, to_int_clamped
from desktop_calendar.utils.logging_setup import get_logger

from .storage import CONFIG_VERSION

logger = get_logger()


def _clamp_hour(val, *, default: int, lo: int, hi: int) -> int:
    return to_int_clamped(val, lo=lo, hi=hi, default=default)


def normalize_config(cfg: dict) -> dict:
    """把 cfg 归一化为当前 CONFIG_VERSION 的合法形态。

    与 ConfigManager._migrate 共用同一份逻辑，但独立成模块级函数，
    供非单例场景（如 SettingDialog 导入配置时校验）复用。
    不修改入参，返回新 dict。
    """
    # deepcopy 而非浅拷贝：docstring 承诺“不修改入参”，但浅拷贝下
    # cfg["memorial_days"] 与入参共享同一 list（及内部 dict），调用方
    # 后续修改原 list 会影响返回值，契约不成立。
    cfg = copy.deepcopy(cfg)
    if not isinstance(cfg.get("memorial_days"), list):
        cfg["memorial_days"] = []

    mem_cfg = cfg.get("memorial_cfg")
    if not isinstance(mem_cfg, dict):
        mem_cfg = {}
    else:
        # 浅拷贝顶层不够：后续 mem_cfg[...] = ... 会写回调用方的原 dict，
        # 违反"不修改入参"契约。这里必须再拷一层。
        mem_cfg = dict(mem_cfg)
    mem_cfg["enable_remind"] = to_bool(mem_cfg.get("enable_remind"), default=True)
    mem_cfg["sound_enable"] = to_bool(mem_cfg.get("sound_enable"), default=True)
    if not isinstance(mem_cfg.get("last_remind_date"), str):
        mem_cfg["last_remind_date"] = ""
    if not isinstance(mem_cfg.get("last_remind_sig"), str):
        mem_cfg["last_remind_sig"] = ""

    start_h = _clamp_hour(mem_cfg.get("remind_start_hour"), default=8, lo=0, hi=23)
    end_h = _clamp_hour(mem_cfg.get("remind_end_hour"), default=22, lo=0, hi=24)
    # start >= end 是非法时段：check_memorial 的 `start <= h < end`
    # 对任意 h 恒为 False，会导致永久静默不提醒。回退默认 8~22。
    #
    # 不自动交换（min/max）：交换会掩盖用户配置错误，且 start=22/
    # end=8 的意图通常是"跨天提醒"，而 check_memorial 当前用的是
    # `start <= h < end` 单区间判断，不支持跨天。交换成 8~22 语义
    # 与用户意图完全相反。回退默认 + warning 是最安全的选择。
    if start_h >= end_h:
        get_logger().warning(
            "配置 remind 时段非法 start=%s >= end=%s，回退默认 8~22", start_h, end_h
        )
        start_h, end_h = 8, 22
    mem_cfg["remind_start_hour"] = start_h
    mem_cfg["remind_end_hour"] = end_h
    cfg["memorial_cfg"] = mem_cfg

    # 考勤配置：提醒开关 + 考勤规则（work_rule）。
    # P1 起提醒时间不再固定复用 STANDARD_START/END，而是由
    # work_rule.work_start / work_end 决定（见 core.attendance.WorkRule，
    # attendance_reminder._next_trigger 每次 reschedule 重读）。
    att_cfg = cfg.get("attendance_cfg")
    if not isinstance(att_cfg, dict):
        att_cfg = {}
    else:
        att_cfg = dict(att_cfg)
    att_cfg["enable_remind"] = to_bool(att_cfg.get("enable_remind"), default=True)
    att_cfg["enable_auto_punch"] = to_bool(att_cfg.get("enable_auto_punch"), default=False)
    # 只补缺失的整段默认值，已有字段一律不动：
    #   - work_rule 不是 dict（缺失 / 被写成 null / 损坏）→ 补整段默认
    #   - work_rule 是 dict（哪怕缺字段）→ 原样保留，由
    #     WorkRule.from_config 逐字段读取时用类默认值兜底
    # 这样 normalize 不持有第二份默认值，避免与 WorkRule 默认值漂移；
    # 也不会把用户手改的 work_rule 悄悄"修正"成他们没设过的值。
    if not isinstance(att_cfg.get("work_rule"), dict):
        att_cfg["work_rule"] = {
            "work_start": "08:00",
            "work_end": "17:00",
            "standard_minutes": 480,
            "lunch_start": "12:00",
            "lunch_end": "13:00",
            "late_grace": 0,
            "overtime_granularity": 0,
        }
    cfg["attendance_cfg"] = att_cfg

    cfg["weather_enabled"] = to_bool(cfg.get("weather_enabled"), default=WEATHER_ENABLED_DEFAULT)
    city = cfg.get("weather_city")
    cfg["weather_city"] = (
        city.strip() if isinstance(city, str) and city.strip() else WEATHER_CITY_DEFAULT
    )
    provider = cfg.get("weather_provider")
    cfg["weather_provider"] = (
        provider if provider == WEATHER_PROVIDER_DEFAULT else WEATHER_PROVIDER_DEFAULT
    )
    for key, default, minimum, maximum in (
        ("weather_lat", WEATHER_LAT_DEFAULT, -90, 90),
        ("weather_lon", WEATHER_LON_DEFAULT, -180, 180),
    ):
        try:
            value = float(cfg.get(key, default))
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError
            cfg[key] = value
        except (TypeError, ValueError, OverflowError):
            cfg[key] = default
    raw_cities = cfg.get("weather_cities")
    cities = []
    seen_locations = set()
    if isinstance(raw_cities, list):
        for item in raw_cities:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            try:
                lat = float(item["lat"])
                lon = float(item["lon"])
                if (
                    not math.isfinite(lat)
                    or not -90 <= lat <= 90
                    or not math.isfinite(lon)
                    or not -180 <= lon <= 180
                ):
                    continue
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            key = (round(lat, 4), round(lon, 4))
            if key in seen_locations:
                continue
            seen_locations.add(key)
            entry = {"name": name.strip(), "lat": lat, "lon": lon}
            label = item.get("label")
            if isinstance(label, str) and label.strip():
                entry["label"] = label.strip()
            cities.append(entry)
    current_key = (round(cfg["weather_lat"], 4), round(cfg["weather_lon"], 4))
    if current_key not in seen_locations:
        cities.insert(
            0,
            {
                "name": cfg["weather_city"],
                "lat": cfg["weather_lat"],
                "lon": cfg["weather_lon"],
            },
        )
    cfg["weather_cities"] = cities
    cfg["weather_refresh_minutes"] = to_int_clamped(
        cfg.get("weather_refresh_minutes"), lo=5, hi=360, default=WEATHER_REFRESH_MINUTES_DEFAULT
    )

    try:
        op = float(cfg.get("opacity", 0.92))
        if math.isnan(op):
            op = 0.92
        cfg["opacity"] = max(0.0, min(1.0, op))
    except (TypeError, ValueError):
        cfg["opacity"] = 0.92
    cfg["config_version"] = CONFIG_VERSION
    if not isinstance(cfg.get("update_skipped_version"), str):
        cfg["update_skipped_version"] = ""
    theme_name = cfg.get("theme_name")
    if not isinstance(theme_name, str) or theme_name not in THEME_PRESETS:
        cfg["theme_name"] = THEME_LIGHT
    cfg["theme_auto_enabled"] = to_bool(cfg.get("theme_auto_enabled"), default=False)
    wallpaper = cfg.get("calendar_wallpaper", "")
    cfg["calendar_wallpaper"] = wallpaper if isinstance(wallpaper, str) else ""
    cfg["calendar_wallpaper_overlay"] = to_int_clamped(
        cfg.get("calendar_wallpaper_overlay"), lo=20, hi=90, default=58
    )
    return cfg
