# coding: utf-8
import copy
import json

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QCheckBox, QPushButton, QSlider, QGroupBox,
    QFileDialog, QComboBox,
)
from desktop_calendar.config.manager import (
    atomic_write_json, get_logger, normalize_config,
)
from desktop_calendar.config.i18n import tr
from desktop_calendar.utils.coerce import to_bool
from desktop_calendar.core.memorial import normalize_memorial_days, REPEAT_ONCE
from desktop_calendar.config.constants import (
    THEME_PRESETS_ORDER, THEME_LIGHT, REFERENCE_LEAP_YEAR,
)
from desktop_calendar.ui.theme import ThemeBundle

from .messages import msg_info, msg_error
from .base import make_button_box
from .memorial import MemorialDialog
from .attendance_rule import AttendanceRuleDialog

logger = get_logger()

__all__ = ["SettingDialog"]


class SettingDialog(QDialog):
    """设置对话框。"""

    preview_opacity_changed = pyqtSignal(float)

    def __init__(self, cfg, auto_start_state, opacity,
                 memorial_remind, memorial_sound, attendance_remind,
                 parent=None, bundle: ThemeBundle = None):
        super().__init__(parent)
        if bundle is None:
            raise ValueError("SettingDialog 需要 ThemeBundle")
        self._bundle = bundle
        self.cfg = copy.deepcopy(cfg) if isinstance(cfg, dict) else {}
        if not isinstance(self.cfg.get("memorial_days"), list):
            self.cfg["memorial_days"] = []
        if not isinstance(self.cfg.get("memorial_cfg"), dict):
            self.cfg["memorial_cfg"] = {}
        # attendance_cfg 防御：导入的配置可能把它写成 list / null，
        # open_attendance_rule_dialog / _sync_widgets_to_cfg 都假定它是 dict。
        if not isinstance(self.cfg.get("attendance_cfg"), dict):
            self.cfg["attendance_cfg"] = {}

        self._auto_start_state = bool(auto_start_state)
        self._autostart_dirty = False
        self._opacity_val = float(opacity)
        self.memorial_remind = bool(memorial_remind)
        self.memorial_sound = bool(memorial_sound)
        self.attendance_remind = bool(attendance_remind)

        # 导入相关状态：done() 在用户取消且导入过时用 _cfg_before_import
        # 还原 self.cfg，避免"导入后点取消，cfg 已变"的隐性副作用。
        self._imported = False
        self._cfg_before_import = None

        dlg = self._bundle.dialog
        self.setWindowTitle(tr("setting.title"))
        self.resize(*dlg.settings_size)
        self.setStyleSheet(dlg.qss_settings)

        main_layout = QVBoxLayout(self)
        mw = dlg.margin_wide
        main_layout.setContentsMargins(mw, mw, mw, mw)
        main_layout.setSpacing(dlg.spacing_wide)

        self.group_general = QGroupBox(tr("setting.general"))
        lay_general = QGridLayout(self.group_general)
        lay_general.setSpacing(10)

        self.combo_theme = QComboBox()
        for code in THEME_PRESETS_ORDER:
            self.combo_theme.addItem(tr(f"theme.{code}"), code)
        idx_t = self.combo_theme.findData(
            self.cfg.get("theme_name", THEME_LIGHT))
        if idx_t >= 0:
            self.combo_theme.setCurrentIndex(idx_t)

        self.lbl_theme = QLabel(tr("setting.theme"))
        lay_general.addWidget(self.lbl_theme, 5, 0)
        lay_general.addWidget(self.combo_theme, 5, 1)

        self.chk_autostart = QCheckBox(tr("setting.autostart"))
        self.chk_autostart.setChecked(self._auto_start_state)
        self.chk_autostart.toggled.connect(self._on_autostart_toggled)

        self.chk_mem_remind = QCheckBox(tr("setting.memorial_remind"))
        self.chk_mem_remind.setChecked(self.memorial_remind)

        self.chk_mem_sound = QCheckBox(tr("setting.memorial_sound"))
        self.chk_mem_sound.setChecked(self.memorial_sound)

        self.chk_att_remind = QCheckBox(tr("setting.attendance_remind"))
        self.chk_att_remind.setChecked(self.attendance_remind)
        self.chk_att_remind.setToolTip(tr("setting.attendance_remind_tip"))
        lay_general.addWidget(self.chk_att_remind, 3, 0)

        lay_general.addWidget(self.chk_autostart, 0, 0)
        lay_general.addWidget(self.chk_mem_remind, 1, 0)
        lay_general.addWidget(self.chk_mem_sound, 2, 0)

        self.lbl_op = QLabel(tr("setting.opacity"))
        self.slider_op = QSlider(Qt.Orientation.Horizontal)
        self.slider_op.setRange(60, 100)
        self.slider_op.setValue(int(opacity * 100))
        self.lbl_op_val = QLabel(f"{int(opacity * 100)}%")
        self.slider_op.valueChanged.connect(self._on_slider_change)

        self.lay_op = QHBoxLayout()
        self.lay_op.addWidget(self.lbl_op)
        self.lay_op.addWidget(self.slider_op)
        self.lay_op.addWidget(self.lbl_op_val)
        lay_general.addLayout(self.lay_op, 4, 0)

        # 考勤规则入口：与 chk_att_remind (3, 0) 同行右列，语义上是
        # 「开关 + 规则」的配套控件，视觉上贴在一起；不占用新行，
        # settings_size 高度不变。
        self.btn_att_rule = QPushButton(tr("setting.attendance_rule"))
        self.btn_att_rule.clicked.connect(self.open_attendance_rule_dialog)
        lay_general.addWidget(self.btn_att_rule, 3, 1)

        main_layout.addWidget(self.group_general)

        self.group_data = QGroupBox(tr("setting.data"))
        lay_data = QHBoxLayout(self.group_data)
        self.btn_export = QPushButton(tr("setting.export"))
        self.btn_import = QPushButton(tr("setting.import"))
        self.btn_export.clicked.connect(self._export_config)
        self.btn_import.clicked.connect(self._import_config)
        lay_data.addWidget(self.btn_export)
        lay_data.addWidget(self.btn_import)
        main_layout.addWidget(self.group_data)

        self.btn_mem = QPushButton(tr("setting.manage_memorial"))
        self.btn_mem.clicked.connect(self.open_mem_dialog)
        main_layout.addWidget(self.btn_mem)

        self._btn_box = make_button_box(self)
        main_layout.addWidget(self._btn_box)

    def done(self, r):
        """取消路径还原 cfg。

        _import_config 会改 self.cfg；用户点取消时如果不还原，调用方
        虽然不会 apply_settings，但 dlg.cfg 已与打开时不一致，后续
        误用（如导出）会得到混合状态。这里在 done 中回滚。
        """
        if r != QDialog.DialogCode.Accepted and self._imported:
            if self._cfg_before_import is not None:
                self.cfg = self._cfg_before_import
        super().done(r)

    def _on_slider_change(self, v: int):
        self._opacity_val = v / 100
        self.lbl_op_val.setText(f"{v}%")
        self.preview_opacity_changed.emit(self._opacity_val)

    def _sync_widgets_to_cfg(self) -> None:
        """把当前控件状态同步到 self.cfg。

        _export_config 与 apply_settings 都需要"控件 → cfg"的方向。
        apply_settings 在 settings_controller 里（不能循环 import），
        这里独立实现一遍，字段与 apply_settings 保持一致。
        """
        self.cfg["opacity"] = self._opacity_val
        self.cfg["theme_name"] = self.get_theme_name()
        mem_cfg = dict(self.cfg.get("memorial_cfg") or {})
        mem_cfg["enable_remind"] = self.chk_mem_remind.isChecked()
        mem_cfg["sound_enable"] = self.chk_mem_sound.isChecked()
        self.cfg["memorial_cfg"] = mem_cfg
        # memorial_days 已在 self.cfg 里（open_mem_dialog 更新过）
        att_cfg = dict(self.cfg.get("attendance_cfg") or {})
        att_cfg["enable_remind"] = self.chk_att_remind.isChecked()
        self.cfg["attendance_cfg"] = att_cfg

    def _export_config(self):
        # 先同步控件状态：导出的是"用户当前看到的配置"，
        # 而非"打开对话框时的快照"。
        self._sync_widgets_to_cfg()

        path, _ = QFileDialog.getSaveFileName(
            self, tr("msg.export_title"),
            "calendar_config.json", "JSON (*.json)")
        if not path:
            return
        try:
            atomic_write_json(path, self.cfg)
            msg_info(self, tr("msg.success"), tr("msg.export_success"))
        except Exception as e:
            msg_error(self, tr("msg.error"),
                      tr("msg.export_failed").format(error=e))

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("msg.import_title"), "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("root is not a dict")
        except Exception as e:
            msg_error(self, tr("msg.error"),
                      tr("msg.import_format_error").format(error=e))
            return
        # 记录导入前的 cfg：用户点"取消"时 done() 用它还原。
        # 只在首次导入时记录——多次导入后取消应回到"打开对话框时"
        # 的状态，而不是最后一次导入前的状态。
        if not self._imported:
            self._cfg_before_import = copy.deepcopy(self.cfg)

        # merge：文件中的键覆盖，其余保留用户已做的改动
        for k, v in data.items():
            if (k == "memorial_cfg" and isinstance(v, dict)
                    and isinstance(self.cfg.get(k), dict)):
                merged = dict(self.cfg[k])
                merged.update(v)
                self.cfg[k] = merged
            else:
                self.cfg[k] = v

        # 归一化：导入的配置可能来自旧版本或手动编辑，字段类型不可信。
        # 在 UI 边界归一化而非等 apply_settings 时崩，让"导入"就是"得到
        # 一个合法配置"，用户点确定后行为可预期。
        self.cfg = normalize_config(self.cfg)
        normalized, skipped = normalize_memorial_days(self.cfg.get("memorial_days", []))
        self.cfg["memorial_days"] = normalized
        if skipped:
            logger.info(f"导入配置：共跳过 {skipped} 条无效纪念日")

        self._reload_from_cfg()
        self._imported = True
        msg_info(self, tr("msg.success"), tr("msg.import_success"))

    def _on_autostart_toggled(self, _checked: bool) -> None:
        self._autostart_dirty = True

    def _reload_from_cfg(self):
        """导入配置后刷新控件；blockSignals 防预览信号闪一下。"""
        widgets = (self.chk_mem_remind, self.chk_mem_sound,
                   self.chk_att_remind,
                   self.slider_op, self.chk_autostart,
                   self.combo_theme)
        for w in widgets:
            w.blockSignals(True)
        try:
            mem_cfg = self.cfg.get("memorial_cfg") or {}
            self.chk_mem_remind.setChecked(
                to_bool(mem_cfg.get("enable_remind", True), default=True))
            self.chk_mem_sound.setChecked(
                to_bool(mem_cfg.get("sound_enable", True), default=True))
            att_cfg = self.cfg.get("attendance_cfg") or {}
            self.chk_att_remind.setChecked(
                to_bool(att_cfg.get("enable_remind", True), default=True))
            # 只有用户没主动改过时才回填快照；改过则保留 UI 状态，
            # 由 apply_settings 走 want_auto != check_auto_start() 分支落盘。
            if not self._autostart_dirty:
                self.chk_autostart.setChecked(self._auto_start_state)

            try:
                op = float(self.cfg.get("opacity", 0.92))
            except (TypeError, ValueError):
                op = 0.92
            op = max(0.6, min(1.0, op))
            self.slider_op.setValue(int(op * 100))
            self._opacity_val = op
            self.lbl_op_val.setText(f"{int(op * 100)}%")

            idx_t = self.combo_theme.findData(
                self.cfg.get("theme_name", THEME_LIGHT))
            if idx_t >= 0:
                self.combo_theme.setCurrentIndex(idx_t)

        finally:
            for w in widgets:
                w.blockSignals(False)

    def open_mem_dialog(self):
        dlg = MemorialDialog(
            self.cfg.get("memorial_days", []), self, bundle=self._bundle)
        try:
            if dlg.exec():
                # get_result 返回 dlg 内部 list 引用，deepcopy 切断别名：
                # 若未来 MemorialDialog 在 exec 后仍操作 memorial_list，
                # 不会污染 self.cfg。
                self.cfg["memorial_days"] = copy.deepcopy(dlg.get_result())
        finally:
            dlg.deleteLater()

    def open_attendance_rule_dialog(self) -> None:
        """打开考勤规则子对话框，确定后只写回 work_rule 段。"""
        att_cfg = self.cfg.get("attendance_cfg")
        if not isinstance(att_cfg, dict):
            att_cfg = {}
        work_rule = att_cfg.get("work_rule")
        if not isinstance(work_rule, dict):
            work_rule = {}
        dlg = AttendanceRuleDialog(work_rule, self, bundle=self._bundle)
        try:
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            new_rule = dlg.get_rule()
        finally:
            dlg.deleteLater()
        # 只写回 work_rule，att_cfg 里其余字段（enable_remind 等）
        # 原样保留。
        att_cfg = dict(att_cfg)
        att_cfg["work_rule"] = new_rule
        self.cfg["attendance_cfg"] = att_cfg

    def get_auto_start_status(self) -> bool:
        return self.chk_autostart.isChecked()

    def get_opacity(self) -> float:
        return self._opacity_val

    def get_memorial_list(self):
        return self.cfg.get("memorial_days", [])

    def get_mem_remind(self) -> bool:
        return self.chk_mem_remind.isChecked()

    def get_mem_sound(self) -> bool:
        return self.chk_mem_sound.isChecked()

    def get_att_remind(self) -> bool:
        return self.chk_att_remind.isChecked()

    def get_theme_name(self) -> str:
        return self.combo_theme.currentData() or THEME_LIGHT