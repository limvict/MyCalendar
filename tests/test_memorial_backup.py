# coding: utf-8
import json

import pytest

from desktop_calendar.core.memorial_backup import (
    backup_to, restore_from, BackupFormatError, BACKUP_FORMAT_VERSION,
)


class FakeConfig:
    def __init__(self, days=None):
        self._data = {"memorial_days": days if days is not None else []}
        self.flushed = False

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value, save=True):
        self._data[key] = value

    def flush(self, raise_on_error=False):
        # 与 ConfigManager.flush 的签名保持一致：restore_from 会传
        # raise_on_error=True，FakeConfig 正常路径不抛异常即可。
        self.flushed = True


class TestBackupTo:
    def test_basic(self, tmp_path):
        cfg = FakeConfig([{"name": "a"}, {"name": "b"}])
        path = tmp_path / "backup.json"
        count = backup_to(str(path), cfg)
        assert count == 2
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == BACKUP_FORMAT_VERSION
        assert "exported_at" in data
        assert len(data["memorial_days"]) == 2

    def test_empty(self, tmp_path):
        cfg = FakeConfig([])
        path = tmp_path / "backup.json"
        assert backup_to(str(path), cfg) == 0

    def test_non_list_normalized(self, tmp_path):
        cfg = FakeConfig()
        cfg._data["memorial_days"] = "not a list"
        path = tmp_path / "backup.json"
        assert backup_to(str(path), cfg) == 0
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["memorial_days"] == []


class TestRestoreFrom:
    def test_basic_dict(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({
            "memorial_days": [{
                "name": "a", "type": "solar", "month": 1, "day": 1,
                "enabled": True, "advance_days": 0, "repeat_type": "year",
            }]
        }), encoding="utf-8")
        cfg = FakeConfig()
        count, skipped = restore_from(str(path), cfg)
        assert count == 1
        assert skipped == 0
        assert cfg.flushed is True
        assert len(cfg._data["memorial_days"]) == 1

    def test_list_format(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps([{
            "name": "a", "type": "solar", "month": 1, "day": 1,
            "enabled": True, "advance_days": 0, "repeat_type": "year",
        }]), encoding="utf-8")
        cfg = FakeConfig()
        count, _ = restore_from(str(path), cfg)
        assert count == 1

    def test_invalid_format_raises(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"other": []}), encoding="utf-8")
        cfg = FakeConfig()
        with pytest.raises(BackupFormatError):
            restore_from(str(path), cfg)

    def test_malformed_json(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text("{invalid", encoding="utf-8")
        cfg = FakeConfig()
        with pytest.raises(json.JSONDecodeError):
            restore_from(str(path), cfg)

    def test_skips_invalid_entries(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text(json.dumps({
            "memorial_days": [
                "not a dict",
                {"name": "valid", "type": "solar", "month": 1, "day": 1,
                 "enabled": True, "advance_days": 0, "repeat_type": "year"},
            ]
        }), encoding="utf-8")
        cfg = FakeConfig()
        count, skipped = restore_from(str(path), cfg)
        assert count == 1
        assert skipped == 1


def test_restore_raises_when_disk_write_fails(tmp_path, monkeypatch):
    """P0 回归：磁盘写失败时 restore_from 必须抛，不能静默成功。

    历史 bug：config.flush() 吞异常，restore_from 返回成功，
    UI 弹"已恢复 N 条"，用户重启后数据丢失。
    """
    from desktop_calendar.config import manager as m

    backup = tmp_path / "b.json"
    backup.write_text(json.dumps({
        "version": BACKUP_FORMAT_VERSION,
        "memorial_days": [{"name": "A", "type": "solar",
                           "repeat_type": "year", "month": 1, "day": 1}],
    }), encoding="utf-8")

    monkeypatch.setattr(m, "get_config_path",
                        lambda: str(tmp_path / "config.json"))
    old = m.ConfigManager._instance
    m.ConfigManager._instance = None
    try:
        cfg = m.ConfigManager()

        def fail_write(path, data):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(m, "atomic_write_json", fail_write)

        with pytest.raises(OSError):
            restore_from(str(backup), cfg)
    finally:
        m.ConfigManager._instance = old


def test_restore_succeeds_and_persists(tmp_path, monkeypatch):
    """正常路径回归：restore 后重启读盘应拿到新数据。"""
    from desktop_calendar.config import manager as m

    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(m, "get_config_path", lambda: str(cfg_path))

    backup = tmp_path / "b.json"
    backup.write_text(json.dumps({
        "version": BACKUP_FORMAT_VERSION,
        "memorial_days": [{"name": "A", "type": "solar",
                           "repeat_type": "year", "month": 1, "day": 1}],
    }), encoding="utf-8")

    old = m.ConfigManager._instance
    m.ConfigManager._instance = None
    try:
        cfg = m.ConfigManager()
        count, skipped = restore_from(str(backup), cfg)
        assert count == 1 and skipped == 0
    finally:
        m.ConfigManager._instance = old

    # 模拟重启：重新构造单例，读磁盘
    m.ConfigManager._instance = None
    try:
        cfg2 = m.ConfigManager()
        mems = cfg2.get("memorial_days", [])
        assert len(mems) == 1
        assert mems[0]["name"] == "A"
    finally:
        m.ConfigManager._instance = old