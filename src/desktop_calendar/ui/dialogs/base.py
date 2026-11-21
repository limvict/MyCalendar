# coding: utf-8
"""对话框公共基础设施：QDialogButtonBox 的创建与重翻译工具。

依赖方向：本模块只依赖 PyQt6 + i18n，不依赖任何具体对话框。
这样 memorial / settings / picker 等子模块才能安全 import 本模块
而不引入循环依赖。
"""

from collections.abc import Callable

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from desktop_calendar.config.i18n import tr

__all__ = [
    "fit_dialog_to_screen",
    "make_button_box",
    "retranslate_button_box",
]


def fit_dialog_to_screen(
    dialog: QDialog,
    preferred_size: tuple[int, int],
    *,
    minimum_size: tuple[int, int] = (1, 1),
    margin: int = 24,
) -> None:
    """Constrain and position a dialog within its parent's screen."""
    parent = dialog.parentWidget()
    owner = parent.window() if parent is not None else None
    screen = None
    if owner is not None:
        handle = owner.windowHandle()
        if handle is not None:
            screen = handle.screen()
        if screen is None:
            screen = QApplication.screenAt(owner.frameGeometry().center())
    screen = screen or QApplication.primaryScreen()
    if screen is None:
        dialog.resize(*preferred_size)
        return

    available = screen.availableGeometry()
    max_width = max(1, available.width() - 2 * margin)
    max_height = max(1, available.height() - 2 * margin)
    min_width = min(max(1, minimum_size[0]), max_width)
    min_height = min(max(1, minimum_size[1]), max_height)
    dialog.setMinimumSize(min_width, min_height)
    dialog.setMaximumSize(max_width, max_height)

    width = max(min_width, min(preferred_size[0], max_width))
    height = max(min_height, min(preferred_size[1], max_height))
    dialog.resize(width, height)

    center = available.center()
    if owner is not None:
        owner_center = owner.frameGeometry().center()
        if available.contains(owner_center):
            center = owner_center
    x = center.x() - width // 2
    y = center.y() - height // 2
    x = max(available.left(), min(x, available.right() - width + 1))
    y = max(available.top(), min(y, available.bottom() - height + 1))
    dialog.move(QPoint(x, y))


# ===================== 按钮盒工具 =====================
def make_button_box(
    dialog: QDialog, on_accept: Callable[[], None] | None = None
) -> QDialogButtonBox:
    """创建带确定/取消的 QDialogButtonBox，统一处理三件事：

    - 中文化按钮文字；
    - accepted 连到 on_accept（默认 dialog.accept）；
    - rejected 连到 dialog.reject。
    """
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    box.button(QDialogButtonBox.StandardButton.Ok).setText(tr("btn.ok"))
    box.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn.cancel"))
    box.accepted.connect(on_accept if on_accept is not None else dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def retranslate_button_box(box: QDialogButtonBox | None) -> None:
    """刷新 QDialogButtonBox 标准按钮文本。box 为 None 时静默返回。"""
    if box is None:
        return
    ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
    if ok_btn is not None:
        ok_btn.setText(tr("btn.ok"))
    cancel_btn = box.button(QDialogButtonBox.StandardButton.Cancel)
    if cancel_btn is not None:
        cancel_btn.setText(tr("btn.cancel"))
