# coding: utf-8
"""程序启动入口（composition root）。"""
from __future__ import annotations

import getpass
import logging
import os
import sys
from typing import TYPE_CHECKING

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME

if TYPE_CHECKING:
    from PyQt6.QtNetwork import QLocalServer

# 模块级只取命名的 logger 对象，不调用 get_logger()：getLogger 不会
# 安装 handler，不碰日志文件。第二实例在双开检查前走到这里也不会
# 打开日志文件。main() 通过双开检查后再调 get_logger() 完成初始化，
# 之后本对象与 get_logger() 返回同一 logger，自动带上 handler。
_logger = logging.getLogger(APP_LOGGER_NAME)

_SINGLETON_NAME = f"MyCalendarApp-{getpass.getuser()}-singleton-v1"


def _notify_existing_instance() -> bool:
    """尝试通知已有实例。返回 True 表示已有实例存在且通知成功。"""
    from PyQt6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(_SINGLETON_NAME)
    if not sock.waitForConnected(300):
        return False
    try:
        sock.write(b"SHOW\n")
        sock.flush()
        sock.waitForBytesWritten(300)
    except Exception:
        # 此时日志可能尚未初始化；无 handler 时这条 debug 静默丢弃，
        # 不会创建日志文件，符合"第二实例不碰日志"的约束。
        _logger.debug("通知已有实例失败", exc_info=True)
    finally:
        sock.disconnectFromServer()
    return True


def _install_singleton_server() -> QLocalServer | None:
    """安装本地 server，接受后续实例的 SHOW 命令。

    调用方必须已通过双开检查并完成日志初始化，本函数会写日志。
    """
    from PyQt6.QtNetwork import QLocalServer
    from desktop_calendar.contracts.event_bus import event_bus, EventType

    QLocalServer.removeServer(_SINGLETON_NAME)
    server = QLocalServer()
    if not server.listen(_SINGLETON_NAME):
        _logger.warning("单实例 server 监听失败: %s；双开保护未生效",
                        server.errorString())
        return None

    def _on_new_connection():
        while (conn := server.nextPendingConnection()) is not None:
            def _on_ready(c=conn):
                # readyRead 在数据分片到达时会多次触发；第二实例只发
                # 一次 SHOW，这里去重，避免重复 publish 导致多次弹窗。
                if getattr(c, "_handled", False):
                    return
                c._handled = True
                try:
                    c.readAll()          # 忽略命令内容
                except Exception:
                    pass
                try:
                    event_bus.publish(EventType.WINDOW_SHOW)
                    _logger.info("收到第二实例请求，已弹出主窗口")
                except Exception:
                    _logger.exception("响应第二实例请求失败")
            conn.readyRead.connect(_on_ready)
            conn.disconnected.connect(conn.deleteLater)

    server.newConnection.connect(_on_new_connection)
    return server


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 双开检查必须在 get_logger() 之前：第二个实例此时尚未打开日志
    # 文件，直接退出，不与第一个实例竞争写盘 / 轮转。
    if _notify_existing_instance():
        # 日志未初始化，用 stderr 输出，确保不碰日志文件。
        print("已有实例运行，已通知其弹出窗口，当前进程退出", file=sys.stderr)
        return 0

    # 双开检查已通过，此处才触发 config / ui 的模块级副作用
    # （包括它们可能调用的 get_logger()）。第二实例走不到这里。
    from desktop_calendar.config.manager import get_logger, get_resource_path
    from desktop_calendar.contracts.event_bus import event_bus
    from desktop_calendar.ui.main_window import MainWindow

    logger = get_logger()

    # 显式构造 EventBus，确保线程亲和性绑在主线程。
    # 必须在 MainWindow 之前：MainWindow.__init__ 会 subscribe。
    event_bus.init()

    icon_path = get_resource_path("assets/app.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        # QIcon(不存在的路径) 得到空图标，setWindowIcon 并不会回退到
        # 系统默认；直接跳过设置，让窗口沿用系统默认图标。
        logger.warning("应用图标不存在: %s，使用系统默认", icon_path)

    try:
        w = MainWindow()
    except Exception:
        logger.exception("主窗口构造失败")
        try:
            QMessageBox.critical(
                None, "启动失败",
                "程序启动失败，请查看日志文件。\n"
                f"{sys.exc_info()[1]}")
        except Exception:
            pass
        return 1

    # server 必须持有强引用：局部变量被 GC 会关闭 server，
    # 后续实例的 connectToServer 会失败（双开保护失效）。
    singleton_server = _install_singleton_server()

    w.show()
    rc = app.exec()
    if singleton_server is not None:
        try:
            singleton_server.close()
        except Exception:
            pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())