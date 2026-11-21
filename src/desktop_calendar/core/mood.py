"""Daily mood notes with local JSON persistence."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

from desktop_calendar.config.manager import atomic_write_json, get_logger
from desktop_calendar.utils.paths import get_app_data_dir

logger = get_logger()

MOOD_CHOICES = ("great", "good", "okay", "low", "awful")
_MAX_NOTE_LENGTH = 200


def _default_path() -> str:
    return os.path.join(get_app_data_dir(), "moods.json")


def _day_key(day: date | str) -> str:
    if isinstance(day, datetime):
        day = day.date()
    if isinstance(day, date):
        return day.isoformat()
    if isinstance(day, str):
        try:
            parsed = date.fromisoformat(day)
        except ValueError as error:
            raise ValueError("日期必须为 YYYY-MM-DD") from error
        if parsed.isoformat() == day:
            return day
    raise ValueError("日期必须为 YYYY-MM-DD")


class MoodStore:
    """Loads and saves one mood entry per calendar day."""

    def __init__(self, path: str | None = None) -> None:
        self._path = path or _default_path()
        self._records: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            logger.warning("读取心情记录失败: %s", self._path, exc_info=True)
            return

        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, dict):
            logger.warning("心情记录文件结构异常: %s", self._path)
            return
        for day, record in records.items():
            if not isinstance(day, str) or not isinstance(record, dict):
                continue
            try:
                if _day_key(day) != day:
                    continue
            except ValueError:
                continue
            mood = record.get("mood")
            note = record.get("note", "")
            if (
                mood not in MOOD_CHOICES
                or not isinstance(note, str)
                or len(note) > _MAX_NOTE_LENGTH
            ):
                continue
            self._records[day] = {"mood": mood, "note": note}

    def _save(self) -> None:
        atomic_write_json(self._path, {"version": 1, "records": self._records}, protect=True)

    def get(self, day: date | str) -> dict[str, str]:
        return dict(self._records.get(_day_key(day), {}))

    def between(self, start: date, end: date) -> dict[date, dict[str, str]]:
        if end < start:
            raise ValueError("结束日期不能早于开始日期")
        records = {}
        day = start
        while day <= end:
            record = self._records.get(day.isoformat())
            if record is not None:
                records[day] = dict(record)
            day += timedelta(days=1)
        return records

    def save(self, day: date | str, mood: str, note: str = "") -> None:
        key = _day_key(day)
        if mood not in MOOD_CHOICES:
            raise ValueError(f"不支持的心情类型: {mood!r}")
        if not isinstance(note, str) or len(note) > _MAX_NOTE_LENGTH:
            raise ValueError(f"心情备注不能超过 {_MAX_NOTE_LENGTH} 个字符")

        previous = self._records.get(key)
        self._records[key] = {"mood": mood, "note": note.strip()}
        try:
            self._save()
        except Exception:
            if previous is None:
                self._records.pop(key, None)
            else:
                self._records[key] = previous
            raise

    def delete(self, day: date | str) -> bool:
        key = _day_key(day)
        previous = self._records.pop(key, None)
        if previous is None:
            return False
        try:
            self._save()
        except Exception:
            self._records[key] = previous
            raise
        return True
