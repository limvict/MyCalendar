# coding: utf-8
"""更新检查：版本比较、清单拉取、环境检测。"""

import json
import re
import sys
from collections.abc import Sequence
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PyQt6.QtCore import QThread, pyqtSignal

from desktop_calendar.config.manager import get_logger

logger = get_logger()

UPDATE_MANIFEST_URL = "https://github.com/limvict/MyCalendar/releases/latest/download/version.json"
# GitHub 在部分网络（尤其国内）不可达；安装包下载已在 release.yml 配了
# ghproxy 镜像，清单也走同一批前缀，否则会出现"下载有镜像、检测却静默失败"。
UPDATE_MANIFEST_MIRROR_PREFIXES = (
    "https://ghproxy.net/",
    "https://mirror.ghproxy.com/",
    "https://gh-proxy.com/",
)
CURRENT_VERSION = "3.1.5"
CHECK_TIMEOUT = 10


def manifest_urls(primary: str = UPDATE_MANIFEST_URL) -> tuple[str, ...]:
    """主地址 + 镜像地址，去重后只保留合法 https 地址。

    主地址本身不是 https 时直接返回空：给非 https 地址套 ghproxy 前缀
    只会得到"看起来合法、实际指向不了"的镜像 URL。
    """
    if not _is_safe_https_url(primary):
        return ()
    candidates = [primary]
    candidates.extend(prefix + primary for prefix in UPDATE_MANIFEST_MIRROR_PREFIXES)
    return tuple(dict.fromkeys(candidates))


# 清单体积上限：正常 version.json 只有几百字节，1 MiB 足够宽松，
# 同时防止被篡改的远端返回超大 JSON 拖垮内存/解析。
_MAX_MANIFEST_BYTES = 1 << 20

# 仅 X.Y.Z：构建链（_version.validate_ver）与 release.yml 拒绝预发布后缀，
# 运行时同步收紧，避免"能检查到却装不了"的错配。
_SAFE_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_PLACEHOLDER_URL_TOKENS = ("yourname", "yourrepo", "<org>", "<repo>", "<your")


def _parse_version(v: str) -> tuple:
    """解析 X.Y.Z 为整数元组。契约由 tests/test_update_manager.py 锁定。

    非数字段回退为 0 是防御性的：版本源已被 _SAFE_VERSION_RE 校验为
    纯 X.Y.Z，正常路径走不到；保留是为了 manifest 被篡改时不抛异常。
    """
    parts = []
    for seg in str(v).split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _is_newer(remote: str, local: str) -> bool:
    """判断 remote 是否为比 local 更新的版本（仅 X.Y.Z 正式版）。"""
    return _parse_version(remote) > _parse_version(local)


def _is_packaged() -> bool:
    if getattr(sys, "frozen", False):
        return True
    if getattr(sys, "_MEIPASS", None) is not None:
        return True
    if getattr(sys, "nuitka_version", None):
        return True
    # Nuitka 也可能注入 __compiled__
    if globals().get("__compiled__"):
        return True
    return False


def _is_placeholder_url(url: str) -> bool:
    if not url:
        return True
    lowered = url.lower()
    return any(t in lowered for t in _PLACEHOLDER_URL_TOKENS)


def _is_safe_https_url(url: str) -> bool:
    """https 且 host 非空。与 scripts/_version.is_safe_https_url 同构。"""
    try:
        p = urlparse(url)
        return p.scheme == "https" and bool(p.netloc)
    except Exception:
        return False


def _is_safe_download_url(url: str) -> bool:
    """download_url 的协议校验（保留旧名字，语义与 https 校验一致）。"""
    return _is_safe_https_url(url)


