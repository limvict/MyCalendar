# coding: utf-8
"""考勤数据模型：状态码、标准工时常量与统计结构体。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

ATTENDANCE_VERSION = 1


_MAX_SESSION_MINUTES = 18 * 60


STANDARD_START = 8 * 60  # 08:00


STANDARD_END = 17 * 60  # 17:00


STANDARD_MINUTES = 8 * 60  # 480


LUNCH_START = 12 * 60  # 12:00


LUNCH_END = 13 * 60  # 13:00


# 上班打卡截止小时：11:00 起不允许再打上班卡（含首次打卡与补卡）。
# 与 work_rule.start 解耦：即便用户自定义上班时间为 10:30，
# 11:00 后仍不可再打上班卡——这是产品硬规则，不是弹性配置。
# 该规则由 AttendanceStore.punch 兜底执行，UI / 提醒层仅做提前提示。
PUNCH_IN_DEADLINE_HOUR = 11


STATUS_OK = "ok"


STATUS_INCOMPLETE = "incomplete"


STATUS_ABNORMAL = "abnormal"


STATUS_ABSENT = "absent"


STATUS_REST = "rest"


STATUS_PENDING = "pending"


class PunchRejected(ValueError):
    """打卡被业务规则拒绝（重复上班卡 / 超过上班卡截止时间）。

    code 供 UI 层区分提示文案；message 供日志与兜底展示。
    继承 ValueError 以兼容历史上 `raise ValueError(...)` 的调用方。
    """

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class DayStat:
    day: date
    in_time: str | None
    out_time: str | None
    minutes: int | None  # 净工时（已扣午休）
    status: str
    is_workday: bool
    is_late: bool = False
    is_early_leave: bool = False
    overtime_minutes: int | None = None


@dataclass(frozen=True)
class WeekSummary:
    start: date
    end: date
    days: tuple[DayStat, ...]
    total_minutes: int
    attended_days: int
    complete_days: int
    avg_minutes: int | None
    total_overtime: int = 0
    late_count: int = 0
    early_count: int = 0


@dataclass(frozen=True)
class MonthSummary:
    year: int
    month: int
    days: tuple[DayStat, ...]
    workdays: int
    total_minutes: int
    attended_days: int
    complete_days: int
    avg_minutes: int | None
    total_overtime: int = 0
    late_count: int = 0
    early_count: int = 0
