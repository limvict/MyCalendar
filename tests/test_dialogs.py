# coding: utf-8
"""ui/dialogs：base 按钮盒、MonthYearPicker、SettingDialog、AddMemorialDialog。"""
import json

import pytest
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QDialog, QDialogButtonBox
from desktop_calendar.config.constants import DEFAULT_THEME, THEME_LIGHT
from desktop_calendar.ui.dialogs.base import  make_button_box, retranslate_button_box
from desktop_calendar.ui.dialogs.memorial import AddMemorialDialog
from desktop_calendar.ui.dialogs.picker import MonthYearPickerDialog
from desktop_calendar.ui.dialogs.settings import SettingDialog
from desktop_calendar.ui.theme.bundle import build_bundle


@pytest.fixture
def bundle(qapp):
    return build_bundle("light", dict(DEFAULT_THEME))


# ===================== base：按钮盒 =====================
def test_make_button_box(qapp):
    dlg = QDialog()
    try:
        box = make_button_box(dlg)
        assert box.button(QDialogButtonBox.StandardButton.Ok) is not None
        assert box.button(QDialogButtonBox.StandardButton.Cancel) is not None
    finally:
        dlg.deleteLater()


def test_make_button_box_custom_accept(qapp):
    dlg = QDialog()
    try:
        called = []
        box = make_button_box(dlg, on_accept=lambda: called.append(1))
        box.accepted.emit()
        assert called == [1]
    finally:
        dlg.deleteLater()


def test_retranslate(qapp):
    dlg = QDialog()
    try:
        box = make_button_box(dlg)
        retranslate_button_box(box)
        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok.text() =="确定"
    finally:
        dlg.deleteLater()


def test_retranslate_none_safe():
    retranslate_button_box(None)


# ===================== MonthYearPickerDialog：年月 clamp =====================
def test_picker_init(qapp, bundle):
    dlg = MonthYearPickerDialog(2024, 6, bundle=bundle)
    try:
        assert dlg.get_year_month() == (2024, 6)
    finally:
        dlg.deleteLater()


def test_month_high_clamped(qapp, bundle):
    dlg = MonthYearPickerDialog(2024, 99, bundle=bundle)
    try:
        assert dlg.get_year_month() == (2024, 12)
    finally:
        dlg.deleteLater()


def test_month_low_clamped(qapp, bundle):
    dlg = MonthYearPickerDialog(2024, 0, bundle=bundle)
    try:
        assert dlg.get_year_month() == (2024, 1)
    finally:
        dlg.deleteLater()


def test_year_out_of_range_clamped(qapp, bundle):
    today = QDate.currentDate()
    lo = today.year() - MonthYearPickerDialog.YEAR_SPAN
    dlg = MonthYearPickerDialog(lo - 100, 1, bundle=bundle)
    try:
        assert dlg.get_year_month()[0] >= lo
    finally:
        dlg.deleteLater()


# ===================== SettingDialog：控件同步 / 导入取消回滚 =====================
@pytest.fixture
def base_cfg():
    """SettingDialog 的最小可用配置。

    attendance_cfg.work_rule 是 P1 新增段：ensure SettingDialog 读取
    规则时不会 KeyError，也便于 open_attendance_rule_dialog 的测试。
    """
    return {
        "opacity": 0.9,
        "language": "zh_CN",
        "theme_name": THEME_LIGHT,
        "memorial_days": [],
        "memorial_cfg": {"enable_remind": True, "sound_enable": True},
        "attendance_cfg": {
            "enable_remind": True,
            "work_rule": {
                "work_start": "08:00", "work_end": "17:00",
                "standard_minutes": 480,
                "lunch_start": "12:00", "lunch_end": "13:00",
                "late_grace": 0, "overtime_granularity": 0,
            },
        },
    }


def _make_settings_dialog(cfg, bundle, auto_start=False, opacity=0.9):
    """SettingDialog 6 参数构造的薄封装，避免每处调用重复 5 个 True。"""
    return SettingDialog(cfg, auto_start, opacity,
                         True, True, True, bundle=bundle)


