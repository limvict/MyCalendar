# coding: utf-8
"""天气接口响应解析：行政区检索 + 三家数据源的字段归一。

全部是纯函数：输入 JSON，输出 `WeatherInfo` / 城市列表，不碰网络与 Qt。
"""

from __future__ import annotations

import math

from ....contracts.weather_source import WeatherInfo
from .codes import _MET_WMO, _uapi_wmo_code, wmo_description


def parse_cities_in_province(province: str, payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValueError(f"城市数据格式无效：{province}")
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError(f"没有找到{province}的城市列表")
    city_results = [
        item
        for item in results
        if isinstance(item, dict) and str(item.get("level", "")).lower() == "city"
    ]
    return parse_districts(province, {"results": city_results})


def parse_districts(name: str, payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValueError(f"城市数据格式无效：{name}")
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError(f"没有找到城市：{name}")
    cities = []
    for result in results:
        if not isinstance(result, dict):
            continue
        city_name = result.get("name")
        level = result.get("level")
        if level and str(level).lower() not in {
            "province",
            "city",
            "district",
            "county",
        }:
            continue
        center = result.get("center")
        if not isinstance(center, dict):
            continue
        try:
            lat = float(center["lat"])
            lon = float(center["lng"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if (
            not isinstance(city_name, str)
            or not city_name.strip()
            or not math.isfinite(lat)
            or not -90 <= lat <= 90
            or not math.isfinite(lon)
            or not -180 <= lon <= 180
        ):
            continue
        label_parts = []
        for key in ("name", "province", "city", "district", "country"):
            value = result.get(key)
            if isinstance(value, str) and value.strip() and value.strip() not in label_parts:
                label_parts.append(value.strip())
        city = {
            "name": city_name.strip(),
            "label": "，".join(label_parts),
            "lat": lat,
            "lon": lon,
        }
        # 国内行政区带 adcode；uapis 天气接口用它区分同名区县
        adcode = result.get("adcode")
        if isinstance(adcode, (str, int)) and str(adcode).strip().isdigit():
            city["adcode"] = str(adcode).strip()
        cities.append(city)
    if not cities:
        raise ValueError(f"城市坐标无效：{name}")
    return cities


def parse_open_meteo(city: str, payload: dict) -> WeatherInfo:
    cur = payload["current"]
    temperature = float(cur["temperature_2m"])
    raw_wind_speed = cur.get("wind_speed_10m")
    wind_speed = float(raw_wind_speed) if raw_wind_speed is not None else None
    if not math.isfinite(temperature) or (wind_speed is not None and not math.isfinite(wind_speed)):
        raise ValueError("天气 API 返回了非有限数值")
    code = int(cur["weather_code"])
    humidity = cur.get("relative_humidity_2m")
    return WeatherInfo(
        city=city,
        temperature=temperature,
        code=code,
        description=wmo_description(code),
        humidity=int(humidity) if humidity is not None else None,
        wind_speed=wind_speed,
        updated_at=str(cur.get("time", "")),
    )


def parse_met_no(city: str, payload: dict) -> WeatherInfo:
    first = payload["properties"]["timeseries"][0]
    details = first["data"]["instant"]["details"]
    temperature = float(details["air_temperature"])
    raw_wind_speed = details.get("wind_speed")
    wind_speed = float(raw_wind_speed) * 3.6 if raw_wind_speed is not None else None
    if not math.isfinite(temperature) or (wind_speed is not None and not math.isfinite(wind_speed)):
        raise ValueError("天气 API 返回了非有限数值")
    forecast = first["data"]
    periods = ("next_1_hours", "next_6_hours", "next_12_hours")
    symbol = next(
        (forecast[key]["summary"]["symbol_code"] for key in periods if key in forecast), None
    )
    if not symbol:
        raise ValueError("天气 API 响应缺少天气状况")
    symbol = symbol.split("_", 1)[0]
    code = _MET_WMO.get(symbol)
    if code is None:
        code = 3
        description = f"天气状况：{symbol}"
    else:
        description = wmo_description(code)
    humidity = details.get("relative_humidity")
    return WeatherInfo(
        city=city,
        temperature=temperature,
        code=code,
        description=description,
        humidity=int(humidity) if humidity is not None else None,
        wind_speed=wind_speed,
        updated_at=str(first.get("time", "")),
    )


def parse_uapis(city: str, payload: dict) -> WeatherInfo:
    try:
        temperature = float(payload["temperature"])
        raw_code = int(payload["weather_icon"])
        humidity = payload.get("humidity")
        humidity = int(humidity) if humidity is not None else None
        description = str(payload["weather"]).strip()
        if not description:
            raise ValueError("天气 API 返回了空天气描述")
        if not math.isfinite(temperature):
            raise ValueError("天气 API 返回了非有限温度")
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"UApi 天气数据无效: {error}") from error
    code = _uapi_wmo_code(raw_code, description)
    response_city = payload.get("city")
    if not isinstance(response_city, str) or not response_city.strip():
        response_city = city
    return WeatherInfo(
        city=response_city.strip(),
        temperature=temperature,
        code=code,
        description=description,
        humidity=humidity,
        updated_at=str(payload.get("report_time", "")),
    )
