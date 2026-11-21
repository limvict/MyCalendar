# coding: utf-8
"""托盘菜单：结构、动态文案、开机自启动开关。"""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QSystemTrayIcon, QWidget

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.contracts.event_bus import EventType
from desktop_calendar.ui import tray_manager as tray_mod
from desktop_calendar.ui.theme.bundle import build_bundle
from desktop_calendar.ui.tray_manager import TrayManager


@pytest.fixture
def tray(qapp, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    monkeypatch.setattr(tray_mod.auto_start, "is_enabled", lambda: False)
    monkeypatch.setattr(tray_mod.auto_start, "is_supported", lambda: True)
    parent = QWidget()
    manager = TrayManager(
        parent,
        config=MagicMock(),
        get_resource_path=lambda path: path,
        bundle=build_bundle("light", dict(DEFAULT_THEME)),
        on_open_pomodoro=lambda: None,
    )
    yield manager, parent
    parent.deleteLater()


def _labels(manager: TrayManager) -> list[str]:
    return [action.text() for action in manager._menu.actions() if not action.isSeparator()]


def test_menu_structure(tray):
    manager, _parent = tray
    labels = _labels(manager)
    assert labels == [
        "恢复窗口",
        "专注计时",
        "开机自启动",
        "设置",
        "退出程序",
    ]
    # 退出单独成组，避免误点到隔壁的「设置」
    actions = manager._menu.actions()
    assert actions[-2].isSeparator() and actions[-1].text() == "退出程序"


def test_show_action_label_tracks_window_visibility(tray):
    manager, parent = tray

    parent.show()
    parent.activateWindow()
    manager._refresh_menu_state()
    assert manager._act_show.text() == "隐藏到托盘"

    parent.hide()
    manager._refresh_menu_state()
    assert manager._act_show.text() == "恢复窗口"


def test_show_action_toggles_window(tray, monkeypatch):
    manager, parent = tray
    published = []

    class FakeBus:
        @staticmethod
        def publish(event, *args, **kwargs):
            published.append(event)

    monkeypatch.setattr(tray_mod, "event_bus", FakeBus())

    parent.show()
    manager._refresh_menu_state()
    manager._act_show.trigger()
    assert published[-1] == EventType.WINDOW_HIDE

    parent.hide()
    manager._refresh_menu_state()
    manager._act_show.trigger()
    assert published[-1] == EventType.WINDOW_SHOW


def test_autostart_toggle_applies_and_confirms(tray, monkeypatch):
    manager, _parent = tray
    calls = []
    messages = []
    monkeypatch.setattr(tray_mod.auto_start, "set_enabled", lambda enabled: calls.append(enabled))
    monkeypatch.setattr(
        manager,
        "show_message",
        lambda title, body, **kwargs: messages.append((title, body)) or True,
    )

    manager._act_autostart.setChecked(True)
    manager._on_toggle_autostart(True)

    assert calls == [True]
    assert messages and "已开启" in messages[-1][1]


def test_autostart_toggle_rolls_back_on_error(tray, monkeypatch):
    manager, _parent = tray

    def boom(_enabled):
        raise tray_mod.auto_start.AutoStartError("permission")

    messages = []
    monkeypatch.setattr(tray_mod.auto_start, "set_enabled", boom)
    monkeypatch.setattr(
        manager,
        "show_message",
        lambda title, body, **kwargs: messages.append((title, body)) or True,
    )

    manager._act_autostart.setChecked(True)
    manager._on_toggle_autostart(True)

    # 失败要回滚勾选，并且用气泡而不是模态框提示
    assert manager._act_autostart.isChecked() is False
    assert messages and "权限" in messages[-1][1]


def test_menu_has_check_update_entry_and_calls_back(qapp, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    monkeypatch.setattr(tray_mod.auto_start, "is_enabled", lambda: False)
    monkeypatch.setattr(tray_mod.auto_start, "is_supported", lambda: True)
    calls = []
    parent = QWidget()
    manager = TrayManager(
        parent,
        config=MagicMock(),
        get_resource_path=lambda path: path,
        bundle=build_bundle("light", dict(DEFAULT_THEME)),
        on_open_pomodoro=lambda: None,
        on_check_update=lambda: calls.append(1),
    )
    try:
        assert _labels(manager) == [
            "恢复窗口",
            "专注计时",
            "开机自启动",
            "设置",
            "检查更新",
            "退出程序",
        ]
        manager._act_check_update.trigger()
        assert calls == [1]
    finally:
        parent.deleteLater()
