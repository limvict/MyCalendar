# coding: utf-8
"""更新下载：多 URL fallback + 退避重试 + 续传 + sha 校验。"""

import os
import subprocess
import tempfile
import threading
import time
from urllib.request import Request, urlopen

from PyQt6.QtCore import QThread, pyqtSignal

from desktop_calendar.config.manager import get_logger

from .update_errors import (
    _DownloadCancelled,
    _IncompleteDownload,
    _InstallerLaunchError,
    _ShaMismatch,
    _SlowDownload,
)
from .update_files import (
    _INSTALLER_LAUNCH_PROBE_SEC,
    _cleanup_old_installers,
    _install_log_path,
    _installer_path,
    _read_log_tail,
    _sha256_of_file,
)
from .update_retry import (
    _ENOSPC,
    _is_retryable_network_error,
)

logger = get_logger()

DOWNLOAD_TIMEOUT = 60
_DOWNLOAD_MAX_ATTEMPTS_PER_URL = 3
_RETRY_BACKOFF_SEC = (1, 2, 4)

_SLOW_SPEED_BYTES_PER_SEC = 40 * 1024
_SLOW_WINDOW_SEC = 8
_SLOW_ABORT_WINDOWS_WITH_FALLBACK = 1
_SLOW_ABORT_WINDOWS_SINGLE_URL = 2


_READ_TIMEOUT_SEC = 15


