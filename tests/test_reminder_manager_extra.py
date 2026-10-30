# coding: utf-8
"""ReminderManager 补充：签名稳定性、shutdown 不落盘、advance_days。"""
from datetime import date

import pytest


@pytest.fixture
def reminder(qapp, fresh_config_manager, monkeypatch):
    from desktop_calendar.core import reminder_manager as rm

    fresh_config_manager.set_nested(
        "memorial_cfg", "remind_start_hour", 0, save=False)
    fresh_config_manager.set_nested(
        "memorial_cfg", "remind_end_hour", 24, save=False)
    monkeypatch.setattr(
        rm.QTimer, "singleShot", staticmethod(lambda ms, fn: fn()))

    emitted = []

    class _Bus:
        def publish(self, evt, **kw):
            emitted.append((evt, kw))

        def subscribe(self, *a, **k):
            pass

        def unsubscribe(self, *a, **k):
            pass

    monkeypatch.setattr(rm, "event_bus", _Bus())
    mgr = rm.ReminderManager(None, fresh_config_manager, sound_manager=None)
    mgr._emitted = emitted
    yield mgr
    mgr.shutdown()


def _today_memorial(name, advance_days=0):
    t = date.today()
    return {"name": name, "type": "solar", "repeat_type": "year",
            "month": t.month, "day": t.day, "enabled": True,
            "advance_days": advance_days, "isleap": False}


def test_hits_signature_order_insensitive(reminder):
    assert (reminder._hits_signature(["A", "B"])
            == reminder._hits_signature(["B", "A"]))


def test_hits_signature_differs_on_content(reminder):
    assert (reminder._hits_signature(["A"])
            != reminder._hits_signature(["A", "B"]))


def test_shutdown_clears_pending_without_persist(
        reminder, fresh_config_manager):
    reminder._pending_remind_date = "2099-01-01"
    reminder._pending_sig = "sig"
    reminder.shutdown()
    assert reminder._pending_remind_date == ""
    assert reminder._pending_sig == ""
    assert fresh_config_manager.get_nested(
        "memorial_cfg", "last_remind_sig", default="") == ""


def test_advance_days_negative_clamped(reminder, fresh_config_manager):
    mem = _today_memorial("A")
    mem["advance_days"] = -5
    fresh_config_manager.set("memorial_days", [mem], save=False)
    assert reminder._enabled_memorials()[0]["advance_days"] == 0


def test_enabled_memorials_skips_missing_fields(
        reminder, fresh_config_manager):
    fresh_config_manager.set("memorial_days", [
        {"name": "no repeat", "type": "solar", "day": 1, "month": 1},
        _today_memorial("ok"),
    ], save=False)
    assert [m["name"] for m in reminder._enabled_memorials()] == ["ok"]


def test_ack_writes_sig_with_today(reminder, fresh_config_manager):
    fresh_config_manager.set(
        "memorial_days", [_today_memorial("A")], save=False)
    reminder.check_memorial()
    today_str = date.today().isoformat()
    reminder.acknowledge_reminder(today_str)
    sig = fresh_config_manager.get_nested(
        "memorial_cfg", "last_remind_sig", default="")
    assert sig.startswith(today_str + ":")