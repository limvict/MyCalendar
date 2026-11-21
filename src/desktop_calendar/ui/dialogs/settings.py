# coding: utf-8
import copy
import json

from PyQt6.QtCore import QRectF, QSizeF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from desktop_calendar.config.constants import (
    THEME_LIGHT,
    THEME_PRESETS_ORDER,
)
from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import (
    atomic_write_json,
    get_logger,
    normalize_config,
)
from desktop_calendar.core.memorial import normalize_memorial_days
from desktop_calendar.infrastructure.network.update_checker import CURRENT_VERSION
from desktop_calendar.ui.calendar_wallpaper import draw_wallpaper, load_wallpaper
from desktop_calendar.ui.theme import ThemeBundle
from desktop_calendar.utils.coerce import to_bool

from .attendance_rule import AttendanceRuleDialog
from .base import fit_dialog_to_screen, make_button_box
from .memorial import MemorialDialog
from .messages import msg_error, msg_info

logger = get_logger()

__all__ = ["SettingDialog"]


class SettingDialog(QDialog):
    """设置对话框。"""

    preview_opacity_changed = pyqtSignal(float)
    theme_preview_requested = pyqtSignal(str)

    def __init__(
        self,
        cfg,
        auto_start_state,
        opacity,
        memorial_remind,
        memorial_sound,
        attendance_remind,
        parent=None,
        bundle: ThemeBundle = None,
        on_check_update=None,
    ):
        super().__init__(parent)
        if bundle is None:
            raise ValueError("SettingDialog 需要 ThemeBundle")
        self._bundle = bundle
        self._on_check_update = on_check_update
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

        self.settings_scroll = QScrollArea(self)
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.settings_content = QWidget(self.settings_scroll)
        content_layout = QVBoxLayout(self.settings_content)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(dlg.spacing_wide)
        self.settings_scroll.setWidget(self.settings_content)
        main_layout.addWidget(self.settings_scroll, stretch=1)

        content_layout.addWidget(self._build_general_group())

        content_layout.addWidget(self._build_appearance_group())

        self.group_data = QGroupBox(tr("setting.data"))
        lay_data = QHBoxLayout(self.group_data)
        self.btn_export = QPushButton(tr("setting.export"))
        self.btn_import = QPushButton(tr("setting.import"))
        self.btn_export.clicked.connect(self._export_config)
        self.btn_import.clicked.connect(self._import_config)
        lay_data.addWidget(self.btn_export)
        lay_data.addWidget(self.btn_import)
        content_layout.addWidget(self.group_data)

        content_layout.addWidget(self._build_update_group())

        self.btn_mem = QPushButton(tr("setting.manage_memorial"))
        self.btn_mem.clicked.connect(self.open_mem_dialog)
        content_layout.addWidget(self.btn_mem)
        content_layout.addStretch(1)

        self._btn_box = make_button_box(self)
        main_layout.addWidget(self._btn_box)
        fit_dialog_to_screen(self, dlg.settings_size, minimum_size=(380, 320))

    def _build_update_group(self) -> QGroupBox:
        """更新分组：显示当前版本 + 手动检查更新入口。"""
        self.group_update = QGroupBox(tr("setting.update"))
        lay_update = QHBoxLayout(self.group_update)
        lay_update.setSpacing(10)
        self.lbl_version = QLabel(tr("setting.current_version").format(version=CURRENT_VERSION))
        self.btn_check_update = QPushButton(tr("setting.check_update"))
        self.btn_check_update.setToolTip(tr("setting.check_update_tip"))
        self.btn_check_update.clicked.connect(self._request_check_update)
        # 没有回调时（例如独立构造对话框的测试）禁用，避免点了没反应
        self.btn_check_update.setEnabled(self._on_check_update is not None)
        lay_update.addWidget(self.lbl_version)
        lay_update.addStretch(1)
        lay_update.addWidget(self.btn_check_update)
        return self.group_update

    def _request_check_update(self) -> None:
        if self._on_check_update is None:
            return
        try:
            self._on_check_update(self)
        except Exception:
            logger.exception("检查更新入口调用失败")

    def _build_general_group(self) -> QGroupBox:
        self.group_general = QGroupBox(tr("setting.general"))
        lay_general = QGridLayout(self.group_general)
        lay_general.setSpacing(10)

        self.combo_theme = QComboBox()
        for code in THEME_PRESETS_ORDER:
            self.combo_theme.addItem(tr(f"theme.{code}"), code)
        idx_t = self.combo_theme.findData(self.cfg.get("theme_name", THEME_LIGHT))
        if idx_t >= 0:
            self.combo_theme.setCurrentIndex(idx_t)
        self.combo_theme.currentIndexChanged.connect(self._on_theme_preview_changed)

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

        self.chk_att_auto_punch = QCheckBox(tr("setting.attendance_auto_punch"))
        self.chk_att_auto_punch.setChecked(
            to_bool((self.cfg.get("attendance_cfg") or {}).get("enable_auto_punch"), default=False)
        )
        self.chk_att_auto_punch.setToolTip(tr("setting.attendance_auto_punch_tip"))

        for row, checkbox in enumerate(
            (self.chk_autostart, self.chk_mem_remind, self.chk_mem_sound)
        ):
            lay_general.addWidget(checkbox, row, 0, 1, 2)
        lay_general.addWidget(self.chk_att_remind, 3, 0)

        self.btn_att_rule = QPushButton(tr("setting.attendance_rule"))
        self.btn_att_rule.clicked.connect(self.open_attendance_rule_dialog)
        lay_general.addWidget(self.btn_att_rule, 3, 1)
        lay_general.addWidget(self.chk_att_auto_punch, 4, 0, 1, 2)
        return self.group_general

    def _build_appearance_group(self) -> QGroupBox:
        self.group_appearance = QGroupBox(tr("setting.appearance"))
        lay_appearance = QGridLayout(self.group_appearance)
        lay_appearance.setSpacing(10)
        self.lbl_theme = QLabel(tr("setting.theme"))
        lay_appearance.addWidget(self.lbl_theme, 0, 0)
        lay_appearance.addWidget(self.combo_theme, 0, 1)
        self.chk_theme_auto = QCheckBox(tr("setting.theme_auto"))
        self.chk_theme_auto.setChecked(to_bool(self.cfg.get("theme_auto_enabled"), default=False))
        self.chk_theme_auto.setToolTip(tr("setting.theme_auto_tip"))
        lay_appearance.addWidget(self.chk_theme_auto, 2, 0, 1, 2)
        self.lbl_op = QLabel(tr("setting.opacity"))
        self.slider_op = QSlider(Qt.Orientation.Horizontal)
        self.slider_op.setRange(60, 100)
        self.slider_op.setValue(int(self._opacity_val * 100))
        self.lbl_op_val = QLabel(f"{int(self._opacity_val * 100)}%")
        self.slider_op.valueChanged.connect(self._on_slider_change)

        self.lay_op = QHBoxLayout()
        self.lay_op.addWidget(self.lbl_op)
        self.lay_op.addWidget(self.slider_op)
        self.lay_op.addWidget(self.lbl_op_val)
        lay_appearance.addLayout(self.lay_op, 1, 0, 1, 2)

        self.lbl_wallpaper = QLabel(tr("setting.calendar_wallpaper"))
        self.wallpaper_preview = QLabel()
        preview_scale = self._bundle.scale_factor
        self.wallpaper_preview.setFixedSize(
            max(60, round(104 * preview_scale)), max(36, round(60 * preview_scale))
        )
        self.wallpaper_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.wallpaper_preview.setStyleSheet(
            f"border: 1px solid {self._bundle.resolver.color('border_color')};border-radius: 6px;"
        )
        self.btn_wallpaper = QPushButton(tr("setting.calendar_wallpaper_change"))
        self.btn_wallpaper.clicked.connect(self._select_calendar_wallpaper)
        self.btn_wallpaper_clear = QPushButton(tr("setting.calendar_wallpaper_clear"))
        self.btn_wallpaper_clear.clicked.connect(self._clear_calendar_wallpaper)
        wallpaper_controls = QHBoxLayout()
        wallpaper_controls.addWidget(self.wallpaper_preview)
        wallpaper_controls.addWidget(self.btn_wallpaper)
        wallpaper_controls.addWidget(self.btn_wallpaper_clear)
        lay_appearance.addWidget(self.lbl_wallpaper, 3, 0)
        lay_appearance.addLayout(wallpaper_controls, 3, 1)

        self.lbl_wallpaper_overlay = QLabel(tr("setting.calendar_wallpaper_overlay"))
        self.slider_wallpaper_overlay = QSlider(Qt.Orientation.Horizontal)
        self.slider_wallpaper_overlay.setRange(20, 90)
        self.slider_wallpaper_overlay.setValue(int(self.cfg.get("calendar_wallpaper_overlay", 58)))
        self.lbl_wallpaper_overlay_val = QLabel(f"{self.slider_wallpaper_overlay.value()}%")
        self.slider_wallpaper_overlay.valueChanged.connect(self._on_wallpaper_overlay_changed)
        overlay_row = QHBoxLayout()
        overlay_row.addWidget(self.lbl_wallpaper_overlay)
        overlay_row.addWidget(self.slider_wallpaper_overlay)
        overlay_row.addWidget(self.lbl_wallpaper_overlay_val)
        lay_appearance.addLayout(overlay_row, 4, 0, 1, 2)
        self.lbl_wallpaper_tip = QLabel(tr("setting.calendar_wallpaper_tip"))
        self.lbl_wallpaper_tip.setWordWrap(True)
        lay_appearance.addWidget(self.lbl_wallpaper_tip, 5, 0, 1, 2)
        self._wallpaper_path = self.cfg.get("calendar_wallpaper", "")
        self._update_wallpaper_preview()
        return self.group_appearance

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

    def _select_calendar_wallpaper(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("setting.calendar_wallpaper"), "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if not path:
            return
        if load_wallpaper(path) is None:
            msg_error(self, tr("msg.error"), "无法读取所选图片。")
            return
        self._wallpaper_path = path
        self.cfg["calendar_wallpaper"] = path
        self._update_wallpaper_preview()

    def _clear_calendar_wallpaper(self) -> None:
        self._wallpaper_path = ""
        self.cfg["calendar_wallpaper"] = ""
        self._update_wallpaper_preview()

    def _update_wallpaper_preview(self) -> None:
        pixmap = load_wallpaper(self._wallpaper_path)
        if pixmap is None:
            self.wallpaper_preview.setPixmap(QPixmap())
            self.wallpaper_preview.setText(tr("setting.calendar_wallpaper_none"))
            return
        self.wallpaper_preview.setText("")
        preview = QPixmap(self.wallpaper_preview.size())
        preview.fill(QColor(self._bundle.calendar_colors["normal_cell_bg"]))
        painter = QPainter(preview)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw_wallpaper(
            painter,
            QRectF(preview.rect()),
            QSizeF(preview.size()),
            pixmap,
            self._bundle.calendar_colors["normal_cell_bg"],
            self.slider_wallpaper_overlay.value(),
            radius=6,
        )
        painter.setPen(QColor(self._bundle.resolver.color("date_text_color")))
        font = QFont(self._bundle.fonts.global_)
        font.setPointSizeF(max(8.0, font.pointSizeF()))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, 7, preview.width(), 30), Qt.AlignmentFlag.AlignCenter, "18")
        font.setPointSizeF(max(7.0, font.pointSizeF() - 2))
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(self._bundle.calendar_colors["normal_lunar_color"]))
        painter.drawText(QRectF(0, 33, preview.width(), 18), Qt.AlignmentFlag.AlignCenter, "初一")
        painter.end()
        self.wallpaper_preview.setPixmap(preview)

    def _on_wallpaper_overlay_changed(self, value: int) -> None:
        self.cfg["calendar_wallpaper_overlay"] = value
        self.lbl_wallpaper_overlay_val.setText(f"{value}%")
        self._update_wallpaper_preview()

    def _on_theme_preview_changed(self, _index: int) -> None:
        name = self.get_theme_name()
        if name:
            self.theme_preview_requested.emit(name)

    def _sync_widgets_to_cfg(self) -> None:
        """把当前控件状态同步到 self.cfg。

        _export_config 与 apply_settings 都需要"控件 → cfg"的方向。
        apply_settings 在 settings_controller 里（不能循环 import），
        这里独立实现一遍，字段与 apply_settings 保持一致。
        """
        self.cfg["opacity"] = self._opacity_val
        self.cfg["theme_name"] = self.get_theme_name()
        self.cfg["theme_auto_enabled"] = self.get_auto_theme_enabled()
        self.cfg["calendar_wallpaper"] = self._wallpaper_path
        self.cfg["calendar_wallpaper_overlay"] = self.slider_wallpaper_overlay.value()
        mem_cfg = dict(self.cfg.get("memorial_cfg") or {})
        mem_cfg["enable_remind"] = self.chk_mem_remind.isChecked()
        mem_cfg["sound_enable"] = self.chk_mem_sound.isChecked()
        self.cfg["memorial_cfg"] = mem_cfg
        # memorial_days 已在 self.cfg 里（open_mem_dialog 更新过）
        att_cfg = dict(self.cfg.get("attendance_cfg") or {})
        att_cfg["enable_remind"] = self.chk_att_remind.isChecked()
        att_cfg["enable_auto_punch"] = self.chk_att_auto_punch.isChecked()
        self.cfg["attendance_cfg"] = att_cfg

    def _export_config(self):
        # 先同步控件状态：导出的是"用户当前看到的配置"，
        # 而非"打开对话框时的快照"。
        self._sync_widgets_to_cfg()

        path, _ = QFileDialog.getSaveFileName(
            self, tr("msg.export_title"), "calendar_config.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            atomic_write_json(path, self.cfg)
            msg_info(self, tr("msg.success"), tr("msg.export_success"))
        except Exception as e:
            msg_error(self, tr("msg.error"), tr("msg.export_failed").format(error=e))

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("msg.import_title"), "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("root is not a dict")
        except Exception as e:
            msg_error(self, tr("msg.error"), tr("msg.import_format_error").format(error=e))
            return
        # 记录导入前的 cfg：用户点"取消"时 done() 用它还原。
        # 只在首次导入时记录——多次导入后取消应回到"打开对话框时"
        # 的状态，而不是最后一次导入前的状态。
        if not self._imported:
            self._cfg_before_import = copy.deepcopy(self.cfg)

        # merge：文件中的键覆盖，其余保留用户已做的改动
        for k, v in data.items():
            if k == "memorial_cfg" and isinstance(v, dict) and isinstance(self.cfg.get(k), dict):
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
        widgets = (
            self.chk_mem_remind,
            self.chk_mem_sound,
            self.chk_att_remind,
            self.chk_att_auto_punch,
            self.slider_op,
            self.chk_autostart,
            self.combo_theme,
            self.chk_theme_auto,
            self.slider_wallpaper_overlay,
        )
        for w in widgets:
            w.blockSignals(True)
        try:
            mem_cfg = self.cfg.get("memorial_cfg") or {}
            self.chk_mem_remind.setChecked(
                to_bool(mem_cfg.get("enable_remind", True), default=True)
            )
            self.chk_mem_sound.setChecked(to_bool(mem_cfg.get("sound_enable", True), default=True))
            att_cfg = self.cfg.get("attendance_cfg") or {}
            self.chk_att_remind.setChecked(
                to_bool(att_cfg.get("enable_remind", True), default=True)
            )
            self.chk_att_auto_punch.setChecked(
                to_bool(att_cfg.get("enable_auto_punch", False), default=False)
            )
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

            idx_t = self.combo_theme.findData(self.cfg.get("theme_name", THEME_LIGHT))
            if idx_t >= 0:
                self.combo_theme.setCurrentIndex(idx_t)
            self.chk_theme_auto.setChecked(
                to_bool(self.cfg.get("theme_auto_enabled"), default=False)
            )
            self._wallpaper_path = self.cfg.get("calendar_wallpaper", "")
            self.slider_wallpaper_overlay.setValue(
                int(self.cfg.get("calendar_wallpaper_overlay", 58))
            )
            self.lbl_wallpaper_overlay_val.setText(f"{self.slider_wallpaper_overlay.value()}%")
            self._update_wallpaper_preview()

        finally:
            for w in widgets:
                w.blockSignals(False)

    def open_mem_dialog(self):
        dlg = MemorialDialog(self.cfg.get("memorial_days", []), self, bundle=self._bundle)
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

    def get_att_auto_punch(self) -> bool:
        return self.chk_att_auto_punch.isChecked()

    def get_theme_name(self) -> str:
        return self.combo_theme.currentData() or THEME_LIGHT

    def get_auto_theme_enabled(self) -> bool:
        return self.chk_theme_auto.isChecked()
