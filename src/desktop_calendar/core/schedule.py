"""日程 / 待办：数据模型与持久化管理（不依赖 Qt）。"""

from __future__ import annotations

import json
import re
import uuid
from calendar import monthrange
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from ..config.constants import SCHEDULE_FILE_NAME
from ..config.manager import atomic_write_json
from ..utils.logging_setup import get_logger
from ..utils.paths import get_app_data_dir

_log = get_logger()

_REPEAT_NONE, _REPEAT_DAILY, _REPEAT_WEEKLY, _REPEAT_MONTHLY, _REPEAT_YEARLY = (
    "none",
    "daily",
    "weekly",
    "monthly",
    "yearly",
)
REPEAT_CHOICES = (_REPEAT_NONE, _REPEAT_DAILY, _REPEAT_WEEKLY, _REPEAT_MONTHLY, _REPEAT_YEARLY)
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass
class Schedule:
    id: str
    title: str
    date: str  # "YYYY-MM-DD"，重复日程为首次发生日
    time: str = ""  # "HH:MM"，空表示全天
    note: str = ""
    repeat: str = _REPEAT_NONE
    done: bool = False  # 仅对非重复日程有意义
    remind_minutes: int = 0  # 0 = 不提醒；提前 N 分钟
    color: str = ""  # "#RRGGBB"，空 = 默认色
    snoozed_until: str = ""  # ISO 时间，非空表示正在 snooze
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("日程标题不能为空")
        try:
            parsed_date = datetime.strptime(self.date, "%Y-%m-%d").date()
        except (TypeError, ValueError) as error:
            raise ValueError("日程日期必须为 YYYY-MM-DD") from error
        if parsed_date.isoformat() != self.date:
            raise ValueError("日程日期必须为 YYYY-MM-DD")
        if self.time:
            try:
                parsed_time = datetime.strptime(self.time, "%H:%M").time()
            except (TypeError, ValueError) as error:
                raise ValueError("日程时间必须为 HH:MM") from error
            if parsed_time.strftime("%H:%M") != self.time:
                raise ValueError("日程时间必须为 HH:MM")
        if self.repeat not in REPEAT_CHOICES:
            raise ValueError(f"不支持的重复规则: {self.repeat!r}")
        if (
            not isinstance(self.remind_minutes, int)
            or isinstance(self.remind_minutes, bool)
            or self.remind_minutes < 0
        ):
            raise ValueError("提前提醒分钟数必须为非负整数")
        if not isinstance(self.color, str) or (self.color and not _COLOR_RE.fullmatch(self.color)):
            raise ValueError("日程颜色必须为 #RRGGBB 格式")
        if not isinstance(self.snoozed_until, str):
            raise ValueError("snoozed_until 必须为 ISO 时间")
        if self.snoozed_until:
            try:
                datetime.fromisoformat(self.snoozed_until)
            except ValueError as error:
                raise ValueError("snoozed_until 必须为 ISO 时间") from error

    @property
    def start(self) -> datetime | None:
        if not self.time:
            return None
        return datetime.strptime(f"{self.date} {self.time}", "%Y-%m-%d %H:%M")

    def occurs_on(self, day: date) -> bool:
        base = datetime.strptime(self.date, "%Y-%m-%d").date()
        if day < base:
            return False
        if self.repeat == _REPEAT_NONE:
            return day == base
        if self.repeat == _REPEAT_DAILY:
            return True
        if self.repeat == _REPEAT_WEEKLY:
            return day.weekday() == base.weekday()
        if self.repeat == _REPEAT_MONTHLY:
            return day.day == min(base.day, monthrange(day.year, day.month)[1])
        if self.repeat == _REPEAT_YEARLY:
            if day.month != base.month:
                return False
            return day.day == min(base.day, monthrange(day.year, day.month)[1])
        return False


class ScheduleManager:
    """读写 schedules.json；线程内使用，Qt 侧调用即可。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (Path(get_app_data_dir()) / SCHEDULE_FILE_NAME)
        self._items: dict[str, Schedule] = {}
        self.load()

    # ---- 持久化（不变）----
    def load(self) -> None:
        self._items.clear()
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            self._items.clear()
            _log.exception("加载日程失败，已备份为 .bak")
            try:
                self._path.with_suffix(".json.bak").write_bytes(self._path.read_bytes())
            except OSError:
                _log.exception("备份损坏日程文件失败: %s", self._path)
            return
        if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
            self._items.clear()
            _log.error("日程文件结构异常: %s", self._path)
            return
        for d in raw["items"]:
            if not isinstance(d, dict):
                _log.warning("跳过无效日程记录: %r", d)
                continue
            # 兼容旧文件（缺少 color / snoozed_until 时用默认值）
            d.setdefault("color", "")
            d.setdefault("snoozed_until", "")
            try:
                s = Schedule(**d)
            except (TypeError, ValueError):
                _log.warning("跳过无效日程记录 id=%r", d.get("id"), exc_info=True)
                continue
            self._items[s.id] = s

    def save(self) -> None:
        payload = {"version": 2, "items": [asdict(s) for s in self._items.values()]}
        # 与其他数据文件一致：写完后置只读，用户不能手改，程序下次写入前自动解锁
        atomic_write_json(str(self._path), payload, protect=True)

    # ---- CRUD（不变）----
    def add(self, **kwargs) -> Schedule:
        kwargs.setdefault("id", uuid.uuid4().hex[:12])
        s = Schedule(**kwargs)
        self._items[s.id] = s
        try:
            self.save()
        except Exception:
            self._items.pop(s.id, None)
            raise
        return s

    def update(self, schedule_id: str, **changes) -> Schedule | None:
        s = self._items.get(schedule_id)
        if s is None:
            return None
        previous = asdict(s)
        candidate = dict(previous)
        candidate.update({k: v for k, v in changes.items() if k in candidate and k != "id"})
        updated = Schedule(**candidate)
        self._items[schedule_id] = updated
        try:
            self.save()
        except Exception:
            self._items[schedule_id] = s
            raise
        return updated

    def remove(self, schedule_id: str) -> bool:
        item = self._items.pop(schedule_id, None)
        if item is None:
            return False
        try:
            self.save()
        except Exception:
            self._items[schedule_id] = item
            raise
        return True

    def toggle_done(self, schedule_id: str) -> bool:
        s = self._items.get(schedule_id)
        if s is None or s.repeat != _REPEAT_NONE:
            return False
        s.done = not s.done
        try:
            self.save()
        except Exception:
            s.done = not s.done
            raise
        return s.done

    # ---- 查询 ----
    def all(self) -> list[Schedule]:
        return sorted(self._items.values(), key=lambda s: (s.date, s.time or "99:99"))

    def on(self, day: date) -> list[Schedule]:
        return [s for s in self.all() if s.occurs_on(day)]

    def markers_between(self, start: date, end: date) -> dict[str, str]:
        """返回 {iso_date: color}，color 为空字符串表示使用默认色。"""
        schedules = self.all()
        markers: dict[str, str] = {}
        day = start
        while day <= end:
            for s in schedules:
                if not s.occurs_on(day):
                    continue
                key = day.isoformat()
                if s.color and not markers.get(key):
                    markers[key] = s.color
                elif key not in markers:
                    markers[key] = ""
            day += timedelta(days=1)
        return markers

    def upcoming(self, days: int = 7, today: date | None = None) -> list[tuple[date, Schedule]]:
        today = today or date.today()
        out: list[tuple[date, Schedule]] = []
        for i in range(days):
            d = today + timedelta(days=i)
            out.extend((d, s) for s in self.on(d))
        return out
