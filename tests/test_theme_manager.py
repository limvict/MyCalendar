# coding: utf-8
"""ThemeManager：切换、回退、持久化一致性、信号。"""

import json

import pytest

from desktop_calendar.config import manager as mgr
from desktop_calendar.config.constants import (
    DEFAULT_THEME,
    THEME_DARK,
    THEME_LIGHT,
    THEME_PRESETS,
)
from desktop_calendar.ui.theme.manager import ThemeManager
from desktop_calendar.ui.theme.scaling import fit_scale


@pytest.fixture
def tm(qapp, fresh_config_manager):
    return ThemeManager(fresh_config_manager)


class TestInit:
    def test_default_light(self, tm):
        assert tm.current.name == THEME_LIGHT

    def test_invalid_name_falls_back(self, qapp, isolated_paths):
        _, cfg_path, _ = isolated_paths
        cfg_path.write_text(json.dumps({"theme_name": "bogus"}), encoding="utf-8")
        old = mgr.ConfigManager._instance
        mgr.ConfigManager._instance = None
        try:
            cfg = mgr.ConfigManager()
            tm2 = ThemeManager(cfg)
            assert tm2.current.name == THEME_LIGHT
            # ConfigManager._load 只归一化内存，不主动回写磁盘；
            # 磁盘回写由 ThemeManager._resolve_initial 的 set(save=True) 负责，
            # 但仅在 config.get() 返回无效值时触发——此处 _migrate 已归一化为
            # light，config.get() 返回 light，不会触发回写。
            assert cfg.get("theme_name") == THEME_LIGHT
        finally:
            mgr.ConfigManager._instance = old


class TestSetTheme:
    def test_auto_theme_switches_on_local_time_and_can_be_disabled(self, tm, monkeypatch):
        class FixedDateTime:
            @classmethod
            def now(cls):
                return type("Time", (), {"hour": 20})()

        monkeypatch.setattr("desktop_calendar.ui.theme.manager.datetime", FixedDateTime)

        assert tm.set_auto_theme_enabled(True) is True
        assert tm.name == THEME_DARK
        assert tm._auto_theme_timer.isActive()
        assert tm.set_auto_theme_enabled(False) is True
        assert not tm._auto_theme_timer.isActive()

    def test_auto_theme_day_and_night_boundaries(self):
        assert ThemeManager._automatic_theme_for_hour(6) == THEME_DARK
        assert ThemeManager._automatic_theme_for_hour(7) == THEME_LIGHT
        assert ThemeManager._automatic_theme_for_hour(18) == THEME_LIGHT
        assert ThemeManager._automatic_theme_for_hour(19) == THEME_DARK

    def test_preview_theme_emits_without_persisting(self, tm, fresh_config_manager):
        events = []
        tm.theme_changed.connect(lambda bundle: events.append(bundle.name))

        assert tm.preview_theme(THEME_DARK) is True

        assert tm.current.name == THEME_DARK
        assert fresh_config_manager.get("theme_name") == THEME_LIGHT
        assert events == [THEME_DARK]

    def test_set_dark(self, tm):
        assert tm.set_theme(THEME_DARK) is True
        assert tm.current.name == THEME_DARK

    def test_same_returns_true(self, tm):
        assert tm.set_theme(THEME_LIGHT) is True

    def test_unknown_returns_false(self, tm):
        assert tm.set_theme("bogus") is False
        assert tm.current.name == THEME_LIGHT

    def test_signal(self, tm):
        events = []
        tm.theme_changed.connect(lambda b: events.append(b.name))
        tm.set_theme(THEME_DARK)
        assert events == [THEME_DARK]

    def test_persists(self, tm, fresh_config_manager):
        tm.set_theme(THEME_DARK)
        assert fresh_config_manager.get("theme_name") == THEME_DARK


class TestLoad:
    def test_light_equals_default(self):
        theme = ThemeManager._load(THEME_LIGHT)
        assert theme == dict(DEFAULT_THEME)

    def test_preset_overrides(self):
        theme = ThemeManager._load(THEME_DARK)
        assert theme["bg_main"] == THEME_PRESETS[THEME_DARK]["bg_main"]
        assert theme["window_width"] == DEFAULT_THEME["window_width"]


class TestScreenScaling:
    def test_fit_scale_keeps_design_size_when_it_fits(self):
        assert (
            fit_scale(1920, 1080, DEFAULT_THEME["window_width"], DEFAULT_THEME["window_height"])
            == 1.0
        )

    def test_fit_scale_uses_available_height_and_keeps_margin(self):
        height = DEFAULT_THEME["window_height"]
        assert fit_scale(800, 500, DEFAULT_THEME["window_width"], height) == pytest.approx(
            484 / height
        )

    def test_fit_scale_has_a_minimum_readable_scale(self):
        assert (
            fit_scale(320, 200, DEFAULT_THEME["window_width"], DEFAULT_THEME["window_height"])
            == 0.5
        )

    def test_main_window_scale_accounts_for_sidebar_and_screen_geometry(self):
        from desktop_calendar.ui.main_window import (
            _SIDEBAR_WIDTH,
            _screen_ui_scale,
        )

        class Geometry:
            def width(self):
                return 640

            def height(self):
                return 640

        class Screen:
            def availableGeometry(self):
                return Geometry()

        screen = Screen()
        compact_scale = _screen_ui_scale(screen)
        sidebar_scale = _screen_ui_scale(screen, sidebar_visible=True)

        assert compact_scale == pytest.approx((640 - 16) / 660)
        sidebar_window_width = DEFAULT_THEME["window_width"] + _SIDEBAR_WIDTH
        assert sidebar_scale == pytest.approx((640 - 16) / sidebar_window_width)

    def test_theme_manager_rescales_ui_without_changing_theme_config(self, tm):
        assert tm.set_ui_scale(0.5) is True
        assert tm.current.scale_factor == 0.5
        assert tm.current.window.width == 230
        assert tm.current.dialog.settings_size == (250, 280)
        assert tm.current.fonts.global_.pointSizeF() == pytest.approx(6.5)
        assert "min-height: 16px" in tm.current.qss.calendar

        assert tm.set_theme(THEME_DARK) is True
        assert tm.current.scale_factor == 0.5
        assert tm.current.window.width == 230
