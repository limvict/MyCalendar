# coding: utf-8
"""考勤打卡：记录存储 + 周/月统计。纯逻辑，不依赖 Qt，可独立单测。

按职责拆成三个模块：

- `models`：状态码、标准工时常量与统计结构体
- `rules` ：工时解析、迟到/早退判定、单日汇总
- `store` ：JSON 持久化、打卡写入与周/月统计

本文件只做汇总导出，`from desktop_calendar.core.attendance import ...`
的既有导入路径保持不变；末尾的私有辅助同样是给 `attendance_auto_punch`、
`attendance_reminder` 和测试用的兼容导出。
"""

from __future__ import annotations

from .models import (
    ATTENDANCE_VERSION,
    LUNCH_END,
    LUNCH_START,
    PUNCH_IN_DEADLINE_HOUR,
    STANDARD_END,
    STANDARD_MINUTES,
    STANDARD_START,
    STATUS_ABNORMAL,
    STATUS_ABSENT,
    STATUS_INCOMPLETE,
    STATUS_OK,
    STATUS_PENDING,
    STATUS_REST,
    DayStat,
    MonthSummary,
    PunchRejected,
    WeekSummary,
)
from .rules import WorkRule
from .rules import _analyze_full as _analyze_full
from .rules import _is_workday as _is_workday
from .rules import _raw_minutes as _raw_minutes
from .rules import _session_minutes as _session_minutes
from .store import AttendanceStore

__all__ = [
    "AttendanceStore",
    "WorkRule",
    "DayStat",
    "WeekSummary",
    "MonthSummary",
    "PunchRejected",
    "STATUS_OK",
    "STATUS_INCOMPLETE",
    "STATUS_ABNORMAL",
    "STATUS_ABSENT",
    "STATUS_REST",
    "STATUS_PENDING",
    "STANDARD_START",
    "STANDARD_END",
    "STANDARD_MINUTES",
    "LUNCH_START",
    "LUNCH_END",
    "PUNCH_IN_DEADLINE_HOUR",
    "ATTENDANCE_VERSION",
]
