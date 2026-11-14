# coding: utf-8
"""更新下载：多 URL fallback + 退避重试 + 续传 + sha 校验。"""
import hashlib
import http.client
import os
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
from desktop_calendar.infrastructure.network import update_bat

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


class _DownloadCancelled(Exception):
    pass


class _ShaMismatch(IOError):
    """下载完成但 sha256 与清单不符——文件可能被截断或篡改。"""


class _IncompleteDownload(IOError):
    """响应正常结束但字节数不足——可续传重试。"""


class _SlowDownload(IOError):
    pass


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


def _is_install_dir_writable(install_dir: str) -> bool:
    """实际写测试探测安装目录可写性。

    不用 os.access：Windows 上 UAC 会虚拟化受保护目录的写入路径，
    os.access 可能返回 True 但实际 move 失败。
    """
    probe = os.path.join(install_dir, f".dlc_probe_{os.getpid()}")
    try:
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        try:
            if os.path.exists(probe):
                os.remove(probe)
        except OSError:
            pass
        return False


def _in_program_files(exe_path: str) -> bool:
    """判断 exe 是否位于 Windows 的 Program Files 系列目录下。"""
    if sys.platform != "win32":
        return False
    try:
        low = os.path.normcase(os.path.abspath(exe_path))
        sep = os.sep
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            root = os.getenv(env)
            if not root:
                continue
            root_norm = os.path.normcase(os.path.abspath(root))
            if low == root_norm or low.startswith(root_norm + sep):
                return True
    except Exception:
        logger.debug("Program Files 检测失败", exc_info=True)
    return False


def precheck_install_target(exe_path: str) -> Optional[str]:
    """下载前的安装目标预检。返回 None 通过，否则返回用户可读原因。

    提前失败的价值：避免下完几十 MB 才发现无权限写，节省流量和时间。
    只做可写性检查，不做 "Program Files + 非管理员" 的硬性拒绝：
    后者在部分配置（如 UAC 虚拟化）下会误判。
    """
    install_dir = os.path.dirname(exe_path) or "."
    if _is_install_dir_writable(install_dir):
        return None
    if _in_program_files(exe_path):
        return ("安装目录不可写：程序位于 Program Files，"
                "请以管理员身份运行后重试，或手动下载安装包")
    return "安装目录不可写，请检查磁盘权限或空间后重试，或手动下载安装包"


class UpdateDownloader(QThread):
    finished_download = pyqtSignal(dict)
    progress = pyqtSignal(int)

    def __init__(self, download_urls, expected_sha256: str,
                 target_pid: int, target_version: str = "", parent=None):
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
        self._pid = int(target_pid)
        self._target_version = str(target_version or "").strip()
        self._cancelled = threading.Event()
        self._partial_path: Optional[str] = None

    def cancel(self):
        self._cancelled.set()

    def cleanup_partial(self) -> None:
        """主线程在 shutdown 强杀前调用：尽力删半成品更新包。

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

    def run(self):
        result = {"ok": False, "error": None, "cancelled": False}
        exe_path = sys.executable
        new_exe = os.path.join(
            tempfile.gettempdir(), update_bat._tmp_exe_name(self._pid))
        self._partial_path = new_exe
        bat_path = os.path.join(
            tempfile.gettempdir(), update_bat._tmp_bat_name(self._pid))
        log_path = os.path.join(
            tempfile.gettempdir(), update_bat._tmp_log_name(self._pid))
        old_exe = exe_path + update_bat._OLD_EXE_SUFFIX
        state_path = update_bat._state_file_path()

        try:
            for p in (new_exe, bat_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            update_bat._clear_state_file()

            logger.info("开始下载更新包: %s", ", ".join(self._urls))
            self._download_and_verify(new_exe)

            if self._cancelled.is_set():
                raise _DownloadCancelled()
            if not os.path.exists(new_exe) or os.path.getsize(new_exe) == 0:
                raise IOError("下载文件为空")
            if not self._expected_sha:
                logger.warning(
                    "更新清单未提供 sha256，跳过完整性校验。"
                    "请尽快在 version.json 中补充该字段。")
            self.progress.emit(100)

            # 无 BOM 的 UTF-8：带 BOM 会让 cmd 把 EF BB BF 当成命令的一部分。
            with open(bat_path, "w", encoding="utf-8", newline="") as f:
                f.write(update_bat.build_bat_script())

            env = os.environ.copy()
            env.update({
                "DLC_PID": str(self._pid),
                "DLC_EXE": exe_path,
                "DLC_NEW": new_exe,
                "DLC_OLD": old_exe,
                "DLC_LOG": log_path,
                "DLC_WAIT": str(update_bat._WAIT_EXIT_MAX_SEC),
                "DLC_PROBE": str(update_bat._NEW_VERSION_PROBE_SEC + 1),
                "DLC_STATE": state_path,
                "DLC_VERSION": self._target_version,
            })

            if self._cancelled.is_set():
                raise _DownloadCancelled()

            proc = subprocess.Popen(
                ["cmd", "/c", os.path.basename(bat_path)],
                cwd=os.path.dirname(bat_path),
                creationflags=(
                    subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                env=env,
            )

            if self._cancelled.is_set():
                try:
                    proc.kill()
                except Exception:
                    logger.debug("kill 更新脚本失败", exc_info=True)
                raise _DownloadCancelled()

            result["ok"] = True
            logger.info(
                f"更新包下载并校验完成，替换脚本已启动；日志: {log_path}")
        except _DownloadCancelled:
            result["cancelled"] = True
            result["error"] = "下载已取消"
            logger.info("下载被用户取消")
        except Exception as e:
            result["error"] = f"下载更新失败: {e}"
            logger.error(result["error"], exc_info=True)
        finally:
            self._partial_path = None
            if not result["ok"]:
                for p in (new_exe, bat_path):
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except OSError:
                        logger.debug("清理临时文件失败: %r", p, exc_info=True)
                update_bat._clear_state_file()

        self.finished_download.emit(result)