# coding: utf-8
"""对话框公共基础设施：QDialogButtonBox 的创建与重翻译工具。

依赖方向：本模块只依赖 PyQt6 + i18n，不依赖任何具体对话框。
这样 memorial / settings / picker 等子模块才能安全 import 本模块
而不引入循环依赖。
"""
from typing import Callable, Optional
from PyQt6.QtWidgets import QDialog, QDialogButtonBox

from desktop_calendar.config.i18n import tr

__all__ = [
    "make_button_box",
    "retranslate_button_box",
]


# ===================== 按钮盒工具 =====================
def make_button_box(
    dialog: QDialog, on_accept: Optional[Callable[[], None]] = None
) -> QDialogButtonBox:
    """创建带确定/取消的 QDialogButtonBox，统一处理三件事：

      - 中文化按钮文字；
      - accepted 连到 on_accept（默认 dialog.accept）；
      - rejected 连到 dialog.reject。
    """
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok
        | QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Ok).setText(tr("btn.ok"))
    box.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("btn.cancel"))
    box.accepted.connect(on_accept if on_accept is not None else dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def retranslate_button_box(box: Optional[QDialogButtonBox]) -> None:
    """刷新 QDialogButtonBox 标准按钮文本。box 为 None 时静默返回。"""
    if box is None:
        return
    ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
    if ok_btn is not None:
        ok_btn.setText(tr("btn.ok"))
    cancel_btn = box.button(QDialogButtonBox.StandardButton.Cancel)
    if cancel_btn is not None:
        cancel_btn.setText(tr("btn.cancel"))