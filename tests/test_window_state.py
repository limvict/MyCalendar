# coding: utf-8
"""WindowStateManager：opacity clamp、topmost 最小化保持。"""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget


@pytest.fixture
def win_and_state(qapp, fresh_config_manager):
    from desktop_calendar.ui.controllers.window_state import WindowStateManager
    w = QWidget()
    state = WindowStateManager(w, fresh_config_manager)
    yield w, state
    w.close()
    w.deleteLater()


def test_opacity_clamped_high(win_and_state):
    w, state = win_and_state
    state.set_opacity(5.0)
    assert w.windowOpacity() == pytest.approx(1.0)


def test_opacity_clamped_low(win_and_state):
    w, state = win_and_state
    state.set_opacity(-1.0)
    assert w.windowOpacity() == pytest.approx(0.0)


def test_topmost_preserves_minimized(win_and_state):
    """从最小化状态切置顶，不应把窗口恢复为正常显示。"""
    w, state = win_and_state
    w.show()
    w.showMinimized()
    state.set_topmost(True)
    assert w.isMinimized()
    assert bool(w.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)


def test_topmost_does_not_show_hidden(win_and_state):
    """未显示的窗口切置顶不应被 show() 拉出来。"""
    w, state = win_and_state
    state.set_topmost(True)
    assert not w.isVisible()