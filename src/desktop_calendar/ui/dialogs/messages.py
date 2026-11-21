# coding: utf-8
"""通用消息弹窗。

标题与正文由调用方通过 tr() 计算好后传入，本模块只负责样式统一
与图标区分。

样式来源：
- 优先从 MainWindow 注入的 ThemeBundle 取预编译 QSS
  （bundle.qss.message_info / message_warn / message_error）；
- 拿不到时回退 DEFAULT_THEME 的现场编译，保证测试 / 窗口销毁场景不崩。
"""

from collections.abc import Callable
from typing import Literal

from PyQt6.QtWidgets import QMessageBox

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.config.manager import get_logger
from desktop_calendar.ui.dialog_styles import build_message_box, build_message_icon

logger = get_logger()

MessageKind = Literal["info", "warn", "error"]

# 由 MainWindow 在 __init__ 注入：返回当前 ThemeBundle 的无参 callable。
# 保持 msg_info/msg_warn/msg_error 签名不变，避免 5+ 个调用点逐一改。
_bundle_provider: Callable[[], object] | None = None


def set_bundle_provider(provider: Callable[[], object] | None) -> None:
    """注入 / 清除当前 ThemeBundle 提供者。

    传入 None 表示清除（例如测试 teardown）。MainWindow 只需调用一次，
    provider 内部读 theme_mgr.current，主题切换天然生效。
    """
    global _bundle_provider
    _bundle_provider = provider


def _current_qss(kind: MessageKind) -> str:
    if _bundle_provider is not None:
        try:
            bundle = _bundle_provider()
            if bundle is not None:
                qss = getattr(bundle.qss, f"message_{kind}", None)
                if qss:
                    return qss
        except Exception:
            logger.debug("获取消息框 QSS 失败，回退 DEFAULT_THEME", exc_info=True)
    return build_message_box(DEFAULT_THEME, kind)


def _current_theme_and_scale() -> tuple[dict, float]:
    """取当前主题与缩放；拿不到就退回 DEFAULT_THEME / 1.0。"""
    if _bundle_provider is not None:
        try:
            bundle = _bundle_provider()
            if bundle is not None:
                return dict(getattr(bundle, "theme", {}) or {}), float(
                    getattr(bundle, "scale_factor", 1.0) or 1.0
                )
        except Exception:
            logger.debug("获取消息框主题失败，回退 DEFAULT_THEME", exc_info=True)
    return DEFAULT_THEME, 1.0


def _current_icon(kind: MessageKind):
    theme, scale = _current_theme_and_scale()
    return build_message_icon(theme, kind, size=round(32 * scale))


class _BaseMsgBox(QMessageBox):
    def __init__(self, parent, title, text, icon, kind: MessageKind):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setText(text)
        # 原生图标由 QStyle 绘制，和主题对不上，换成主题色绘制的图标
        self.setIcon(icon)
        try:
            self.setIconPixmap(_current_icon(kind))
        except Exception:
            logger.debug("消息框主题图标生成失败，保留系统图标", exc_info=True)
        self.setStyleSheet(_current_qss(kind))


def _show_message(parent, title, text, icon, kind: MessageKind) -> None:
    """创建-显示-销毁的完整生命周期。

    deleteLater 在事件循环下一轮删除 C++ 对象：exec 返回后 Qt 需要
    处理 Modal 结束事件，立即 delete 会崩。deleteLater 保证清理，
    且避免"对话框子对象在 parent 下累积"——匿名临时对象
    `_BaseMsgBox(...).exec()` 在 exec 返回后 Python 引用消失，但
    C++ 对象作为 parent 的子对象存活至 parent 销毁，长时间运行的
    主窗口会累积上百个 QMessageBox（每个几百 KB）。
    """
    box = _BaseMsgBox(parent, title, text, icon, kind)
    try:
        box.exec()
    finally:
        box.deleteLater()


def msg_info(parent, title, text):
    _show_message(parent, title, text, QMessageBox.Icon.Information, "info")


def msg_warn(parent, title, text):
    _show_message(parent, title, text, QMessageBox.Icon.Warning, "warn")


def msg_error(parent, title, text):
    _show_message(parent, title, text, QMessageBox.Icon.Critical, "error")


def msg_question(
    parent, title, text, *, yes: str = "确定", no: str = "取消", default_yes: bool = False
) -> bool:
    """主题化的二选一确认框。

    原生 ``QMessageBox.question`` 的按钮是系统样式的 Yes/No，和主题
    以及中文界面都不搭；这里复用消息框的主题 QSS 与自绘图标，并把
    默认按钮放在「取消」上，避免误触确认。
    """
    box = _BaseMsgBox(parent, title, text, QMessageBox.Icon.Warning, "warn")
    yes_button = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    no_button = box.addButton(no, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(yes_button if default_yes else no_button)
    box.setEscapeButton(no_button)
    try:
        box.exec()
    finally:
        box.deleteLater()
    return box.clickedButton() is yes_button
