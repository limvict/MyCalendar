# coding: utf-8
"""更新下载：多 URL fallback + 退避重试 + 续传 + sha 校验。

下载目标是 Inno Setup 安装包；校验通过后以 detached 方式静默启动安装器，
由安装器负责关闭占用进程、替换文件并重启应用。
"""
import hashlib
import http.client
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

from PyQt6.QtCore import QThread, pyqtSignal

from desktop_calendar.config.manager import get_logger

logger = get_logger()

DOWNLOAD_TIMEOUT = 60
_ENOSPC = 28
_RETRYABLE_WINERRORS = frozenset({10053, 10054, 10060, 10061})
_DOWNLOAD_MAX_ATTEMPTS_PER_URL = 3
_RETRY_BACKOFF_SEC = (1, 2, 4)

_SLOW_SPEED_BYTES_PER_SEC = 40 * 1024
_SLOW_WINDOW_SEC = 8
_SLOW_ABORT_WINDOWS_WITH_FALLBACK = 1
_SLOW_ABORT_WINDOWS_SINGLE_URL = 2

_INSTALLER_PREFIX = "DLC_Setup_"
_INSTALL_LOG_PREFIX = "DLC_install_"
_ORPHAN_INSTALLER_MAX_AGE_SEC = 86400
_INSTALLER_LAUNCH_PROBE_SEC = 1.5


class _DownloadCancelled(Exception):
    pass


class _ShaMismatch(IOError):
    """下载完成但 sha256 与清单不符——文件可能被截断或篡改。"""


class _IncompleteDownload(IOError):
    """响应正常结束但字节数不足——可续传重试。"""


class _SlowDownload(IOError):
    pass


class _InstallerLaunchError(IOError):
    """安装器启动后立即以非零退出码结束。"""


def _iter_exc_chain(exc: BaseException):
    seen: set = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ or cur.__context__


def _is_retryable_network_error(exc: BaseException) -> bool:
    """连接被重置 / 超时 / 响应截断等应退避重试的错误。"""
    for e in _iter_exc_chain(exc):
        if isinstance(e, (ConnectionResetError, ConnectionAbortedError,
                          TimeoutError, socket.timeout,
                          _IncompleteDownload, http.client.IncompleteRead)):
            return True
        if getattr(e, "winerror", None) in _RETRYABLE_WINERRORS:
            return True
        if isinstance(e, URLError):
            reason = getattr(e, "reason", None)
            if isinstance(reason, str):
                low = reason.lower()
                if any(t in low for t in (
                        "reset", "aborted", "timed out",
                        "connection closed", "connection aborted")):
                    return True
    return False


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _safe_name_part(value: str) -> str:
    """把版本号清洗成可安全拼进文件名的片段。"""
    cleaned = re.sub(r"[^0-9A-Za-z._\-]", "_", str(value or "")).strip("._")
    return cleaned or "unknown"


def _installer_path(version: str) -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"{_INSTALLER_PREFIX}{_safe_name_part(version)}.exe")


def _install_log_path(version: str) -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"{_INSTALL_LOG_PREFIX}{_safe_name_part(version)}.log")


def _cleanup_old_installers(keep: str) -> None:
    """清理 %TEMP% 下过期的旧安装包，保留本次目标文件。"""
    tmp_dir = tempfile.gettempdir()
    keep_norm = os.path.normcase(os.path.normpath(keep)) if keep else None
    now = time.time()
    try:
        names = os.listdir(tmp_dir)
    except OSError:
        logger.debug("扫描临时目录失败", exc_info=True)
        return
    for name in names:
        if not (name.startswith(_INSTALLER_PREFIX) and name.endswith(".exe")):
            continue
        full = os.path.normpath(os.path.join(tmp_dir, name))
        if keep_norm is not None and (
                os.path.normcase(full) == keep_norm):
            continue
        try:
            if now - os.path.getmtime(full) < _ORPHAN_INSTALLER_MAX_AGE_SEC:
                continue
            os.remove(full)
            logger.info("清理旧更新安装包: %s", full)
        except OSError:
            logger.debug("清理旧安装包失败: %r", full, exc_info=True)


