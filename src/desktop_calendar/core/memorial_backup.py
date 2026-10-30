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
    """备份文件结构不符合预期（如缺少 memorial_days 字段）。"""


class BackupWriteError(OSError):
    """备份文件读取成功，但配置落盘失败（磁盘满 / 权限不足等）。

    继承 OSError 的理由：
      - 语义上"写盘失败"就是 IO 错误，OSError 是最贴切的基类；
      - 历史调用方 / 测试里写 `except OSError` 的路径保持兼容；
      - UI 侧显式 `except BackupWriteError` 优先于 `except OSError`
        匹配（Python 按 except 顺序），仍能拿到专门提示。
    """


def backup_to(path: str, config: ConfigManager) -> int:
    """导出纪念日到 JSON 文件。"""
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
    """从备份文件恢复纪念日，完全覆盖当前列表。

    异常契约：
      - BackupFormatError：文件读成功但结构不对（缺 memorial_days）。
      - json.JSONDecodeError / UnicodeDecodeError / OSError：
        读取阶段失败（文件损坏、编码错、权限不足）。
      - BackupWriteError（OSError 子类）：读取 + 归一化成功，但
        配置落盘失败。UI 应显式 `except BackupWriteError` 显示
        "保存配置失败"而非"读取备份失败"。
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    mem_list = (data if isinstance(data, list)
                else data.get("memorial_days") if isinstance(data, dict)
                else None)
    if not isinstance(mem_list, list):
        raise BackupFormatError("backup file has no memorial_days list")

    normalized, skipped = normalize_memorial_days(mem_list)
    if skipped:
        logger.warning(
            "恢复：%d 条归一化失败被跳过（详见 debug 日志）", skipped)

    config.set("memorial_days", normalized, save=False)
    # raise_on_error=True：restore_from 是数据安全场景，必须区分
    # "已写盘成功"与"内存改了但磁盘写失败"。默认的 flush() 吞异常，
    # 会导致 MemorialDataManager.restore 误报成功，用户重启后丢数据。
    try:
        config.flush(raise_on_error=True)
    except Exception as e:
        # 包装成 BackupWriteError：读阶段已成功，写阶段失败。
        # 继承 OSError 让历史上写 `except OSError` 的调用方继续兼容；
        # UI 侧显式 `except BackupWriteError` 优先匹配，得到专用提示。
        raise BackupWriteError(str(e)) from e

    logger.info(
        "纪念日已从 %s 恢复，共 %d 条，跳过 %d 条",
        path, len(normalized), skipped)
    return len(normalized), skipped