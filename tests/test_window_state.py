# coding: utf-8
"""WindowStateManager：opacity clamp/回退、位置恢复、save_position、ensure_on_screen。"""
import pytest
from PyQt6.QtWidgets import QWidget


@pytest.fixture
def state(qapp, fresh_config_manager):
    from desktop_calendar.ui.controllers.window_state import WindowStateManager
    w = QWidget()
    w.setGeometry(100, 100, 300, 200)
    s = WindowStateManager(w, fresh_config_manager)
    yield w, s, fresh_config_manager
    w.close()
    w.deleteLater()


class TestInit:
    def test_invalid_opacity_fallback(self, qapp, fresh_config_manager, opacity_quantized):
        from desktop_calendar.ui.controllers.window_state import WindowStateManager
        fresh_config_manager.set("opacity", "not-a-number", save=False)
        w = QWidget()
        try:
            WindowStateManager(w, fresh_config_manager)
            assert w.windowOpacity() == opacity_quantized(0.92)
        finally:
            w.close()
            w.deleteLater()

    def test_restores_position(self, qapp, fresh_config_manager):
        from desktop_calendar.ui.controllers.window_state import WindowStateManager
        fresh_config_manager.set("pos_x", 100, save=False)
        fresh_config_manager.set("pos_y", 200, save=False)
        w = QWidget()
        try:
            WindowStateManager(w, fresh_config_manager)
            assert w.x() == 100
            assert w.y() == 200
        finally:
            w.close()
            w.deleteLater()


class TestSavePosition:
    def test_writes_geometry(self, state):
        w, s, cfg = state
        w.move(50, 60)
        s.save_position()
        assert cfg.get("pos_x") == 50
        assert cfg.get("pos_y") == 60


class TestEnsureOnScreen:
    def test_visible_no_move(self, state):
        w, s, _ = state
        w.move(100, 100)
        before = w.pos()
        s.ensure_on_screen()
        assert w.pos() == before


class TestOpacity:
    def test_clamped_high(self, state):
        w, s, _ = state
        s.set_opacity(5.0)
        assert w.windowOpacity() == pytest.approx(1.0)

    def test_clamped_low(self, state):
        w, s, _ = state
        s.set_opacity(-1.0)
        assert w.windowOpacity() == pytest.approx(0.0)

    def test_nan_does_not_crash(self, state):
        w, s, _ = state
        try:
            s.set_opacity(float("nan"))
        except (TypeError, ValueError):
            pass  # 允许抛，只要不是段错误
