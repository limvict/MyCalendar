# coding: utf-8
"""天气数据源：open-meteo → met.no → uapis 依次兜底。

拆成四个模块，按「数据 / 解析 / 传输」分工：

- `codes`  ：天气代码 → 中文描述（met.no、uapis 的码统一归一到 WMO）
- `parsing`：接口响应 → `WeatherInfo` / 城市列表（纯函数，不碰网络）
- `source` ：`OpenMeteoSource`，负责请求、兜底与 24 小时本地缓存

对外只暴露 `OpenMeteoSource`。
"""

from __future__ import annotations

from .source import OpenMeteoSource

__all__ = ["OpenMeteoSource"]
