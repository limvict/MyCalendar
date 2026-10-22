# coding: utf-8
"""对话框公共基础设施。

- RetranslatableDialog：i18n 语言切换 mixin，自动挂载 / 卸载监听。
- make_button_box / retranslate_button_box：QDialogButtonBox 的
  创建与重翻译工具。

依赖方向：本模块只依赖 PyQt6 + i18n + config，不依赖任何具体
对话框。这样 memorial / settings / picker 等子模块才能安全 import
本模块而不引入循环依赖。
"""
from typing import Callable, Optional
from functools import partial

from PyQt6.QtWidgets import QDialog, QDialogButtonBox

from desktop_calendar.config.manager import get_logger
from desktop_calendar.config.i18n import (
    tr, on_language_changed, off_language_changed,
)

logger = get_logger()

__all__ = [
    "RetranslatableDialog",
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


# ===================== 语言联动 Mixin =====================
class RetranslatableDialog:
    _retranslate_cb: Optional[Callable[[str], None]] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cb = self._on_language_changed
        self._retranslate_cb = cb
        # destroyed 触发时 C++ 对象已被删除，访问 self 会抛 RuntimeError。
        # 用 partial 直接绑 off_language_changed，完全不经过 self。
        self.destroyed.connect(partial(off_language_changed, cb))
        on_language_changed(cb)

    def _on_language_changed(self, _lang: str = "") -> None:
        """适配 i18n.set_language 的 Callable[[str], None] 约定。"""
        self.retranslate_ui()

    def _detach_language_listener(self, _obj=None):
        """done() 路径用。destroyed 路径由 partial 直接处理，不走这里。"""
        cb = getattr(self, "_retranslate_cb", None)
        if cb is None:
            return
        off_language_changed(cb)
        self._retranslate_cb = None

    def done(self, r):
        self._detach_language_listener()
        super().done(r)

    def retranslate_ui(self):
        raise NotImplementedError(
            f"{type(self).__name__} 必须实现 retranslate_ui()")