# coding: utf-8
"""P0 / P1 考勤规则：净工时、加班判定、WorkRule 配置解析。"""
from datetime import date

import pytest

from desktop_calendar.core.attendance import (
    WorkRule, AttendanceStore,
    _session_minutes, _analyze_full, _raw_minutes,
    STANDARD_START, STANDARD_END, STANDARD_MINUTES,
    LUNCH_START, LUNCH_END,
    STATUS_OK, STATUS_ABNORMAL, STATUS_INCOMPLETE,
)


class _Cfg:
    """最小 config 桩：get_nested('attendance_cfg','work_rule') 返回给定 dict。"""
    def __init__(self, work_rule):
        self._wr = work_rule

    def get_nested(self, *keys, default=None):
        if keys == ("attendance_cfg", "work_rule"):
            return self._wr
        return default


# ===================== P0：净工时 =====================
class TestSessionMinutesP0:
    @pytest.mark.parametrize("in_t,out_t,net", [
        ("08:00", "17:00", 480),   # 标准：raw 540 − 午休 60
        ("09:00", "18:00", 480),   # 迟到补足
        ("10:00", "18:00", 420),   # 净工时 7h（旧实现 8h）
        ("08:00", "19:00", 600),   # 净工时 10h
        ("09:00", "19:00", 540),   # 净工时 9h（旧实现 10h）
        ("12:00", "13:00", 0),     # 全在午休
        ("12:30", "13:30", 30),    # 部分重叠
        ("22:00", "02:00", 240),   # 跨天：raw 4h − 午休 0
    ])
    def test_net(self, in_t, out_t, net):
        assert _session_minutes(in_t, out_t) == net

    def test_invalid(self):
        assert _session_minutes(None, "17:00") is None
        assert _session_minutes("08:00", None) is None
        assert _session_minutes("25:00", "17:00") is None


# ===================== P0：加班判定 =====================
class TestAnalyzeFullP0:
    @pytest.mark.parametrize("in_t,out_t,wd,late,early,ot", [
        ("08:00", "17:00", True,  False, False, None),   # 标准
        ("09:00", "18:00", True,  True,  False, None),   # 迟到补足
        ("10:00", "18:00", True,  True,  False, None),   # 旧版误报 1h 加班
        ("08:00", "19:00", True,  False, False, 120),    # 标准 + 2h
        ("09:00", "19:00", True,  True,  False, 60),     # 迟到 + 1h（旧版 2h）
        ("08:00", "16:00", True,  False, True,  None),   # 早退
        ("10:00", "14:00", False, False, False, 180),    # 休息日：净工时全加班
        ("22:00", "02:00", True,  True,  False, None),   # 跨天：不判早退
    ])
    def test_analyze(self, in_t, out_t, wd, late, early, ot):
        assert _analyze_full(in_t, out_t, wd) == (late, early, ot)