def _host_of(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


# 生产清单 version.json 是只读产物：运行时只读校验，不修正、不回写。
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
# https，且不含空白 / 引号 / 尖括号：防止字段里夹带控制字符或截断
_MANIFEST_URL_RE = re.compile(r"^https://[^\s\"'<>]+$")


def manifest_problems(info) -> list[str]:
    """用正则校验 version.json 的字段，返回问题列表（空表示合法）。

    只校验、不修正：清单由发布流程生成，客户端与校验脚本都只读它。
    任何一条不合法都意味着清单被篡改或生成链有 bug，调用方应整体拒绝。
    """
    if not isinstance(info, dict):
        return ["version.json 根节点不是对象"]

    problems: list[str] = []

    version = info.get("version")
    if not isinstance(version, str) or not _SAFE_VERSION_RE.fullmatch(version.strip()):
        problems.append(f"version 必须为 X.Y.Z（当前 {version!r}）")

    sha = info.get("sha256")
    if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
        problems.append(f"sha256 必须为 64 位十六进制（当前 {sha!r}）")

    url = info.get("download_url")
    if not isinstance(url, str) or not _MANIFEST_URL_RE.fullmatch(url):
        problems.append(f"download_url 必须为 https 且不含空白/引号（当前 {url!r}）")
    elif not _is_safe_https_url(url):
        problems.append(f"download_url host 为空（当前 {url!r}）")

    mirrors = info.get("download_url_mirrors")
    if mirrors is not None:
        if not isinstance(mirrors, list):
            problems.append("download_url_mirrors 必须是列表")
        else:
            for index, mirror in enumerate(mirrors):
                if not isinstance(mirror, str) or not _MANIFEST_URL_RE.fullmatch(mirror):
                    problems.append(f"download_url_mirrors[{index}] 非法：{mirror!r}")

    notes = info.get("release_notes")
    if notes is not None and not isinstance(notes, str):
        problems.append("release_notes 必须是字符串")

    return problems


class UpdateChecker(QThread):
    """拉取 version.json：按地址顺序尝试（主站 + 镜像），全部失败才报错。"""

    checked = pyqtSignal(dict)

    def __init__(self, urls: str | Sequence[str], parent=None):
        super().__init__(parent)
        if isinstance(urls, str):
            urls = [urls]
        candidates = [u for u in dict.fromkeys(urls or []) if isinstance(u, str) and u]
        self._urls = tuple(u for u in candidates if _is_safe_https_url(u))
        rejected = [u for u in candidates if u not in self._urls]
        if rejected:
            logger.warning("忽略非 https 的更新清单地址: %r", rejected)
        # 测试/诊断用：本次实际会尝试的地址
        self.urls = self._urls

    def run(self):
        result = {"has_update": False, "info": {}, "error": None, "manifest_url": ""}
        if not self._urls:
            result["error"] = "没有可用的更新清单地址（必须为 https）"
            self.checked.emit(result)
            return

        attempts: list[str] = []
        for url in self._urls:
            try:
                data = self._fetch_json(url)
                remote_ver = self._validate_manifest(data)
                result["info"] = data
                result["manifest_url"] = url
                result["has_update"] = _is_newer(remote_ver, CURRENT_VERSION)
                break
            except Exception as e:
                # 任一地址失败都继续尝试下一个（镜像可能返回代理错误页）
                attempts.append(f"{_host_of(url)}: {e}")
                logger.warning("更新清单地址失败 %s: %s", url, e)
        else:
            result["error"] = f"全部 {len(attempts)} 个清单地址均不可用：" + "；".join(attempts)
        self.checked.emit(result)

    @staticmethod
    def _fetch_json(url: str) -> dict:
        req = Request(url, headers={"User-Agent": "DLC-Updater"})
        with urlopen(req, timeout=CHECK_TIMEOUT) as resp:
            clen = resp.headers.get("Content-Length")
            if clen and clen.strip().isdigit() and int(clen) > _MAX_MANIFEST_BYTES:
                raise ValueError(f"version.json 过大（{clen} 字节），拒绝解析")
            raw_bytes = resp.read()
        if len(raw_bytes) > _MAX_MANIFEST_BYTES:
            raise ValueError(f"version.json 超过 {_MAX_MANIFEST_BYTES} 字节上限")
        data = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("version.json 根节点不是 dict")
        return data

    @staticmethod
    def _validate_manifest(data: dict) -> str:
        remote_ver = str(data.get("version", "")).strip()
        if not remote_ver:
            raise ValueError("version.json 缺少 version 字段")
        if not _SAFE_VERSION_RE.fullmatch(remote_ver):
            raise ValueError(f"version.json version 非 X.Y.Z 格式: {remote_ver!r}")
        return remote_ver
