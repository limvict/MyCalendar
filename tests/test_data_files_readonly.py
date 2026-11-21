# coding: utf-8
"""应用数据文件只读：写后置只读、程序自己可重写、用户直接改会被拒。

覆盖 config / schedules / attendance / moods / focus_log / holiday_cache
六个存储（weather_cache 走同一个 atomic_write_json 路径）。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest


def _assert_locked(path):
    """文件存在、只读，且直接写入会被系统拒绝。"""
    from desktop_calendar.utils.paths import is_readonly

    assert path.exists(), f"{path} 应已创建"
    assert is_readonly(str(path)), f"{path} 应为只读"
    with pytest.raises(OSError):
        path.write_text("{}", encoding="utf-8")


class TestAtomicWriterProtection:
    def test_protect_sets_readonly_and_allows_rewrite(self, tmp_path):
        from desktop_calendar.config.manager import atomic_write_json
        from desktop_calendar.utils.paths import is_readonly

        target = tmp_path / "x.json"
        atomic_write_json(str(target), {"a": 1}, protect=True)
        assert is_readonly(str(target))
        with pytest.raises(OSError):
            target.write_text("{}", encoding="utf-8")

        # 程序自己再次写入：先解锁再落盘，写完仍只读
        atomic_write_json(str(target), {"a": 2}, protect=True)
        assert '"a": 2' in target.read_text(encoding="utf-8")
        assert is_readonly(str(target))

    def test_without_protect_keeps_file_writable(self, tmp_path):
        from desktop_calendar.config.manager import atomic_write_json
        from desktop_calendar.utils.paths import is_readonly

        target = tmp_path / "export.json"
        atomic_write_json(str(target), {"a": 1})
        assert not is_readonly(str(target))
        target.write_text('{"a": 2}', encoding="utf-8")


class TestReadonlyHelpers:
    def test_mark_and_clear(self, tmp_path):
        from desktop_calendar.utils.paths import clear_readonly, is_readonly, mark_readonly

        path = tmp_path / "f.json"
        path.write_text("{}", encoding="utf-8")
        assert not is_readonly(str(path))
        mark_readonly(str(path))
        assert is_readonly(str(path))
        clear_readonly(str(path))
        assert not is_readonly(str(path))

    def test_clear_missing_is_noop(self, tmp_path):
        from desktop_calendar.utils.paths import clear_readonly

        clear_readonly(str(tmp_path / "nope.json"))


class TestDataStoresProtectFiles:
    def test_config(self, fresh_config_manager, isolated_paths):
        _tmp, cfg_path, _hc = isolated_paths
        fresh_config_manager.set("opacity", 0.8, save=False)
        fresh_config_manager.flush()
        _assert_locked(cfg_path)

        # 程序侧仍可更新并重新落盘（只读在写入前自动解锁）
        fresh_config_manager.set("opacity", 0.81, save=False)
        fresh_config_manager.flush()
        _assert_locked(cfg_path)

    def test_holiday_cache(self, isolated_paths):
        from desktop_calendar.config.manager import save_holiday_cache, storage

        _tmp, _cfg, hc_path = isolated_paths
        assert storage.get_holiday_cache_path() == str(hc_path)
        save_holiday_cache({"2024": {"ts": 1, "days": {}}})
        _assert_locked(hc_path)
        save_holiday_cache({"2024": {"ts": 2, "days": {}}})
        _assert_locked(hc_path)

    def test_schedules(self, tmp_path):
        from desktop_calendar.core.schedule import ScheduleManager

        path = tmp_path / "schedules.json"
        manager = ScheduleManager(path)
        manager.add(title="A", date="2024-06-10")
        _assert_locked(path)

        manager.add(title="B", date="2024-06-11")
        _assert_locked(path)

    def test_attendance(self, tmp_path):
        from desktop_calendar.core.attendance import AttendanceStore

        path = tmp_path / "attendance.json"
        store = AttendanceStore(path=str(path))
        store.punch("in", now=datetime(2024, 6, 10, 8, 30))
        _assert_locked(path)

        store.punch("out", now=datetime(2024, 6, 10, 18, 0))
        _assert_locked(path)

    def test_moods(self, tmp_path):
        from desktop_calendar.core.mood import MoodStore

        path = tmp_path / "moods.json"
        store = MoodStore(str(path))
        store.save(date(2024, 6, 10), "good", "note")
        _assert_locked(path)

        store.save(date(2024, 6, 11), "okay", "")
        _assert_locked(path)

    def test_focus_log(self, tmp_path):
        from desktop_calendar.core.focus_log import FocusLog

        path = tmp_path / "focus_log.json"
        log = FocusLog(str(path))
        log.add(25)
        _assert_locked(path)

        log.add(30)
        _assert_locked(path)
