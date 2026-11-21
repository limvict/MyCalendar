from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...config.i18n import tr
from ...core.pomodoro import PomodoroTimer


class _Ring(QWidget):  # 环形进度
    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress = 0.0

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        p.setPen(QPen(QColor("#E0E0E0"), 10))
        p.drawArc(rect, 0, 360 * 16)
        p.setPen(QPen(QColor("#E8564B"), 10))
        p.drawArc(rect, 90 * 16, int(-360 * 16 * self.progress))


class PomodoroDialog(QDialog):
    def __init__(self, timer: PomodoroTimer, parent=None, focus_log=None):
        super().__init__(parent)
        self._t = timer
        self._focus_log = focus_log
        self.setWindowTitle(self.tr("专注计时"))
        self.resize(320, 420)
        self._ring = _Ring()
        self._lbl_time = QLabel("25:00", alignment=Qt.AlignmentFlag.AlignCenter)
        self._lbl_time.setStyleSheet("font-size:44px;font-weight:600;")
        self._lbl_phase = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self._btn_start = QPushButton(self.tr("开始"))
        self._btn_reset = QPushButton(self.tr("重置"))
        self._btn_skip = QPushButton(self.tr("跳过"))

        lay = QVBoxLayout(self)
        lay.addWidget(self._ring)
        lay.addWidget(self._lbl_time)
        lay.addWidget(self._lbl_phase)
        self._lbl_stats = QLabel("", alignment=Qt.AlignmentFlag.AlignCenter)
        self._lbl_stats.setStyleSheet("color:#888;font-size:12px;")
        lay.addWidget(self._lbl_stats)
        row = QHBoxLayout()
        [row.addWidget(b) for b in (self._btn_start, self._btn_skip, self._btn_reset)]
        lay.addLayout(row)

        self._btn_start.clicked.connect(self._toggle)
        self._btn_reset.clicked.connect(self._reset)
        self._btn_skip.clicked.connect(timer.skip)
        timer.tick.connect(self._on_tick)
        timer.phase_changed.connect(self._on_phase)
        timer.paused_changed.connect(self._on_paused_changed)
        timer.work_completed.connect(lambda *_args: self._refresh_stats())
        self._on_phase(timer.phase.value)
        self._on_tick(timer.remaining, timer.phase.value)
        self._refresh_stats()

    def _refresh_stats(self):
        if self._focus_log is None:
            self._lbl_stats.hide()
            return
        self._lbl_stats.show()
        count = self._focus_log.today_count()
        minutes = self._focus_log.today_minutes()
        if count:
            duration = f"{minutes // 60}h{minutes % 60:02d}m"
            self._lbl_stats.setText(tr("focus.today_stats", n=count, hm=duration))
        else:
            self._lbl_stats.setText(tr("focus.empty"))

    def _toggle(self):
        if self._t.paused or self._t.phase.value == "idle":
            self._t.start()
            self._btn_start.setText(self.tr("暂停"))
        else:
            self._t.pause()
            self._btn_start.setText(self.tr("继续"))

    def _on_tick(self, sec, phase):
        self._lbl_time.setText(f"{sec // 60:02d}:{sec % 60:02d}")
        total = self._t.duration_seconds(phase)
        self._ring.progress = 1 - sec / total if total else 0
        self._ring.update()

    def _on_phase(self, phase):
        self._lbl_phase.setText(
            {"idle": "待开始", "work": "专注中", "short_break": "小憩", "long_break": "长休息"}.get(
                phase, ""
            )
        )

    def _on_paused_changed(self, paused: bool):
        self._btn_start.setText(self.tr("继续") if paused else self.tr("暂停"))

    def _reset(self):
        self._t.reset()
        self._btn_start.setText(self.tr("开始"))
