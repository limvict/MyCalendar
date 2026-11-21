# coding: utf-8
"""OpenMeteoSource：三家天气接口的异步请求、兜底与本地缓存。"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable

from PyQt6.QtCore import QObject, QUrl, QUrlQuery
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ....config.manager import atomic_write_json, get_logger
from ....contracts.weather_source import WeatherInfo
from ....utils.paths import get_app_data_dir
from .parsing import (
    parse_cities_in_province,
    parse_districts,
    parse_met_no,
    parse_open_meteo,
    parse_uapis,
)

logger = get_logger()

_API = "https://api.open-meteo.com/v1/forecast"
_MET_API = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
_UAPI_API = "https://uapis.cn/api/v1/misc/weather"
_UAPI_DISTRICT_API = "https://uapis.cn/api/v1/misc/district"
_PROVIDERS = ("open_meteo", "met_no", "uapis")
_CACHE_FILE = "weather_cache.json"
_CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
_CACHE_MAX_LOCATIONS = 8
_REQUEST_TIMEOUT_MS = 8_000


class OpenMeteoSource(QObject):
    """天气数据源：open-meteo → met.no → uapis 依次兜底，并缓存 24 小时。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._cache: dict[str, dict] | None = None

    @staticmethod
    def _cache_key(lat: float, lon: float) -> str:
        return f"{float(lat):.4f},{float(lon):.4f}"

    @staticmethod
    def _cache_path() -> str:
        return os.path.join(get_app_data_dir(), _CACHE_FILE)

    def _load_cache(self) -> dict[str, dict]:
        if self._cache is not None:
            return self._cache
        path = self._cache_path()
        try:
            with open(path, encoding="utf-8") as cache_file:
                data = json.load(cache_file)
        except FileNotFoundError:
            data = {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            logger.warning("读取天气缓存失败: %s", error)
            data = {}
        if not isinstance(data, dict):
            logger.warning("天气缓存格式异常，已忽略")
            data = {}
        entries = data.get("locations", {})
        if not isinstance(entries, dict):
            logger.warning("天气缓存条目格式异常，已忽略")
            entries = {}
        self._cache = {
            key: entry
            for key, entry in entries.items()
            if isinstance(key, str)
            and isinstance(entry, dict)
            and isinstance(entry.get("info"), dict)
            and isinstance(entry.get("cached_at"), (int, float))
            and math.isfinite(entry["cached_at"])
        }
        if len(self._cache) != len(entries):
            logger.warning("天气缓存包含无效条目，已忽略")
        return self._cache

    def get_cached(self, city: str, lat: float, lon: float) -> WeatherInfo | None:
        entry = self._load_cache().get(self._cache_key(lat, lon))
        if not isinstance(entry, dict):
            return None
        try:
            age = time.time() - float(entry["cached_at"])
            if age < 0 or age > _CACHE_MAX_AGE_SECONDS:
                return None
            info = entry["info"]
            temperature = float(info["temperature"])
            wind_speed = float(info["wind_speed"]) if info.get("wind_speed") is not None else None
            if not math.isfinite(temperature) or (
                wind_speed is not None and not math.isfinite(wind_speed)
            ):
                raise ValueError("缓存包含非有限天气数值")
            return WeatherInfo(
                city=city,
                temperature=temperature,
                code=int(info["code"]),
                description=str(info["description"]),
                humidity=(int(info["humidity"]) if info.get("humidity") is not None else None),
                wind_speed=wind_speed,
                updated_at=str(info.get("updated_at", "")),
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            logger.warning("天气缓存条目无效，已忽略 location=%s", self._cache_key(lat, lon))
            return None

    def fetch(
        self,
        city,
        lat,
        lon,
        on_ok: Callable[[WeatherInfo], None],
        on_err: Callable[[str], None],
        adcode: str | None = None,
    ) -> None:
        # adcode 仅对 uapis 兜底有效（该接口不支持经纬度，但 adcode 优先于城市名，
        # 能区分“北京朝阳区 / 长春朝阳区”这类同名行政区）。
        self._fetch_provider(city, float(lat), float(lon), on_ok, on_err, 0, [], adcode)

    def resolve_city(self, name: str, on_ok, on_err) -> None:
        query = QUrlQuery()
        query.addQueryItem("keywords", name)
        self._request_districts(
            query, lambda payload: parse_districts(name, payload), on_ok, on_err
        )

    def list_cities(self, province: str, adcode: str, on_ok, on_err) -> None:
        query = QUrlQuery()
        query.addQueryItem("keywords", province)
        query.addQueryItem("adcode", adcode)
        self._request_districts(
            query, lambda payload: parse_cities_in_province(province, payload), on_ok, on_err
        )

    def _request_districts(self, query, parser, on_ok, on_err) -> None:
        url = QUrl(_UAPI_DISTRICT_API)
        url.setQuery(query)
        request = QNetworkRequest(url)
        request.setTransferTimeout(_REQUEST_TIMEOUT_MS)
        reply = self._nam.get(request)

        def finish() -> None:
            reply.deleteLater()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                on_err(reply.errorString())
                return
            try:
                payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
                result = parser(payload)
            except (
                KeyError,
                TypeError,
                ValueError,
                UnicodeDecodeError,
            ) as error:
                on_err(str(error))
                return
            on_ok(result)

        reply.finished.connect(finish)

    def _fetch_provider(
        self,
        city: str,
        lat: float,
        lon: float,
        on_ok,
        on_err,
        provider_index: int,
        errors: list[str],
        adcode: str | None = None,
    ) -> None:
        if provider_index >= len(_PROVIDERS):
            on_err("；".join(errors))
            return
        provider = _PROVIDERS[provider_index]
        url = QUrl(
            {
                "open_meteo": _API,
                "met_no": _MET_API,
                "uapis": _UAPI_API,
            }[provider]
        )
        query = QUrlQuery()
        if provider == "open_meteo":
            query.addQueryItem("latitude", str(lat))
            query.addQueryItem("longitude", str(lon))
            query.addQueryItem(
                "current", "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
            )
            query.addQueryItem("timezone", "auto")
        elif provider == "met_no":
            query.addQueryItem("lat", str(lat))
            query.addQueryItem("lon", str(lon))
        else:
            # uapis 不支持经纬度；adcode 优先级高于 city，两者同时给更稳
            if adcode:
                query.addQueryItem("adcode", adcode)
            query.addQueryItem("city", city)
        url.setQuery(query)
        req = QNetworkRequest(url)
        req.setTransferTimeout(_REQUEST_TIMEOUT_MS)
        if provider == "met_no":
            req.setRawHeader(
                b"User-Agent", b"MyCalendarApp/3.0.5 (https://github.com/limvict/MyCalendar)"
            )
        reply = self._nam.get(req)
        reply.finished.connect(
            lambda: self._on_reply(
                reply, city, lat, lon, on_ok, on_err, provider, provider_index, errors, adcode
            )
        )

    def _on_reply(
        self,
        reply: QNetworkReply,
        city: str,
        lat: float,
        lon: float,
        on_ok,
        on_err,
        provider: str,
        provider_index: int,
        errors: list[str],
        adcode: str | None = None,
    ) -> None:
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            error = reply.errorString()
            logger.warning("天气 API %s 请求失败: %s", provider, error)
            self._fetch_provider(
                city,
                lat,
                lon,
                on_ok,
                on_err,
                provider_index + 1,
                [*errors, f"{provider}: {error}"],
                adcode,
            )
            return
        try:
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            parsers = {
                "open_meteo": parse_open_meteo,
                "met_no": parse_met_no,
                "uapis": parse_uapis,
            }
            info = parsers[provider](city, payload)
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
        ) as exc:
            error = str(exc)
            logger.warning("天气 API %s 响应无效: %s", provider, error)
            self._fetch_provider(
                city,
                lat,
                lon,
                on_ok,
                on_err,
                provider_index + 1,
                [*errors, f"{provider}: {error}"],
                adcode,
            )
            return
        self._save_cache(lat, lon, info)
        on_ok(info)

    def _save_cache(self, lat: float, lon: float, info: WeatherInfo) -> None:
        cache = self._load_cache()
        cache[self._cache_key(lat, lon)] = {
            "cached_at": time.time(),
            "info": {
                "temperature": info.temperature,
                "code": info.code,
                "description": info.description,
                "humidity": info.humidity,
                "wind_speed": info.wind_speed,
                "updated_at": info.updated_at,
            },
        }
        while len(cache) > _CACHE_MAX_LOCATIONS:
            oldest = min(cache, key=lambda key: cache[key].get("cached_at", 0))
            del cache[oldest]
        try:
            atomic_write_json(self._cache_path(), {"locations": cache}, protect=True)
        except OSError:
            logger.exception("保存天气缓存失败")
