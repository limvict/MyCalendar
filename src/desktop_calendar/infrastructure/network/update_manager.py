# coding: utf-8
"""自动更新调度器（UpdateManager 对外唯一入口）。

本模块拆分为 4 个文件：
  - update_checker.py   版本比较、清单拉取、环境检测
  - update_bat.py       替换脚本生成、state 文件读写
  - update_downloader.py 下载线程
  - update_manager.py   本文件（调度 + 镜像合并 + 重试）
"""
import os
import sys
from typing import Optional

from PyQt6.QtCore import QObject

from desktop_calendar.config.manager import config, get_logger
from desktop_calendar.contracts.event_bus import event_bus, EventType

# 兼容性 re-export（保留旧 import 路径 + 测试 fixture）
from desktop_calendar.infrastructure.network.update_checker import (
    UPDATE_MANIFEST_URL, CURRENT_VERSION, CHECK_TIMEOUT,
    _parse_version, _is_newer, _is_packaged, _is_placeholder_url,
    _is_safe_download_url, _SAFE_VERSION_RE, UpdateChecker,
)
from desktop_calendar.infrastructure.network.update_bat import (
    _WAIT_EXIT_MAX_SEC, _NEW_VERSION_PROBE_SEC, _OLD_EXE_SUFFIX,
    _state_file_path, _clear_state_file, _tmp_exe_name, _tmp_bat_name,
    _tmp_log_name, _cleanup_leftover_new_exe, _cleanup_orphan_update_logs,
    consume_state_file, build_bat_script,
)
from desktop_calendar.infrastructure.network.update_downloader import (
    UpdateDownloader, precheck_install_target, DOWNLOAD_TIMEOUT,
    _sha256_of_file, _is_retryable_network_error,
)

logger = get_logger()

__all__ = [
    "UpdateManager", "UpdateChecker", "UpdateDownloader",
    "UPDATE_MANIFEST_URL", "CURRENT_VERSION",
    "consume_state_file", "precheck_install_target",
]


def _collect_mirrors(info: dict) -> list[str]:
    """从 manifest 收集所有镜像地址（去重保序）。

    优先读 download_url_mirrors（列表，新格式），再合并
    download_url_mirror（单个，旧格式兼容）。
    """
    out: list[str] = []
    seen: set = set()
    mirrors = info.get("download_url_mirrors")
    if isinstance(mirrors, list):
        for m in mirrors:
            if isinstance(m, str) and m and m not in seen:
                seen.add(m)
                out.append(m)
    single = info.get("download_url_mirror")
    if isinstance(single, str) and single and single not in seen:
        seen.add(single)
        out.append(single)
    return out


