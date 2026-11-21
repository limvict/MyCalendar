# coding: utf-8
"""天气代码 → 中文描述：met.no / uapis 的代码统一归一到 WMO。"""

from __future__ import annotations

# met.no 的 symbol_code → WMO。中文描述统一由 _wmo.wmo_description(code) 提供，
# 避免每个数据源各维护一份文案、彼此漂移。
_MET_WMO = {
    "clearsky": 0,
    "fair": 1,
    "partlycloudy": 2,
    "cloudy": 3,
    "fog": 45,
    "lightrain": 61,
    "rain": 63,
    "heavyrain": 65,
    # WMO 只有「轻/重」两档冻雨，met.no 有三档：轻与普通都归 66，强归 67，
    # 与 uapis 的「冻雨」→ 66 保持一致
    "lightsleet": 66,
    "sleet": 66,
    "heavysleet": 67,
    "lightsnow": 71,
    "snow": 73,
    "heavysnow": 75,
    "lightrainshowers": 80,
    "rainshowers": 81,
    "heavyrainshowers": 82,
    "lightsnowshowers": 85,
    "snowshowers": 86,
    "heavysnowshowers": 86,
    "thunderstorm": 95,
}


# uapis 的 weather_icon 用的是和风天气图标码（晴=100、多云=101、小雨=305……），
# 与 open_meteo 的 WMO 代码不是一套。这里统一映射成 WMO，让描述与图标保持一致。
# 参考和风天气天气图标代码表；夜间码 150-153 与对应白天码同义。
_UAPI_WMO = {
    # 晴 / 云
    100: 0,
    150: 0,  # 晴
    101: 2,
    151: 2,  # 多云
    102: 1,
    152: 1,  # 少云
    103: 2,
    153: 2,  # 晴间多云
    104: 3,  # 阴
    # 雨
    300: 80,  # 阵雨
    301: 82,  # 强阵雨
    302: 95,  # 雷阵雨
    303: 95,  # 强雷阵雨
    304: 96,  # 雷阵雨伴有冰雹
    305: 61,  # 小雨
    306: 63,  # 中雨
    307: 65,  # 大雨
    308: 65,  # 极端降雨
    309: 51,  # 毛毛雨/细雨
    310: 65,
    311: 65,
    312: 65,  # 暴雨 / 大暴雨 / 特大暴雨
    313: 66,  # 冻雨
    314: 63,
    315: 65,
    316: 65,
    317: 65,
    318: 65,  # 各级降雨
    399: 63,  # 雨
    # 雪
    400: 71,  # 小雪
    401: 73,  # 中雪
    402: 75,  # 大雪
    403: 75,  # 暴雪
    404: 66,  # 雨夹雪
    405: 66,  # 雨雪天气
    406: 66,  # 阵雨夹雪
    407: 85,  # 阵雪
    408: 73,
    409: 75,
    410: 75,  # 各级降雪
    499: 73,  # 雪
    # 雾 / 霾 / 沙尘（WMO 里没有沙尘码，统一按低能见度处理）
    500: 45,  # 薄雾
    501: 45,  # 雾
    502: 45,  # 霾
    503: 45,  # 扬沙
    504: 45,  # 浮尘
    507: 45,  # 沙尘暴
    508: 45,  # 强沙尘暴
    509: 48,  # 浓雾
    510: 48,  # 强浓雾
    511: 45,
    512: 45,
    513: 45,  # 中度 / 重度 / 严重霾
    514: 48,  # 大雾
    515: 48,  # 特强浓雾
    # 其他
    900: 0,  # 热
    901: 0,  # 冷
}


# 未知图标码时按描述文本归类，顺序敏感（“雨夹雪”应先命中“雪”）
_UAPI_TEXT_WMO = (
    (("雷", "thunder"), 95),
    (("冰雹", "hail"), 96),
    (("雪", "snow"), 71),
    (("雨", "rain", "drizzle"), 61),
    (("雾", "霾", "沙尘", "fog", "haze", "mist", "dust"), 45),
    (("多云",), 2),
    (("阴", "overcast"), 3),
    (("晴", "sun", "clear"), 0),
)


def _uapi_wmo_code(code: int, description: str) -> int:
    """把 uapis 图标码归一到 WMO；未知码退化为文本判断，最后按阴处理。"""
    mapped = _UAPI_WMO.get(code)
    if mapped is not None:
        return mapped
    text = description.lower()
    for keywords, wmo in _UAPI_TEXT_WMO:
        if any(keyword in text for keyword in keywords):
            return wmo
    # 判断不出时按“阴”给个中性图标，文字描述仍然是接口原文，不会误导
    return 3


_WMO_DESCRIPTIONS = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "冻雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    56: "轻度冻毛毛雨",
    57: "冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "轻度冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def wmo_description(code: int) -> str:
    """返回天气代码的中文描述，未知代码明确标记。"""
    return _WMO_DESCRIPTIONS.get(code, f"未知天气（{code}）")