class TestSettingsGetters:
    def test_defaults(self, qapp, bundle, base_cfg):
        dlg = _make_settings_dialog(base_cfg, bundle)
        try:
            assert dlg.get_theme_name() == THEME_LIGHT
            assert dlg.get_opacity() == 0.9
            assert dlg.get_mem_remind() is True
            assert dlg.get_mem_sound() is True
            assert dlg.get_att_remind() is True
        finally:
            dlg.deleteLater()


class TestSettingsSyncWidgets:
    def test_sync(self, qapp, bundle, base_cfg):
        dlg = _make_settings_dialog(base_cfg, bundle)
        try:
            dlg._sync_widgets_to_cfg()
            assert dlg.cfg["opacity"] == 0.9
            assert dlg.cfg["theme_name"] == THEME_LIGHT
        finally:
            dlg.deleteLater()


class TestSettingsImport:
    def test_import_overwrites(self, qapp, bundle, base_cfg, tmp_path,
                               monkeypatch):
        dlg = _make_settings_dialog(base_cfg, bundle)
        try:
            import_cfg = {
                "opacity": 0.5,
                "memorial_days": [{
                    "name": "x", "type": "solar", "repeat_type": "year",
                    "month": 1, "day": 1,
                }],
            }
            path = tmp_path / "import.json"
            path.write_text(json.dumps(import_cfg), encoding="utf-8")
            monkeypatch.setattr(
                "desktop_calendar.ui.dialogs.settings.QFileDialog.getOpenFileName",
                lambda *a, **k: (str(path), ""))
            monkeypatch.setattr(
                "desktop_calendar.ui.dialogs.settings.msg_info",
                lambda *a, **k: None)
            dlg._import_config()
            assert dlg.cfg["opacity"] == 0.5
            assert len(dlg.cfg["memorial_days"]) == 1
        finally:
            dlg.deleteLater()

    def test_cancel_reverts_imported_cfg(self, qapp, bundle, base_cfg,
                                         tmp_path, monkeypatch):
        dlg = _make_settings_dialog(base_cfg, bundle)
        try:
            path = tmp_path / "import.json"
            path.write_text(json.dumps({"opacity": 0.5}), encoding="utf-8")
            monkeypatch.setattr(
                "desktop_calendar.ui.dialogs.settings.QFileDialog.getOpenFileName",
                lambda *a, **k: (str(path), ""))
            monkeypatch.setattr(
                "desktop_calendar.ui.dialogs.settings.msg_info",
                lambda *a, **k: None)
            dlg._import_config()
            assert dlg.cfg["opacity"] == 0.5
            dlg.done(0)  # 模拟取消
            assert dlg.cfg["opacity"] == 0.9
        finally:
            dlg.deleteLater()


