# coding: utf-8
"""主窗口包：对外只暴露 `MainWindow`。

拆分前 `ui.main_window` 是单文件模块，外部（`__main__`、测试）只用到
`MainWindow` 和两个模块级辅助（`_SIDEBAR_WIDTH` / `_screen_ui_scale`），
这里保持同样的导入路径，避免调用方跟着改动。
"""

from __future__ import annotations

from .helpers import _SIDEBAR_WIDTH, _screen_ui_scale
from .window import MainWindow

__all__ = ["MainWindow", "_SIDEBAR_WIDTH", "_screen_ui_scale"]
