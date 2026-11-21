from PyQt6.QtCore import Qt

from desktop_calendar import __main__ as app_main


def test_main_enables_shared_opengl_contexts_before_qapplication(monkeypatch):
    calls = []

    class FakeApplication:
        @staticmethod
        def setAttribute(attribute):
            calls.append(("attribute", attribute))

        def __init__(self, _argv):
            calls.append(("application", None))

        def setQuitOnLastWindowClosed(self, _enabled):
            pass

    monkeypatch.setattr(app_main, "QApplication", FakeApplication)
    monkeypatch.setattr(
        app_main.QGuiApplication, "setHighDpiScaleFactorRoundingPolicy", lambda _policy: None
    )
    monkeypatch.setattr(app_main, "_notify_existing_instance", lambda: True)

    assert app_main.main([]) == 0
    assert calls == [
        ("attribute", Qt.ApplicationAttribute.AA_ShareOpenGLContexts),
        ("application", None),
    ]
