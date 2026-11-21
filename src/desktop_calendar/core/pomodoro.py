"""番茄钟状态机：纯 QObject，界面无关。"""

from __future__ import annotations

from enum import StrEnum

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..config.constants import (
    POMODORO_LONG_BREAK_MINUTES_DEFAULT,
    POMODORO_ROUNDS_BEFORE_LONG_DEFAULT,
    POMODORO_SHORT_BREAK_MINUTES_DEFAULT,
    POMODORO_WORK_MINUTES_DEFAULT,
)


class Phase(StrEnum):
    IDLE = "idle"
    WORK = "work"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class PomodoroTimer(QObject):
    tick = pyqtSignal(int, str)  # (剩余秒数, phase.value)
    phase_changed = pyqtSignal(str)  # 新阶段
    paused_changed = pyqtSignal(bool)
    round_finished = pyqtSignal(int)  # 完成的第 N 个番茄
    work_completed = pyqtSignal(int, int)  # 完成轮次与专注秒数

    def __init__(
        self,
        work_min: int = POMODORO_WORK_MINUTES_DEFAULT,
        short_min: int = POMODORO_SHORT_BREAK_MINUTES_DEFAULT,
        long_min: int = POMODORO_LONG_BREAK_MINUTES_DEFAULT,
        rounds_before_long: int = POMODORO_ROUNDS_BEFORE_LONG_DEFAULT,
        parent=None,
    ):
        super().__init__(parent)
        values = (work_min, short_min, long_min, rounds_before_long)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in values
        ):
            raise ValueError("番茄钟时长和长休息轮数必须为正整数")
        self._cfg = {
            "work": work_min * 60,
            "short": short_min * 60,
            "long": long_min * 60,
            "rounds": rounds_before_long,
        }
        self._phase = Phase.IDLE
        self._remaining = 0
        self._round = 0
        self._paused = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

    # ---- 查询 ----
    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def remaining(self) -> int:
        return self._remaining

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def round_index(self) -> int:
        return self._round

    def duration_seconds(self, phase: Phase | str) -> int:
        value = phase.value if isinstance(phase, Phase) else phase
        return {
            "work": self._cfg["work"],
            "short_break": self._cfg["short"],
            "long_break": self._cfg["long"],
        }.get(value, 0)

    # ---- 控制 ----
    def start(self) -> None:
        if self._phase == Phase.IDLE:
            self._enter(Phase.WORK)
        self._paused = False
        self.paused_changed.emit(False)
        self._timer.start()

    def pause(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._paused = True
            self.paused_changed.emit(True)

    def reset(self) -> None:
        self._timer.stop()
        self._phase = Phase.IDLE
        self._remaining = 0
        self._round = 0
        self._paused = False
        self.phase_changed.emit(self._phase.value)
        self.paused_changed.emit(False)
        self.tick.emit(0, self._phase.value)

    def skip(self) -> None:  # 跳过当前阶段
        if self._phase == Phase.IDLE:
            return
        self._advance(natural=False)

    def stop(self) -> None:
        self._timer.stop()

    # ---- 内部 ----
    def _enter(self, phase: Phase) -> None:
        self._phase = phase
        self._remaining = {
            "work": self._cfg["work"],
            "short_break": self._cfg["short"],
            "long_break": self._cfg["long"],
        }.get(phase.value, 0)
        self.phase_changed.emit(phase.value)
        self.tick.emit(self._remaining, phase.value)

    def _on_tick(self) -> None:
        self._remaining -= 1
        self.tick.emit(max(self._remaining, 0), self._phase.value)
        if self._remaining <= 0:
            self._advance(natural=True)

    def _advance(self, *, natural: bool = True) -> None:
        self._timer.stop()
        if self._phase == Phase.WORK:
            self._round += 1
            self.round_finished.emit(self._round)
            if natural:
                self.work_completed.emit(self._round, self._cfg["work"])
            nxt = Phase.LONG_BREAK if self._round % self._cfg["rounds"] == 0 else Phase.SHORT_BREAK
        else:
            nxt = Phase.WORK
        self._enter(nxt)
        self._timer.start()  # 自动进入下一阶段；想手动则去掉这行
