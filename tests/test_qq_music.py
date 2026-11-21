from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWidgets import QWidget

from desktop_calendar.ui.dialogs import qq_music
from desktop_calendar.ui.main_window import MainWindow


def test_qq_music_dialog_loads_site_and_reports_load_failure(qapp, monkeypatch):
    loaded_urls = []

    class FakeWebView(QWidget):
        loadStarted = pyqtSignal()
        loadFinished = pyqtSignal(bool)

        def load(self, url):
            loaded_urls.append(url.toString())

        def back(self):
            pass

        def forward(self):
            pass

        def reload(self):
            pass

        def url(self):
            return QUrl()

    monkeypatch.setattr(qq_music.QQMusicDialog, "_create_web_view", lambda self: FakeWebView(self))
    opened_urls = []
    monkeypatch.setattr(
        qq_music.QDesktopServices, "openUrl", lambda url: opened_urls.append(url.toString()) or True
    )

    dialog = qq_music.QQMusicDialog()
    try:
        assert loaded_urls == [qq_music.QQ_MUSIC_URL]
        dialog.web_view.loadFinished.emit(False)
        assert "加载失败" in dialog.status_label.text()
        dialog.external_button.click()
        assert opened_urls == [qq_music.QQ_MUSIC_URL]
    finally:
        dialog.deleteLater()


def test_main_window_reuses_qq_music_dialog(monkeypatch):
    instances = []

    class FakeDialog:
        def __init__(self, parent):
            self.parent = parent
            self.show_count = 0
            self.raise_count = 0
            self.activate_count = 0
            instances.append(self)

        def show(self):
            self.show_count += 1

        def raise_(self):
            self.raise_count += 1

        def activateWindow(self):
            self.activate_count += 1

    monkeypatch.setattr(qq_music, "QQMusicDialog", FakeDialog)
    window = type("Window", (), {})()

    MainWindow._open_qq_music(window)
    MainWindow._open_qq_music(window)

    assert len(instances) == 1
    assert instances[0].parent is window
    assert instances[0].show_count == 2
    assert instances[0].raise_count == 2
    assert instances[0].activate_count == 2
