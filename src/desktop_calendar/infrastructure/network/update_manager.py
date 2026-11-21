# coding: utf-8
"""自动更新调度器。"""

import sys

from PyQt6.QtCore import QObject

from desktop_calendar.config.manager import config, get_logger
from desktop_calendar.contracts.event_bus import EventType, event_bus
from desktop_calendar.infrastructure.network.update_checker import (
    _SAFE_VERSION_RE,
    CURRENT_VERSION,
    UPDATE_MANIFEST_URL,
    UpdateChecker,
    _is_packaged,
    _is_placeholder_url,
    _is_safe_download_url,
    _parse_version,
    manifest_problems,
    manifest_urls,
)
from desktop_calendar.infrastructure.network.update_downloader import (
    UpdateDownloader,
)

logger = get_logger()

__all__ = [
    "UpdateManager",
    "UpdateChecker",
    "UpdateDownloader",
    "UPDATE_MANIFEST_URL",
    "CURRENT_VERSION",
]


def _collect_mirrors(info: dict) -> list[str]:
    out: list[str] = []
    seen: set = set()
    for key in ("download_url_mirrors", "download_url_mirror"):
        v = info.get(key)
        if isinstance(v, list):
            candidates = v
        elif isinstance(v, str):
            candidates = [v]
        else:
            continue
        for m in candidates:
            if not isinstance(m, str) or not m:
                continue
            if m in seen:
                continue
            seen.add(m)
            if _is_safe_download_url(m):
                out.append(m)
            else:
                logger.warning("镜像地址非法，已忽略: %r", m)
    return out


