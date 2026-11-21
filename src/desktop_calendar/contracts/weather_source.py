from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WeatherInfo:
    city: str
    temperature: float  # ℃
    code: int  # WMO 天气代码
    description: str  # 中文描述
    humidity: int | None = None
    wind_speed: float | None = None
    updated_at: str = ""


class WeatherSource(Protocol):
    def get_cached(self, city: str, lat: float, lon: float) -> WeatherInfo | None: ...

    def fetch(
        self,
        city: str,
        lat: float,
        lon: float,
        on_ok: Callable[[WeatherInfo], None],
        on_err: Callable[[str], None],
        adcode: str | None = None,
    ) -> None: ...

    def list_cities(
        self,
        province: str,
        adcode: str,
        on_ok: Callable[[list[dict]], None],
        on_err: Callable[[str], None],
    ) -> None: ...
