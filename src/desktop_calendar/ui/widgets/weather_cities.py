# coding: utf-8
"""城市列表：单条城市的校验与去重键（纯函数，不依赖 Qt）。"""

from __future__ import annotations

MAX_CITIES = 50


def valid_city(item) -> dict | None:
    """把配置/接口里的一条城市记录规整成 {name, lat, lon}，非法返回 None。"""
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    try:
        lat, lon = float(item["lat"]), float(item["lon"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if (
        not isinstance(name, str)
        or not name.strip()
        or not -90 <= lat <= 90
        or not -180 <= lon <= 180
    ):
        return None
    city = {"name": name.strip(), "lat": lat, "lon": lon}
    label = item.get("label")
    if isinstance(label, str) and label.strip():
        city["label"] = label.strip()
    adcode = item.get("adcode")
    if isinstance(adcode, (str, int)) and str(adcode).strip().isdigit():
        city["adcode"] = str(adcode).strip()
    return city


def city_key(city: dict) -> tuple[str, float, float]:
    """去重键：同名 + 坐标四舍五入到 4 位（约 10 米，足够区分同名区县）。"""
    return city["name"], round(city["lat"], 4), round(city["lon"], 4)
