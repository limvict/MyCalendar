# coding: utf-8
"""程序启动入口（composition root）。"""
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from desktop_calendar.bootstrap import wiring
from desktop_calendar.config.config import get_resource_path
from desktop_calendar.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(get_resource_path("assets/app.ico")))

    w = MainWindow(wiring=wiring)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())