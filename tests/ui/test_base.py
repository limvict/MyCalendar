# coding: utf-8
"""RetranslatableDialog 生命周期单测。"""
from PyQt6.QtWidgets import QDialog, QDialogButtonBox
import pytest
from PyQt6.QtCore import QCoreApplication, QEvent
from desktop_calendar.config.i18n import (
    _listeners, set_language, off_language_changed,
)
from desktop_calendar.ui.dialogs.base import (
    RetranslatableDialog,
    make_button_box,
    retranslate_button_box,
)
pytestmark = pytest.mark.ui

@pytest.fixture(autouse=True)
def _reset_lang_and_listeners():
    """每个用例前重置 i18n 全局状态，避免跨用例污染。

    直接赋值 _current_lang / _current_table，不用 set_language：
    后者在 new_lang == _current_lang 时会提前 return，若前序测试
    把语言留在 en_US，本 fixture 的 set_language("zh_CN") 反而
    救不回来，导致后续 set_language("en_US") 也被跳过、监听者
    不被通知。
    """
    from desktop_calendar.config import i18n
    from desktop_calendar.config.translations import ZH_CN

    snapshot = list(_listeners)
    _listeners.clear()
    i18n._current_lang = "zh_CN"
    i18n._current_table = ZH_CN
    yield
    for cb in list(_listeners):
        off_language_changed(cb)
    _listeners.extend(snapshot)
    i18n._current_lang = "zh_CN"
    i18n._current_table = ZH_CN


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
    from desktop_calendar.config import i18n
    dlg = _Dlg()
    before = dlg.translate_calls
    cb = i18n._listeners[0]
    print("\n[diag] before =", before,
          "cb =", cb,
          "cb.__self__ is dlg =", cb.__self__ is dlg,
          "dlg.translate_calls =", dlg.translate_calls)
    # 手动调一次，绕过 set_language
    try:
        cb("en_US")
        print("[diag] manual cb -> translate_calls =", dlg.translate_calls)
    except Exception:
        import traceback; traceback.print_exc()
    # 重置计数，再走真实 set_language
    dlg.translate_calls = 0
    before = 0 
    print("[diag] before set_language: _current_lang =", i18n._current_lang,
          "listeners =", len(i18n._listeners))
    set_language("en_US")
    print("[diag] after set_language: _current_lang =", i18n._current_lang,
          "translate_calls =", dlg.translate_calls)
    assert dlg.translate_calls == 1
    assert dlg.translate_calls == before + 1


def test_done_detaches_listener(qtbot):
    set_language("zh_CN")
    dlg = _Dlg()
    before = dlg.translate_calls
    set_language("en_US")
    assert dlg.translate_calls == before + 1
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
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
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