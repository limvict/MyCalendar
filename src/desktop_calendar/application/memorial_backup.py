# coding: utf-8
"""纪念日备份/恢复的纯逻辑：不碰 Qt 控件、不弹窗。"""
import json
from datetime import datetime
from typing import Any

from desktop_calendar.config.config import ConfigManager, get_logger
from desktop_calendar.core.memorial import normalize_memorial

logger = get_logger()
BACKUP_FORMAT_VERSION = 1


def backup_to(path: str, config: ConfigManager) -> int:
    """导出 memorial_days 到 path，返回导出条数。失败抛异常。"""
    raw = config.get("memorial_days", []) or []
    if not isinstance(raw, list):
        logger.warning(
            "memorial_days 类型异常（%s），按空列表导出", type(raw).__name__)
        raw = []
    payload = {
        "version": BACKUP_FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "memorial_days": raw,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("纪念日已备份到 %s，共 %d 条", path, len(raw))
    return len(raw)


def restore_from(path: str, config: ConfigManager) -> tuple[int, int]:
    """从 path 恢复 memorial_days，返回 (恢复条数, 跳过条数)。失败抛异常。"""
    with open(path, "r", encoding="utf-8") as f:
        data: Any = json.load(f)

    # 兼容 {"memorial_days":[...]} 与裸 list
    if isinstance(data, list):
        mem_list = data
    elif (isinstance(data, dict)
          and isinstance(data.get("memorial_days"), list)):
        mem_list = data["memorial_days"]
    else:
        raise ValueError("backup.format_error")

    normalized = []
    skipped = 0
    for i, item in enumerate(mem_list):
        if not isinstance(item, dict):
            logger.warning("跳过第 %d 条（非 dict）：%r", i, item)
            skipped += 1
            continue
        try:
            normalized.append(normalize_memorial(item))
        except Exception as e:
            logger.warning("第 %d 条纪念日归一化失败，已跳过: %s", i, e)
            skipped += 1

    config.set("memorial_days", normalized, save=False)
    config.flush()
    logger.info(
        "纪念日已从 %s 恢复，共 %d 条，跳过 %d 条",
        path, len(normalized), skipped)
    return len(normalized), skipped