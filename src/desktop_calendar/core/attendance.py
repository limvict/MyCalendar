# coding: utf-8
"""考勤打卡：记录存储 + 周/月统计。纯逻辑，不依赖 Qt，可独立单测。"""
from __future__ import annotations

import calendar
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Optional, Tuple

from desktop_calendar.config.manager import atomic_write_json, get_logger
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.utils.coerce import to_int_clamped
from desktop_calendar.utils.paths import get_app_data_dir

logger = get_logger()

__all__ = [
    "AttendanceStore", "WorkRule", "DayStat", "WeekSummary", "MonthSummary",
    "STATUS_OK", "STATUS_INCOMPLETE", "STATUS_ABNORMAL",
    "STATUS_ABSENT", "STATUS_REST", "STATUS_PENDING",
    "STANDARD_START", "STANDARD_END", "STANDARD_MINUTES",
    "LUNCH_START", "LUNCH_END",
    "PUNCH_IN_DEADLINE_HOUR",
]

ATTENDANCE_VERSION = 1
_MAX_SESSION_MINUTES = 18 * 60

STANDARD_START = 8 * 60    # 08:00
STANDARD_END = 17 * 60     # 17:00
STANDARD_MINUTES = 8 * 60  # 480
LUNCH_START = 12 * 60      # 12:00
LUNCH_END = 13 * 60        # 13:00

# 上班打卡截止小时：11:00 起不允许再打上班卡（含首次打卡与补卡）。
# 与 work_rule.start 解耦：即便用户自定义上班时间为 10:30，
# 11:00 后仍不可再打上班卡——这是产品硬规则，不是弹性配置。
PUNCH_IN_DEADLINE_HOUR = 11

STATUS_OK = "ok"
STATUS_INCOMPLETE = "incomplete"
STATUS_ABNORMAL = "abnormal"
STATUS_ABSENT = "absent"
STATUS_REST = "rest"
STATUS_PENDING = "pending"


@dataclass(frozen=True)
class DayStat:
    day: date
    in_time: Optional[str]
    out_time: Optional[str]
    minutes: Optional[int]        # 净工时（已扣午休）
    status: str
    is_workday: bool
    is_late: bool = False
    is_early_leave: bool = False
    overtime_minutes: Optional[int] = None


@dataclass(frozen=True)
class WeekSummary:
    start: date
    end: date
    days: Tuple[DayStat, ...]
    total_minutes: int
    attended_days: int
    complete_days: int
    avg_minutes: Optional[int]
    total_overtime: int = 0
    late_count: int = 0
    early_count: int = 0


@dataclass(frozen=True)
class MonthSummary:
    year: int
    month: int
    days: Tuple[DayStat, ...]
    workdays: int
    total_minutes: int
    attended_days: int
    complete_days: int
    avg_minutes: Optional[int]
    total_overtime: int = 0
    late_count: int = 0
    early_count: int = 0


def _default_path() -> str:
    return os.path.join(get_app_data_dir(), "attendance.json")


def _parse_hm(value) -> Optional[int]:
    """'HH:MM' → 当日分钟数；非法返回 None。"""
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


# ===================== 考勤规则 =====================
@dataclass(frozen=True)
class WorkRule:
    """考勤规则。默认值与模块常量一致；from_config 从 attendance_cfg.work_rule 读取。

    时间字段单位为「当日分钟数」。lunch_start / lunch_end 同为 None 表示
    无午休扣除；一端为 None 时 from_config 会归一化为两端 None。
    """
    start: int = STANDARD_START
    end: int = STANDARD_END
    standard_minutes: int = STANDARD_MINUTES
    lunch_start: Optional[int] = LUNCH_START
    lunch_end: Optional[int] = LUNCH_END
    late_grace: int = 0
    overtime_granularity: int = 0

    @classmethod
    def from_config(cls, config) -> "WorkRule":
        if config is None:
            return cls()
        try:
            cfg = config.get_nested(
                "attendance_cfg", "work_rule", default={})
        except Exception:
            logger.debug("读取 work_rule 失败，使用默认规则", exc_info=True)
            return cls()
        if not isinstance(cfg, dict):
            return cls()

        def _hm(key, default):
            """值缺失 / 非法 → default；字符串 → parse。"""
            v = cfg.get(key)
            if not isinstance(v, str):
                return default
            parsed = _parse_hm(v)
            return default if parsed is None else parsed

        def _opt_hm(key, default):
            """区分「未配置」和「显式 None」：
            - 键不存在 → default（继承类默认值）
            - 值为 None → None（显式关闭午休）
            - 字符串 → parse；非法 → default
            - 其他类型 → default
            """
            if key not in cfg:
                return default
            v = cfg.get(key)
            if v is None:
                return None
            if isinstance(v, str):
                parsed = _parse_hm(v)
                return default if parsed is None else parsed
            return default

        start = _hm("work_start", cls.start)
        end = _hm("work_end", cls.end)
        if start >= end:
            logger.warning(
                "work_rule 上下班时刻非法 start=%s >= end=%s，回退默认",
                start, end)
            start, end = cls.start, cls.end

        lunch_start = _opt_hm("lunch_start", cls.lunch_start)
        lunch_end = _opt_hm("lunch_end", cls.lunch_end)
        if (lunch_start is None) != (lunch_end is None):
            logger.warning(
                "work_rule 午休区间只配了一端（start=%r end=%r），按无午休处理",
                lunch_start, lunch_end)
            lunch_start = lunch_end = None
        elif lunch_start is not None and lunch_start >= lunch_end:
            logger.warning(
                "work_rule 午休区间非法 start=%s >= end=%s，按无午休处理",
                lunch_start, lunch_end)
            lunch_start = lunch_end = None

        return cls(
            start=start,
            end=end,
            standard_minutes=to_int_clamped(
                cfg.get("standard_minutes"), lo=60, hi=24 * 60,
                default=cls.standard_minutes),
            lunch_start=lunch_start,
            lunch_end=lunch_end,
            late_grace=to_int_clamped(
                cfg.get("late_grace"), lo=0, hi=60, default=0),
            overtime_granularity=to_int_clamped(
                cfg.get("overtime_granularity"), lo=0, hi=60, default=0),
        )


