# coding: utf-8
"""memorial_backup 补充：BackupWriteError 精度、dict/None 输入。"""
import json

import pytest

from desktop_calendar.core.memorial_backup import (
    backup_to, restore_from, BackupFormatError, BackupWriteError,
)


class FakeConfig:
    def __init__(self, days=None):
        self._data = {"memorial_days": days if days is not None else []}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value, save=True):
        self._data[key] = value

    def flush(self, raise_on_error=False):
        pass


class _FlushFailConfig(FakeConfig):
    def flush(self, raise_on_error=False):
        if raise_on_error:
            raise OSError(28, "No space left on device")


def _write_backup(tmp_path, payload):
    p = tmp_path / "b.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


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


def test_backup_with_dict_memorial_days(tmp_path):
    cfg = FakeConfig()
    cfg._data["memorial_days"] = {"a": 1}
    path = tmp_path / "b.json"
    assert backup_to(str(path), cfg) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["memorial_days"] == []


def test_backup_with_none_memorial_days(tmp_path):
    cfg = FakeConfig()
    cfg._data["memorial_days"] = None
    assert backup_to(str(tmp_path / "b.json"), cfg) == 0


def test_restore_dict_without_memorial_days_raises(tmp_path):
    path = _write_backup(tmp_path, {"version": 1})
    with pytest.raises(BackupFormatError):
        restore_from(path, FakeConfig())


def test_restore_memorial_days_not_list_raises(tmp_path):
    path = _write_backup(tmp_path, {"memorial_days": {"a": 1}})
    with pytest.raises(BackupFormatError):
        restore_from(path, FakeConfig())


def test_restore_empty_list_root_ok(tmp_path):
    path = tmp_path / "b.json"
    path.write_text("[]", encoding="utf-8")
    cfg = FakeConfig()
    count, skipped = restore_from(str(path), cfg)
    assert (count, skipped) == (0, 0)
    assert cfg._data["memorial_days"] == []