class UpdateManager(QObject):
    """自动更新调度器：对外的唯一入口。"""

    def __init__(self, parent=None, manifest_url: str = UPDATE_MANIFEST_URL):
        super().__init__(parent)
        self._manifest_url = manifest_url
        # 默认地址才带镜像；测试/自定义地址只用它自己，避免误连外网
        self._manifest_urls = (
            manifest_urls(manifest_url) if manifest_url == UPDATE_MANIFEST_URL else (manifest_url,)
        )
        self._checker: UpdateChecker | None = None
        self._downloader: UpdateDownloader | None = None
        self._pending_info: dict = {}
        self._orphan_threads: list = []
        self._retry_version: str = ""
        self._pending_failure: dict | None = None
        self._installer_started = False
        self._on_result = None

    @property
    def checking(self) -> bool:
        """版本检查线程是否在运行（手动入口用于防重入）。"""
        checker = self._checker
        if checker is None:
            return False
        try:
            return bool(checker.isRunning())
        except RuntimeError:
            return False

    def consume_pending_failure(self) -> dict | None:
        state = self._pending_failure
        self._pending_failure = None
        return state

    def _prune_orphan_threads(self) -> None:
        if not self._orphan_threads:
            return
        alive = []
        for t in self._orphan_threads:
            try:
                finished = t.isFinished()
            except RuntimeError:
                continue
            if finished:
                try:
                    t.deleteLater()
                except RuntimeError:
                    pass
            else:
                alive.append(t)
        self._orphan_threads = alive

    def check_async(
        self,
        retry_version: str = "",
        *,
        manual: bool = False,
        on_result=None,
    ) -> bool:
        """发起版本检查。

        manual=True 由用户手动触发：不要求已打包（开发环境也能测），
        并在结束时把原始 result 交给 on_result 回调（用于"已是最新/失败"提示）。
        """
        self._prune_orphan_threads()
        if not manual and not _is_packaged():
            logger.debug("非打包环境，跳过自动更新检查")
            return False
        if _is_placeholder_url(self._manifest_url):
            logger.info("更新地址尚未配置，跳过自动更新检查")
            return False
        if self.checking:
            logger.debug("版本检查进行中，忽略重复请求")
            return False

        self._retry_version = str(retry_version or "").strip()
        self._on_result = on_result
        self._checker = UpdateChecker(self._manifest_urls, self)
        self._checker.finished.connect(self._checker.deleteLater)
        self._checker.checked.connect(self._on_checked)
        self._checker.start()
        return True

    def _on_checked(self, result: dict):
        sender = self.sender()
        if sender is not None and sender is not self._checker:
            return
        self._checker = None
        callback, self._on_result = self._on_result, None
        try:
            self._apply_check_result(result)
        finally:
            if callback is not None:
                try:
                    callback(result)
                except Exception:
                    logger.exception("更新检查回调异常")

    def _apply_check_result(self, result: dict):
        retry_version = self._retry_version
        self._retry_version = ""

        if result.get("error"):
            # 全部地址都失败才走到这里：对用户是可感知的故障，用 warning
            logger.warning("检查更新失败: %s", result["error"])
            return
        if not result.get("has_update"):
            if retry_version:
                logger.warning(f"重试目标版本 {retry_version} 在远程已不可用")
            else:
                logger.debug("当前已是最新版本")
            return

        info = result.get("info", {})
        if not isinstance(info, dict):
            return

        # 生产清单是只读产物：任何字段不合规都整体拒绝，不猜测、不修正。
        problems = manifest_problems(info)
        if problems:
            logger.warning(
                "version.json 字段非法，忽略本次更新：%s",
                "；".join(problems),
            )
            return

        valid_mirrors = _collect_mirrors(info)
        if valid_mirrors:
            info["download_url_mirrors"] = valid_mirrors
            info["download_url_mirror"] = valid_mirrors[0]
            logger.info(f"启用 {len(valid_mirrors)} 个下载镜像")
        else:
            info.pop("download_url_mirror", None)
            info.pop("download_url_mirrors", None)

        version = str(info.get("version", "")).strip()

        if retry_version and version and (_parse_version(version) == _parse_version(retry_version)):
            logger.info(f"按用户重试意图直接下载版本 {version}")
            self._pending_info = info
            if not self.download_and_apply_async():
                event_bus.publish(
                    EventType.UPDATE_FAILED,
                    stage="download",
                    error=f"retry download start failed for {version}",
                )
            return

        skipped = config.get("update_skipped_version", "") or ""
        if skipped and version and (_parse_version(version) == _parse_version(skipped)):
            logger.info(f"版本 {version} 已被用户忽略")
            return

        self._pending_info = info
        logger.info(f"发现新版本 {version}（当前 {CURRENT_VERSION}）")
        event_bus.publish(EventType.UPDATE_AVAILABLE, info=info)

    def download_and_apply_async(self) -> bool:
        self._prune_orphan_threads()
        if not _is_packaged():
            logger.warning("非打包环境，拒绝执行自动替换")
            return False
        if sys.platform != "win32":
            logger.warning("自动替换仅支持 Windows")
            return False
        if not self._pending_info:
            return False
        if self._downloader is not None and self._downloader.isRunning():
            return False

        url = self._pending_info.get("download_url")
        sha = self._pending_info.get("sha256", "")
        version = str(self._pending_info.get("version", "")).strip()
        if not url or not sha:
            logger.warning("version.json 缺 download_url 或 sha256")
            return False
        if not _SAFE_VERSION_RE.fullmatch(version):
            logger.warning(f"version 字段非 X.Y.Z 格式: {version!r}")
            return False

        urls = [url] + [m for m in _collect_mirrors(self._pending_info) if m != url]

        self._downloader = UpdateDownloader(urls, sha, target_version=version, parent=self)
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
        sender = self.sender()
        if sender is not None and sender is not self._downloader:
            return
        self._downloader = None

        if result.get("cancelled"):
            logger.info("更新下载已取消")
            return

        if not result.get("ok"):
            logger.error(f"更新失败: {result.get('error')}")
            self._pending_failure = {
                "version": (self._pending_info or {}).get("version", ""),
                "stage": result.get("stage", "download"),
                "error": result.get("error", "unknown"),
                "download_url": (self._pending_info or {}).get("download_url", ""),
                "log_path": result.get("log_path", ""),
            }
            event_bus.publish(
                EventType.UPDATE_FAILED,
                stage=result.get("stage", "download"),
                error=result.get("error", "unknown"),
                download_url=(self._pending_info or {}).get("download_url", ""),
                log_path=result.get("log_path", ""),
            )
            return

        logger.info("更新安装器已启动，请求主程序退出")
        self._installer_started = True
        event_bus.publish(
            EventType.UPDATE_READY,
            installer=result.get("installer", ""),
            log_path=result.get("log_path", ""),
        )

    def shutdown(self):
        # 安装器已 detach 启动：主进程即将硬退出，不要 cancel 下载线程，
        # 也不要阻塞等待任何线程，否则会拖慢退出甚至误杀安装器。
        if self._installer_started:
            logger.info("更新安装器已启动，跳过更新线程等待")
            self._downloader = None
            self._checker = None
            return

        d = self._downloader
        if d is not None:
            self._safe_disconnect(d.finished_download, self._on_downloaded)
            self._safe_disconnect(d.progress, self._on_progress)
            try:
                d.cancel()
            except Exception:
                pass
            try:
                running = d.isRunning()
            except RuntimeError:
                running = False
            if running and not d.wait(8000):
                logger.warning("下载线程未在 8s 内退出，强制终止")
                try:
                    d.cleanup_partial()
                except Exception:
                    pass
                self._terminate_thread(d)
            self._downloader = None

        c = self._checker
        if c is not None:
            self._safe_disconnect(c.checked, self._on_checked)
            try:
                running = c.isRunning()
            except RuntimeError:
                running = False
            if running and not c.wait(3000):
                logger.warning("检查线程未在 3s 内退出，强制终止")
                self._terminate_thread(c)
            self._checker = None

    @staticmethod
    def _safe_disconnect(signal, slot) -> None:
        try:
            signal.disconnect(slot)
        except (TypeError, RuntimeError):
            pass

    @staticmethod
    def _terminate_thread(t) -> None:
        # 兜底：确保进程退出前 QThread 不再 running，
        # 否则 QThread 析构会 abort（优雅退出路径必须处理）。
        try:
            t.terminate()
            t.wait(1000)
        except Exception:
            logger.warning("终止更新线程失败", exc_info=True)
