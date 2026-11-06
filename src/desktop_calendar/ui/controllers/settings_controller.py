import copy
from PyQt6.QtWidgets import QDialog

from desktop_calendar.ui.controllers.startup import (
    check_auto_start, apply_auto_start,
)
from desktop_calendar.ui.dialogs import SettingDialog, msg_error   
from desktop_calendar.contracts.event_bus import EventType , event_bus
from desktop_calendar.config.i18n import set_language, tr 
from desktop_calendar.config.manager import config, get_logger

logger = get_logger()


def open_settings_dialog(window) -> None:
    snapshot = config.snapshot()
    orig_opacity = float(snapshot.get("opacity", 0.92))

    mem_cfg = snapshot.get("memorial_cfg") or {}
    mem_remind = bool(mem_cfg.get("enable_remind", True))
    mem_sound = bool(mem_cfg.get("sound_enable", True))

    auto_start = check_auto_start()
    dlg = SettingDialog(
        snapshot, auto_start, orig_opacity,
        mem_remind, mem_sound, window,
        bundle=window.theme_mgr.current,)
    dlg.preview_opacity_changed.connect(window.window_state.set_opacity)

    try:
        if dlg.exec() == QDialog.DialogCode.Accepted:
            apply_settings(window, dlg)
        else:
            window.window_state.set_opacity(orig_opacity)
    finally:
        # QDialog 无 parent 管理时 exec 后不会自动销毁；显式 deleteLater
        # 避免反复打开设置对话框在事件循环中累积 C++ 对象。
        dlg.deleteLater()


def apply_settings(window, dlg: SettingDialog) -> None:
    # 完整快照：任何失败路径都回滚到此状态。
    # 注意 theme_mgr.current.name 与 snapshot["theme_name"] 可能不同
    # （ThemeManager 初始化时可能回写过磁盘），以内存 snapshot 为准。
    old_snapshot = config.snapshot()
    old_opacity = float(old_snapshot.get("opacity", 0.92))
    old_theme_name = window.theme_mgr.current.name
    old_lang = config.get("language", "zh_CN")

    new_cfg = copy.deepcopy(dlg.cfg)
    new_lang = dlg.get_language()
    lang_changed = new_lang != old_lang
    new_cfg["language"] = new_lang
 
    # 主题：先切换，失败则沿用当前主题名。
    new_theme_name = dlg.get_theme_name()
    if new_theme_name and new_theme_name != old_theme_name:
        if not window.theme_mgr.set_theme(new_theme_name):
            new_theme_name = old_theme_name
    new_cfg["theme_name"] = new_theme_name or old_theme_name
 
    final_opacity = float(dlg.get_opacity())
    new_cfg["opacity"] = final_opacity

    new_cfg["memorial_days"] = copy.deepcopy(dlg.get_memorial_list())
 
    mem_cfg = dict(new_cfg.get("memorial_cfg") or {})
    mem_cfg["enable_remind"] = bool(dlg.get_mem_remind())
    mem_cfg["sound_enable"] = bool(dlg.get_mem_sound())
    new_cfg["memorial_cfg"] = mem_cfg
 
    def _rollback(reason: str) -> None:
        """回滚内存 + 主题 + 预览 opacity + 磁盘（尽力而为）。

        顺序：内存先回滚（保证后续读路径看到旧值），再回滚主题
        （set_theme 内部会 flush 主题名），最后尝试 flush 整体。
        任何子步骤失败只记日志——回滚本身已在异常路径上，不能让
        回滚失败再抛异常打断用户。
        """
        try:
            config.replace_all(old_snapshot, save=False)
        except Exception:
            logger.exception("回滚内存配置失败（可能残留不一致）")
        if window.theme_mgr.current.name != old_theme_name:
            try:
                window.theme_mgr.set_theme(old_theme_name)
            except Exception:
                logger.exception("回滚主题到 %r 失败", old_theme_name)
        try:
            window.window_state.set_opacity(old_opacity)
        except Exception:
            logger.exception("回滚窗口透明度失败")
        try:
            config.flush(raise_on_error=True)
        except Exception:
            logger.exception(
                "回滚后 flush 仍失败，磁盘可能与内存不一致（%s）", reason)

    try:
         config.replace_all(new_cfg, save=False)
    except Exception as e:
        logger.exception("设置归一化失败: %s", e)
        _rollback("replace_all_failed")
        msg_error(window, tr("msg.error"),
                tr("setting.save_failed").format(error=e))
        return
    try:
        config.flush(raise_on_error=True)
    except Exception as e:
        logger.exception("设置保存失败: %s", e)
        _rollback("flush_failed")
        msg_error(window, tr("msg.error"),
                tr("setting.save_failed").format(error=e))
        return    

    # 落盘成功后才应用剩余 UI 状态。opacity 已被 preview 信号驱动过，
    # 但语言 / 纪念日 / 自启还未生效。
    window.window_state.set_opacity(final_opacity)
 
    event_bus.publish(EventType.MEMORIAL_CHANGED, check_today=True)
    if lang_changed:
        set_language(new_lang)
 
    want_auto = dlg.get_auto_start_status()
    if want_auto != check_auto_start():
        apply_auto_start(window, want_auto)