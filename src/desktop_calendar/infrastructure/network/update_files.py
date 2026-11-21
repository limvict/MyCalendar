# coding: utf-8
"""更新包文件操作：校验和、安装器路径、日志与旧包清理。"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time

from desktop_calendar.config.manager import get_logger

logger = get_logger()


_INSTALLER_PREFIX = "DLC_Setup_"


_INSTALL_LOG_PREFIX = "DLC_install_"


_ORPHAN_INSTALLER_MAX_AGE_SEC = 86400


_INSTALLER_LAUNCH_PROBE_SEC = 3.0


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _safe_name_part(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._\-]", "_", str(value or "")).strip("._")
    return cleaned or "unknown"


def _installer_path(version: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"{_INSTALLER_PREFIX}{_safe_name_part(version)}.exe")


def _install_log_path(version: str) -> str:
    return os.path.join(
        tempfile.gettempdir(), f"{_INSTALL_LOG_PREFIX}{_safe_name_part(version)}.log"
    )


def _read_log_tail(path: str, max_lines: int = 20) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return ""
    return "".join(lines[-max_lines:]).strip()


def _cleanup_old_installers(keep: str) -> None:
    tmp_dir = tempfile.gettempdir()
    keep_norm = os.path.normcase(os.path.normpath(keep)) if keep else None
    now = time.time()
    try:
        names = os.listdir(tmp_dir)
    except OSError:
        return
    for name in names:
        is_installer = name.startswith(_INSTALLER_PREFIX) and name.endswith(".exe")
        is_log = name.startswith(_INSTALL_LOG_PREFIX) and name.endswith(".log")
        if not (is_installer or is_log):
            continue
        full = os.path.normpath(os.path.join(tmp_dir, name))
        if is_installer and keep_norm is not None and (os.path.normcase(full) == keep_norm):
            continue
        try:
            if now - os.path.getmtime(full) < _ORPHAN_INSTALLER_MAX_AGE_SEC:
                continue
            os.remove(full)
            logger.info("清理旧更新文件: %s", full)
        except OSError:
            pass
