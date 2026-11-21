"""Embedded QQ Music web player."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .base import fit_dialog_to_screen

QQ_MUSIC_URL = "https://y.qq.com/"


class QQMusicDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QQ 音乐")

        self.web_view = self._create_web_view()
        self.status_label = QLabel("正在加载 QQ 音乐…", self)
        self.status_label.setWordWrap(True)

        toolbar = QHBoxLayout()
        self.back_button = QPushButton("后退", self)
        self.forward_button = QPushButton("前进", self)
        self.reload_button = QPushButton("刷新", self)
        self.external_button = QPushButton("在浏览器打开", self)
        toolbar.addWidget(self.back_button)
        toolbar.addWidget(self.forward_button)
        toolbar.addWidget(self.reload_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.status_label, stretch=1)
        toolbar.addWidget(self.external_button)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.web_view, stretch=1)

        self.back_button.clicked.connect(self.web_view.back)
        self.forward_button.clicked.connect(self.web_view.forward)
        self.reload_button.clicked.connect(self.web_view.reload)
        self.external_button.clicked.connect(self._open_in_browser)
        self.web_view.loadStarted.connect(lambda: self.status_label.setText("正在加载 QQ 音乐…"))
        self.web_view.loadFinished.connect(self._on_load_finished)
        self.web_view.load(QUrl(QQ_MUSIC_URL))
        fit_dialog_to_screen(self, (1100, 760), minimum_size=(720, 520))

    def _create_web_view(self):
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        return QWebEngineView(self)

    def _on_load_finished(self, succeeded: bool) -> None:
        self.status_label.setText(
            "" if succeeded else "页面加载失败，请检查网络后重试，或在浏览器中打开。"
        )

    def _open_in_browser(self) -> None:
        url = self.web_view.url()
        if not url.isValid() or url.isEmpty():
            url = QUrl(QQ_MUSIC_URL)
        if not QDesktopServices.openUrl(url):
            self.status_label.setText("无法打开浏览器，请检查系统默认浏览器设置。")