# ===================== SettingDialog：P1 考勤规则入口 =====================
class TestSettingsAttendanceRule:
    def test_button_exists(self, qapp, bundle, base_cfg):
        dlg = _make_settings_dialog(base_cfg, bundle)
        try:
            assert dlg.btn_att_rule is not None
            assert "考勤规则" in dlg.btn_att_rule.text()
        finally:
            dlg.deleteLater()

    def test_open_rule_dialog_writes_back_work_rule(
            self, qapp, bundle, base_cfg, monkeypatch):
        """确定后 work_rule 写回 cfg，att_cfg 其余字段保留。"""
        from desktop_calendar.ui.dialogs import settings as settings_mod

        new_rule = dict(base_cfg["attendance_cfg"]["work_rule"],
                        work_start="09:00", work_end="18:00")

        class _FakeRuleDlg:
            def __init__(self, *a, **k):
                pass
            def exec(self):
                return QDialog.DialogCode.Accepted
            def get_rule(self):
                return new_rule
            def deleteLater(self):
                pass

        monkeypatch.setattr(
            settings_mod, "AttendanceRuleDialog", _FakeRuleDlg)

        dlg = _make_settings_dialog(base_cfg, bundle)
        try:
            dlg.open_attendance_rule_dialog()
            rule = dlg.cfg["attendance_cfg"]["work_rule"]
            assert rule["work_start"] == "09:00"
            assert rule["work_end"] == "18:00"
            # 其余 att_cfg 字段未被覆盖
            assert dlg.cfg["attendance_cfg"]["enable_remind"] is True
        finally:
            dlg.deleteLater()

    def test_open_rule_dialog_cancel_keeps_cfg(
            self, qapp, bundle, base_cfg, monkeypatch):
        """取消时不写回。"""
        from desktop_calendar.ui.dialogs import settings as settings_mod

        class _CancelledDlg:
            def __init__(self, *a, **k):
                pass
            def exec(self):
                return QDialog.DialogCode.Rejected
            def get_rule(self):
                raise AssertionError("取消路径不应调用 get_rule")
            def deleteLater(self):
                pass

        monkeypatch.setattr(
            settings_mod, "AttendanceRuleDialog", _CancelledDlg)

        original_rule = dict(base_cfg["attendance_cfg"]["work_rule"])
        dlg = _make_settings_dialog(base_cfg, bundle)
        try:
            dlg.open_attendance_rule_dialog()
            assert dlg.cfg["attendance_cfg"]["work_rule"] == original_rule
        finally:
            dlg.deleteLater()


# ===================== AddMemorialDialog：往返 / 归一化 =====================
class TestMemorialInit:
    def test_initial(self, qapp, bundle):
        dlg = AddMemorialDialog(bundle=bundle)
        try:
            data = dlg.get_data()
            assert data["type"] == "solar"
            assert data["repeat_type"] == "year"
        finally:
            dlg.deleteLater()


class TestMemorialRoundtrip:
    def test_solar_yearly(self, qapp, bundle):
        dlg = AddMemorialDialog(bundle=bundle)
        try:
            dlg.load_data({
                "name": "Birthday", "type": "solar",
                "repeat_type": "year", "month": 6, "day": 15,
                "advance_days": 3, "enabled": True,
            })
            data = dlg.get_data()
            assert data["name"] == "Birthday"
            assert data["month"] == 6
            assert data["day"] == 15
            assert data["advance_days"] == 3
        finally:
            dlg.deleteLater()

    def test_week(self, qapp, bundle):
        dlg = AddMemorialDialog(bundle=bundle)
        try:
            dlg.load_data({"name": "W", "repeat_type": "week", "day": 3})
            data = dlg.get_data()
            assert data["repeat_type"] == "week"
            assert data["day"] == 3
            assert data["type"] == "solar"
        finally:
            dlg.deleteLater()

    def test_once_with_year(self, qapp, bundle):
        dlg = AddMemorialDialog(bundle=bundle)
        try:
            dlg.load_data({
                "name": "Once", "repeat_type": "once",
                "year": 2025, "month": 6, "day": 15,
            })
            data = dlg.get_data()
            assert data["year"] == 2025
        finally:
            dlg.deleteLater()

    def test_lunar_with_leap(self, qapp, bundle):
        dlg = AddMemorialDialog(bundle=bundle)
        try:
            dlg.load_data({
                "name": "L", "type": "lunar", "repeat_type": "year",
                "month": 4, "day": 15, "isleap": True,
            })
            data = dlg.get_data()
            assert data["type"] == "lunar"
            assert data["isleap"] is True
        finally:
            dlg.deleteLater()


class TestMemorialNormalization:
    def test_feb_30_clamped(self, qapp, bundle):
        dlg = AddMemorialDialog(bundle=bundle)
        try:
            dlg.load_data({"name": "X", "month": 2, "day": 30})
            data = dlg.get_data()
            assert data["day"] <= 29
        finally:
            dlg.deleteLater()

    def test_disabled_flag(self, qapp, bundle):
        dlg = AddMemorialDialog(bundle=bundle)
        try:
            dlg.load_data({"name": "X", "enabled": False})
            data = dlg.get_data()
            assert data["enabled"] is False
        finally:
            dlg.deleteLater()