# coding: utf-8
"""P1 回归：ReminderManager 命中签名去重。

历史 bug：last_remind_date 全局布尔，用户当天 ack 后新增纪念日
被吞掉，当天不再提醒。
"""
from datetime import date

import pytest


@pytest.fixture
def reminder(qapp, fresh_config_manager, monkeypatch):
    """构造 ReminderManager；单 shot 异步改同步，屏蔽音效。"""
    from desktop_calendar.core import reminder_manager as rm

    # 放宽提醒时段：不依赖测试运行时刻
    fresh_config_manager.set_nested(
        "memorial_cfg", "remind_start_hour", 0, save=False)
    fresh_config_manager.set_nested(
        "memorial_cfg", "remind_end_hour", 24, save=False)

    # QTimer.singleShot → 同步执行，测试无需等事件循环
    monkeypatch.setattr(
        rm.QTimer, "singleShot",
        staticmethod(lambda ms, fn: fn()),
    )

    emitted = []

    class _RecordingBus:
        """替换模块级 event_bus。

        _EventBusProxy 有 __slots__ 且 publish 是类属性，
        不能在实例上 monkeypatch；直接换掉模块绑定最干净，
        且不会影响全局单例与其他测试。
        """
        def publish(self, evt, **kw):
            emitted.append((evt, kw))

        def subscribe(self, *args, **kwargs):
            pass

        def unsubscribe(self, *args, **kwargs):
            pass

    monkeypatch.setattr(rm, "event_bus", _RecordingBus())

    mgr = rm.ReminderManager(None, fresh_config_manager, sound_manager=None)
    mgr._emitted = emitted
    return mgr

def _today_memorial(name: str) -> dict:
    t = date.today()
    return {
        "name": name, "type": "solar", "repeat_type": "year",
        "month": t.month, "day": t.day, "enabled": True,
        "advance_days": 0, "isleap": False,
    }


def test_new_memorial_same_day_retriggers(reminder, fresh_config_manager):
    """P1 回归：当天 ack 后新增命中纪念日 → 重新弹。"""
    from desktop_calendar.contracts.events import EventType

    fresh_config_manager.set("memorial_days",
                             [_today_memorial("A")], save=False)
    reminder.check_memorial()
    assert len(reminder._emitted) == 1
    assert reminder._emitted[0][0] == EventType.MEMORIAL_REMIND_TRIGGERED

    today_str = date.today().isoformat()
    reminder.acknowledge_reminder(today_str)

    # 新增 B，同样今天命中
    fresh_config_manager.set("memorial_days",
                             [_today_memorial("A"), _today_memorial("B")],
                             save=False)
    reminder.check_memorial()
    assert len(reminder._emitted) == 2
    hits = reminder._emitted[1][1]["hit_list"]
    assert "A" in hits and "B" in hits


def test_same_hits_not_retrigger(reminder, fresh_config_manager):
    """同命中集合 ack 后不重复弹。"""
    fresh_config_manager.set("memorial_days",
                             [_today_memorial("A")], save=False)
    reminder.check_memorial()
    assert len(reminder._emitted) == 1

    today_str = date.today().isoformat()
    reminder.acknowledge_reminder(today_str)

    reminder.check_memorial()
    assert len(reminder._emitted) == 1     # 未重新弹


def test_legacy_last_remind_date_blocks_same_day(
        reminder, fresh_config_manager, monkeypatch):
    """升级兼容：last_remind_sig 为空且 last_remind_date==today 时不弹。"""
    today_str = date.today().isoformat()
    fresh_config_manager.set_nested(
        "memorial_cfg", "last_remind_date", today_str, save=False)
    fresh_config_manager.set_nested(
        "memorial_cfg", "last_remind_sig", "", save=False)
    fresh_config_manager.set("memorial_days",
                             [_today_memorial("A")], save=False)

    reminder.check_memorial()
    assert reminder._emitted == []