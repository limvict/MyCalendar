# coding: utf-8
"""节假日接口响应解析：多种返回结构统一成 {date: kind}（纯函数）。

数据源格式差异（NateScarlet / chinese-days / Timor / 缓存文件）都在这里
收敛，网络层只负责拿字符串过来。
"""

from __future__ import annotations

import json
from datetime import datetime

from ...utils.coerce import to_holiday_kind


def kind_from_off(is_off) -> str:
    """isOffDay / type 归一化为 "holiday" | "workday"。

    兼容 bool / 字符串 / 数字；缺失或未知值保守回退 workday
    （漏报休息日好于把工作日误标为休息日）。
    """
    kind = to_holiday_kind(is_off)
    return kind if kind is not None else "workday"


def is_date_like(s: str) -> bool:
    """YYYY-MM-DD 形状判断（宽松版，不校验月日范围）。"""
    return len(s) == 10 and s[4] == "-" and s[7] == "-"


def parse_day_items(items) -> dict:
    """[{"date": "...", "isOffDay": true}, ...] → {date: kind}。

    取值优先级：isOffDay → type → 保守回退 workday。
    isOffDay 为 None（键缺失）时才回退 type；显式 False / 0 / "" 视为有效。
    """
    result = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        date_str = item.get("date")
        if not isinstance(date_str, str) or not date_str:
            continue
        raw = item.get("isOffDay")
        if raw is None:
            raw = item.get("type")
        result[date_str] = kind_from_off(raw)
    return result


def parse_day_map(mapping, *, date_keys_only: bool) -> dict:
    """{date: is_off, ...} → {date: kind}。

    date_keys_only=True 时只保留日期形状的 key（顶层 map 可能混入
    version/updated 等元数据）；False 时保留全部字符串 key。
    """
    result = {}
    for date_str, is_off in mapping.items():
        if not isinstance(date_str, str):
            continue
        if date_keys_only and not is_date_like(date_str):
            continue
        result[date_str] = kind_from_off(is_off)
    return result


def parse_timor_response(payload, default_year: int) -> dict:
    if (
        not isinstance(payload, dict)
        or payload.get("code") != 0
        or not isinstance(payload.get("holiday"), dict)
    ):
        raise ValueError("Timor 节假日 API 响应无效")
    result = {}
    for item in payload["holiday"].values():
        if not isinstance(item, dict):
            continue
        date_str = item.get("date")
        holiday = item.get("holiday")
        if not isinstance(date_str, str) or type(holiday) is not bool:
            continue
        try:
            parsed = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if parsed.isoformat() != date_str or parsed.year != default_year:
            continue
        result[date_str] = "holiday" if holiday else "workday"
    if not result:
        raise ValueError("Timor 节假日 API 未返回有效日期")
    return result


def looks_like_date_map(mapping) -> bool:
    """至少一个 key 是 YYYY-MM-DD 形状。"""
    return any(isinstance(k, str) and is_date_like(k) for k in mapping.keys())


def parse_cache_like(mapping, default_year: int):
    """尝试按缓存文件结构解析；不是缓存结构返回 None。

    缓存结构：{ "2027": {"ts": ..., "days": {...}}, ... }
    只取 default_year 那年的数据；不含该年返回 {}。
    """
    entries = []
    for year_key, year_data in mapping.items():
        if not isinstance(year_data, dict):
            continue
        days = year_data.get("days")
        if not isinstance(days, dict):
            continue
        try:
            year_int = int(year_key)
        except (TypeError, ValueError):
            continue
        entries.append((year_int, days))
    if not entries:
        return None
    for year_int, days in entries:
        if year_int == default_year:
            return parse_day_map(days, date_keys_only=False)
    return {}


def parse_holiday_json(raw: str, default_year: int) -> dict:
    """兼容多种源格式，统一输出 {date_str: "holiday" | "workday"}。

    1. NateScarlet: {"year":..., "days":[{"date":..., "isOffDay":...}]}
    2. chinese-days: {"days": {...}} 或顶层 {date: is_off}
    3. list of {"date":..., "isOffDay"/"type":...}
    4. 缓存文件整体结构（只取 default_year 那年）

    无法识别时抛 ValueError，由 on_reply 捕获后重试下一个 CDN。
    """
    j = json.loads(raw)

    if isinstance(j, dict):
        if "holiday" in j or "code" in j:
            return parse_timor_response(j, default_year)
        cached = parse_cache_like(j, default_year)
        if cached is not None:
            return cached

        days = j.get("days")
        if isinstance(days, list):
            return parse_day_items(days)
        if isinstance(days, dict):
            return parse_day_map(days, date_keys_only=False)
        if looks_like_date_map(j):
            return parse_day_map(j, date_keys_only=True)

    if isinstance(j, list):
        return parse_day_items(j)

    raise ValueError(f"无法识别的节假日JSON结构，year={default_year}")
