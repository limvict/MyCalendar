# coding: utf-8
"""settings_controller.apply_settings 的编排顺序测试。

【核心价值】钉死 config 落盘 → window_state 生效 → 事件广播
→ 语言切换 → 自启处理的顺序。任何人"整理"这段代码都会先让
这些测试变红。
"""
from unittest.mock import MagicMock

import pytest

from desktop_calendar.app import settings_controller


# ---------- 桩 ----------

class FakeBus:
    """替换 settings_controller.event_bus（它是个只读代理）。"""
    def __init__(self, calls):
        self.calls = calls

    def publish(self, evt, **kw):
        self.calls.append(("publish", evt, kw))

class FakeDlg:
    """只实现 apply_settings 需要的读取接口。"""

    def __init__(self, *, lang="zh_CN", topmost=False, opacity=0.9,
                 memorial_list=None, mem_remind=True, mem_sound=True,
                 auto_start=False):
        self.cfg = {"language": lang}
        self._lang = lang
        self._topmost = topmost
        self._opacity = opacity
        self._memorial_list = memorial_list or []
        self._mem_remind = mem_remind
        self._mem_sound = mem_sound
        self._auto_start = auto_start

    def get_language(self):           return self._lang
    def get_topmost_status(self):     return self._topmost
    def get_opacity(self):            return self._opacity
    def get_memorial_list(self):      return self._memorial_list
    def get_mem_remind(self):         return self._mem_remind
    def get_mem_sound(self):          return self._mem_sound
    def get_auto_start_status(self):  return self._auto_start


class _FakeConfig:
    def __init__(self, language="zh_CN"):
        self._snap = {"language": language}
        self.calls = []

    def get(self, k, d=None):
        return self._snap.get(k, d)

    def replace_all(self, cfg, save=False):
        self.calls.append(("replace_all", save))
        self._snap = dict(cfg)

    def flush(self):
        self.calls.append(("flush",))


@pytest.fixture
def fake_window():
    w = MagicMock()
    return w


def _wire(monkeypatch, calls, fake_config):
    """统一接线：把带副作用的入口全改成往 calls 里塞标签。"""
    monkeypatch.setattr(settings_controller, "config", fake_config)
    monkeypatch.setattr(settings_controller, "event_bus", FakeBus(calls))
    monkeypatch.setattr(
        settings_controller, "set_language",
        lambda lang: calls.append(("set_language", lang)))
    monkeypatch.setattr(
        settings_controller, "check_auto_start",
        lambda: calls.append(("check_auto_start",)) or False)
    monkeypatch.setattr(
        settings_controller, "apply_auto_start",
        lambda w, enable: calls.append(("apply_auto_start", enable)))


def test_apply_settings_orchestration_order(fake_window, monkeypatch):
    calls = []
    cfg = _FakeConfig()
    _wire(monkeypatch, calls, cfg)

    # config.replace_all / flush 也要记录
    orig_replace = cfg.replace_all
    orig_flush = cfg.flush

    def replace_all(c, save=False):
        calls.append(("config.replace_all", save))
        orig_replace(c, save)

    def flush():
        calls.append(("config.flush",))
        orig_flush()

    monkeypatch.setattr(cfg, "replace_all", replace_all)
    monkeypatch.setattr(cfg, "flush", flush)

    fake_window.window_state.set_opacity.side_effect = (
        lambda v: calls.append(("set_opacity", v)))
    fake_window.window_state.set_topmost.side_effect = (
        lambda v: calls.append(("set_topmost", v)))
    fake_window.tray_mgr.update_topmost_check.side_effect = (
        lambda v: calls.append(("tray.update_topmost", v)))

    dlg = FakeDlg(lang="en_US", topmost=True, opacity=0.8, auto_start=True)
    settings_controller.apply_settings(fake_window, dlg)

    names = [c[0] for c in calls]
    idx = {n: i for i, n in enumerate(names)}

    # --- 核心顺序断言 ---
    assert names[0] == "config.replace_all"
    assert names[1] == "config.flush"
    assert idx["set_opacity"]    > idx["config.flush"]
    assert idx["set_topmost"]    > idx["config.flush"]
    assert idx["tray.update_topmost"] > idx["set_topmost"]
    assert idx["set_language"]   > idx["config.flush"]
    # 自启处理在最后（check 后可能跳过 apply，因此断言 apply 是最后一次）
    assert names[-1] == "apply_auto_start"


def test_apply_settings_lang_unchanged_skips_set_language(
        fake_window, monkeypatch):
    """语言没变时不应调用 set_language。"""
    calls = []
    cfg = _FakeConfig(language="zh_CN")
    _wire(monkeypatch, calls, cfg)

    fake_window.window_state.set_opacity   = lambda v: None
    fake_window.window_state.set_topmost   = lambda v: None
    fake_window.tray_mgr.update_topmost_check = lambda v: None

    dlg = FakeDlg(lang="zh_CN")   # 与 config 一致
    settings_controller.apply_settings(fake_window, dlg)

    assert not any(c[0] == "set_language" for c in calls)


def test_apply_settings_auto_start_skipped_when_unchanged(
        fake_window, monkeypatch):
    """want_auto == check_auto_start 时不应调用 apply_auto_start。"""
    calls = []
    cfg = _FakeConfig()
    _wire(monkeypatch, calls, cfg)

    # check 返回 True，dlg 也返回 True → 应该跳过
    monkeypatch.setattr(
        settings_controller, "check_auto_start",
        lambda: calls.append(("check_auto_start",)) or True)

    fake_window.window_state.set_opacity   = lambda v: None
    fake_window.window_state.set_topmost   = lambda v: None
    fake_window.tray_mgr.update_topmost_check = lambda v: None

    dlg = FakeDlg(lang="zh_CN", auto_start=True)
    settings_controller.apply_settings(fake_window, dlg)

    assert not any(c[0] == "apply_auto_start" for c in calls)