class UpdateManager(QObject):
    """自动更新调度器：对外的唯一入口。"""

    def __init__(self, parent=None, manifest_url: str = UPDATE_MANIFEST_URL):
        super().__init__(parent)
        self._manifest_url = manifest_url
        self._checker: Optional[UpdateChecker] = None
        self._downloader: Optional[UpdateDownloader] = None
        self._pending_info: dict = {}
        self._orphan_threads: list = []
        self._retry_version: str = ""

    def check_async(self, retry_version: str = "") -> bool:
        if not _is_packaged():
            logger.debug("非打包环境，跳过自动更新检查")
            return False
        if _is_placeholder_url(self._manifest_url):
            logger.info("更新地址尚未配置（占位符 URL），跳过自动更新检查")
            return False
        if self._checker is not None and self._checker.isRunning():
            logger.debug("版本检查进行中，忽略重复请求")
            return False

        self._retry_version = str(retry_version or "").strip()
        self._checker = UpdateChecker(self._manifest_url, self)
        self._checker.finished.connect(self._checker.deleteLater)
        self._checker.checked.connect(self._on_checked)
        self._checker.start()
        return True

    def _on_checked(self, result: dict):
        self._checker = None
        retry_version = self._retry_version
        self._retry_version = ""

        if result.get("error"):
            logger.debug(f"版本检查未命中: {result['error']}")
            return
        if not result.get("has_update"):
            if retry_version:
                logger.warning(
                    f"重试目标版本 {retry_version} 在远程已不可用，放弃")
            else:
                logger.debug("当前已是最新版本")
            return

        info = result.get("info", {})
        if not isinstance(info, dict):
            logger.warning(
                f"version.json info 非 dict: {type(info).__name__}")
            return

        required = ("version", "download_url", "sha256")
        missing = [k for k in required if not info.get(k)]
        if missing:
            logger.warning(
                f"version.json 缺少必填字段 {missing}，忽略本次更新。")
            return
        if not _is_safe_download_url(info.get("download_url", "")):
            logger.warning(
                f"download_url 协议非法或格式错误: "
                f"{info.get('download_url')!r}")
            return

        valid_mirrors: list[str] = []
        for m in _collect_mirrors(info):
            if _is_safe_download_url(m):
                valid_mirrors.append(m)
            else:
                logger.warning("镜像地址非法，已忽略: %r", m)
        if valid_mirrors:
            info["download_url_mirrors"] = valid_mirrors
            info["download_url_mirror"] = valid_mirrors[0]
            logger.info(
                "启用 %d 个下载镜像: %s", len(valid_mirrors), valid_mirrors)
        else:
            info.pop("download_url_mirror", None)
            info.pop("download_url_mirrors", None)

        version = str(info.get("version", "")).strip()

        # 用户显式"重试"优先于历史"忽略"记录
        if retry_version and version and (
                _parse_version(version) == _parse_version(retry_version)):
            logger.info(f"按用户重试意图直接下载版本 {version}")
            self._pending_info = info
            if not self.download_and_apply_async():
                event_bus.publish(
                    EventType.UPDATE_FAILED, stage="download",
                    error=f"retry download start failed for {version}")
            return

        skipped = config.get("update_skipped_version", "") or ""
        if skipped and version and (
                _parse_version(version) == _parse_version(skipped)):
            logger.info(f"版本 {version} 已被用户忽略，跳过提示")
            return

        self._pending_info = info
        logger.info(f"发现新版本 {version}（当前 {CURRENT_VERSION}）")
        event_bus.publish(EventType.UPDATE_AVAILABLE, info=info)

    def download_and_apply_async(self) -> bool:
        """启动下载流程。返回值契约：

        - True ：已启动下载线程，或预检失败但已通过 event_bus 发出
                 UPDATE_FAILED(stage="precheck")。
        - False：静默拒绝（非打包 / 非 win32 / 缺字段 / 正在下载）。
        """
        if not _is_packaged():
            logger.warning("非打包环境，拒绝执行自动替换")
            return False
        if sys.platform != "win32":
            logger.warning(
                "自动替换仅支持 Windows，当前平台为 %s", sys.platform)
            return False
        if not self._pending_info:
            logger.warning("无待下载的更新信息")
            return False
        if self._downloader is not None and self._downloader.isRunning():
            logger.debug("下载进行中，忽略重复请求")
            return False

        precheck_error = precheck_install_target(sys.executable)
        if precheck_error:
            logger.warning("更新预检失败: %s", precheck_error)
            event_bus.publish(
                EventType.UPDATE_FAILED, stage="precheck",
                error=precheck_error,
                download_url=self._pending_info.get("download_url", ""),
            )
            return True

        url = self._pending_info.get("download_url")
        sha = self._pending_info.get("sha256", "")
        version = str(self._pending_info.get("version", "")).strip()
        if not url:
            logger.warning("version.json 缺少 download_url")
            return False
        if not sha:
            logger.warning("version.json 缺少 sha256，拒绝下载")
            return False
        if not _SAFE_VERSION_RE.fullmatch(version):
            logger.warning(
                f"version.json 的 version 字段含非法字符，拒绝下载: "
                f"{version!r}")
            return False

        # 主 URL 在前，镜像作为 fallback。
        urls = [url] + [
            m for m in _collect_mirrors(self._pending_info) if m != url
        ]

        self._downloader = UpdateDownloader(
            urls, sha, os.getpid(), target_version=version, parent=self)
        self._downloader.finished.connect(self._downloader.deleteLater)
        self._downloader.finished_download.connect(self._on_downloaded)
        self._downloader.progress.connect(self._on_progress)
        self._downloader.start()
        return True

    def cancel_download(self) -> bool:
        if self._downloader is None or not self._downloader.isRunning():
            return False
        self._downloader.cancel()
        return True

    def _on_progress(self, pct: int):
        event_bus.publish(EventType.UPDATE_PROGRESS, percent=int(pct))

    def _on_downloaded(self, result: dict):
        self._downloader = None
        if result.get("cancelled"):
            logger.info("更新下载已取消")
            return
        if not result.get("ok"):
            logger.error(f"更新下载失败: {result.get('error')}")
            event_bus.publish(
                EventType.UPDATE_FAILED, stage="download",
                error=result.get("error", "unknown"),
                download_url=(self._pending_info or {}).get(
                    "download_url", ""),
            )
            return
        logger.info("更新已就绪，等待主程序退出")
        event_bus.publish(EventType.UPDATE_READY)

    def consume_pending_failure(self) -> Optional[dict]:
        return consume_state_file()

    def shutdown(self):
        d = self._downloader
        if d is not None:
            try:
                d.cancel()
            except Exception:
                pass
            if d.isRunning() and not d.wait(8000):
                logger.warning("下载线程未在 8s 内退出，保留引用")
                try:
                    d.cleanup_partial()
                except Exception:
                    logger.debug("cleanup_partial 异常", exc_info=True)
                self._orphan_threads.append(d)
            self._downloader = None

        c = self._checker
        if c is not None:
            if c.isRunning() and not c.wait(3000):
                logger.warning("检查线程未在 3s 内退出，保留引用")
                self._orphan_threads.append(c)
            self._checker = None