# coding: utf-8
"""自动更新相关的 UI 控制器。

主窗口只保留事件订阅转发，全部弹窗交互（询问、进度、失败提示、
上次失败处理）集中在此类。
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QObject
from PyQt6.QtWidgets import QMessageBox, QProgressDialog

from desktop_calendar.config.manager import config, get_logger
from desktop_calendar.config.i18n import tr
from desktop_calendar.ui.dialogs import msg_error

logger = get_logger()

# 上次更新失败原因 → i18n key
_REASON_I18N_KEYS = {
    "backup_failed":         "update.reason.backup_failed",
    "install_failed":        "update.reason.install_failed",
    "probe_failed":          "update.reason.probe_failed",
    "rollback_failed":       "update.reason.rollback_failed",
    "probe_rollback_failed": "update.reason.probe_rollback_failed",
}


class UpdateUIController(QObject):
    """自动更新的全部弹窗交互。

    与 MainWindow 约定：
    - 构造时传 parent_widget（作为对话框 parent）
    - 主窗口通过 update_mgr 发起检查 / 下载；本类只负责 UI
    """

    def __init__(self, parent_widget, update_mgr, window_quit_cb):
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._update_mgr = update_mgr
        self._quit_cb = window_quit_cb
        self._progress_dlg: Optional[QProgressDialog] = None
        self._progress_dismissed = False
        self._user_cancelled = False

    # ---------- 启动时检查 ----------
    def check_on_start(self) -> None:
        try:
            retry_ver = self._handle_pending_failure()
        except Exception:
            logger.exception("处理上次更新失败标记异常")
            retry_ver = ""
        try:
            started = self._update_mgr.check_async(retry_version=retry_ver)
            if retry_ver and not started:
                msg_error(
                    self._parent, tr("update.title"),
                    tr("update.failed").format(
                        error=tr("update.cannot_start")))
        except Exception:
            logger.exception("启动时检查更新失败")

    def _handle_pending_failure(self) -> str:
        """返回用户选择重试的版本号；空串表示无重试请求。"""
        state = self._update_mgr.consume_pending_failure()
        if not state:
            return ""

        version_raw = str(state.get("version") or "").strip()
        version_display = version_raw or "?"
        reason_key = _REASON_I18N_KEYS.get(state.get("reason", ""))
        reason_text = tr(reason_key) if reason_key else (state.get("reason") or "?")
        log_path = state.get("log_path") or "-"

        box = QMessageBox(self._parent)
        box.setWindowTitle(tr("update.title"))
        box.setText(tr("update.prev_failed").format(version=version_display))
        box.setInformativeText(tr("update.prev_failed_detail").format(
            reason=reason_text, log=log_path))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(
            QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Ignore)
        box.button(QMessageBox.StandardButton.Retry).setText(tr("update.retry"))
        box.button(QMessageBox.StandardButton.Ignore).setText(
            tr("update.ignore_version"))

        choice = box.exec()
        if choice == QMessageBox.StandardButton.Retry:
            if not version_raw:
                logger.warning("用户选择重试但 state 缺 version，忽略")
                return ""
            logger.info(f"用户选择重试版本 {version_raw} 的更新")
            return version_raw
        if choice == QMessageBox.StandardButton.Ignore:
            if version_raw:
                config.set("update_skipped_version", version_raw, save=True)
                logger.info(f"用户忽略版本 {version_raw} 的失败提示")
            else:
                logger.warning(
                    "用户选择忽略但 state 缺 version，跳过写 update_skipped_version")
            return ""
        # 点叉 / Esc / NoButton：下次启动继续提示
        logger.debug(f"用户关闭上次更新失败提示（choice={choice}），本次不处理")
        return ""
    
    @staticmethod
    def _fix_mojibake(text: str) -> str:
        """尝试修复 UTF-8 被误认为 CP1252 造成的乱码。"""
        if not isinstance(text, str):
            return text
        try:
            fixed = text.encode("cp1252").decode("utf-8")
            if fixed != text:
                return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return text

    # ---------- 有新版本 ----------
    def on_available(self, data: dict = None) -> None:
        if not isinstance(data, dict):
            return
        info = data.get("info") or {}
        version = info.get("version", "?")
        notes = info.get("release_notes", "")

        if notes:
            # 调用时加上 self
            notes = self._fix_mojibake(notes)
        
        box = QMessageBox(self._parent)
        box.setWindowTitle(tr("update.title"))
        box.setText(tr("update.available").format(version=version))
        if notes:
            box.setInformativeText(notes)
        box.setIcon(QMessageBox.Icon.Information)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText(tr("update.download"))
        box.button(QMessageBox.StandardButton.No).setText(tr("update.later"))

        if box.exec() == QMessageBox.StandardButton.Yes:
            started = self._update_mgr.download_and_apply_async()
            if not started:
                msg_error(
                    self._parent, tr("update.title"),
                    tr("update.failed").format(error=tr("update.cannot_start")))
            self._progress_dismissed = False
            self._user_cancelled = False
            
    # ---------- 进度 ----------
    def on_progress(self, data: dict = None) -> None:
        if not isinstance(data, dict):
            return
        try:
            pct = int(data.get("percent", -1))
        except (TypeError, ValueError, OverflowError):
            return
        if pct < 0:
            return

        if self._progress_dlg is None:
            if self._progress_dismissed:
                return
            dlg = QProgressDialog(self._parent)
            dlg.setWindowTitle(tr("update.title"))
            dlg.setLabelText(tr("update.downloading"))
            dlg.setRange(0, 100)
            dlg.setValue(0)
            dlg.setCancelButtonText(tr("btn.cancel"))
            dlg.setMinimumDuration(0)
            dlg.setWindowModality(Qt.WindowModality.WindowModal)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            dlg.canceled.connect(self._on_progress_canceled)
            self._progress_dlg = dlg
            dlg.show()
        self._progress_dlg.setValue(min(100, max(0, pct)))

    def _on_progress_canceled(self) -> None:
        dlg = self._progress_dlg
        self._progress_dlg = None
        self._progress_dismissed = True
        self._user_cancelled = True 
        # 通知下载线程中止：cancelled=True 时不发 UPDATE_FAILED，不弹错误框
        try:
            self._update_mgr.cancel_download()
        except Exception:
            logger.exception("取消下载请求异常")
        if dlg is not None:
            try:
                dlg.canceled.disconnect(self._on_progress_canceled)
            except (TypeError, RuntimeError):
                pass
            try:
                dlg.close()
            except Exception:
                pass

    def close_progress(self) -> None:
        dlg = self._progress_dlg
        self._progress_dlg = None
        self._progress_dismissed = False
        if dlg is not None:
            try:
                dlg.canceled.disconnect(self._on_progress_canceled)
            except Exception:
                pass
            try:
                dlg.close()
            except Exception:
                pass

    # ---------- 失败 / 就绪 ----------
    def on_failed(self, data: dict = None) -> None:
        data = data or {}
        # 取消路径不发 UPDATE_FAILED，但防御性拦截：用户已取消时
        # 不再弹错误框，避免"点了取消又看到错误提示"的困惑。
        if self._user_cancelled:
            logger.info("用户已取消更新，忽略 UPDATE_FAILED")
            self.close_progress()
            return
        err = data.get("error", "")
        logger.warning(f"更新失败: {err}")
        self.close_progress()
        if data.get("stage") == "download":
            msg_error(self._parent, tr("update.title"),
                      tr("update.failed").format(error=err))

    def on_ready(self, _data=None) -> None:
        self.close_progress()
        if self._user_cancelled:
            # 用户已取消，不强制重启。此时 bat 可能已被 Popen（见下方
            # update_manager 侧的二次检查），最坏情况是 bat 在后台超时
            # 后写入 backup_failed 标记；配合 1.3 的 Popen 前二次检查
            # 与 Popen 后 kill 可消除该残留。
            logger.info("用户已取消更新，跳过重启")
            self._user_cancelled = False
            return
        QMessageBox.information(
            self._parent, tr("update.title"), tr("update.applying"))
        self._quit_cb()