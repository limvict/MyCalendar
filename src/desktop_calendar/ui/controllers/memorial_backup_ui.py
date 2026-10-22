# coding: utf-8
"""纪念日备份/恢复的 UI 适配器：只负责文件选择与弹窗。"""
import json

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog

from desktop_calendar.contracts.event_bus import event_bus
from desktop_calendar.contracts.events import EventType
from desktop_calendar.ui.dialogs import msg_info, msg_error
from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import ConfigManager, get_logger
from desktop_calendar.core.memorial_backup import (
    backup_to, restore_from, BackupFormatError,
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
            logger.error("备份纪念日失败: %s", e)
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.failed").format(error=e))
            return
        msg_info(self.parent, tr("msg.success"),
                 tr("backup.success").format(count=count))

    def restore(self):
        path, _ = QFileDialog.getOpenFileName(
            self.parent, tr("backup.dialog_restore_title"), "",
            "JSON (*.json)")
        if not path:
            return
        try:
            count, skipped = restore_from(path, self.config)
        except json.JSONDecodeError as e:
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.read_failed").format(error=e))
            return
        except UnicodeDecodeError as e:
            # 非 UTF-8 备份（老版记事本存 GBK 等）。
            # 必须早于 BackupFormatError/ValueError：UnicodeDecodeError
            # 是 ValueError 子类，晚捕获会被误报为"格式错误"。
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.read_failed").format(error=e))
            return
        except BackupFormatError:
            # 精确匹配：JSON 合法但结构不对
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.format_error"))
            return
        except Exception as e:
            logger.error("恢复纪念日失败: %s", e)
            msg_error(self.parent, tr("msg.error"),
                      tr("backup.read_failed").format(error=e))
            return

        event_bus.publish(EventType.MEMORIAL_CHANGED, check_today=True)
        tail = (tr("backup.restore_skipped").format(count=skipped)
                if skipped else "")
        msg_info(self.parent, tr("msg.success"),
                 tr("backup.restore_success").format(
                     count=count, tail=tail))