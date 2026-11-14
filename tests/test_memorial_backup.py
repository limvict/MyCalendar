# coding: utf-8
"""memorial_backup：备份 / 恢复、格式校验、写盘失败传播。"""
import json
import copy
import pytest

from desktop_calendar.core.memorial_backup import (
    backup_to, restore_from, BackupFormatError, BackupWriteError,
    BACKUP_FORMAT_VERSION,
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

    def replace_key_atomically(self, key, value, *, raise_on_error=True):
        """模拟 ConfigManager.replace_key_atomically 的可观测行为：

        - 备份旧值；
        - 写新值；
        - 调 flush；
        - flush 抛异常时回滚旧值并把原异常原样 re-raise
          （restore_from 依赖 __cause__ 是 OSError，不能被包裹）。
        """
        old = self.get(key)
        self.set(key, value, save=False)
        try:
            self.flush(raise_on_error=raise_on_error)
        except Exception:
            self.set(key, old, save=False)
            raise

class _FlushFailConfig(FakeConfig):
    def flush(self, raise_on_error=False):
        raise OSError(28, "disk full")


def _write_backup(tmp_path, payload):
    p = tmp_path / "b.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


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

    def test_backup_with_dict_memorial_days(self, tmp_path):
        cfg = FakeConfig()
        cfg._data["memorial_days"] = {"a": 1}
        path = tmp_path / "b.json"
        assert backup_to(str(path), cfg) == 0
        assert json.loads(
            path.read_text(encoding="utf-8"))["memorial_days"] == []

    def test_backup_with_none_memorial_days(self, tmp_path):
        cfg = FakeConfig()
        cfg._data["memorial_days"] = None
        assert backup_to(str(tmp_path / "b.json"), cfg) == 0


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

    def test_restore_dict_without_memorial_days_raises(self, tmp_path):
        path = _write_backup(tmp_path, {"version": 1})
        with pytest.raises(BackupFormatError):
            restore_from(path, FakeConfig())

    def test_restore_memorial_days_not_list_raises(self, tmp_path):
        path = _write_backup(tmp_path, {"memorial_days": {"a": 1}})
        with pytest.raises(BackupFormatError):
            restore_from(path, FakeConfig())

    def test_restore_empty_list_root_ok(self, tmp_path):
        path = tmp_path / "b.json"
        path.write_text("[]", encoding="utf-8")
        cfg = FakeConfig()
        count, skipped = restore_from(str(path), cfg)
        assert (count, skipped) == (0, 0)
        assert cfg._data["memorial_days"] == []


def test_restore_wraps_flush_error_as_backup_write_error(tmp_path):
    """flush 抛异常必须包装为 BackupWriteError，__cause__ 保留原 OSError。"""
    path = _write_backup(tmp_path, {
        "memorial_days": [{"name": "A", "type": "solar",
                           "month": 1, "day": 1, "repeat_type": "year"}],
    })
    with pytest.raises(BackupWriteError) as ei:
        restore_from(path, _FlushFailConfig())
    assert isinstance(ei.value.__cause__, OSError)
    assert ei.value.__cause__.errno == 28


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

        from desktop_calendar.core.memorial_backup import BackupWriteError
        with pytest.raises(BackupWriteError):
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

def test_restore_rolls_back_memory_on_flush_failure(tmp_path, monkeypatch):
    """flush 失败时内存中 memorial_days 必须回滚到旧值。

    否则磁盘未变、内存已变，后续任何 MEMORIAL_CHANGED 触发路径
    都会把未落盘的数据写下去。
    """
    old_list = [{"name": "old", "type": "solar", "repeat_type": "year",
                 "month": 1, "day": 1}]
    backup = tmp_path / "b.json"
    backup.write_text(json.dumps({
        "memorial_days": [{"name": "new", "type": "solar",
                           "repeat_type": "year", "month": 2, "day": 2}],
    }), encoding="utf-8")

    cfg = FakeConfig(copy.deepcopy(old_list))

    def fail_flush(raise_on_error=False):
        if raise_on_error:
            raise OSError(28, "No space left on device")
    monkeypatch.setattr(cfg, "flush", fail_flush)

    with pytest.raises(BackupWriteError):
        restore_from(str(backup), cfg)

    # 关键断言：内存回滚
    assert cfg._data["memorial_days"] == old_list


def test_restore_keeps_new_list_on_flush_success(tmp_path):
    """对照组：flush 成功时内存保持新列表。"""
    cfg = FakeConfig([])
    backup = tmp_path / "b.json"
    backup.write_text(json.dumps({
        "memorial_days": [{"name": "new", "type": "solar",
                           "repeat_type": "year", "month": 2, "day": 2}],
    }), encoding="utf-8")
    restore_from(str(backup), cfg)
    assert cfg._data["memorial_days"][0]["name"] == "new"
