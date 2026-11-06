# coding: utf-8
"""更新检查：版本比较、清单拉取、环境检测。"""
import json
import re
import sys
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import URLError

from PyQt6.QtCore import QThread, pyqtSignal

from desktop_calendar.config.manager import get_logger

logger = get_logger()

UPDATE_MANIFEST_URL = (
    "https://github.com/limvict/MyCalendar/releases/latest/download/version.json")
CURRENT_VERSION = "3.0.4"
CHECK_TIMEOUT = 10

_SAFE_VERSION_RE = re.compile(r"^[0-9A-Za-z._\-]+$")
_PLACEHOLDER_URL_TOKENS = ("yourname", "yourrepo", "<org>", "<repo>", "<your")


def _parse_version(v: str) -> tuple:
    """解析版本号为整数元组。契约由 tests/test_update_manager.py 锁定。"""
    parts = []
    for seg in str(v).split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def _is_packaged() -> bool:
    return (
        getattr(sys, "frozen", False)
        or getattr(sys, "_MEIPASS", None) is not None
        or hasattr(sys, "nuitka_version")
    )


def _is_placeholder_url(url: str) -> bool:
    if not url:
        return True
    return any(t in url.lower() for t in _PLACEHOLDER_URL_TOKENS)


def _is_safe_download_url(url: str) -> bool:
    try:
        p = urlparse(url)
        # 自更新 = 最高权限操作。允许 http 时中间人可同时替换
        # 安装包与 manifest 里的 sha256，完整性校验形同虚设。
        return p.scheme == "https" and bool(p.netloc)
    except Exception:
        return False


class UpdateChecker(QThread):
    checked = pyqtSignal(dict)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        result = {"has_update": False, "info": {}, "error": None}
        try:
            req = Request(self._url, headers={"User-Agent": "DLC-Updater"})
            with urlopen(req, timeout=CHECK_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("version.json 根节点不是 dict")
            remote_ver = str(data.get("version", "")).strip()
            if not remote_ver:
                raise ValueError("version.json 缺少 version 字段")
            if not _SAFE_VERSION_RE.fullmatch(remote_ver):
                raise ValueError(
                    f"version.json version 含非法字符: {remote_ver!r}")
            result["info"] = data
            result["has_update"] = _is_newer(remote_ver, CURRENT_VERSION)
        except (URLError, TimeoutError) as e:
            result["error"] = f"网络不可达: {e}"
        except (json.JSONDecodeError, ValueError) as e:
            result["error"] = f"版本清单解析失败: {e}"
        except Exception as e:
            result["error"] = f"检查更新异常: {e}"
        self.checked.emit(result)