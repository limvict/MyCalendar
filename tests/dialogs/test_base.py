# coding: utf-8
"""RetranslatableDialog 生命周期单测。"""
from PyQt6.QtWidgets import QDialog, QDialogButtonBox

from i18n import (
    _listeners, set_language, off_language_changed,
)
from dialogs.base import (
    RetranslatableDialog,
    make_button_box,
    retranslate_button_box,
)


@pytest.fixture(autouse=True)
def _reset_lang_and_listeners():
    """每个用例前清空监听表，避免跨用例污染。"""
    snapshot = list(_listeners)
    _listeners.clear()
    set_language("zh_CN")
    yield
    for cb in list(_listeners):
        off_language_changed(cb)
    _listeners.extend(snapshot)


class _Dlg(RetranslatableDialog, QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.translate_calls = 0
        self.retranslate_ui()   # 契约要求：构造末尾显式调一次

    def retranslate_ui(self):
        self.translate_calls += 1


def test_init_registers_listener(qtbot):
    dlg = _Dlg()
    assert len(_listeners) == 1
    dlg.done(QDialog.DialogCode.Rejected)
    assert _listeners == []


def test_language_change_triggers_retranslate(qtbot):
    dlg = _Dlg()
    before = dlg.translate_calls
    set_language("en_US")
    assert dlg.translate_calls == before + 1
    set_language("zh_CN")
    assert dlg.translate_calls == before + 2


def test_done_detaches_listener(qtbot):
    dlg = _Dlg()
    assert len(_listeners) == 1
    dlg.done(QDialog.DialogCode.Accepted)
    assert _listeners == []
    # 再次 done 幂等，不报错
    dlg.done(QDialog.DialogCode.Rejected)
    assert _listeners == []


def test_destroyed_fallback_detaches(qtbot):
    """不经过 done，直接 deleteLater → destroyed 兜底卸载。"""
    dlg = _Dlg()
    assert len(_listeners) == 1
    dlg.deleteLater()
    qtbot.wait(20)   # 让事件循环处理 deleteLater
    assert _listeners == []


def test_make_button_box_text_and_wiring(qtbot):
    dlg = _Dlg()
    box = make_button_box(dlg)
    assert isinstance(box, QDialogButtonBox)
    assert box.button(QDialogButtonBox.StandardButton.Ok).text() == "确定"
    assert box.button(QDialogButtonBox.StandardButton.Cancel).text() == "取消"


def test_retranslate_button_box_none_safe():
    # 不应抛 AttributeError
    retranslate_button_box(None)