class UpdateDownloader(QThread):
    finished_download = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self, download_urls, expected_sha256: str, target_version: str = "", parent=None):
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
        self._partial_path: str | None = None

    def cancel(self):
        self._cancelled.set()

    def cleanup_partial(self) -> None:
        p = self._partial_path
        self._partial_path = None
        if not p:
            return
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass

    def _download_once(
        self,
        url: str,
        dest: str,
        resume_from: int,
        *,
        allow_slow_abort: bool = False,
        slow_abort_windows: int = 1,
    ):
        headers = {"User-Agent": "DLC-Updater"}
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=_READ_TIMEOUT_SEC) as resp:
            status = getattr(resp, "status", None)
            if status is None:
                try:
                    status = resp.getcode()
                except Exception:
                    status = None
            if resume_from > 0 and status != 206:
                resume_from = 0
            clen = resp.headers.get("Content-Length")
            remaining = int(clen.strip()) if clen and clen.strip().isdigit() else 0
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
                            raise _DownloadCancelled() from None
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        try:
                            f.write(chunk)
                        except OSError as e:
                            if getattr(e, "errno", None) == _ENOSPC:
                                raise OSError("下载更新时磁盘空间不足") from e
                            raise
                        downloaded += len(chunk)
                        if total_expected:
                            pct = min(99, downloaded * 100 // total_expected)
                            if pct != last_pct:
                                last_pct = pct
                                self.progress.emit(pct)
                        if allow_slow_abort and (not total_expected or downloaded < total_expected):
                            now = time.monotonic()
                            elapsed = now - window_start
                            if elapsed >= _SLOW_WINDOW_SEC:
                                speed = (downloaded - window_bytes) / elapsed
                                window_start = now
                                window_bytes = downloaded
                                if speed < _SLOW_SPEED_BYTES_PER_SEC:
                                    slow_windows += 1
                                    if slow_windows >= slow_abort_windows:
                                        raise _SlowDownload(
                                            f"连续 {slow_windows} 个窗口速度"
                                            f"低于 {_SLOW_SPEED_BYTES_PER_SEC // 1024}"
                                            f" KB/s"
                                        )
                                else:
                                    slow_windows = 0
            finally:
                pass
        return (total_expected, resume_from) if total_expected else None

    def _download_and_verify(self, dest: str) -> None:
        last_exc: BaseException | None = None
        for idx, url in enumerate(self._urls):
            has_next = idx + 1 < len(self._urls)
            slow_windows = (
                _SLOW_ABORT_WINDOWS_WITH_FALLBACK if has_next else _SLOW_ABORT_WINDOWS_SINGLE_URL
            )
            for attempt in range(_DOWNLOAD_MAX_ATTEMPTS_PER_URL):
                if self._cancelled.is_set():
                    raise _DownloadCancelled()
                try:
                    try:
                        resume = os.path.getsize(dest) if os.path.exists(dest) else 0
                    except OSError:
                        resume = 0
                    info = self._download_once(
                        url, dest, resume, allow_slow_abort=True, slow_abort_windows=slow_windows
                    )
                    if info is not None:
                        total_expected, _ = info
                        actual = os.path.getsize(dest)
                        if actual < total_expected:
                            raise _IncompleteDownload("更新包不完整，将续传重试")
                        if actual > total_expected:
                            try:
                                os.remove(dest)
                            except OSError:
                                pass
                            last_exc = OSError("更新包长度异常")
                            # 超长不是瞬时网络错误，重试同一 URL 无意义：
                            # 跳出 attempt 循环，交给外层切到下一个地址。
                            break
                    if self._expected_sha:
                        actual_sha = _sha256_of_file(dest)
                        if actual_sha != self._expected_sha:
                            raise _ShaMismatch("更新包校验失败，已中止更新")
                    return
                except _DownloadCancelled:
                    raise
                except _ShaMismatch as e:
                    last_exc = e
                    try:
                        if os.path.exists(dest):
                            os.remove(dest)
                    except OSError:
                        pass
                    break
                except _SlowDownload as e:
                    if has_next:
                        last_exc = e
                        break
                    primary = self._urls[0] if self._urls else url
                    raise OSError(
                        f"下载速度持续低于 {_SLOW_SPEED_BYTES_PER_SEC // 1024} KB/s，"
                        f"已中止更新。请检查网络后重试，或手动下载: {primary}"
                    ) from e
                except Exception as e:
                    last_exc = e
                    if not _is_retryable_network_error(e):
                        break
                    if attempt + 1 >= _DOWNLOAD_MAX_ATTEMPTS_PER_URL:
                        break
                    backoff = _RETRY_BACKOFF_SEC[min(attempt, len(_RETRY_BACKOFF_SEC) - 1)]
                    if self._cancelled.wait(backoff):
                        raise _DownloadCancelled() from None
        raise last_exc or OSError("所有下载地址均失败")

    def _launch_installer(self, installer_path: str, log_path: str) -> subprocess.Popen:
        """以 detached 方式启动 Inno Setup 安装器。

        不再经过 cmd.exe：Popen(list) 在 Windows 上会由 list2cmdline
        给含空格参数加引号；若再套一层 cmd /c "..."，cmd 不认 \" 转义，
        会语法错误退出 1，安装器根本不会启动（表现为没有 /LOG 文件）。
        延迟由调用方 time.sleep 完成，不再用 ping。
        """
        env = os.environ.copy()
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        args = [
            installer_path,
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/FORCECLOSEAPPLICATIONS",
            f"/LOG={log_path}",
        ]
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
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

    def _probe_installer(self, proc: subprocess.Popen, log_path: str) -> None:
        deadline = time.monotonic() + _INSTALLER_LAUNCH_PROBE_SEC
        while time.monotonic() < deadline:
            tail = _read_log_tail(log_path, max_lines=50)
            if "Got EAbort exception" in tail:
                raise _InstallerLaunchError(
                    f"Inno Setup 安装器因运行中检测失败（EAbort），日志: {log_path}\n{tail}"
                )
            rc = proc.poll()
            if rc is not None:
                if rc != 0:
                    hint = (
                        f"\n安装器日志末尾：\n{tail}"
                        if tail
                        else "\n安装器未产生日志（可能根本未启动）"
                    )
                    raise _InstallerLaunchError(
                        f"Inno Setup 安装器启动后立即失败（退出码 {rc}），日志: {log_path}{hint}"
                    )
                return
            time.sleep(0.1)
        tail = _read_log_tail(log_path, max_lines=50)
        if "Got EAbort exception" in tail:
            raise _InstallerLaunchError(
                f"Inno Setup 安装器因运行中检测失败（EAbort），日志: {log_path}\n{tail}"
            )
        logger.info("安装器已启动并持续运行，日志: %s", log_path)

    def run(self):
        result = {"ok": False, "error": None, "cancelled": False, "stage": "download"}
        installer_path = _installer_path(self._target_version)
        log_path = _install_log_path(self._target_version)
        self._partial_path = installer_path

        try:
            _cleanup_old_installers(keep=installer_path)
            if os.path.exists(installer_path):
                try:
                    os.remove(installer_path)
                except OSError as e:
                    raise OSError(
                        f"无法清理旧的更新安装包 {installer_path}，请检查文件是否被占用后重试"
                    ) from e
            if os.path.exists(log_path):
                try:
                    os.remove(log_path)
                except OSError:
                    pass

            logger.info("开始下载更新安装包: %s", ", ".join(self._urls) or "<无地址>")
            self._download_and_verify(installer_path)

            if self._cancelled.is_set():
                raise _DownloadCancelled()
            if not os.path.exists(installer_path) or os.path.getsize(installer_path) == 0:
                raise OSError("下载文件为空")
            if not self._expected_sha:
                logger.warning("更新清单未提供 sha256，跳过完整性校验。")
            self.progress.emit(100)

            if self._cancelled.is_set():
                raise _DownloadCancelled()

            # 原先靠 cmd 里的 ping 延迟 2s；现在直接 sleep，
            # 给主程序退出留时间，避免再经 shell。
            if self._cancelled.wait(2.0):
                raise _DownloadCancelled()

            try:
                proc = self._launch_installer(installer_path, log_path)
            except OSError as e:
                result["stage"] = "installer"
                raise _InstallerLaunchError(f"启动更新安装器失败: {e}") from e
            try:
                self._probe_installer(proc, log_path)
            except _InstallerLaunchError:
                result["stage"] = "installer"
                raise

            result["ok"] = True
            result["stage"] = "installer"
            result["installer"] = installer_path
            result["log_path"] = log_path
        except _DownloadCancelled:
            result["cancelled"] = True
            result["stage"] = "download"
            result["error"] = "下载已取消"
        except Exception as e:
            result["error"] = f"更新失败: {e}"
            if result["stage"] == "installer" and os.path.exists(installer_path):
                result["error"] += f"（安装包已保留：{installer_path}）"
            logger.error(result["error"], exc_info=True)
        finally:
            self._partial_path = None
            if not result["ok"] and not result["cancelled"]:
                if result["stage"] == "download":
                    # 下载阶段失败：删除不完整/被篡改的临时文件。
                    try:
                        if os.path.exists(installer_path):
                            os.remove(installer_path)
                    except OSError:
                        pass
                elif os.path.exists(installer_path):
                    # 安装器阶段失败：保留安装包，便于用户手动重试。
                    logger.info("已保留安装包供手动重试: %s", installer_path)

        self.finished_download.emit(result)
