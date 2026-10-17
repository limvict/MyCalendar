# coding: utf-8
from datetime import date

from PyQt6.QtCore import QDate

from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core import memorial as mem_mod
import pytest


def test_qdate_to_pydate():
    from desktop_calendar.core.lunar import qdate_to_pydate
    assert qdate_to_pydate(QDate(2024, 2, 29)) == date(2024, 2, 29)


def test_normalize_invalid_repeat_and_week():
    m = mem_mod.normalize_memorial({
        "name": "x", "repeat_type": "bad",
        "type": "lunar", "day": 99,
    })
    assert m["repeat_type"] == mem_mod.REPEAT_YEAR

    m = mem_mod.normalize_memorial({
        "name": "w", "repeat_type": mem_mod.REPEAT_WEEK,
        "type": "lunar", "day": 99,
    })
    assert m["type"] == "solar"
    assert m["day"] == 7
    assert m["isleap"] is False


def test_normalize_advance_clamp():
    assert mem_mod.normalize_memorial(
        {"advance_days": 999})["advance_days"] == 365
    assert mem_mod.normalize_memorial(
        {"advance_days": -1})["advance_days"] == 0


def test_match_solar():
    m = mem_mod.normalize_memorial({
        "name": "元旦", "type": "solar", "repeat_type": "year",
        "month": 1, "day": 1,
    })
    assert mem_mod.match_memorial_date(m, date(2025, 1, 1), normalized=True)
    assert not mem_mod.match_memorial_date(
        m, date(2025, 1, 2), normalized=True)

    w = mem_mod.normalize_memorial({
        "name": "周一", "type": "solar", "repeat_type": "week", "day": 1,
    })
    assert mem_mod.match_memorial_date(w, date(2025, 1, 6), normalized=True)
    assert not mem_mod.match_memorial_date(
        w, date(2025, 1, 7), normalized=True)


def test_next_solar_yearly_include_base():
    m = mem_mod.normalize_memorial({
        "name": "元旦", "type": "solar", "repeat_type": "year",
        "month": 1, "day": 1,
    })
    assert mem_mod.get_next_memorial_date(
        m, date(2025, 1, 1), include_base=True, normalized=True
    ) == date(2025, 1, 1)
    assert mem_mod.get_next_memorial_date(
        m, date(2025, 1, 1), include_base=False, normalized=True
    ) == date(2026, 1, 1)


def test_next_week_strictly_future():
    m = mem_mod.normalize_memorial({
        "name": "周一", "type": "solar", "repeat_type": "week", "day": 1,
    })
    assert mem_mod.get_next_memorial_date(
        m, date(2025, 1, 6), include_base=False, normalized=True
    ) == date(2025, 1, 13)


def test_lunar_dependency_absent(monkeypatch):
    monkeypatch.setattr(lunar_mod, "HAS_CNLUNAR", False)
    m = mem_mod.normalize_memorial({
        "name": "农历", "type": "lunar",
        "repeat_type": "year", "month": 1, "day": 1,
    })
    assert mem_mod.get_next_memorial_date(
        m, date(2025, 1, 1), normalized=True) is None
    

# ---------- normalize: week 强制公历 + isleap ----------

@pytest.mark.parametrize("raw", [
    True, "true", "True", "1", "yes", "on", 1, 1.0,
])
def test_normalize_week_forces_isleap_false(raw):
    """week 是纯公历概念：无论输入什么"真值"，isleap 一律归 False。

    回归保护：若实现被"简化"成无条件
    ``mem["isleap"] = to_bool(mem.get("isleap"), default=False)``
    且 week 分支不再显式置 False，则本用例对 raw=True / "true" /
    "1" 等真值输入会返回 True，week + 闰月这种无意义组合会被
    写进配置。
    """
    m = mem_mod.normalize_memorial({
        "name": "w", "repeat_type": mem_mod.REPEAT_WEEK,
        "type": "solar", "day": 1, "isleap": raw,
    })
    assert m["isleap"] is False


@pytest.mark.parametrize("raw", [
    False, "false", "False", "0", "no", "off", 0, 0.0,
])
def test_normalize_week_falsy_isleap_stays_false(raw):
    """对称：falsy 输入也应归 False，且走的是"归一化"而不是"被盖掉"。

    与上一条职责分开：上一条管"真值输入被强制"，本条管"假值输入
    本来就该是 False"。两条都绿才说明 week 分支对 isleap 的语义
    完整，不是碰巧。
    """
    m = mem_mod.normalize_memorial({
        "name": "w", "repeat_type": mem_mod.REPEAT_WEEK,
        "type": "solar", "day": 1, "isleap": raw,
    })
    assert m["isleap"] is False


def test_normalize_week_lunar_type_plus_isleap_true():
    """week + type=lunar + isleap=True：type 被改 solar，isleap 被强制 False。

    三个字段同时脏：既验证 type 强制、也验证 isleap 强制，还覆盖
    "用户先在 lunar 视图勾了闰月，再切到每周重复"的真实操作路径。
    """
    m = mem_mod.normalize_memorial({
        "name": "w", "repeat_type": mem_mod.REPEAT_WEEK,
        "type": "lunar", "day": 1, "isleap": True,
    })
    assert m["type"] == "solar"
    assert m["isleap"] is False


