# coding: utf-8
"""P3 全链路回归：check_memorial → event_bus.publish → MainWindow
handler → _show_remind_dialog → acknowledge/abandon → 落盘 → 去重。

与 test_reminder_manager.py 的区别：
  - 后者把 event_bus 替换成 _RecordingBus，只验证"publish 被调用"；
  - 本文件使用**真实** event_bus + MainWindow._on_memorial_remind_triggered
    的真实实现，验证端到端流程（含同步 publish 时序、pending 清理、
    去重生效）。

覆盖两类历史回归：
  P2：publish 必须同步触发订阅者。若回退到 QTimer.singleShot，
      首次 check_memorial 返回时弹窗桩尚未调用 → 首断言失败。
  P3b：_on_memorial_remind_triggered 必须真正调用
      _show_remind_dialog 后才 acknowledge。若退化为直接 acknowledge，
      calls["show"] == 0 → 首断言失败。
"""
from __future__ import annotations

import hashlib
from datetime import date

import pytest


def _today_memorial(name: str) -> dict:
    t = date.today()
    return {
        "name": name,
        "type": "solar",
        "repeat_type": "year",
        "month": t.month,
        "day": t.day,
        "advance_days": 0,
        "enabled": True,
        "isleap": False,
    }


def _expected_signature(name: str) -> str:
    """与 ReminderManager._hits_signature 保持同一算法。"""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


@pytest.fixture
def full_chain(qapp, fresh_config_manager):
    """组装"真实 event_bus + 真实 MainWindow handler"的最小栈。

    MainWindow 通过 __new__ 构造，绕开主题 / 托盘 / 网络 / update
    等重量级初始化，只保留 handler 方法（类上定义）+ 注入的
    reminder_mgr + 桩化的 _show_remind_dialog。

    QWidget.__init__ 不调用：handler 链路是纯 Python 逻辑，不触碰
    C++ 对象。测试结束后实例被 GC，无需 deleteLater。
    """
    from desktop_calendar.config.i18n import set_language
    from desktop_calendar.contracts.event_bus import EventType, event_bus
    from desktop_calendar.core.reminder_manager import ReminderManager
    from desktop_calendar.ui.main_window import MainWindow

    set_language("zh_CN")

    # 提醒时段放宽到全天，覆盖任意运行时刻；关闭音效避免 winsound。
    fresh_config_manager.set_nested(
        "memorial_cfg", "remind_start_hour", 0, save=False)
    fresh_config_manager.set_nested(
        "memorial_cfg", "remind_end_hour", 24, save=False)
    fresh_config_manager.set_nested(
        "memorial_cfg", "sound_enable", False, save=False)
    fresh_config_manager.set_nested(
        "memorial_cfg", "enable_remind", True, save=False)
    fresh_config_manager.set_nested(
        "memorial_cfg", "last_remind_date", "", save=False)
    fresh_config_manager.set_nested(
        "memorial_cfg", "last_remind_sig", "", save=False)

    rm = ReminderManager(None, fresh_config_manager, sound_manager=None)

    w = MainWindow.__new__(MainWindow)
    w.reminder_mgr = rm

    calls = {"show": 0, "result": True}

    def _fake_show(hit_list, today_str):
        calls["show"] += 1
        return calls["result"]

    w._show_remind_dialog = _fake_show

    event_bus.subscribe(
        EventType.MEMORIAL_REMIND_TRIGGERED,
        w._on_memorial_remind_triggered,
    )
    try:
        yield {
            "reminder": rm,
            "window": w,
            "calls": calls,
            "config": fresh_config_manager,
        }
    finally:
        try:
            event_bus.unsubscribe(
                EventType.MEMORIAL_REMIND_TRIGGERED,
                w._on_memorial_remind_triggered,
            )
        except Exception:
            pass
        rm.shutdown()


