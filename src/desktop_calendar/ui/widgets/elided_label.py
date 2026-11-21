# coding: utf-8
"""按可用宽度省略显示的标签。

用于宽度会被布局压缩、但文字长度不可控的位置（城市名等）：
文字超长时显示省略号，而不是被裁掉或把相邻控件挤变形。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__("", parent)
        self._full_text = ""
        # Ignored：允许布局把宽度压到 sizeHint 以下，由省略号负责表达
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt 接口)
        self._full_text = str(text)
        self._update_elided()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event):  # noqa: N802 (Qt 接口)
        super().resizeEvent(event)
        self._update_elided()

    def changeEvent(self, event):  # noqa: N802 (Qt 接口)
        super().changeEvent(event)
        # 字号 / 字体随主题变化后需要重新计算省略位置
        if event.type() in (event.Type.FontChange, event.Type.StyleChange):
            self._update_elided()

    def _update_elided(self) -> None:
        text = self._full_text
        if not text:
            super().setText("")
            return
        width = max(0, self.contentsRect().width())
        metrics = self.fontMetrics()
        if width <= 0 or metrics.horizontalAdvance(text) <= width:
            super().setText(text)
            return
        super().setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, width))
