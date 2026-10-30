# coding: utf-8
"""纪念日备份/恢复的 UI 适配器：只负责文件选择与弹窗。"""
import json

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from desktop_calendar.contracts.event_bus import event_bus
from desktop_calendar.contracts.events import EventType
from desktop_calendar.ui.dialogs import msg_info, msg_error
from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import ConfigManager, get_logger
from desktop_calendar.core.memorial_backup import (
    backup_to, restore_from, BackupFormatError, BackupWriteError,
)
logger = get_logger()


class MemorialDataManager(QObject):
    def __init__(self, parent_widget, config: ConfigManager):
        super().__init__(parent_widget)
        self.parent = parent_widget
        self.config = config

    def backup(self):
        from datetime import datetime
        default_name = (
            f"memorial_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        path, _ = QFileDialog.getSaveFileName(
            self.parent, tr("backup.dialog_title"), default_name,
            "JSON (*.json)")
        if not path:
            return
        try:
            count = backup_to(path, self.config)
        except Exception as e:
            # exception 保留 traceback：备份失败可能是磁盘满 / 权限 /
            # 序列化异常，仅 error 字符串会丢失根因。
            logger.exception("备份纪念日失败: %s", e)
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.failed").format(error=e))
            return
        msg_info(self.parent, tr("msg.success"),
                 tr("backup.success").format(count=count))

    def restore(self):
        # 检查当前纪念日数量：非空时弹确认，避免用户误以为"恢复"是
        # "合并"而丢失现有数据。恢复语义是快照覆盖，UI 必须明确告知。
        current = self.config.get("memorial_days", [])
        current_count = len(current) if isinstance(current, list) else 0

        path, _ = QFileDialog.getOpenFileName(
            self.parent, tr("backup.dialog_restore_title"), "",
            "JSON (*.json)")
        if not path:
            return

        if current_count > 0:
            reply = QMessageBox.question(
                self.parent,
                tr("backup.confirm_restore_title"),
                tr("backup.confirm_restore").format(count=current_count),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            count, skipped = restore_from(path, self.config)
        except BackupFormatError:
            msg_error(self.parent, tr("msg.error"), tr("backup.format_error"))
            return
        except BackupWriteError as e:
            # 读成功、写失败：不能提示"读取失败"，否则用户会去查备份文件
            # 而问题实际在磁盘 / 权限。
            logger.exception("恢复纪念日：配置落盘失败: %s", e)
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.write_failed").format(error=e))
            return
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.read_failed").format(error=e))
            return
        except Exception as e:
            logger.exception("恢复纪念日失败: %s", e)
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.read_failed").format(error=e))
            return

        tail = tr("backup.restore_skipped").format(count=skipped) if skipped else ""
        msg_info(self.parent, tr("msg.success"),
                 tr("backup.restore_success").format(
                     count=count, tail=tail))

        # 延迟 MEMORIAL_CHANGED 到弹窗关闭后：恢复大量纪念日时
        # reschedule(force=True) 在主线程同步遍历所有纪念日，可能
        # 耗时数秒。先让用户看到并关闭成功提示，事件循环下一轮
        # 再处理重排。注意不能放在 msg_info 之前——msg_info 是
        # 模态 exec 循环，singleShot(0) 的 timer 会在这个循环里触发，
        # 用户看到弹窗时主线程就开始卡，弹窗无法响应点击。
        if count > 100:
            logger.info("恢复 %d 条纪念日，开始重排（可能耗时数秒）", count)
        QTimer.singleShot(0, lambda: event_bus.publish(
            EventType.MEMORIAL_CHANGED, check_today=True))