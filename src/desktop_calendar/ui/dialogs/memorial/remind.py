# coding: utf-8
"""纪念日到点提醒弹窗。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import get_logger
from desktop_calendar.ui.theme import ThemeBundle

logger = get_logger()


# ===================== 提醒弹窗 =====================
class MemorialRemindDialog(QDialog):
    def __init__(self, memorial_list, parent=None, bundle: ThemeBundle = None):
        super().__init__(parent)
        if bundle is None:
            raise ValueError("MemorialRemindDialog 需要 ThemeBundle")
        self._bundle = bundle

        dlg = self._bundle.dialog
        r = self._bundle.resolver

        self.setWindowTitle(tr("memorial.remind_title"))
        self.resize(*dlg.remind_size)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet(dlg.qss_remind)

        layout = QVBoxLayout(self)
        mw = dlg.margin_wide
        layout.setContentsMargins(mw, mw - 2, mw, mw - 2)
        layout.setSpacing(dlg.spacing_wide)

        self.title_label = QLabel(tr("memorial.remind_heading"))
        self.title_label.setStyleSheet(
            f"font-size:{dlg.title_font_size}px;font-weight:bold;color:{r.color('dialog_text')};"
        )
        layout.addWidget(self.title_label)

        content_text = "\n".join(f"• {line}" for line in memorial_list)
        orange = r.color("memorial_orange")
        self.content_label = QLabel(content_text)
        # 内容含用户自由输入的纪念日名称，必须禁 HTML 解析：
        # 否则名称里的 <b>/<img> 会被 QLabel 当富文本渲染。
        self.content_label.setTextFormat(Qt.TextFormat.PlainText)
        self.content_label.setStyleSheet(
            f"font-size:{dlg.content_font_size}px;color:{orange};background:transparent;"
        )
        self.content_label.setWordWrap(True)
        layout.addWidget(self.content_label)
        layout.addStretch(1)

        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton(tr("memorial.remind_ok"))
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self.accept)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)
