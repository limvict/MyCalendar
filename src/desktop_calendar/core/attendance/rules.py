# coding: utf-8
"""考勤规则：工时解析、迟到/早退判定与单日汇总。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from desktop_calendar.config.manager import get_logger
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.utils.coerce import to_int_clamped

from .models import (
    LUNCH_END,
    LUNCH_START,
    STANDARD_END,
    STANDARD_MINUTES,
    STANDARD_START,
)

logger = get_logger()


def _parse_hm(value) -> int | None:
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
    lunch_start: int | None = LUNCH_START
    lunch_end: int | None = LUNCH_END
    late_grace: int = 0
    overtime_granularity: int = 0

    @classmethod
    def from_config(cls, config) -> WorkRule:
        if config is None:
            return cls()
        try:
            cfg = config.get_nested("attendance_cfg", "work_rule", default={})
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
            logger.warning("work_rule 上下班时刻非法 start=%s >= end=%s，回退默认", start, end)
            start, end = cls.start, cls.end

        lunch_start = _opt_hm("lunch_start", cls.lunch_start)
        lunch_end = _opt_hm("lunch_end", cls.lunch_end)
        if (lunch_start is None) != (lunch_end is None):
            logger.warning(
                "work_rule 午休区间只配了一端（start=%r end=%r），按无午休处理",
                lunch_start,
                lunch_end,
            )
            lunch_start = lunch_end = None
        elif lunch_start is not None and lunch_start >= lunch_end:
            logger.warning(
                "work_rule 午休区间非法 start=%s >= end=%s，按无午休处理", lunch_start, lunch_end
            )
            lunch_start = lunch_end = None

        return cls(
            start=start,
            end=end,
            standard_minutes=to_int_clamped(
                cfg.get("standard_minutes"), lo=60, hi=24 * 60, default=cls.standard_minutes
            ),
            lunch_start=lunch_start,
            lunch_end=lunch_end,
            late_grace=to_int_clamped(cfg.get("late_grace"), lo=0, hi=60, default=0),
            overtime_granularity=to_int_clamped(
                cfg.get("overtime_granularity"), lo=0, hi=60, default=0
            ),
        )


def _raw_minutes(in_time: str | None, out_time: str | None) -> int | None:
    """原始在岗时长（不扣午休，跨天 +24h）。非法时间串返回 None。"""
    i = _parse_hm(in_time)
    o = _parse_hm(out_time)
    if i is None or o is None:
        return None
    return (o - i) + (24 * 60 if o < i else 0)


def _session_minutes(
    in_time: str | None, out_time: str | None, rule: WorkRule | None = None
) -> int | None:
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


def _judge_late_early(in_min: int | None, out_min: int | None, rule: WorkRule) -> tuple[bool, bool]:
    """判定迟到 / 早退，供完整打卡与缺卡两条路径共用。

    口径约定：
    - 缺上班卡（in_min is None）不判迟到：因为没有上班时刻。
    - 只要下班时刻早于规定下班时间，就判早退（即使缺少上班卡）。
      例如：未打上班卡，下班卡为 16:30，应判为“未打上班卡（早退）”。
    - 缺下班卡不判早退。
    - 跨天（out_min < in_min）不判早退。
    """
    is_late = False
    if in_min is not None:
        is_late = in_min > rule.start + rule.late_grace

    is_early = False
    if out_min is not None:
        # 如果存在上班卡，且非跨天，才与规定下班时间对比；
        # 如果不存在上班卡，只要下班卡早于规定时间，就直接判定为早退。
        if in_min is None:
            is_early = out_min < rule.end
        elif out_min >= in_min:
            is_early = out_min < rule.end

    return is_late, is_early


def _analyze_full(
    in_time: str, out_time: str, is_workday: bool, rule: WorkRule | None = None
) -> tuple[bool, bool, int | None]:
    """返回 (is_late, is_early_leave, overtime_minutes)。

    迟到 / 早退由 _judge_late_early 统一判定；加班 = 净工时 − standard_minutes，
    再按粒度取整。非工作日：不判迟到/早退，净工时全部计加班。
    """
    i = _parse_hm(in_time)
    o = _parse_hm(out_time)
    if i is None or o is None:
        return False, False, None
    rule = rule or WorkRule()
    net = _session_minutes(in_time, out_time, rule)
    net = 0 if net is None else net

    if not is_workday:
        return False, False, (net or None)

    is_late, is_early = _judge_late_early(i, o, rule)
    overtime = max(0, net - rule.standard_minutes)
    if rule.overtime_granularity > 0 and overtime:
        overtime = (overtime // rule.overtime_granularity) * rule.overtime_granularity
    return is_late, is_early, (overtime or None)
