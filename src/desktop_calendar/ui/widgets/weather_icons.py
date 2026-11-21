# coding: utf-8
"""天气图标映射：WMO 代码 → emoji，未知代码按中文/英文描述归类。"""

from __future__ import annotations

# WMO 天气代码 → 图标。描述文案由 weather_source/codes.py 统一提供，
# 这里只负责挑一个最接近的 emoji。
_WMO_ICONS = {
    0: "☀️",
    1: "🌤️",
    2: "⛅",
    3: "☁️",
    45: "🌫️",
    48: "🌫️",
    51: "🌦️",
    53: "🌦️",
    55: "🌧️",
    56: "🌧️",
    57: "🌧️",
    61: "🌧️",
    63: "🌧️",
    65: "🌧️",
    66: "🌧️",
    67: "🌧️",
    71: "🌨️",
    73: "🌨️",
    75: "❄️",
    77: "🌨️",
    80: "🌦️",
    81: "🌧️",
    82: "🌧️",
    85: "🌨️",
    86: "❄️",
    95: "⛈️",
    96: "⛈️",
    99: "⛈️",
}


def weather_icon_for(info) -> str:
    """按天气代码取图标；代码缺失或未知时退化为描述文本归类。"""
    code = getattr(info, "code", None)
    if code in _WMO_ICONS:
        return _WMO_ICONS[code]

    description = str(getattr(info, "description", "")).lower()
    if any(word in description for word in ("雷", "thunder")):
        return "⛈️"
    if any(word in description for word in ("雪", "冰雹", "snow", "hail")):
        return "🌨️"
    if any(word in description for word in ("雨", "rain", "drizzle")):
        return "🌧️"
    if any(word in description for word in ("雾", "霾", "fog", "mist", "haze")):
        return "🌫️"
    if any(word in description for word in ("阴", "多云", "cloud")):
        return "☁️"
    if any(word in description for word in ("晴", "sun", "clear")):
        return "☀️"
    return "🌡️"
