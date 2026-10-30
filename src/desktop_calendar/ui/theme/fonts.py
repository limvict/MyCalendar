# coding: utf-8
from __future__ import annotations

from PyQt6.QtGui import QFont

from .resolver import ThemeResolver


def _families(r: ThemeResolver) -> list[str]:
    # font_family 是逗号分隔的候选列表，过滤空项，避免 "a, , b"
    # 产生空 family 名。
    return [f.strip() for f in r.str("font_family").split(",") if f.strip()]


def _make(r: ThemeResolver, size_key: str) -> QFont:
    # 用 setFamilies 保留 fallback 链，跨平台缺失首个字体时仍能落到
    # 后续候选，而不是整体退回系统默认（与 QSS 侧 font-family 行为一致）。
    f = QFont()
    families = _families(r)
    if families:
        f.setFamilies(families)
    f.setPointSize(r.int(size_key))
    return f


def global_font(r: ThemeResolver) -> QFont:
    return _make(r, "font_size")


def calendar_day(r: ThemeResolver) -> QFont:
    # 当前与 global_font 同字号，保留独立入口便于后续分化。
    return _make(r, "font_size")


def calendar_small(r: ThemeResolver) -> QFont:
    return _make(r, "small_font_size")