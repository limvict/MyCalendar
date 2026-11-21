"""番茄钟专注记录：本地 JSON 持久化，按天聚合。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from desktop_calendar.config.constants import FOCUS_LOG_FILE_NAME
from desktop_calendar.config.manager import atomic_write_json, get_logger
from desktop_calendar.utils.paths import get_app_data_dir

logger = get_logger()


@dataclass
class FocusRecord:
    date: str  # YYYY-MM-DD
    started_at: str  # ISO 时间
    minutes: int
    title: str = ""
    schedule_id: str = ""

    def __post_init__(self) -> None:
        try:
            parsed_date = date.fromisoformat(self.date)
            started = datetime.fromisoformat(self.started_at)
        except (TypeError, ValueError) as error:
            raise ValueError("专注记录日期或开始时间无效") from error
        if parsed_date.isoformat() != self.date or started.date() != parsed_date:
            raise ValueError("专注记录日期必须与开始时间一致")
        if not isinstance(self.minutes, int) or isinstance(self.minutes, bool) or self.minutes <= 0:
            raise ValueError("专注分钟数必须为正整数")
        if not isinstance(self.title, str) or not isinstance(self.schedule_id, str):
            raise ValueError("专注标题和日程编号必须为文本")


def _default_path() -> str:
    return os.path.join(get_app_data_dir(), FOCUS_LOG_FILE_NAME)


class FocusLog:
    def __init__(self, path: str | None = None) -> None:
        self._path = path or _default_path()
        self._records: list[FocusRecord] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("读取专注记录失败: %s", self._path, exc_info=True)
            return
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            logger.warning("专注记录文件结构异常: %s", self._path)
            return
        for item in records:
            if not isinstance(item, dict):
                logger.warning("跳过无效专注记录: %r", item)
                continue
            try:
                self._records.append(FocusRecord(**item))
            except (TypeError, ValueError):
                logger.warning("跳过无效专注记录: %r", item.get("date"), exc_info=True)
                continue

    def _save(self) -> None:
        atomic_write_json(
            self._path,
            {"version": 1, "records": [asdict(r) for r in self._records]},
            protect=True,
        )

    def add(
        self,
        minutes: int,
        title: str = "",
        schedule_id: str = "",
        started_at: datetime | None = None,
    ) -> FocusRecord:
        started = started_at or datetime.now()
        record = FocusRecord(
            date=started.date().isoformat(),
            started_at=started.isoformat(timespec="seconds"),
            minutes=minutes,
            title=title,
            schedule_id=schedule_id,
        )
        previous = list(self._records)
        self._records.append(record)
        try:
            self._save()
        except Exception:
            self._records = previous
            raise
        return record

    def today_count(self, today: date | None = None) -> int:
        key = (today or date.today()).isoformat()
        return sum(1 for r in self._records if r.date == key)

    def today_minutes(self, today: date | None = None) -> int:
        key = (today or date.today()).isoformat()
        return sum(r.minutes for r in self._records if r.date == key)

    def recent(self, days: int = 7, today: date | None = None) -> list[tuple[date, int, int]]:
        """返回最近 N 天 (日期, 次数, 分钟)，旧→新。"""
        if not isinstance(days, int) or isinstance(days, bool) or days < 0:
            raise ValueError("天数必须为非负整数")
        today = today or date.today()
        buckets: dict[str, list[FocusRecord]] = {}
        for r in self._records:
            buckets.setdefault(r.date, []).append(r)
        out = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            items = buckets.get(d.isoformat(), [])
            out.append((d, len(items), sum(x.minutes for x in items)))
        return out
