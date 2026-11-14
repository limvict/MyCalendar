# coding: utf-8
"""上下班打卡提醒：工作日固定时间提醒未打卡的用户。

与 ReminderManager（纪念日）独立：触发源、去重键、配置段都不同，
合并会让两边逻辑互相牵连。本类只负责"该提醒了"的判断，展示
交给主窗口（托盘气泡 / tooltip），避免 core 层依赖任何 Widget。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Dict, Optional, Tuple

from PyQt6.QtCore import QObject, QTimer

from desktop_calendar.config.manager import ConfigManager, get_logger, to_bool
from desktop_calendar.contracts.event_bus import EventType, event_bus
from desktop_calendar.core import lunar as lunar_mod
from desktop_calendar.core.attendance import (
    AttendanceStore, STANDARD_START, STANDARD_END, WorkRule,
    PUNCH_IN_DEADLINE_HOUR,
)

logger = get_logger()

__all__ = ["AttendanceReminderManager"]

# 提醒点过后最多补提醒多久：程序下午才启动时，"该打上班卡了"已无意义。
_REMIND_WINDOW = timedelta(hours=4)
# 向前搜索未来提醒点的最大天数：覆盖国庆 7 天假 + 周末。
_LOOKAHEAD_DAYS = 15
# 单次 timer 上限 24h：长假期间下一个提醒点可能隔数天，分段等待，
# 避免设置超长 interval 后系统休眠唤醒导致的计时偏差累积。
_MAX_TIMER_MS = 24 * 60 * 60 * 1000
# 提前触发的容差：timer 因 _MAX_TIMER_MS 截断后可能早于目标时刻，
# 此时重排而非提醒。2s 容差避免毫秒级误差导致死循环。
_EARLY_TOLERANCE = timedelta(seconds=2)

_KIND_START = "start"
_KIND_END = "end"


def _is_workday(d: date) -> bool:
    try:
        return bool(lunar_mod.is_workday(d))
    except Exception:
        return d.weekday() < 5


class AttendanceReminderManager(QObject):
    """工作日上下班打卡提醒。

    去重：内存记录 (date, kind)，程序重启后当天若仍满足条件会再提醒
    一次——这是有意为之（用户重启后大概率还没打卡）。若已打卡，
    _should_remind 会拦下。
    """

    def __init__(self, parent, config: ConfigManager,
                 store: AttendanceStore, sound_manager=None):
        super().__init__(parent)
        self._config = config
        self._store = store
        self.sound_mgr = sound_manager
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_trigger)
        self._pending_kind: Optional[str] = None
        self._pending_when: Optional[datetime] = None
        # 逻辑目标日期，与 when 分开保存。补提醒的 when（now+1s）在
        # 23:59:59.x 可能跨天，但打卡判断 / 去重键必须用原目标日 d，
        # 否则会用错误日期的打卡记录判断，且污染次日的去重键。
        self._pending_date: Optional[date] = None
        self._reminded: Dict[Tuple[str, str], bool] = {}
        self._shutting_down = False
        self._rule = WorkRule.from_config(self._config)

    # ---------- 配置 ----------
    def _enabled(self) -> bool:
        return to_bool(
            self._config.get_nested(
                "attendance_cfg", "enable_remind", default=True),
            default=True)

    def _sound_enabled(self) -> bool:
        # 复用纪念日提醒的声音开关：语义都是"提醒时播放提示音"，
        # 避免设置界面出现两个几乎相同的复选框。
        return to_bool(
            self._config.get_nested(
                "memorial_cfg", "sound_enable", default=True),
            default=True)

    # ---------- 调度 ----------
    def reschedule(self) -> None:
        """重算下一个提醒点。打卡、设置变更、启动时调用。"""
        if self._shutting_down:
            return
        # 每次重排重读规则：用户在设置里改了作息时间后，
        # 下一次 reschedule 自动生效，无需额外信号机制。
        self._rule = WorkRule.from_config(self._config)
        self._timer.stop()
        self._pending_kind = None
        self._pending_when = None
        self._pending_date = None
        if not self._enabled():
            return
        self._prune_reminded()
        nxt = self._next_trigger()
        if nxt is None:
            return
        when, kind, target_date = nxt
        self._pending_kind = kind
        self._pending_when = when
        self._pending_date = target_date
        delay_ms = int((when - datetime.now()).total_seconds() * 1000)
        delay_ms = max(0, min(delay_ms, _MAX_TIMER_MS))
        self._timer.start(delay_ms)

    def _prune_reminded(self) -> None:
        """清理非今天的去重键，防止长期运行内存缓慢累积。

        原实现只增不减。虽然每天最多 2 条，但进程数月不退出时累积
        量不可忽略；且 _reminded 的语义只是"今天是否已提醒过"，
        历史键无任何用处。已提醒项必然是今天或过去（未来键只可能
        来自系统时间跳变），保留今天即可。
        """
        today_key = datetime.now().date().isoformat()
        stale = [k for k in self._reminded if k[0] != today_key]
        for k in stale:
            self._reminded.pop(k, None)

    def _next_trigger(self) -> Optional[Tuple[datetime, str, date]]:
        """返回 (触发时刻, 提醒类型, 逻辑目标日期)。

        目标日期与触发时刻分开返回：补提醒时触发时刻是 now+1s，
        在 23:59:59.x 会跨天，但打卡判断必须用原目标日 d。调用方
        将 d 存入 _pending_date，_on_trigger 据此判断，不受跨天影响。
        """
        now = datetime.now()
        today = now.date()
        for offset in range(_LOOKAHEAD_DAYS):
            d = today + timedelta(days=offset)
            if not _is_workday(d):
                continue
            for kind, target in (
                (_KIND_START, self._target_dt(d, self._rule.start)),
                (_KIND_END, self._target_dt(d, self._rule.end)),
            ):
                if (d.isoformat(), kind) in self._reminded:
                    continue
                if target > now:
                    # 未来提醒点：定时到点再判断，打卡后触发时会跳过
                    return target, kind, d
                # 已过提醒点：仅在补提醒窗口内、且仍需要提醒时才补
                if now - target > _REMIND_WINDOW:
                    continue
                if not self._should_remind(kind, d):
                    continue
                return now + timedelta(seconds=1), kind, d
        return None

    @staticmethod
    def _target_dt(d: date, minutes_from_midnight: int) -> datetime:
        h, m = divmod(int(minutes_from_midnight), 60)
        return datetime.combine(d, time(h, m))

    def _should_remind(self, kind: str, d: date) -> bool:
        rec = self._store.get_record(d)
        if kind == _KIND_START:
            if rec.get("in"):
                return False
            # 11:00 后不再补提醒上班打卡：此时用户已无法打卡
            # （main_window 禁用 + _do_punch 拒绝），提醒只会造成"点了没反应"。
            # 用 d == today 限定：_next_trigger 只在今天/未来日循环，
            # 补提醒分支的 d 必为今天，此判断仅防御性明确语义。
            if (d == date.today()
                    and datetime.now().hour >= PUNCH_IN_DEADLINE_HOUR):
                return False
            return True
        if kind == _KIND_END:
            return not rec.get("out")
        return False

    # ---------- 触发 ----------
    def _on_trigger(self) -> None:
        now = datetime.now()
        kind = self._pending_kind
        when = self._pending_when
        target_date = self._pending_date
        self._pending_kind = None
        self._pending_when = None
        self._pending_date = None
        if self._shutting_down or not kind or when is None \
                or target_date is None:
            return
        # timer 因 _MAX_TIMER_MS 截断提前触发：还没到提醒点，重排等待。
        if now + _EARLY_TOLERANCE < when:
            self.reschedule()
            return
        # 过期放弃：timer 因系统休眠 / 时间跳变延迟超过补提醒窗口时，
        # 该提醒已无意义（如 17:00 的下班提醒拖到次日才触发）。
        # 原实现缺此分支会用"今天的打卡记录"判断"昨天的提醒"，既可能
        # 错弹，也可能把 _reminded 写到错误日期、吞掉当天真正的提醒。
        if now - when > _REMIND_WINDOW:
            self.reschedule()
            return
        try:
            if not self._should_remind(kind, target_date):
                return
            self._reminded[(target_date.isoformat(), kind)] = True
            if self._sound_enabled() and self.sound_mgr is not None:
                try:
                    self.sound_mgr.play("assets/alert.wav")
                except Exception:
                    logger.debug("考勤提醒播放提示音失败", exc_info=True)
            event_bus.publish(
                EventType.ATTENDANCE_REMIND_TRIGGERED,
                kind=kind, date=target_date.isoformat())
        except Exception:
            logger.exception("[考勤提醒] 触发异常")
        finally:
            self.reschedule()

    def notify_punched(self, action: str) -> None:
        """主窗口打卡后调用：重排以跳过已完成的提醒。

        例如 08:00 上班提醒触发后用户打卡，下一次 reschedule 会
        直接定到 17:00 下班提醒。
        """
        self.reschedule()

    def shutdown(self) -> None:
        self._shutting_down = True
        self._timer.stop()
        self._pending_kind = None
        self._pending_when = None
        self._pending_date = None
        self._reminded.clear()