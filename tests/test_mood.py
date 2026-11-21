from datetime import date, datetime

import pytest

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.config.manager import normalize_config
from desktop_calendar.core.mood import MoodStore
from desktop_calendar.ui.dialogs.mood import MoodDialog
from desktop_calendar.ui.theme.bundle import build_bundle


def test_mood_store_persists_and_deletes_record(tmp_path):
    path = tmp_path / "moods.json"
    store = MoodStore(str(path))
    day = date(2024, 6, 3)

    store.save(day, "good", "  Productive day  ")

    assert store.get(day) == {"mood": "good", "note": "Productive day"}
    assert MoodStore(str(path)).get(day.isoformat()) == {
        "mood": "good",
        "note": "Productive day",
    }
    assert store.delete(day)
    assert not store.delete(day)
    assert MoodStore(str(path)).get(day) == {}


def test_auto_punch_is_disabled_by_default():
    assert normalize_config({})["attendance_cfg"]["enable_auto_punch"] is False


def test_mood_store_validates_input_and_rolls_back_save_failure(tmp_path, monkeypatch):
    store = MoodStore(str(tmp_path / "moods.json"))
    day = date(2024, 6, 3)
    store.save(day, "good", "steady")

    with pytest.raises(ValueError):
        store.save("2024-02-30", "great")
    with pytest.raises(ValueError):
        store.save(day, "unknown")
    with pytest.raises(ValueError):
        store.save(day, "great", "x" * 201)

    def fail_save():
        raise OSError("disk full")

    monkeypatch.setattr(store, "_save", fail_save)
    with pytest.raises(OSError, match="disk full"):
        store.save(day, "low")
    assert store.get(day) == {"mood": "good", "note": "steady"}


def test_mood_dialog_edits_and_deletes_record(qapp, tmp_path):
    store = MoodStore(str(tmp_path / "moods.json"))
    day = date(2024, 6, 3)
    bundle = build_bundle("light", dict(DEFAULT_THEME))
    dialog = MoodDialog(store, day, bundle=bundle)
    try:
        dialog._buttons["great"].setChecked(True)
        dialog._note.setText("Feeling good")
        dialog._save()
        assert store.get(day) == {"mood": "great", "note": "Feeling good"}

        updated = MoodDialog(store, day, bundle=bundle)
        try:
            assert updated._buttons["great"].isChecked()
            updated._delete()
            assert store.get(day) == {}
        finally:
            updated.deleteLater()
    finally:
        dialog.deleteLater()


def test_auto_punch_skips_missed_start_after_launch(qapp, tmp_path, monkeypatch):
    from desktop_calendar.core import attendance_auto_punch as auto_module

    class Config:
        def get_nested(self, *keys, default=None):
            values = {
                ("attendance_cfg", "enable_auto_punch"): True,
                ("attendance_cfg", "work_rule"): {
                    "work_start": "08:00",
                    "work_end": "17:00",
                },
            }
            return values.get(keys, default)

    monkeypatch.setattr(auto_module, "_is_workday", lambda _day: True)
    store = auto_module.AttendanceStore(str(tmp_path / "attendance.json"))
    manager = auto_module.AttendanceAutoPunchManager(None, Config(), store)
    try:
        next_target = manager._next_target(datetime(2024, 6, 3, 9, 0))
        assert next_target == (datetime(2024, 6, 4, 8, 0), "in")
    finally:
        manager.shutdown()


def test_auto_punch_writes_record_at_trigger_time(qapp, tmp_path, monkeypatch):
    from desktop_calendar.core import attendance_auto_punch as auto_module

    class Config:
        def get_nested(self, *keys, default=None):
            values = {
                ("attendance_cfg", "enable_auto_punch"): True,
                ("attendance_cfg", "work_rule"): {
                    "work_start": "08:00",
                    "work_end": "17:00",
                },
            }
            return values.get(keys, default)

    fixed_now = datetime(2024, 6, 3, 8, 0, 5)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(auto_module, "datetime", FixedDateTime)
    monkeypatch.setattr(auto_module, "_is_workday", lambda _day: True)
    store = auto_module.AttendanceStore(str(tmp_path / "attendance.json"))
    manager = auto_module.AttendanceAutoPunchManager(None, Config(), store)
    events = []
    manager.punched.connect(lambda action, stamp: events.append((action, stamp)))
    manager._pending = (datetime(2024, 6, 3, 8, 0), "in")
    try:
        manager._on_trigger()
        assert store.get_record(date(2024, 6, 3))["in"] == "08:00"
        assert events == [("in", "08:00")]
    finally:
        manager.shutdown()
