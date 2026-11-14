# coding: utf-8
"""ReminderManager：命中签名去重、shutdown、advance_days、enabled 过滤。"""
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
    yield mgr
    mgr.shutdown()


def _today_memorial(name: str, advance_days: int = 0) -> dict:
    t = date.today()
    return {
        "name": name, "type": "solar", "repeat_type": "year",
        "month": t.month, "day": t.day, "enabled": True,
        "advance_days": advance_days, "isleap": False,
    }


# ---------------- P1 回归：命中签名去重 ----------------
def test_new_memorial_same_day_retriggers(reminder, fresh_config_manager):
    """P1 回归：当天 ack 后新增命中纪念日 → 重新弹。"""
    from desktop_calendar.contracts.event_bus import EventType

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


# ---------------- 补充 ----------------
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
    
# ---------------- 缓存键白名单（B4 修复回归） ----------------
def test_memorial_cache_key_covers_all_date_fields(reminder):
    """P2 回归：白名单任一日期字段变化 → 缓存键必须不同。

    旧实现遍历所有可哈希字段、跳过不可哈希字段：未来新增
    `months: [1,2]` 之类的不可哈希字段会被静默跳过，导致两条不同
    纪念日命中同一缓存键、提醒时间错误。白名单漏登记会立即表现为
    "改了字段不生效"，比静默错误可诊断。
    """
    base = _today_memorial("A")
    base_key = reminder._memorial_cache_key(base, remind_h=8)

    for field, new_val in (
        ("repeat_type", "month"),
        ("type", "lunar"),
        ("month", base["month"] + 1 if base["month"] < 12 else 1),
        ("day", base["day"] + 1 if base["day"] < 28 else 1),
        ("advance_days", base["advance_days"] + 1),
        ("isleap", not base["isleap"]),
    ):
        modified = dict(base)
        modified[field] = new_val
        assert reminder._memorial_cache_key(modified, remind_h=8) != base_key, (
            f"字段 {field} 变化未反映到缓存键，白名单漏登记"
        )

    # name 不影响日期计算，不进缓存键
    renamed = dict(base, name="B")
    assert reminder._memorial_cache_key(renamed, remind_h=8) == base_key

    # remind_h 必须参与缓存键（不同提醒时段计算出的下一个时间戳不同）
    assert reminder._memorial_cache_key(base, remind_h=9) != base_key


def test_memorial_cache_key_handles_unhashable(reminder):
    """不可 hash 字段不能导致异常；白名单实现用 repr 兜底。"""
    mem = _today_memorial("A")
    mem["advance_days"] = [1, 2]   # 故意塞不可 hash 值
    # 不抛即可（白名单里 advance_days 走 repr 分支）
    key = reminder._memorial_cache_key(mem, remind_h=8)
    assert isinstance(key, tuple)


def test_memorial_cache_key_distinguishes_unhashable_field(reminder):
    """B4 契约：同一纪念日的不可 hash 字段变化 → 键必须不同。

    旧实现跳过不可 hash 字段，两条只有 `extra` 不同的纪念日会命中
    同一缓存键；新实现用 repr 兜底，键不同。
    """
    a = _today_memorial("A")
    a["extra"] = [1, 2]
    b = _today_memorial("A")
    b["extra"] = [3, 4]
    # 注意：extra 不在白名单，两边都不应进键 → 键相同
    assert reminder._memorial_cache_key(a, remind_h=8) == \
        reminder._memorial_cache_key(b, remind_h=8)

    # 但白名单里的字段若为不可 hash（理论上不该发生，防御性检查）
    c = _today_memorial("A")
    c["advance_days"] = [1]
    d = _today_memorial("A")
    d["advance_days"] = [2]
    assert reminder._memorial_cache_key(c, remind_h=8) != \
        reminder._memorial_cache_key(d, remind_h=8)