def _raw_minutes(in_time: Optional[str],
                 out_time: Optional[str]) -> Optional[int]:
    """原始在岗时长（不扣午休，跨天 +24h）。非法时间串返回 None。"""
    i = _parse_hm(in_time)
    o = _parse_hm(out_time)
    if i is None or o is None:
        return None
    return (o - i) + (24 * 60 if o < i else 0)


def _session_minutes(in_time: Optional[str],
                     out_time: Optional[str],
                     rule: Optional[WorkRule] = None) -> Optional[int]:
    """返回净工时（扣除与午休区间重叠的部分）。rule=None 时用模块常量。"""
    i = _parse_hm(in_time)
    o = _parse_hm(out_time)
    if i is None or o is None:
        return None
    if rule is None:
        lunch_start, lunch_end = LUNCH_START, LUNCH_END
    else:
        lunch_start, lunch_end = rule.lunch_start, rule.lunch_end
    o_abs = o + (24 * 60 if o < i else 0)
    raw = o_abs - i
    if lunch_start is None or lunch_end is None:
        return max(0, raw)
    lunch = max(0, min(o_abs, lunch_end) - max(i, lunch_start))
    return max(0, raw - lunch)


def _is_workday(d: date) -> bool:
    try:
        return bool(lunar_mod.is_workday(d))
    except Exception:
        return d.weekday() < 5