# ===================== P1：WorkRule 解析 =====================
class TestWorkRule:
    def test_default(self):
        r = WorkRule.from_config(None)
        assert (r.start, r.end) == (STANDARD_START, STANDARD_END)
        assert r.standard_minutes == STANDARD_MINUTES
        assert (r.lunch_start, r.lunch_end) == (LUNCH_START, LUNCH_END)

    def test_custom_9_18(self):
        r = WorkRule.from_config(_Cfg({
            "work_start": "09:00", "work_end": "18:00",
            "standard_minutes": 480,
            "lunch_start": "12:00", "lunch_end": "13:00",
        }))
        assert (r.start, r.end) == (540, 1080)
        # 10:00 上班相对 09:00 基准算迟到；净工时 7h 不算加班
        assert _analyze_full("10:00", "18:00", True, r) == (True, False, None)

    def test_explicit_no_lunch(self):
        """显式 None 表示无午休，不是回退默认 12–13。"""
        r = WorkRule.from_config(_Cfg({
            "lunch_start": None, "lunch_end": None,
        }))
        assert r.lunch_start is None and r.lunch_end is None
        assert _session_minutes("08:00", "17:00", r) == 540
        # 无午休：净工时 9h，超出 8h → 加班 1h
        assert _analyze_full("08:00", "17:00", True, r) == (False, False, 60)

    def test_partial_lunch_string_uses_default_for_missing_side(self):
        """只配一端字符串：另一端用默认（部分覆盖语义，容错手改 config）。"""
        r = WorkRule.from_config(_Cfg({"lunch_start": "12:30"}))
        assert r.lunch_start == 12 * 60 + 30     # 750，用户覆盖
        assert r.lunch_end == LUNCH_END          # 780，回退默认
        # 净工时 = 540 − (13:00 − 12:30) = 540 − 30 = 510
        assert _session_minutes("08:00", "17:00", r) == 510

    def test_explicit_null_one_side_normalized_to_no_lunch(self):
        """任一端显式 null → 视为「想关午休」，两端归一化为 None。"""
        for cfg in (
            {"lunch_start": None},
            {"lunch_end": None},
            {"lunch_start": None, "lunch_end": None},
            {"lunch_start": "12:00", "lunch_end": None},
            {"lunch_start": None, "lunch_end": "13:00"},
        ):
            r = WorkRule.from_config(_Cfg(cfg))
            assert r.lunch_start is None, f"cfg={cfg}"
            assert r.lunch_end is None, f"cfg={cfg}"
            # 无午休：08:00–17:00 净工时 9h，超出 8h → 加班 1h
            assert _session_minutes("08:00", "17:00", r) == 540
            assert _analyze_full("08:00", "17:00", True, r) == (False, False, 60)

    def test_invalid_times_fallback(self):
        r = WorkRule.from_config(_Cfg({
            "work_start": "18:00", "work_end": "09:00",
            "lunch_start": "13:00", "lunch_end": "12:00",
        }))
        assert (r.start, r.end) == (STANDARD_START, STANDARD_END)
        assert r.lunch_start is None and r.lunch_end is None

    def test_late_grace(self):
        r = WorkRule.from_config(_Cfg({"late_grace": 5}))
        assert _analyze_full("08:04", "17:00", True, r)[0] is False
        assert _analyze_full("08:06", "17:00", True, r)[0] is True

    def test_overtime_granularity_floor(self):
        r = WorkRule.from_config(_Cfg({"overtime_granularity": 30}))
        # 17:20 净 500，超出 20 不足 30 → 0
        assert _analyze_full("08:00", "17:20", True, r)[2] is None
        # 17:40 净 520，超出 40 → 向下取整 30
        assert _analyze_full("08:00", "17:40", True, r)[2] == 30

    def test_none_or_non_dict_cfg_uses_default(self):
        assert WorkRule.from_config(_Cfg(None)).start == STANDARD_START
        assert WorkRule.from_config(_Cfg("garbage")).start == STANDARD_START


# ===================== P0/P1 集成：AttendanceStore._day_stat =====================
class TestDayStatIntegration:
    def test_complete_day_net(self, tmp_path):
        store = AttendanceStore(path=str(tmp_path / "a.json"))
        rec = {"in": "08:00", "out": "17:00"}
        st = store._day_stat(date(2024, 6, 3), rec=rec, is_wd=True)
        assert st.status == STATUS_OK
        assert st.minutes == 480            # 净工时，不是 540
        assert st.overtime_minutes is None

    def test_abnormal_uses_raw_not_net(self, tmp_path):
        """忘记打下班卡：raw 19h > 18h → ABNORMAL。"""
        store = AttendanceStore(path=str(tmp_path / "a.json"))
        rec = {"in": "08:00", "out": "03:00"}   # 次日 03:00
        st = store._day_stat(date(2024, 6, 3), rec=rec, is_wd=True)
        assert st.status == STATUS_ABNORMAL
        assert st.minutes is None

    def test_half_card_late_uses_rule(self, tmp_path):
        """P1：半卡迟到判定读 self._rule.start，不读模块常量。"""
        cfg = _Cfg({"work_start": "09:00", "work_end": "18:00"})
        store = AttendanceStore(path=str(tmp_path / "a.json"), config=cfg)
        # 08:30 打卡：相对 08:00 不算迟到，相对 09:00 算迟到
        st = store._day_stat(
            date(2024, 6, 3), rec={"in": "08:30"}, is_wd=True)
        assert st.status == STATUS_INCOMPLETE
        assert st.is_late is False
        st = store._day_stat(
            date(2024, 6, 3), rec={"in": "09:30"}, is_wd=True)
        assert st.is_late is True

    def test_week_summary_uses_rule(self, tmp_path):
        cfg = _Cfg({"work_start": "09:00", "work_end": "18:00"})
        store = AttendanceStore(path=str(tmp_path / "a.json"), config=cfg)
        store._records["2024-06-03"] = {"in": "09:00", "out": "18:00"}
        summary = store.week_summary(date(2024, 6, 3), as_of=date(2024, 6, 7))
        mon = summary.days[0]
        assert mon.status == STATUS_OK
        assert mon.minutes == 480          # 净工时 9h − 午休 1h
        assert mon.is_late is False        # 09:00 不迟于 09:00
        assert mon.overtime_minutes is None


# ===================== 辅助函数 =====================
def test_raw_minutes_cross_day():
    assert _raw_minutes("22:00", "02:00") == 240
    assert _raw_minutes("08:00", "17:00") == 540
    assert _raw_minutes(None, "17:00") is None
    assert _raw_minutes("08:00", "25:00") is None