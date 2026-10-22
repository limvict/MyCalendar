# coding: utf-8
"""纪念日备份/恢复的纯逻辑：不碰 Qt 控件、不弹窗。"""
import json
from datetime import datetime

from desktop_calendar.config.manager import (
    ConfigManager, get_logger, atomic_write_json,
)
from desktop_calendar.core.memorial import normalize_memorial_days

logger = get_logger()
BACKUP_FORMAT_VERSION = 1


class BackupFormatError(ValueError):
    """备份文件结构不符合预期（如缺少 memorial_days 字段）。

    继承 ValueError 的原因：
      - 语义上"格式不对"确实是 ValueError 的一种；
      - 任何历史上写成 `except ValueError` 的调用点不会因本次
        改动而漏捕获，属于向后兼容的加固而非破坏性重构。

    UI 侧应优先 `except BackupFormatError` 精确匹配，
    `except ValueError` 仅作兜底，避免"JSON 语法错"与
    "结构不对"两类错误被混为一谈。
    """


def backup_to(path: str, config: ConfigManager) -> int:
    raw = config.get("memorial_days", [])
    if not isinstance(raw, list):
        if raw is not None:
            logger.warning(
                "memorial_days 类型异常（%s），按空列表导出",
                type(raw).__name__)
        raw = []
    payload = {
        "version": BACKUP_FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "memorial_days": raw,
    }
    atomic_write_json(path, payload)
    logger.info("纪念日已备份到 %s，共 %d 条", path, len(raw))
    return len(raw)


def restore_from(path: str, config: ConfigManager) -> tuple:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        mem_list = data
    elif isinstance(data, dict) and isinstance(data.get("memorial_days"), list):
        mem_list = data["memorial_days"]
    else:
        raise BackupFormatError("backup file has no memorial_days list")

    normalized, skipped = normalize_memorial_days(mem_list)
    config.set("memorial_days", normalized, save=False)
    config.flush()
    logger.info(
        "纪念日已从 %s 恢复，共 %d 条，跳过 %d 条",
        path, len(normalized), skipped)
    return len(normalized), skipped