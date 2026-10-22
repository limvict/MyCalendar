import json
import pytest

from desktop_calendar.core.memorial_backup import restore_from, backup_to
from desktop_calendar.config.config import ConfigManager


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    # 让 ConfigManager 指向 tmp_path 下的 config.json
    monkeypatch.setattr(
        "desktop_calendar.config.config.get_config_path",
        lambda: str(tmp_path / "config.json"),
    )
    # 单例按测试隔离
    monkeypatch.setattr(ConfigManager, "_instance", None)
    return ConfigManager()


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_restore_from_dict_format_keeps_data(tmp_path, cfg):
    p = tmp_path / "backup.json"
    _write(p, {
        "version": 1,
        "memorial_days": [
            {"name": "生日", "type": "solar", "month": 6, "day": 15},
            {"name": "结婚", "type": "solar", "month": 10, "day": 1},
        ],
    })
    count, skipped = restore_from(str(p), cfg)
    assert (count, skipped) == (2, 0)
    # 关键断言：不能为空
    assert len(cfg.get("memorial_days")) == 2


def test_restore_from_bare_list(tmp_path, cfg):
    p = tmp_path / "backup.json"
    _write(p, [{"name": "a", "type": "solar", "month": 1, "day": 1}])
    count, _ = restore_from(str(p), cfg)
    assert count == 1
    assert cfg.get("memorial_days")[0]["name"] == "a"


def test_restore_skips_non_dict_entries(tmp_path, cfg):
    p = tmp_path / "backup.json"
    _write(p, {
        "memorial_days": [
            {"name": "ok", "type": "solar", "month": 1, "day": 1},
            "garbage",
            123,
        ],
    })
    count, skipped = restore_from(str(p), cfg)
    assert (count, skipped) == (1, 2)
    assert len(cfg.get("memorial_days")) == 1


def test_backup_then_restore_roundtrip(tmp_path, cfg):
    cfg.set("memorial_days", [
        {"name": "x", "type": "solar", "month": 3, "day": 8,
         "enabled": True, "advance_days": 0, "repeat_type": "year",
         "isleap": False},
    ])
    p = tmp_path / "b.json"
    assert backup_to(str(p), cfg) == 1
    cfg.set("memorial_days", [])
    count, _ = restore_from(str(p), cfg)
    assert count == 1
    assert cfg.get("memorial_days")[0]["name"] == "x"