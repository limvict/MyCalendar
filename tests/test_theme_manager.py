# coding: utf-8
"""ThemeManager：切换、回退、持久化一致性、信号。"""
import json

import pytest

from desktop_calendar.config import manager as mgr
from desktop_calendar.config.constants import (
    DEFAULT_THEME, THEME_DARK, THEME_LIGHT, THEME_PRESETS,
)
from desktop_calendar.ui.theme.manager import ThemeManager


@pytest.fixture
def tm(qapp, fresh_config_manager):
    return ThemeManager(fresh_config_manager)


class TestInit:
    def test_default_light(self, tm):
        assert tm.current.name == THEME_LIGHT

    def test_invalid_name_falls_back(self, qapp, isolated_paths):
        _, cfg_path, _ = isolated_paths
        cfg_path.write_text(
            json.dumps({"theme_name": "bogus"}), encoding="utf-8")
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