def _analyze_full(in_time: str, out_time: str, is_workday: bool,
                  rule: Optional[WorkRule] = None
                  ) -> Tuple[bool, bool, Optional[int]]:
    """返回 (is_late, is_early_leave, overtime_minutes)。

    迟到 / 早退按时刻；加班 = 净工时 − standard_minutes，再按粒度取整。
    非工作日：不判迟到/早退，净工时全部计加班。
    跨天（o_abs >= 24h）不判早退。
    """
    i = _parse_hm(in_time)
    o = _parse_hm(out_time)
    if i is None or o is None:
        return False, False, None
    if rule is None:
        start, end = STANDARD_START, STANDARD_END
        standard, grace, granularity = STANDARD_MINUTES, 0, 0
    else:
        start, end = rule.start, rule.end
        standard = rule.standard_minutes
        grace = rule.late_grace
        granularity = rule.overtime_granularity

    o_abs = o + (24 * 60 if o < i else 0)
    net = _session_minutes(in_time, out_time, rule)
    net = 0 if net is None else net

    if not is_workday:
        return False, False, (net or None)

    is_late = i > start + grace
    is_early = o_abs < end
    overtime = max(0, net - standard)
    if granularity > 0 and overtime:
        overtime = (overtime // granularity) * granularity
    return is_late, is_early, (overtime or None)


class AttendanceStore:
    """打卡记录的加载 / 修改 / 统计。"""

    def __init__(self, path: Optional[str] = None, config=None):
        self._path = path or _default_path()
        self._rule = WorkRule.from_config(config)
        self._records: Dict[str, dict] = {}
        self._load()

    # ---------- 持久化 ----------
    def _backup_corrupt(self) -> None:
        try:
            base = f"{self._path}.corrupt-{time.strftime('%Y%m%d_%H%M%S')}"
            backup, n = base, 1
            while os.path.exists(backup):
                backup = f"{base}_{n}"
                n += 1
                if n > 10:
                    logger.warning(
                        "损坏考勤文件备份同名冲突超过 10 次，使用 %s", backup)
                    break
            os.replace(self._path, backup)
            logger.warning("损坏的考勤文件已备份到 %s", backup)
        except OSError:
            logger.debug("备份损坏考勤文件失败", exc_info=True)

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            logger.warning("读取考勤数据失败: %s", self._path, exc_info=True)
            self._backup_corrupt()
            return
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, dict):
            logger.warning(
                "考勤文件结构异常（records 非 dict），已备份: %s", self._path)
            self._backup_corrupt()
            return
        clean: Dict[str, dict] = {}
        for k, v in records.items():
            if not isinstance(k, str) or not isinstance(v, dict):
                continue
            in_t = v.get("in")
            out_t = v.get("out")
            if _parse_hm(in_t) is None:
                in_t = None
            if _parse_hm(out_t) is None:
                out_t = None
            if in_t is None and out_t is None:
                continue
            clean[k] = {**v, "in": in_t, "out": out_t}
        self._records = clean

    def _save(self) -> None:
        atomic_write_json(self._path, {
            "version": ATTENDANCE_VERSION,
            "records": self._records,
        })

    # ---------- 打卡 ----------
    def punch(self, action: str,
              now: Optional[datetime] = None) -> Tuple[str, bool]:
        now = now or datetime.now()
        if action not in ("in", "out"):
            raise ValueError(f"unknown punch action: {action!r}")
        day_key = now.date().isoformat()
        hm = now.strftime("%H:%M")

        old = self._records.get(day_key)
        old_copy = dict(old) if old else None
        rec = dict(old) if old else {}
        updated = rec.get(action) is not None
        rec[action] = hm
        self._records[day_key] = rec
        try:
            self._save()
        except Exception:
            if old_copy is None:
                self._records.pop(day_key, None)
            else:
                self._records[day_key] = old_copy
            raise
        return hm, updated

    def get_record(self, day) -> dict:
        if isinstance(day, datetime):
            day = day.date()
        key = day.isoformat() if isinstance(day, date) else str(day)
        return dict(self._records.get(key) or {})

    # ---------- 统计 ----------
    def _day_stat(self, d: date, rec: Optional[dict] = None,
                  is_wd: Optional[bool] = None,
                  as_of: Optional[date] = None) -> DayStat:
        if rec is None:
            rec = self._records.get(d.isoformat()) or {}
        if is_wd is None:
            is_wd = _is_workday(d)
        in_t = rec.get("in")
        out_t = rec.get("out")
        minutes = None
        is_late = False
        is_early = False
        overtime = None

        if not in_t and not out_t:
            if as_of is not None and d > as_of:
                status = STATUS_PENDING if is_wd else STATUS_REST
            else:
                status = STATUS_ABSENT if is_wd else STATUS_REST
        elif not in_t or not out_t:
            status = STATUS_INCOMPLETE
            if is_wd:
                if in_t is not None:
                    i = _parse_hm(in_t)
                    if (i is not None
                            and i > self._rule.start + self._rule.late_grace):
                        is_late = True
                if out_t is not None:
                    o = _parse_hm(out_t)
                    if o is not None and o < self._rule.end:
                        is_early = True
        else:
            minutes = _session_minutes(in_t, out_t, self._rule)
            raw = _raw_minutes(in_t, out_t)
            if (minutes is None or minutes <= 0
                    or raw is None or raw > _MAX_SESSION_MINUTES):
                status = STATUS_ABNORMAL
                minutes = None
            else:
                status = STATUS_OK
                is_late, is_early, overtime = _analyze_full(
                    in_t, out_t, is_wd, self._rule)
        return DayStat(d, in_t, out_t, minutes, status, is_wd,
                       is_late, is_early, overtime)

    @staticmethod
    def _aggregate(stats: Tuple[DayStat, ...]):
        attended = sum(1 for s in stats if s.in_time or s.out_time)
        complete = sum(1 for s in stats if s.status == STATUS_OK)
        total = sum((s.minutes or 0) for s in stats
                    if s.status == STATUS_OK)
        avg = round(total / complete) if complete else None
        overtime = sum((s.overtime_minutes or 0) for s in stats)
        late = sum(1 for s in stats if s.is_late)
        early = sum(1 for s in stats if s.is_early_leave)
        return total, attended, complete, avg, overtime, late, early

    def week_summary(self, base: date,
                     as_of: Optional[date] = None) -> WeekSummary:
        if isinstance(base, datetime):
            base = base.date()
        as_of = as_of or date.today()
        monday = base - timedelta(days=base.weekday())
        days = tuple(self._day_stat(monday + timedelta(days=i),
                                    as_of=as_of)
                     for i in range(7))
        total, attended, complete, avg, overtime, late, early = \
            self._aggregate(days)
        return WeekSummary(monday, monday + timedelta(days=6), days,
                           total, attended, complete, avg,
                           overtime, late, early)

    def month_summary(self, year: int, month: int,
                      as_of: Optional[date] = None) -> MonthSummary:
        as_of = as_of or date.today()
        last = calendar.monthrange(year, month)[1]
        days = []
        workdays = 0
        for d in range(1, last + 1):
            day = date(year, month, d)
            is_wd = _is_workday(day)
            if is_wd and day <= as_of:
                workdays += 1
            rec = self._records.get(day.isoformat())
            if rec is None and not is_wd:
                continue
            if rec is None and is_wd and day > as_of:
                continue
            days.append(self._day_stat(day, rec or {}, is_wd, as_of=as_of))
        stats = tuple(days)
        total, attended, complete, avg, overtime, late, early = \
            self._aggregate(stats)
        return MonthSummary(year, month, stats, workdays,
                            total, attended, complete, avg,
                            overtime, late, early)