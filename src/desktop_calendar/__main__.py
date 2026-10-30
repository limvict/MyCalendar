# coding: utf-8
"""程序启动入口（composition root）。"""
import getpass
import sys
import os
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from desktop_calendar import wiring
from desktop_calendar.config.manager import get_logger, get_resource_path
from desktop_calendar.contracts.event_bus import event_bus
from desktop_calendar.contracts.events import EventType
from desktop_calendar.ui.main_window import MainWindow

logger = get_logger()

# 单实例名称：加用户标识，避免同机多用户互相干扰。
# Windows 命名管道默认按 session 隔离，但 Unix socket 在 /tmp 是
# 全局的，不加用户标识会导致用户 A 的实例把用户 B 的拉起来。
_SINGLETON_NAME = f"MyCalendarApp-{getpass.getuser()}-singleton-v1"


def _notify_existing_instance() -> bool:
    """尝试通知已有实例。返回 True 表示已有实例存在且通知成功。

    用 QLocalSocket 连接固定的 QLocalServer 名称：连接成功说明
    已有实例在跑，发送 SHOW 命令让它把窗口弹到前台，当前进程退出。
    连接失败（waitForConnected 超时）说明没有实例，返回 False，
    由调用方安装 server。
    """
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
        logger.debug("通知已有实例失败", exc_info=True)
    finally:
        sock.disconnectFromServer()
    return True


def _install_singleton_server() -> "QLocalServer | None":
    """安装本地 server，接受后续实例的 SHOW 命令。

    必须在 QApplication 创建后调用（QLocalServer 依赖 QtCore 事件循环）。
    removeServer 先清理上次崩溃残留的 socket 文件 / 管道名，否则
    listen 会因 "Address already in use" 失败。

    返回 server 对象（调用方需持有引用，否则被 GC 回收导致 server
    关闭），失败返回 None。
    """
    from PyQt6.QtNetwork import QLocalServer
    QLocalServer.removeServer(_SINGLETON_NAME)
    server = QLocalServer()
    if not server.listen(_SINGLETON_NAME):
        logger.warning(
            "单实例 server 监听失败: %s；双开保护未生效",
            server.errorString())
        return None

    def _on_new_connection():
        while (conn := server.nextPendingConnection()) is not None:
            def _on_ready(c=conn):
                try:
                    c.readAll()          # 忽略命令内容
                except Exception:
                    pass
                try:
                    event_bus.publish(EventType.WINDOW_SHOW)
                    logger.info("收到第二实例请求，已弹出主窗口")
                except Exception:
                    logger.exception("响应第二实例请求失败")
            conn.readyRead.connect(_on_ready)
            conn.disconnected.connect(conn.deleteLater)

    server.newConnection.connect(_on_new_connection)
    return server


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 双开检查在 MainWindow 创建之前：第二个实例直接退出，不碰
    # config / 日志文件，避免与第一个实例竞争写盘。
    if _notify_existing_instance():
        logger.info("已有实例运行，已通知其弹出窗口，当前进程退出")
        return 0

    icon_path = get_resource_path("assets/app.ico")
    if not os.path.exists(icon_path):
        logger.warning("应用图标不存在: %s，使用系统默认", icon_path)
    app.setWindowIcon(QIcon(icon_path))

    try:
        w = MainWindow(wiring=wiring)
    except Exception:
        logger.exception("主窗口构造失败")
        # QApplication 已就绪，尽量弹错误框；弹不出来退回 stderr
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
    # 退出时清理 server（进程结束会清理，但显式清理让下次启动
    # 的 removeServer 更干净；异常路径无影响）。
    if singleton_server is not None:
        try:
            singleton_server.close()
        except Exception:
            pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())