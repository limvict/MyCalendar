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
    
# ===================== release_notes 富文本转义（安全回归） =====================
def test_sanitize_release_notes_escapes_html():
    """P1 回归：release_notes 里的 HTML 必须被转义。

    背景：setInformativeText 内部按 Qt::mightBeRichText 自动判定，
    含 < 的文本走 HTML 渲染。远程 manifest 一旦被篡改，可注入
    <img src=...>（触发外链 / 泄露 IP）或 <a href=...>（诱导点击）。
    """
    from desktop_calendar.ui.controllers.update_ui import UpdateUIController

    out = UpdateUIController._sanitize_release_notes(
        'v3.1\n<img src="http://evil/x">\n<a href="x">click</a>')

    # 原始标签必须不可见
    assert "<img" not in out
    assert "<a " not in out
    # 转义后的实体应出现（否则 escape 没生效）
    assert "&lt;img" in out
    assert "&lt;a " in out
    # 换行转 <br>，外层包 <qt> 强制 rich-text 路径
    assert "<br>" in out
    assert out.startswith("<qt>") and out.endswith("</qt>")


def test_sanitize_release_notes_preserves_plain_text():
    """无 HTML 的普通文本原样保留，仅包 <qt> 外层。"""
    from desktop_calendar.ui.controllers.update_ui import UpdateUIController

    out = UpdateUIController._sanitize_release_notes("修复了 N 个 bug")
    assert "修复了 N 个 bug" in out


def test_sanitize_release_notes_escapes_quotes():
    """单/双引号也转义：防属性闭合型注入（如 <a href="...">）。"""
    from desktop_calendar.ui.controllers.update_ui import UpdateUIController

    out = UpdateUIController._sanitize_release_notes('a "b" \'c\'')
    assert "&quot;" in out
    assert "&#x27;" in out
    # <qt></qt> 本身不含引号，可整体断言
    assert '"' not in out
    assert "'" not in out


def test_sanitize_release_notes_empty_and_none():
    """空值安全：返回空串而非 "<qt></qt>" 空壳。"""
    from desktop_calendar.ui.controllers.update_ui import UpdateUIController

    assert UpdateUIController._sanitize_release_notes("") == ""
    assert UpdateUIController._sanitize_release_notes(None) == ""