def test_normalize_non_week_keeps_isleap():
    """非 week 周期下 isleap 语义不变：True 保留，便于对照上一条。

    没有这条，上一条的"isleap 为 False"可能被误读为
    "normalize 无条件把 isleap 压成 False"。
    """
    m = mem_mod.normalize_memorial({
        "name": "lunar", "repeat_type": mem_mod.REPEAT_YEAR,
        "type": "lunar", "month": 4, "day": 15, "isleap": True,
    })
    assert m["isleap"] is True
    
    
def test_normalize_solar_clears_isleap():
    m = mem_mod.normalize_memorial({
        "name": "s", "repeat_type": mem_mod.REPEAT_YEAR,
        "type": "solar", "month": 2, "day": 29, "isleap": True,
    })
    assert m["isleap"] is False 
    
    
# ----------  语义链：normalize → match → next_date ----------

def test_normalize_feb29_preserved():
    """起点：normalize 用 REFERENCE_LEAP_YEAR=2024 校验，2/29 保留
    为 day=29。若这里被收敛成 28，match 就永远不会在闰年 2/29 匹配。
    """
    m = mem_mod.normalize_memorial({
        "name": "2/29", "type": "solar", "repeat_type": "year",
        "month": 2, "day": 29,
    })
    assert m["month"] == 2
    assert m["day"] == 29


def test_match_feb29_converges_on_non_leap_years():
    """match 层：2/29 在平年收敛到 2/28 匹配。

    与 get_next_memorial_date 的收敛语义一致 —— 否则 check_memorial
    在平年 2/28 当天不会命中（target=次年 2/28，diff=365），提醒丢失。
    """
    m = mem_mod.normalize_memorial({
        "name": "2/29", "type": "solar", "repeat_type": "year",
        "month": 2, "day": 29,
    })
    # 闰年 2/29：匹配
    assert mem_mod.match_memorial_date(m, date(2024, 2, 29), normalized=True)
    assert mem_mod.match_memorial_date(m, date(2028, 2, 29), normalized=True)
    # 平年 2/28：匹配（收敛）
    assert mem_mod.match_memorial_date(m, date(2025, 2, 28), normalized=True)
    assert mem_mod.match_memorial_date(m, date(2023, 2, 28), normalized=True)
    # 闰年 2/28（2/29 前一天）：不匹配
    assert not mem_mod.match_memorial_date(
        m, date(2024, 2, 28), normalized=True)
    # 平年 2/27：不匹配
    assert not mem_mod.match_memorial_date(
        m, date(2025, 2, 27), normalized=True)


def test_next_date_feb29_include_base_on_leap_day():
    """next_date 层：include_base=True 且基准日恰为闰年 2/29，
    返回基准日自身。"""
    m = mem_mod.normalize_memorial({
        "name": "2/29", "type": "solar", "repeat_type": "year",
        "month": 2, "day": 29,
    })
    assert mem_mod.get_next_memorial_date(
        m, date(2024, 2, 29), include_base=True, normalized=True
    ) == date(2024, 2, 29)


def test_next_date_feb29_include_base_false_after_leap_day():
    """include_base=False 且基准日恰为闰年 2/29：返回 2025-02-28。

    体现 next_date 层的收敛语义：平年把 29 收敛到 28。
    """
    m = mem_mod.normalize_memorial({
        "name": "2/29", "type": "solar", "repeat_type": "year",
        "month": 2, "day": 29,
    })
    assert mem_mod.get_next_memorial_date(
        m, date(2024, 2, 29), include_base=False, normalized=True
    ) == date(2025, 2, 28)


def test_next_date_feb29_from_non_leap_jan_first():
    """从平年年初出发：目标日收敛到当年 2/28。"""
    m = mem_mod.normalize_memorial({
        "name": "2/29", "type": "solar", "repeat_type": "year",
        "month": 2, "day": 29,
    })
    assert mem_mod.get_next_memorial_date(
        m, date(2025, 1, 1), include_base=False, normalized=True
    ) == date(2025, 2, 28)


def test_next_date_feb29_from_leap_year_eve():
    """闰年 2/28（2/29 前一天）：返回 2024-02-29。"""
    m = mem_mod.normalize_memorial({
        "name": "2/29", "type": "solar", "repeat_type": "year",
        "month": 2, "day": 29,
    })
    assert mem_mod.get_next_memorial_date(
        m, date(2024, 2, 28), include_base=False, normalized=True
    ) == date(2024, 2, 29)


def test_next_date_feb29_from_non_leap_convergence_day():
    """从 2025-02-28（平年 2/29 的收敛日）出发，include_base=True
    返回基准日自身。与 match_memorial_date 的收敛匹配一致。

    回归保护：修复前实现用 `base_date.day == day` 字面比较（28 != 29），
    会把候选推到 2026-02-28，导致 reminder_manager 在该日
    diff=365、恒不命中，2/29 纪念日在所有平年被漏提醒。
    """
    m = mem_mod.normalize_memorial({
        "name": "2/29", "type": "solar", "repeat_type": "year",
        "month": 2, "day": 29,
    })
    assert mem_mod.get_next_memorial_date(
        m, date(2025, 2, 28), include_base=True, normalized=True
    ) == date(2025, 2, 28)


def test_next_date_feb29_from_non_leap_convergence_day_exclusive():
    """include_base=False 时从 2025-02-28 推到 2026-02-28。"""
    m = mem_mod.normalize_memorial({
        "name": "2/29", "type": "solar", "repeat_type": "year",
        "month": 2, "day": 29,
    })
    assert mem_mod.get_next_memorial_date(
        m, date(2025, 2, 28), include_base=False, normalized=True
    ) == date(2026, 2, 28)