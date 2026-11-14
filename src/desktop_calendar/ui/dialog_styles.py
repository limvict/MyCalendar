# coding: utf-8
"""消息框样式兜底构造器：无 ThemeBundle 时用 DEFAULT_THEME 编译 QSS。"""
from __future__ import annotations
from typing import Literal

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.ui.theme.qss import message_box
from desktop_calendar.ui.theme.resolver import ThemeResolver

MessageKind = Literal["info", "warn", "error"]


def build_message_box(theme: dict, kind: MessageKind) -> str:
    # ThemeResolver 内部对缺失 key 逐个回退 DEFAULT_THEME，
    # theme 为空 / 部分字段缺失都能得到合法 QSS。
    return message_box(ThemeResolver(theme or DEFAULT_THEME), kind)