class UpdateDownloader(QThread):
    finished_download = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self, download_urls, expected_sha256: str,
                 target_version: str = "", parent=None):
        super().__init__(parent)
        if isinstance(download_urls, str):
            download_urls = [download_urls]
        seen: set = set()
        self._urls: list[str] = []
        for u in download_urls:
            if u and u not in seen:
                seen.add(u)
                self._urls.append(u)
        self._expected_sha = (expected_sha256 or "").strip().lower()
        self._target_version = str(target_version or "").strip()
        self._cancelled = threading.Event()
        self._partial_path: Optional[str] = None

    def cancel(self):
        self._cancelled.set()

    def cleanup_partial(self) -> None:
        """主线程在 shutdown 强杀前调用：尽力删半成品安装包。

        与 run() 的 finally 存在竞争——主线程删时下载线程可能正在写
        同一文件（Windows 会 OSError，被吞）。线程最终退出时 finally
        会再删一次。两者都尽力而为。
        """
        p = self._partial_path
        self._partial_path = None
        if not p:
            return
        try:
            if os.path.exists(p):
                os.remove(p)
                logger.info("已清理半成品更新包: %s", p)
        except OSError:
            logger.debug("清理半成品失败: %r", p, exc_info=True)

    def _download_once(self, url: str, dest: str, resume_from: int, *,
                       allow_slow_abort: bool = False,
                       slow_abort_windows: int = 1,
                       read_timeout: int = 15):
        headers = {"User-Agent": "DLC-Updater"}
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
        req = Request(url, headers=headers)
        effective_resume = resume_from
        with urlopen(req, timeout=read_timeout) as resp:
            status = getattr(resp, "status", None)
            if status is None:
                try:
                    status = resp.getcode()
                except Exception:
                    status = None
            if resume_from > 0 and status != 206:
                logger.info(
                    "服务端未返回 206（status=%s），放弃续传从头下载: %s",
                    status, url)
                resume_from = 0
                effective_resume = 0
            clen = resp.headers.get("Content-Length")
            remaining = int(clen) if clen and clen.isdigit() else 0
            total_expected = (resume_from + remaining) if remaining else 0
            downloaded = resume_from
            last_pct = -1
            mode = "ab" if resume_from > 0 else "wb"
            t0 = time.monotonic()
            window_start = t0
            window_bytes = downloaded
            slow_windows = 0
            try:
                with open(dest, mode) as f:
                    while True:
                        if self._cancelled.is_set():
                            raise _DownloadCancelled()
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        try:
                            f.write(chunk)
                        except OSError as e:
                            if getattr(e, "errno", None) == _ENOSPC:
                                raise IOError(
                                    f"下载更新时磁盘空间不足（目标: {dest}），"
                                    f"请清理临时目录后重试") from e
                            raise
                        downloaded += len(chunk)
                        if total_expected:
                            pct = min(99, downloaded * 100 // total_expected)
                            if pct != last_pct:
                                last_pct = pct
                                self.progress.emit(pct)
                        if (allow_slow_abort
                                and (not total_expected
                                     or downloaded < total_expected)):
                            now = time.monotonic()
                            elapsed = now - window_start
                            if elapsed >= _SLOW_WINDOW_SEC:
                                speed = (downloaded - window_bytes) / elapsed
                                window_start = now
                                window_bytes = downloaded
                                if speed < _SLOW_SPEED_BYTES_PER_SEC:
                                    slow_windows += 1
                                    logger.info(
                                        "下载速度偏低: %.0f KB/s"
                                        "（窗口 %d/%d），%s",
                                        speed / 1024, slow_windows,
                                        slow_abort_windows, url)
                                    if slow_windows >= slow_abort_windows:
                                        raise _SlowDownload(
                                            f"连续 {slow_windows} 个窗口速度"
                                            f"低于 "
                                            f"{_SLOW_SPEED_BYTES_PER_SEC//1024}"
                                            f" KB/s")
                                else:
                                    slow_windows = 0
            finally:
                try:
                    elapsed = time.monotonic() - t0
                    if os.path.exists(dest):
                        actual = os.path.getsize(dest)
                    else:
                        actual = downloaded
                    added = max(0, actual - effective_resume)
                    speed = added / max(elapsed, 0.001)
                    logger.info(
                        "URL 下载结束: %s, %.0f KB/s, %.1f s, %d/%d bytes",
                        url, speed / 1024, elapsed, actual,
                        total_expected or actual)
                except OSError:
                    logger.debug("记录下载速度失败: %r", dest, exc_info=True)
        return (total_expected, resume_from) if total_expected else None

    def _download_and_verify(self, dest: str) -> None:
        last_exc: Optional[BaseException] = None
        for idx, url in enumerate(self._urls):
            has_next = idx + 1 < len(self._urls)
            slow_windows = (
                _SLOW_ABORT_WINDOWS_WITH_FALLBACK if has_next
                else _SLOW_ABORT_WINDOWS_SINGLE_URL)
            for attempt in range(_DOWNLOAD_MAX_ATTEMPTS_PER_URL):
                if self._cancelled.is_set():
                    raise _DownloadCancelled()
                try:
                    resume = os.path.getsize(dest) if os.path.exists(dest) else 0
                    info = self._download_once(
                        url, dest, resume,
                        allow_slow_abort=True,
                        slow_abort_windows=slow_windows,
                        read_timeout=min(DOWNLOAD_TIMEOUT, 15))
                    if info is not None:
                        total_expected, _ = info
                        actual = os.path.getsize(dest)
                        if actual < total_expected:
                            raise _IncompleteDownload(
                                f"更新包不完整（期望 {total_expected}，"
                                f"实际 {actual}），将续传重试")
                        if actual > total_expected:
                            # 残文件比预期大，续传会拿到 416 / 错误偏移。
                            # 先删残文件，让下一个 URL 从 0 重新下载。
                            try:
                                os.remove(dest)
                                logger.warning(
                                    "更新包长度异常，已删除残文件: %r", dest)
                            except OSError:
                                logger.debug(
                                    "删除超长残文件失败: %r", dest,
                                    exc_info=True)
                            raise IOError(
                                f"更新包长度异常（期望 {total_expected}，"
                                f"实际 {actual}）")
                    if self._expected_sha:
                        actual_sha = _sha256_of_file(dest)
                        if actual_sha != self._expected_sha:
                            raise _ShaMismatch(
                                "更新包校验失败（期望 "
                                f"{self._expected_sha[:12]}...，实际 "
                                f"{actual_sha[:12]}...），已中止更新")
                    return
                except _DownloadCancelled:
                    raise
                except _ShaMismatch as e:
                    last_exc = e
                    logger.warning(
                        "sha256 校验失败，丢弃残文件并尝试下一个地址: %s", url)
                    try:
                        if os.path.exists(dest):
                            os.remove(dest)
                    except OSError:
                        logger.debug("删除残文件失败: %r", dest,
                                     exc_info=True)
                    break
                except _SlowDownload as e:
                    if has_next:
                        last_exc = e
                        logger.warning(
                            "下载过慢，切换下一个地址: %s: %s", url, e)
                        break
                    primary = self._urls[0] if self._urls else url
                    raise IOError(
                        f"下载速度持续低于 "
                        f"{_SLOW_SPEED_BYTES_PER_SEC // 1024} KB/s，"
                        f"已中止更新（{e}）。"
                        f"请检查网络后重试，或手动下载: {primary}"
                    ) from e
                except Exception as e:
                    last_exc = e
                    if not _is_retryable_network_error(e):
                        logger.warning(
                            "下载失败（不可重试），换下一个地址: %s: %s",
                            url, e)
                        break
                    if attempt + 1 >= _DOWNLOAD_MAX_ATTEMPTS_PER_URL:
                        logger.warning("下载重试耗尽: %s: %s", url, e)
                        break
                    backoff = _RETRY_BACKOFF_SEC[
                        min(attempt, len(_RETRY_BACKOFF_SEC) - 1)]
                    logger.warning(
                        "下载连接中断（attempt %d/%d），%ss 后续传重试: "
                        "%s: %s",
                        attempt + 1, _DOWNLOAD_MAX_ATTEMPTS_PER_URL,
                        backoff, url, e)
                    if self._cancelled.wait(backoff):
                        raise _DownloadCancelled()
        raise last_exc or IOError("所有下载地址均失败")

    def _launch_installer(self, installer_path: str,
                          log_path: str) -> subprocess.Popen:
        """以 detached 方式静默启动 Inno Setup 安装器。

        /VERYSILENT /SUPPRESSMSGBOXES 全程无 UI；/NORESTART 阻止安装器
        触发系统重启；/CLOSEAPPLICATIONS 让安装器兜底关闭仍占用文件的
        进程（主程序收到 UPDATE_READY 后应主动退出，此处仅作保险）；
        /LOG= 把安装过程写入指定日志，用于失败诊断。
        重启由安装器 [Run] 段负责（静默安装下默认执行）。

        PYINSTALLER_RESET_ENVIRONMENT=1 避免新进程继承当前 PyInstaller
        onefile 的 _MEI 临时目录，否则父进程退出后新进程会加载失败。
        """
        env = os.environ.copy()
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        args = [
            installer_path,
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            f'/LOG="{log_path}"',
        ]
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        return subprocess.Popen(
            args,
            cwd=os.path.dirname(installer_path) or tempfile.gettempdir(),
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=env,
        )

    def _probe_installer(self, proc: subprocess.Popen,
                         log_path: str) -> None:
        """短暂观察安装器是否启动即失败（参数错误 / 文件损坏等）。"""
        deadline = time.monotonic() + _INSTALLER_LAUNCH_PROBE_SEC
        while time.monotonic() < deadline:
            rc = proc.poll()
            if rc is not None:
                if rc != 0:
                    raise _InstallerLaunchError(
                        f"Inno Setup 安装器启动后立即失败（退出码 {rc}），"
                        f"日志: {log_path}")
                logger.warning(
                    "安装器在 %.1fs 内已退出（退出码 0），可能快速完成；"
                    "日志: %s", _INSTALLER_LAUNCH_PROBE_SEC, log_path)
                return
            time.sleep(0.1)
        logger.info("安装器已启动并持续运行，日志: %s", log_path)

    def run(self):
        result = {"ok": False, "error": None, "cancelled": False,
                  "stage": "download"}
        installer_path = _installer_path(self._target_version)
        log_path = _install_log_path(self._target_version)
        self._partial_path = installer_path

        try:
            _cleanup_old_installers(keep=installer_path)
            if os.path.exists(installer_path):
                try:
                    os.remove(installer_path)
                except OSError as e:
                    raise IOError(
                        f"无法清理旧的更新安装包 {installer_path}，"
                        f"请检查文件是否被占用后重试") from e
            if os.path.exists(log_path):
                try:
                    os.remove(log_path)
                except OSError:
                    logger.debug("清理旧安装日志失败: %r", log_path,
                                 exc_info=True)

            logger.info("开始下载更新安装包: %s",
                        ", ".join(self._urls) or "<无地址>")
            self._download_and_verify(installer_path)

            if self._cancelled.is_set():
                raise _DownloadCancelled()
            if (not os.path.exists(installer_path)
                    or os.path.getsize(installer_path) == 0):
                raise IOError("下载文件为空")
            if not self._expected_sha:
                logger.warning(
                    "更新清单未提供 sha256，跳过完整性校验。"
                    "请尽快在 version.json 中补充该字段。")
            self.progress.emit(100)

            if self._cancelled.is_set():
                raise _DownloadCancelled()

            try:
                proc = self._launch_installer(installer_path, log_path)
            except OSError as e:
                result["stage"] = "installer"
                raise _InstallerLaunchError(
                    f"启动更新安装器失败: {e}") from e
            try:
                self._probe_installer(proc, log_path)
            except _InstallerLaunchError:
                result["stage"] = "installer"
                raise

            result["ok"] = True
            result["stage"] = "installer"
            result["installer"] = installer_path
            result["log_path"] = log_path
            logger.info(
                "更新安装器已启动，等待主程序退出；安装日志: %s", log_path)
        except _DownloadCancelled:
            result["cancelled"] = True
            result["stage"] = "download"
            result["error"] = "下载已取消"
            logger.info("下载被用户取消")
        except Exception as e:
            result["error"] = f"更新失败: {e}"
            logger.error(result["error"], exc_info=True)
        finally:
            self._partial_path = None
            if not result["ok"]:
                try:
                    if os.path.exists(installer_path):
                        os.remove(installer_path)
                except OSError:
                    logger.debug("清理安装包失败: %r", installer_path,
                                 exc_info=True)

        self.finished_download.emit(result)