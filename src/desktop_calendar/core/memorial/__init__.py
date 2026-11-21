# coding: utf-8
"""纪念日：归一化、日期匹配、下次发生日期计算、日历索引。

按职责拆成四个模块：

- `common`    ：重复类型常量与日期/整数小工具
- `normalize` ：把外部数据收敛成合法结构
- `recurrence`：公历/农历的匹配与「下一次发生」计算
- `index`     ：按「公历/农历 × 年/月/周」建表，供日历快速查询

`from desktop_calendar.core.memorial import ...` 的既有导入路径保持不变。
"""

from __future__ import annotations

from .common import REPEAT_MONTH, REPEAT_ONCE, REPEAT_WEEK, REPEAT_YEAR
from .index import build_memorial_index
from .normalize import normalize_memorial, normalize_memorial_days
from .recurrence import (
    get_anniversary_years,
    get_next_memorial_date,
    match_memorial_date,
)

__all__ = [
    "REPEAT_YEAR",
    "REPEAT_MONTH",
    "REPEAT_WEEK",
    "normalize_memorial",
    "normalize_memorial_days",
    "get_next_memorial_date",
    "match_memorial_date",
    "get_anniversary_years",
    "build_memorial_index",
    "REPEAT_ONCE",
]