# ===================== 正常路径 =====================
def test_full_chain_triggers_dialog_and_persists(full_chain):
    """一次完整流程：弹窗 → ack → 落盘 → 二次 check 静默。"""
    rm = full_chain["reminder"]
    cfg = full_chain["config"]
    calls = full_chain["calls"]

    memorial = _today_memorial("P3Tester")
    cfg.set("memorial_days", [memorial], save=False)

    # --- 首次 check：应触发弹窗 + ack + 落盘 ---
    rm.check_memorial()
    assert calls["show"] == 1, (
        "首次 check_memorial 未触发弹窗："
        "P3b 退化为直接 acknowledge 会命中此断言"
    )

    today_str = date.today().isoformat()
    expected_sig = _expected_signature(memorial["name"])
    last_sig = cfg.get_nested(
        "memorial_cfg", "last_remind_sig", default="")
    last_date = cfg.get_nested(
        "memorial_cfg", "last_remind_date", default="")
    assert last_sig == f"{today_str}:{expected_sig}", (
        f"last_remind_sig 期望 {today_str}:{expected_sig}，实际 {last_sig}"
    )
    assert last_date == today_str
    assert rm._pending_remind_date == ""
    assert rm._pending_sig == ""

    # --- 二次 check：签名一致 → 静默 ---
    rm.check_memorial()
    assert calls["show"] == 1, (
        "签名一致时不应重复弹窗；"
        "若变成 2，说明去重链路断裂（P2 回退导致的 pending 卡住也会命中）"
    )


# ===================== 用户关闭对话框 =====================
def test_full_chain_user_closes_dialog_abandons(full_chain):
    """用户关闭对话框 → abandon 也写 sig → 同日不重弹。

    abandon 与 acknowledge 的区别仅在日志级别（warning vs debug），
    落盘行为相同：弹窗**已展示**给用户即视为知晓当日提醒。
    与 discard_pending 的区分：后者用于弹窗未展示场景，不写 sig。
    """
    rm = full_chain["reminder"]
    cfg = full_chain["config"]
    calls = full_chain["calls"]

    calls["result"] = False  # 模拟用户关闭

    memorial = _today_memorial("P3Abandon")
    cfg.set("memorial_days", [memorial], save=False)

    rm.check_memorial()
    assert calls["show"] == 1

    today_str = date.today().isoformat()
    expected_sig = _expected_signature(memorial["name"])
    assert cfg.get_nested(
        "memorial_cfg", "last_remind_sig", default=""
    ) == f"{today_str}:{expected_sig}"
    assert cfg.get_nested(
        "memorial_cfg", "last_remind_date", default="") == today_str
    assert rm._pending_remind_date == ""
    assert rm._pending_sig == ""

    # 同日再检查：sig 命中 → 静默
    rm.check_memorial()
    assert calls["show"] == 1


# ===================== 非法 payload 防御 =====================
def test_full_chain_invalid_payload_releases_pending(full_chain):
    """payload 非法时 handler 解 pending 且不写 sig。

    关键契约：清 pending 防止当天永久静默，但不写 last_remind_sig
    —— 用户根本没看到弹窗，下次 check_memorial 若仍命中应重新提醒。
    若误用 abandon_reminder，sig 会被写入 → 当日漏提醒。
    """
    rm = full_chain["reminder"]
    cfg = full_chain["config"]

    from desktop_calendar.contracts.event_bus import EventType, event_bus

    # 模拟一次 pending 状态（模拟 _emit_reminder 刚置位）
    today_str = date.today().isoformat()
    rm._pending_remind_date = today_str
    rm._pending_sig = "fake_sig"

    # 手动发一个非法 payload（空 hit_list）
    event_bus.publish(
        EventType.MEMORIAL_REMIND_TRIGGERED,
        hit_list=[],
        today_str=today_str,
    )

    # 核心断言 1：pending 已清（否则当天后续提醒永久静默）
    assert rm._pending_remind_date == ""
    assert rm._pending_sig == ""

    # 核心断言 2：不写 sig（否则当日同签名提醒被永久吞掉）
    assert cfg.get_nested(
        "memorial_cfg", "last_remind_sig", default="") == "", (
        "非法 payload 分支不写 last_remind_sig；"
        "写 sig 会导致当日同签名提醒永久静默（P3b 修法 A 的核心修复点）"
    )
