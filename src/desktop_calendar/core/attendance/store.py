# coding: utf-8
"""考勤记录存储：JSON 持久化、打卡写入与周/月统计。"""

from __future__ import annotations

import calendar
import json
import os
import time
from datetime import date, datetime, timedelta

from desktop_calendar.config.manager import atomic_write_json, get_logger
from desktop_calendar.utils.paths import get_app_data_dir

from .models import (
    _MAX_SESSION_MINUTES,
    ATTENDANCE_VERSION,
    PUNCH_IN_DEADLINE_HOUR,
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
from .rules import (
    WorkRule,
    _analyze_full,
    _is_workday,
    _judge_late_early,
    _parse_hm,
    _raw_minutes,
    _session_minutes,
)

logger = get_logger()


def _default_path() -> str:
    return os.path.join(get_app_data_dir(), "attendance.json")


class AttendanceStore:
    """打卡记录的加载 / 修改 / 统计。"""

    def __init__(self, path: str | None = None, config=None):
        self._path = path or _default_path()
        self._rule = WorkRule.from_config(config)
        self._records: dict[str, dict] = {}
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
                    logger.warning("损坏考勤文件备份同名冲突超过 10 次，使用 %s", backup)
                    break
            os.replace(self._path, backup)
            logger.warning("损坏的考勤文件已备份到 %s", backup)
        except OSError:
            logger.debug("备份损坏考勤文件失败", exc_info=True)

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            logger.warning("读取考勤数据失败: %s", self._path, exc_info=True)
            self._backup_corrupt()
            return
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, dict):
            logger.warning("考勤文件结构异常（records 非 dict），已备份: %s", self._path)
            self._backup_corrupt()
            return
        clean: dict[str, dict] = {}
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
        atomic_write_json(
            self._path,
            {
                "version": ATTENDANCE_VERSION,
                "records": self._records,
            },
            protect=True,
        )

    # ---------- 打卡 ----------
    def punch(self, action: str, now: datetime | None = None) -> tuple[str, bool]:
        now = now or datetime.now()
        if action not in ("in", "out"):
            raise ValueError(f"unknown punch action: {action!r}")
        day_key = now.date().isoformat()
        hm = now.strftime("%H:%M")

        old = self._records.get(day_key)
        old_copy = dict(old) if old else None
        rec = dict(old) if old else {}

        if action == "in":
            # 严禁覆盖上班卡：每日仅一次
            if rec.get("in") is not None:
                raise PunchRejected(
                    "already_punched_in", f"上班卡已打过（{rec.get('in')}），不可重复打卡"
                )
            # 硬规则下沉到 store：11:00 起不再允许写上班卡。
            # 即使 UI / 提醒层漏判，逻辑层也保证数据不被污染。
            if now.hour >= PUNCH_IN_DEADLINE_HOUR:
                raise PunchRejected(
                    "in_deadline_passed",
                    f"上班打卡截止 {PUNCH_IN_DEADLINE_HOUR:02d}:00，已无法打卡",
                )

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
    def _day_stat(
        self,
        d: date,
        rec: dict | None = None,
        is_wd: bool | None = None,
        as_of: date | None = None,
    ) -> DayStat:
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
                # 与完整打卡共用同一判定：缺上班卡时不会误判早退。
                is_late, is_early = _judge_late_early(
                    _parse_hm(in_t) if in_t else None,
                    _parse_hm(out_t) if out_t else None,
                    self._rule,
                )
        else:
            minutes = _session_minutes(in_t, out_t, self._rule)
            raw = _raw_minutes(in_t, out_t)
            if minutes is None or minutes <= 0 or raw is None or raw > _MAX_SESSION_MINUTES:
                status = STATUS_ABNORMAL
                minutes = None
            else:
                status = STATUS_OK
                is_late, is_early, overtime = _analyze_full(in_t, out_t, is_wd, self._rule)
        return DayStat(d, in_t, out_t, minutes, status, is_wd, is_late, is_early, overtime)

    @staticmethod
    def _aggregate(stats: tuple[DayStat, ...]):
        attended = sum(1 for s in stats if s.in_time or s.out_time)
        complete = sum(1 for s in stats if s.status == STATUS_OK)
        total = sum((s.minutes or 0) for s in stats if s.status == STATUS_OK)
        avg = round(total / complete) if complete else None
        overtime = sum((s.overtime_minutes or 0) for s in stats)
        late = sum(1 for s in stats if s.is_late)
        early = sum(1 for s in stats if s.is_early_leave)
        return total, attended, complete, avg, overtime, late, early

    def week_summary(self, base: date, as_of: date | None = None) -> WeekSummary:
        if isinstance(base, datetime):
            base = base.date()
        as_of = as_of or date.today()
        monday = base - timedelta(days=base.weekday())
        days = tuple(self._day_stat(monday + timedelta(days=i), as_of=as_of) for i in range(7))
        total, attended, complete, avg, overtime, late, early = self._aggregate(days)
        return WeekSummary(
            monday,
            monday + timedelta(days=6),
            days,
            total,
            attended,
            complete,
            avg,
            overtime,
            late,
            early,
        )

    def month_summary(self, year: int, month: int, as_of: date | None = None) -> MonthSummary:
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
            # 与 week_summary 对齐：输出范围内全部自然日。
            # 无记录日由 _day_stat 依 is_wd / as_of 归类为
            # 休息 / 缺勤 / 待打卡，避免周/月视图行数、内容不一致。
            days.append(self._day_stat(day, rec or {}, is_wd, as_of=as_of))
        stats = tuple(days)
        total, attended, complete, avg, overtime, late, early = self._aggregate(stats)
        return MonthSummary(
            year, month, stats, workdays, total, attended, complete, avg, overtime, late, early
        )
