# coding: utf-8
"""AddMemorialDialog 的 get_data / _on_accept 契约测试。"""
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QMessageBox

from dialogs import AddMemorialDialog
from memorial import REPEAT_WEEK, REPEAT_YEAR

# ---------- helpers ----------

def _select_repeat(dlg, repeat_type):
    """选中 combo_repeat 中 data == repeat_type 的项。

    已选中时不重复 setCurrentIndex：语义更清晰，也避免无谓信号。
    """
    idx = dlg.combo_repeat.findData(repeat_type)
    assert idx >= 0, f"combo_repeat 里找不到 {repeat_type!r}"
    if dlg.combo_repeat.currentIndex() != idx:
        dlg.combo_repeat.setCurrentIndex(idx)


@pytest.fixture
def dlg(qapp):
    """每个用例独立的 AddMemorialDialog。"""
    d = AddMemorialDialog()
    yield d
    d.close()

# ---------- 周模式强制公历 ----------

def test_add_memorial_week_forces_solar(dlg):
    """UI 层路径：切到 WEEK 会立刻强制 radio_solar 勾选。"""
    dlg.radio_lunar.setChecked(True)
    _select_repeat(dlg, REPEAT_WEEK)
    dlg.spin_day.setValue(3)

    data = dlg.get_data()

    assert data["type"] == "solar"
    assert data["repeat_type"] == REPEAT_WEEK
    assert data["day"] == 3


def test_get_data_week_forces_solar_even_if_internal_state_is_dirty(dlg):
    """get_data() 的兜底：绕开 UI 层强制后仍应归一为 solar。

    UI 层路径（上一条）会被 _update_day_range 强制纠正，堵不住
    "get_data() 里的兜底被挪走 / 删掉"的洞。这里用 blockSignals
    绕开信号，构造"radio 说 lunar、combo 说 WEEK"的脏状态。

    真实 UI 到不了该状态，但导入配置 / 程序化编辑可能进入，
    届时 get_data() 必须归一，否则会带 type=lunar 落盘。
    """
    dlg.radio_lunar.setChecked(True)
    assert dlg.radio_lunar.isChecked()

    idx = dlg.combo_repeat.findData(REPEAT_WEEK)
    dlg.combo_repeat.blockSignals(True)
    dlg.combo_repeat.setCurrentIndex(idx)
    dlg.combo_repeat.blockSignals(False)

    # 脏状态就位：radio 说 lunar，combo 说 WEEK
    assert dlg.radio_lunar.isChecked()
    assert not dlg.radio_solar.isChecked()
    assert dlg.combo_repeat.currentData() == REPEAT_WEEK

    data = dlg.get_data()
    assert data["type"] == "solar"           # get_data() 兜底生效
    assert data["repeat_type"] == REPEAT_WEEK
    assert data["isleap"] is False           # 顺带钉住闰月字段被清

# ---------- _on_accept 校验 ----------

def test_accept_rejects_invalid_solar_date(dlg):
    """2/30 在闰年基准（2024）下也非法，_on_accept 应早退。"""
    dlg.edit_name.setText("测试")
    dlg.radio_solar.setChecked(True)
    _select_repeat(dlg, REPEAT_YEAR)
    dlg.spin_month.setValue(2)
    dlg.spin_day.setValue(30)

    spy = MagicMock()
    dlg.accept = spy  # 覆盖实例属性
    dlg._on_accept()

    spy.assert_not_called()
    assert dlg.result() == 0


def test_accept_valid_solar_date(dlg):
    """2/28 合法：accept 被调用，get_data 反映全部字段。"""
    dlg.edit_name.setText("测试")
    dlg.radio_solar.setChecked(True)
    _select_repeat(dlg, REPEAT_YEAR)
    dlg.spin_month.setValue(2)
    dlg.spin_day.setValue(28)

    dlg._on_accept()

    # QDialog.Accepted 在 PyQt6 里等于 1
    assert dlg.result() != 0

    data = dlg.get_data()
    assert data["name"] == "测试"
    assert data["type"] == "solar"
    assert data["repeat_type"] == REPEAT_YEAR
    assert data["month"] == 2
    assert data["day"] == 28


def test_accept_rejects_when_user_says_no_on_leap_warning(
        dlg, monkeypatch):
    """用户在闰月确认框点 No → _on_accept 早退，不 accept。

    回归保护：conftest._kill_modals 全局把 QMessageBox.question
    强制为 YES，本测试局部覆盖为 No，验证"用户拒绝"这条分支。
    """
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: QMessageBox.StandardButton.No)

    dlg.edit_name.setText("农历闰月")
    dlg.radio_lunar.setChecked(True)
    _select_repeat(dlg, REPEAT_YEAR)
    dlg.spin_month.setValue(4)
    dlg.spin_day.setValue(15)
    dlg.chk_leap.setChecked(True)

    dlg._on_accept()

    assert dlg.result() == 0
    
# ---------- 周模式字段形状 ----------

