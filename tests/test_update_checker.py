# coding: utf-8
"""update_checker：本文件只补充 test_update_manager.py 未覆盖的测试点。

- _is_packaged 的三种判定（frozen / _MEIPASS / nuitka_version）
- 一些额外边界（不重复 test_update_manager.py 已有内容）
"""
import sys

import pytest

from desktop_calendar.infrastructure.network.update_checker import (
    _is_packaged,
)


# ===================== _is_packaged =====================
class TestIsPackaged:
    def test_not_packaged(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.delattr(sys, "nuitka_version", raising=False)
        assert _is_packaged() is False

    def test_pyinstaller_frozen(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.delattr(sys, "nuitka_version", raising=False)
        assert _is_packaged() is True

    def test_pyinstaller_meipass(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI123", raising=False)
        monkeypatch.delattr(sys, "nuitka_version", raising=False)
        assert _is_packaged() is True

    def test_nuitka(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "nuitka_version", "1.0", raising=False)
        assert _is_packaged() is True
