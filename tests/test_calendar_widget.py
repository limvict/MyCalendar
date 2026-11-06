# coding: utf-8
"""LunarCalendarWidget._warmup_adjacent_years：相邻年预热去重。

用 SimpleNamespace 伪造 self，绕过 QWidget.__init__（需要 qapp、
主题 bundle、memorial_list 等重量级依赖）。本测试只验证纯 Python
逻辑：哪些年份被传给 presenter、同一组年份是否只传一次。
"""
import pytest

from desktop_calendar.ui.calendar_widget import LunarCalendarWidget


@pytest.mark.skipif(
    not hasattr(LunarCalendarWidget, "_warmup_adjacent_years"),
    reason="P2 农历预热未实施")
def test_warmup_adjacent_years_dedupes():
    from types import SimpleNamespace

    calls = []
    fake = SimpleNamespace(
        _presenter=SimpleNamespace(
            warmup_for_years=lambda ys: calls.append(tuple(ys))),
        _warmed_years=set(),
    )

    LunarCalendarWidget._warmup_adjacent_years(fake, 2024)
    LunarCalendarWidget._warmup_adjacent_years(fake, 2024)

    # 同一组年份只预热一次
    assert calls == [(2023, 2024, 2025)]
    # _warmed_years 被记录
    assert fake._warmed_years == {2023, 2024, 2025}


@pytest.mark.skipif(
    not hasattr(LunarCalendarWidget, "_warmup_adjacent_years"),
    reason="P2 农历预热未实施")
def test_warmup_adjacent_years_incremental():
    """跨页只预热新增年份，已预热的年份不重复。"""
    from types import SimpleNamespace

    calls = []
    fake = SimpleNamespace(
        _presenter=SimpleNamespace(
            warmup_for_years=lambda ys: calls.append(tuple(ys))),
        _warmed_years=set(),
    )

    LunarCalendarWidget._warmup_adjacent_years(fake, 2024)   # 2023,2024,2025
    LunarCalendarWidget._warmup_adjacent_years(fake, 2025)   # 只新增 2026

    assert calls == [(2023, 2024, 2025), (2026,)]


@pytest.mark.skipif(
    not hasattr(LunarCalendarWidget, "_warmup_adjacent_years"),
    reason="P2 农历预热未实施")
def test_warmup_adjacent_years_noop_when_all_warmed():
    from types import SimpleNamespace

    calls = []
    fake = SimpleNamespace(
        _presenter=SimpleNamespace(
            warmup_for_years=lambda ys: calls.append(tuple(ys))),
        _warmed_years={2023, 2024, 2025},
    )

    LunarCalendarWidget._warmup_adjacent_years(fake, 2024)
    assert calls == []   # 全部已预热，不调 presenter