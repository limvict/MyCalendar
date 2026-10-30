# coding: utf-8
import json

import pytest

from desktop_calendar.config import manager as mgr_module


class TestAtomicWriteJson:
    def test_basic(self, tmp_path):
        path = tmp_path / "out.json"
        mgr_module.atomic_write_json(str(path), {"a": 1})
        assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}

    def test_creates_dir(self, tmp_path):
        path = tmp_path / "sub" / "out.json"
        mgr_module.atomic_write_json(str(path), {"a": 1})
        assert path.exists()

    def test_overwrites(self, tmp_path):
        path = tmp_path / "out.json"
        mgr_module.atomic_write_json(str(path), {"a": 1})
        mgr_module.atomic_write_json(str(path), {"b": 2})
        assert json.loads(path.read_text(encoding="utf-8")) == {"b": 2}


class TestHolidayCache:
    def test_roundtrip(self, isolated_paths):
        mgr_module.save_holiday_cache({"2024": {"ts": 1, "days": {}}})
        assert mgr_module.load_holiday_cache() == {
            "2024": {"ts": 1, "days": {}}
        }

    def test_load_missing(self, isolated_paths):
        assert mgr_module.load_holiday_cache() == {}

    def test_load_corrupt(self, isolated_paths):
        _, _, hc = isolated_paths
        hc.write_text("{invalid", encoding="utf-8")
        assert mgr_module.load_holiday_cache() == {}

    def test_load_non_dict(self, isolated_paths):
        _, _, hc = isolated_paths
        hc.write_text("[]", encoding="utf-8")
        assert mgr_module.load_holiday_cache() == {}


class TestConfigMigrate:
    def test_defaults(self, fresh_config_manager):
        cm = fresh_config_manager
        assert cm.get("memorial_days") == []
        assert cm.get("topmost") is False
        assert cm.get("opacity") == 0.92
        assert cm.get("language") == "zh_CN"
        assert cm.get("theme_name") == "light"
        assert cm.get("config_version") == mgr_module.CONFIG_VERSION

    def test_memorial_cfg_defaults(self, fresh_config_manager):
        cfg = fresh_config_manager.get("memorial_cfg")
        assert cfg["enable_remind"] is True
        assert cfg["sound_enable"] is True
        assert cfg["remind_start_hour"] == 8
        assert cfg["remind_end_hour"] == 22


class TestConfigInvalidValues:
    def _load_with(self, cfg_path, payload):
        cfg_path.write_text(json.dumps(payload), encoding="utf-8")
        old = mgr_module.ConfigManager._instance
        mgr_module.ConfigManager._instance = None
        try:
            return mgr_module.ConfigManager()
        finally:
            mgr_module.ConfigManager._instance = old

    def test_invalid_language(self, isolated_paths):
        _, cfg_path, _ = isolated_paths
        cm = self._load_with(cfg_path, {"language": "fr_FR"})
        assert cm.get("language") == "zh_CN"

    def test_invalid_opacity_clamped(self, isolated_paths):
        _, cfg_path, _ = isolated_paths
        cm = self._load_with(cfg_path, {"opacity": 5.0})
        assert cm.get("opacity") == 1.0

    def test_invalid_theme(self, isolated_paths):
        _, cfg_path, _ = isolated_paths
        cm = self._load_with(cfg_path, {"theme_name": "not_a_theme"})
        assert cm.get("theme_name") == "light"


class TestGetSet:
    def test_get_default(self, fresh_config_manager):
        assert fresh_config_manager.get("nonexistent", "dft") == "dft"

    def test_set_and_get(self, fresh_config_manager):
        fresh_config_manager.set("test_key", "test_val", save=False)
        assert fresh_config_manager.get("test_key") == "test_val"

    def test_mutable_returns_copy(self, fresh_config_manager):
        fresh_config_manager.set("test_list", [1, 2, 3], save=False)
        lst = fresh_config_manager.get("test_list")
        lst.append(4)
        assert fresh_config_manager.get("test_list") == [1, 2, 3]

    def test_set_nested(self, fresh_config_manager):
        fresh_config_manager.set_nested("a", "b", "c", 1, save=False)
        assert fresh_config_manager.get_nested("a", "b", "c") == 1

    def test_get_nested_missing(self, fresh_config_manager):
        assert fresh_config_manager.get_nested(
            "x", "y", default="dft") == "dft"

    def test_snapshot_deep_copy(self, fresh_config_manager):
        fresh_config_manager.set("nested", {"a": [1]}, save=False)
        snap = fresh_config_manager.snapshot()
        snap["nested"]["a"].append(2)
        assert fresh_config_manager.get("nested") == {"a": [1]}

    def test_replace_all_reruns_migrate(self, fresh_config_manager):
        fresh_config_manager.replace_all({"custom": "v"}, save=False)
        assert fresh_config_manager.get("custom") == "v"
        # migrate 仍然生效
        assert fresh_config_manager.get("memorial_days") == []


class TestCorruptBackup:
    def test_backup_created(self, isolated_paths):
        _, cfg_path, _ = isolated_paths
        cfg_path.write_text("{invalid", encoding="utf-8")
        old = mgr_module.ConfigManager._instance
        mgr_module.ConfigManager._instance = None
        try:
            mgr_module.ConfigManager()
        finally:
            mgr_module.ConfigManager._instance = old
        backups = list(cfg_path.parent.glob("config.json.corrupt-*"))
        assert len(backups) >= 1
        
@pytest.mark.parametrize("bad_json", [
    '[]',          # list
    '[1, 2]',      # 非空 list
    '{"a": 1}',    # dict
    '{"theme": "dark"}',
])
def test_theme_name_unhashable_does_not_crash(
        tmp_path, monkeypatch, bad_json):
    """P0 回归：theme_name 是 list / dict 时 _migrate 不崩，归一到 light。

    JSON 不支持 set，这里用 list / dict 覆盖 unhashable 的两类容器。
    """
    from desktop_calendar.config import manager as m

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        '{"theme_name": ' + bad_json + ', "opacity": 0.8}',
        encoding="utf-8")
    monkeypatch.setattr(m, "get_config_path", lambda: str(cfg_path))

    old = m.ConfigManager._instance
    m.ConfigManager._instance = None
    try:
        cfg = m.ConfigManager()
        assert cfg.get("theme_name") == "light"
        assert cfg.get("opacity") == 0.8
    finally:
        m.ConfigManager._instance = old


def test_migrate_failure_degrades_to_default(tmp_path, monkeypatch):
    """_migrate 抛异常时降级为空配置重新迁移，不传播。"""
    from desktop_calendar.config import manager as m

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text('{"memorial_days": []}', encoding="utf-8")
    monkeypatch.setattr(m, "get_config_path", lambda: str(cfg_path))

    orig_migrate = m.ConfigManager._migrate
    state = {"n": 0}

    def flaky_migrate(self):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("模拟迁移失败")
        return orig_migrate(self)

    monkeypatch.setattr(m.ConfigManager, "_migrate", flaky_migrate)

    old = m.ConfigManager._instance
    m.ConfigManager._instance = None
    try:
        cfg = m.ConfigManager()
        # 降级后走默认值
        assert cfg.get("theme_name") == "light"
        assert cfg.get("opacity") == 0.92
    finally:
        m.ConfigManager._instance = old