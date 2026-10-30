# coding: utf-8
"""P1 回归：UpdateUIController 取消后不得强制重启。"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def ui_controller(qapp):
    """构造 UpdateUIController，quit_cb 收集调用。"""
    from desktop_calendar.ui.controllers.update_ui import UpdateUIController

    quit_called = []
    mgr = MagicMock()
    ui = UpdateUIController(
        parent_widget=None,
        update_mgr=mgr,
        window_quit_cb=lambda: quit_called.append(1),
    )
    ui._quit_calls = quit_called
    return ui


def test_on_ready_skips_restart_when_cancelled(ui_controller, monkeypatch):
    """P1 回归：_user_cancelled=True 时 on_ready 不重启。"""
    monkeypatch.setattr(
        "desktop_calendar.ui.controllers.update_ui.QMessageBox.information",
        lambda *a, **k: None,
    )
    ui_controller._user_cancelled = True
    ui_controller.on_ready()
    assert ui_controller._quit_calls == []
    assert ui_controller._user_cancelled is False      # 已复位


def test_on_ready_restarts_when_not_cancelled(ui_controller, monkeypatch):
    """正常路径回归：未取消时 on_ready 弹提示 + 退出。"""
    monkeypatch.setattr(
        "desktop_calendar.ui.controllers.update_ui.QMessageBox.information",
        lambda *a, **k: None,
    )
    ui_controller._user_cancelled = False
    ui_controller.on_ready()
    assert ui_controller._quit_calls == [1]


def test_on_failed_ignored_when_cancelled(ui_controller, monkeypatch):
    """P1 回归：取消后到达的 UPDATE_FAILED 不弹错误框。"""
    called = []
    monkeypatch.setattr(
        "desktop_calendar.ui.controllers.update_ui.msg_error",
        lambda *a, **k: called.append(1),
    )
    ui_controller._user_cancelled = True
    ui_controller.on_failed({"stage": "download", "error": "x"})
    assert called == []