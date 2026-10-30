import copy
from PyQt6.QtWidgets import QDialog

from desktop_calendar.ui.controllers.startup import (
    check_auto_start, apply_auto_start,
)
from desktop_calendar.ui.dialogs import SettingDialog
from desktop_calendar.contracts.event_bus import event_bus
from desktop_calendar.contracts.events import EventType
from desktop_calendar.config.i18n import set_language
from desktop_calendar.config.manager import config, get_logger

logger = get_logger()


def open_settings_dialog(window) -> None:
    snapshot = config.snapshot()
    orig_opacity = float(snapshot.get("opacity", 0.92))
    orig_topmost = bool(snapshot.get("topmost", False))

    mem_cfg = snapshot.get("memorial_cfg") or {}
    mem_remind = bool(mem_cfg.get("enable_remind", True))
    mem_sound = bool(mem_cfg.get("sound_enable", True))

    auto_start = check_auto_start()
    dlg = SettingDialog(
        snapshot, auto_start,
        orig_topmost, orig_opacity,
        mem_remind, mem_sound, window,
        bundle=window.theme_mgr.current,)
    dlg.preview_opacity_changed.connect(window.window_state.set_opacity)
    dlg.preview_topmost_changed.connect(window.window_state.set_topmost)

    try:
        if dlg.exec() == QDialog.DialogCode.Accepted:
            apply_settings(window, dlg)
        else:
            window.window_state.set_opacity(orig_opacity)
            window.window_state.set_topmost(orig_topmost)
            window.tray_mgr.update_topmost_check(orig_topmost)
    finally:
        # QDialog 无 parent 管理时 exec 后不会自动销毁；显式 deleteLater
        # 避免反复打开设置对话框在事件循环中累积 C++ 对象。
        dlg.deleteLater()


def apply_settings(window, dlg: SettingDialog) -> None:
    new_cfg = copy.deepcopy(dlg.cfg)
    new_lang = dlg.get_language()
    lang_changed = new_lang != config.get("language", "zh_CN")
    new_cfg["language"] = new_lang

    # 主题：先切换，失败则回滚为当前主题名。
    # - set_theme 成功：内部已 config.set("theme_name", name, save=True)，
    #   随后 replace_all 再写同值，幂等。
    # - set_theme 失败：new_theme_name 回滚为当前主题名，replace_all
    #   写入旧主题名，磁盘与内存一致（不会重启后变 light）。
    new_theme_name = dlg.get_theme_name()
    if new_theme_name and new_theme_name != window.theme_mgr.current.name:
        if not window.theme_mgr.set_theme(new_theme_name):
            new_theme_name = window.theme_mgr.current.name
    new_cfg["theme_name"] = new_theme_name or window.theme_mgr.current.name

    final_topmost = bool(dlg.get_topmost_status())
    final_opacity = float(dlg.get_opacity())
    new_cfg["topmost"] = final_topmost
    new_cfg["opacity"] = final_opacity
    # deepcopy：dlg.get_memorial_list() 返回 dlg.cfg 内部 list 引用，
    # 直接赋给 new_cfg 会让 config 与 dlg 共享同一 list；dlg 关闭后
    # 若被第三方持有并修改，会污染 config。
    new_cfg["memorial_days"] = copy.deepcopy(dlg.get_memorial_list())

    mem_cfg = dict(new_cfg.get("memorial_cfg") or {})
    mem_cfg["enable_remind"] = bool(dlg.get_mem_remind())
    mem_cfg["sound_enable"] = bool(dlg.get_mem_sound())
    new_cfg["memorial_cfg"] = mem_cfg

    config.replace_all(new_cfg, save=False)
    config.flush()

    window.window_state.set_opacity(final_opacity)
    window.window_state.set_topmost(final_topmost)

    event_bus.publish(EventType.MEMORIAL_CHANGED, check_today=True)
    window.tray_mgr.update_topmost_check(final_topmost)
    if lang_changed:
        set_language(new_lang)

    want_auto = dlg.get_auto_start_status()
    if want_auto != check_auto_start():
        apply_auto_start(window, want_auto)