def test_week_mode_field_shape(dlg):
    """周模式：month 保留 spin_month 当前值（默认 1），匹配时不读它。"""
    dlg.edit_name.setText("周一")
    _select_repeat(dlg, REPEAT_WEEK)
    dlg.spin_day.setValue(1)

    data = dlg.get_data()
    assert data["repeat_type"] == REPEAT_WEEK
    assert data["day"] == 1
    # 周模式下 month 无意义，实现保留 spin_month 当前取值。
    # 若将来实现改为清零，把这里改成 == 0 即可。
    assert data["month"] == dlg.spin_month.value()


def test_week_mode_preserves_nondefault_month(dlg):
    """周模式下 month 即使被设为非默认值也应原样保留。"""
    _select_repeat(dlg, REPEAT_WEEK)
    dlg.spin_month.setValue(7)  # 非默认值
    dlg.spin_day.setValue(3)
    assert dlg.get_data()["month"] == 7
       
# ---------- WEEK 状态机往返 ----------

def test_week_roundtrip_restores_lunar_and_isleap(dlg):
    """lunar + 勾选闰月 → 切 WEEK → 切回 YEAR，用户意图完整恢复。"""
    dlg.radio_lunar.setChecked(True)
    dlg.chk_leap.setChecked(True)
    assert dlg.radio_lunar.isChecked()
    assert dlg.chk_leap.isChecked()

    _select_repeat(dlg, REPEAT_WEEK)
    # WEEK 期间：强制 solar，lunar / leap 被禁用且清空
    assert dlg.radio_solar.isChecked()
    assert not dlg.radio_lunar.isChecked()
    assert not dlg.chk_leap.isChecked()
    assert not dlg.radio_lunar.isEnabled()
    assert not dlg.chk_leap.isEnabled()

    _select_repeat(dlg, REPEAT_YEAR)
    # 切回后：type / isleap 意图恢复，控件重新可用
    assert dlg.radio_lunar.isChecked()
    assert dlg.chk_leap.isChecked()
    assert dlg.radio_lunar.isEnabled()
    assert dlg.chk_leap.isEnabled()


def test_week_roundtrip_keeps_solar_when_original_was_solar(dlg):
    """原状态是 solar 时，WEEK 往返不应把 lunar 变出来。"""
    dlg.radio_solar.setChecked(True)

    _select_repeat(dlg, REPEAT_WEEK)
    _select_repeat(dlg, REPEAT_YEAR)

    assert dlg.radio_solar.isChecked()
    assert not dlg.radio_lunar.isChecked()


def test_week_roundtrip_keeps_leap_unchecked_when_original_unchecked(dlg):
    """原状态是 lunar 但未勾选闰月时，WEEK 往返不应把 leap 勾上。"""
    dlg.radio_lunar.setChecked(True)
    assert not dlg.chk_leap.isChecked()

    _select_repeat(dlg, REPEAT_WEEK)
    _select_repeat(dlg, REPEAT_YEAR)

    assert dlg.radio_lunar.isChecked()
    assert not dlg.chk_leap.isChecked()

# ---------- load_data 跨 WEEK 数据的回归 ----------

def test_load_data_lunar_after_week_data_is_not_overridden(dlg):
    """回归：紧接 WEEK 数据之后 load_data 一份 lunar 数据，
    radio 选择不应被上一次 WEEK 状态压制。

    原实现路径：load_data 先 setChecked(lunar)，此时 combo 还是
    上一次 load 留下的 WEEK → _update_day_range 走 week 分支，
    把 radio 强制改回 solar；随后 combo 虽切到 YEAR，但 radio 已经
    是 solar，chk_leap 也被 setEnabled(False)。
    """
    dlg.load_data({
        "name": "w", "type": "solar", "repeat_type": REPEAT_WEEK,
        "month": 1, "day": 3, "advance_days": 0, "enabled": True,
    })
    assert dlg.combo_repeat.currentData() == REPEAT_WEEK

    dlg.load_data({
        "name": "lunar", "type": "lunar", "repeat_type": REPEAT_YEAR,
        "month": 1, "day": 1, "isleap": True,
        "advance_days": 0, "enabled": True,
    })
    assert dlg.combo_repeat.currentData() == REPEAT_YEAR
    assert dlg.radio_lunar.isChecked()
    assert dlg.chk_leap.isChecked()
    assert dlg.chk_leap.isEnabled()


def test_load_data_lunar_after_week_data_roundtrip(dlg):
    """加载 WEEK 数据后再加载 lunar + YEAR 数据，此时切到 WEEK 再切回
    YEAR，用户数据里的 lunar 意图应能被快照并恢复。"""
    dlg.load_data({
        "name": "w", "type": "solar", "repeat_type": REPEAT_WEEK,
        "month": 1, "day": 1, "advance_days": 0, "enabled": True,
    })
    dlg.load_data({
        "name": "lunar", "type": "lunar", "repeat_type": REPEAT_YEAR,
        "month": 5, "day": 5, "isleap": True,
        "advance_days": 0, "enabled": True,
    })
    assert dlg.radio_lunar.isChecked()
    assert dlg.chk_leap.isChecked()

    _select_repeat(dlg, REPEAT_WEEK)
    assert dlg.radio_solar.isChecked()

    _select_repeat(dlg, REPEAT_YEAR)
    assert dlg.radio_lunar.isChecked()
    assert dlg.chk_leap.isChecked()
    
    