# coding: utf-8
"""
程序启动入口。

职责：
  - 装配 QApplication（图标、退出策略）
  - 创建并显示 MainWindow
  - 进入事件循环
"""
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from desktop_calendar.config.config import get_resource_path
from desktop_calendar.ui.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    """启动应用，返回退出码。"""
    app = QApplication(argv if argv is not None else sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(get_resource_path("assets/app.ico")))

    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())