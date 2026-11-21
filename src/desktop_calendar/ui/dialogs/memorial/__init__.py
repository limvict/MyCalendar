# coding: utf-8
"""纪念日对话框：新增/编辑、列表管理、到点提醒。

三种弹窗拆在独立模块里，本文件只做汇总导出，
`from desktop_calendar.ui.dialogs import MemorialDialog` 保持可用。
"""

from __future__ import annotations

from .add import AddMemorialDialog
from .manage import MemorialDialog
from .remind import MemorialRemindDialog

__all__ = ["AddMemorialDialog", "MemorialDialog", "MemorialRemindDialog"]
