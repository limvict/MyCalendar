# file: update_manager.py
# coding: utf-8
"""自动更新：版本检查、下载、替换、重启。"""
import os
import sys
import json
import hashlib
import tempfile
import subprocess
import threading
import re
import http.client          # [FIX] IncompleteRead
import socket               # [FIX] socket.timeout
import time                 # [FIX] 慢速检测 / 速度日志
from typing import Optional
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import URLError

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from desktop_calendar.config.manager import get_logger, get_config_path, config
from desktop_calendar.contracts.event_bus import event_bus
from desktop_calendar.contracts.events import EventType

logger = get_logger()

UPDATE_MANIFEST_URL = (
    "https://github.com/limvict/MyCalendar/releases/latest/download/version.json")
CURRENT_VERSION = "3.0.3"

CHECK_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 120
_WAIT_EXIT_MAX_SEC = 60       # bat 等待旧进程退出上限
_NEW_VERSION_PROBE_SEC = 5    # bat 观察新版本存活秒数

_STATE_FILE_NAME = "update_state.txt"

# version 字段会被拼进 .bat（echo version=%VER%）。
# 本正则的职责只是**防 cmd 注入**：白名单只允许字母数字与 . _ -，
# 排除 % & | < > ^ 等 cmd 元字符，避免远端 manifest 注入破坏 bat。
# 它不限定版本语义格式（X.Y.Z / 预发布后缀 / v 前缀 / 多段都允许），
# 版本解析与比较交给 _parse_version。
_SAFE_VERSION_RE = re.compile(r"^[0-9A-Za-z._\-]+$")

# [FIX] 可重试的网络错误：Windows 下连接被重置/中止最常见的几个 winsock 码。
#   10053 WSAECONNABORTED / 10054 WSAECONNRESET /
#   10060 WSAETIMEDOUT  / 10061 WSAECONNREFUSED
_RETRYABLE_WINERRORS = frozenset({10053, 10054, 10060, 10061})
_DOWNLOAD_MAX_ATTEMPTS_PER_URL = 3
_RETRY_BACKOFF_SEC = (1, 2, 4)

# [FIX] 慢速判定：观察窗口内平均速度低于阈值视为"能连但龟速"。
#       无 Content-Length 的响应同样适用：窗口只看增量字节，不依赖总长。
_SLOW_SPEED_BYTES_PER_SEC = 40 * 1024
_SLOW_WINDOW_SEC = 8

# 连续多少个慢速窗口触发中止：
#   有备选源时 1 个窗口（8s）即切换，快速 fallback；
#   无备选源时 2 个窗口（16s）才中止，避免网络抖动误杀，
#   同时不让用户无声等待数十分钟（曾出现 48 分钟 30MiB 的龟速下载）。
_SLOW_ABORT_WINDOWS_WITH_FALLBACK = 1
_SLOW_ABORT_WINDOWS_SINGLE_URL = 2


def _state_file_path() -> str:
    return os.path.join(os.path.dirname(get_config_path()), _STATE_FILE_NAME)


def _clear_state_file() -> None:
    p = _state_file_path()
    try:
        if os.path.exists(p):
            os.remove(p)
    except OSError:
        logger.debug("清除更新状态标记失败", exc_info=True)


def _cleanup_leftover_new_exe(path: Optional[str]) -> None:
    """清理上次更新失败遗留的临时更新包（及对应的 bat）。

    只接受 ``%TEMP%/DLC_update_new_<pid>.exe`` 形状的路径，
    防止 state 文件被篡改后诱导删除任意文件。

    清理 log 不做：``update.prev_failed_detail`` 里向用户展示的
    诊断日志路径指向它，删了用户就没法查失败原因。
    """
    if not path:
        return
    try:
        norm = os.path.normpath(path)
        tmp_dir = os.path.normpath(tempfile.gettempdir())
        base = os.path.basename(norm)
        # 目录比较用 normcase：Windows 下大小写/斜杠不敏感，
        # state 里 bat 写入的路径大小写可能与 gettempdir() 不同。
        if (os.path.normcase(os.path.dirname(norm))
                != os.path.normcase(tmp_dir)
                or not base.startswith("DLC_update_new_")
                or not base.endswith(".exe")):
            logger.warning(
                "state 中 new_exe 路径不合规，跳过清理: %r", path)
            return

        pid_part = base[len("DLC_update_new_"):-len(".exe")]
        targets = [norm]
        if pid_part.isdigit():
            targets.append(os.path.join(
                tmp_dir, f"DLC_update_apply_{pid_part}.bat"))

        for t in targets:
            try:
                if os.path.exists(t):
                    os.remove(t)
                    logger.info("已清理遗留更新临时文件: %s", t)
            except OSError:
                logger.debug("清理遗留文件失败: %r", t, exc_info=True)
    except Exception:
        logger.debug("清理遗留更新包失败: %r", path, exc_info=True)


def _cleanup_orphan_update_logs(keep: Optional[str]) -> None:
    """清理 %TEMP% 下所有 DLC_update_*.log，保留 keep 指定的文件。

    keep 是当前 state 文件引用的 log_path：
      - _handle_pending_failure 刚把它展示给用户，用户可能还要查；
      - Retry 路径会复用同一 pid 的 log 路径写新内容，删了会丢上下文。
    其余 log 是历史更新失败遗留，不会再被任何提示引用，清理安全。

    仅在 consume_state_file 成功解析出 log_path 时调用；state 文件
    为空/损坏（解析结果为空 dict）时跳过，避免误删可能仍相关的日志。
    """
    keep_norm = os.path.normpath(keep) if keep else None
    tmp_dir = tempfile.gettempdir()
    try:
        names = os.listdir(tmp_dir)
    except OSError:
        logger.debug("扫描临时目录失败", exc_info=True)
        return
    for name in names:
        if not (name.startswith("DLC_update_") and name.endswith(".log")):
            continue
        full = os.path.normpath(os.path.join(tmp_dir, name))
        if keep_norm is not None and full == keep_norm:
            continue
        try:
            os.remove(full)
            logger.info("清理历史更新日志: %s", full)
        except OSError:
            logger.debug("清理更新日志失败: %r", full, exc_info=True)


def consume_state_file() -> Optional[dict]:
    """读取并删除上次更新失败标记。文件为 bat 写的 key=value 行。

    读完后顺手清理 state 里记录的遗留临时文件——正常情况下 bat 的
    ``:cleanup`` 已删除，这里只兜底断电 / 进程被杀 / 用户强关 cmd
    导致 bat 未执行完的场景。
    """
    p = _state_file_path()
    if not os.path.exists(p):
        return None
    result: dict = {}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip().strip('"')
    except Exception:
        logger.warning("读取更新状态标记失败", exc_info=True)
        result = {}
    _clear_state_file()
    _cleanup_leftover_new_exe(result.get("new_exe"))
    # 仅在 state 文件解析出 log_path 时清理历史 log；state 为空/
    # 损坏（result 为空 dict）或缺少 log_path 时不删，避免误删
    # 可能仍相关的诊断日志。下次正常 state 再清理。
    if result and result.get("log_path"):
        _cleanup_orphan_update_logs(keep=result["log_path"])
    return result or None


def _tmp_exe_name(pid: int) -> str:
    return f"DLC_update_new_{pid}.exe"


def _tmp_bat_name(pid: int) -> str:
    return f"DLC_update_apply_{pid}.bat"


def _tmp_log_name(pid: int) -> str:
    return f"DLC_update_{pid}.log"


_OLD_EXE_SUFFIX = ".old"


class _DownloadCancelled(Exception):
    pass


# [FIX] 新增异常类型 + 网络错误判定。
class _ShaMismatch(IOError):
    """下载完成但 sha256 与清单不符——文件可能被截断或篡改。"""


class _IncompleteDownload(IOError):
    """响应正常结束但字节数不足——可续传重试。"""


# [FIX] 当前 URL 速度持续过低。
#       有备选源时由调用方切下一个；无备选源时由调用方转成终态错误。
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


# ===================== 版本比较 =====================
def _parse_version(v: str) -> tuple:
    """解析版本号为整数元组。

    契约（由 tests/test_update_manager.py 锁定）：
      - 按 "." 切分，每段 int() 转换，失败置 0：
        "1.2.3" -> (1, 2, 3)；"1.x.3" -> (1, 0, 3)；"" -> (0,)
      - 负数段保留："1.-2.3" -> (1, -2, 3)
      - "1.2.3-beta" 末段 "3-beta" 转换失败 -> (1, 2, 0)，与 "1.2.0"
        同序。这是有意设计：发布侧 _version.validate_ver 只接受 X.Y.Z，
        预发布号不会出现在正常发布流程；运行时按同序处理可避免把
        预发布自动推给正式版用户。
    """
    parts = []
    for seg in str(v).split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


# ===================== 环境检测 =====================
def _is_packaged() -> bool:
    return (
        getattr(sys, "frozen", False)
        or getattr(sys, "_MEIPASS", None) is not None
        or hasattr(sys, "nuitka_version")
    )


_PLACEHOLDER_URL_TOKENS = ("yourname", "yourrepo", "<org>", "<repo>", "<your")


def _is_placeholder_url(url: str) -> bool:
    if not url:
        return True
    lowered = url.lower()
    return any(t in lowered for t in _PLACEHOLDER_URL_TOKENS)


def _is_safe_download_url(url: str) -> bool:
    try:
        p = urlparse(url)
        # 自更新 = 最高权限操作。允许 http 时中间人可同时替换
        # 安装包与 manifest 里的 sha256，完整性校验形同虚设。
        return p.scheme == "https" and bool(p.netloc)
    except Exception:
        return False


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _collect_mirrors(info: dict) -> list[str]:
    """从 manifest 收集所有镜像地址（去重保序）。

    优先读 download_url_mirrors（列表，新格式），再合并
    download_url_mirror（单个，旧格式兼容）。列表顺序即 fallback
    顺序——发布侧写入的顺序决定先试哪个源。
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


# ===================== 版本检查线程 =====================
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
            # 远程数据不可信，先过一遍防 cmd 注入白名单再交给
            # _parse_version。这里拒绝的是含 cmd 元字符的字符串，
            # 不是"非 X.Y.Z 格式"。
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


# ===================== 下载 + 替换 =====================
class UpdateDownloader(QThread):
    finished_download = pyqtSignal(dict)
    progress = pyqtSignal(int)

    # [FIX] 接受 URL 列表，第一个为主、其余为镜像；传 str 也兼容。
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
        # 当前正在下载的临时文件路径。run() 开头写入，finally 清空；
        # 主线程 shutdown 超时时通过 cleanup_partial() 读取它做最后清理。
        self._partial_path: Optional[str] = None

    def cancel(self):
        self._cancelled.set()

    def cleanup_partial(self) -> None:
        """主线程在 shutdown 强杀前调用：尽力删半成品更新包。

        与 run() 的 finally 存在竞争——主线程删时下载线程可能正在
        写同一文件（Windows 会 OSError，被吞）。线程最终退出时
        finally 会再删一次。两者都尽力而为，覆盖了"线程卡死 →
        主线程 wait 超时 → 进程退出前"这段 finally 不会执行的窗口。
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

    @staticmethod
    def _build_bat_script() -> str:
        lines = [
            "@echo off",
            "chcp 65001 >nul",
            "setlocal enableextensions",
            'set "TARGET_PID=%DLC_PID%"',
            'set "EXE=%DLC_EXE%"',
            'set "NEW=%DLC_NEW%"',
            'set "OLD=%DLC_OLD%"',
            'set "LOG=%DLC_LOG%"',
            'set "STATE=%DLC_STATE%"',
            'set "VER=%DLC_VERSION%"',
            "set /a WAIT_MAX=%DLC_WAIT%",
            "set /a WAIT_COUNT=0",
            "set /a PROBE_SEC=%DLC_PROBE%",
            'for %%F in ("%EXE%") do set "EXE_NAME=%%~nxF"',
            "",
            'call :log "updater start pid=%TARGET_PID% ver=%VER%"',
            'call :log "script entered, cmd environment ok"',
            "",
            ":waitloop",
            'tasklist /FI "PID eq %TARGET_PID%" 2>nul | find "%TARGET_PID%" >nul',
            "if errorlevel 1 goto do_move",
            "set /a WAIT_COUNT+=1",
            "if %WAIT_COUNT% GEQ %WAIT_MAX% goto do_move",
            "ping -n 2 127.0.0.1 >nul",
            "goto waitloop",
            "",
            ":do_move",
            'call :log "backup old"',
            'move /y "%EXE%" "%OLD%" >nul 2>>"%LOG%"',
            "if errorlevel 1 (",
            'call :log "backup old failed"',
            'call :write_state "backup_failed"',
            "goto cleanup",
            ")",
            'call :log "install new"',
            'move /y "%NEW%" "%EXE%" >nul 2>>"%LOG%"',
            "if errorlevel 1 (",
            'call :log "install new failed - rollback"',
            'call :do_rollback "install_failed" "rollback_failed"',
            "goto cleanup",
            ")",
            'call :log "start new"',
            'start "" "%EXE%"',
            'call :log "probe new version (%PROBE_SEC%s)"',
            "ping -n %PROBE_SEC% 127.0.0.1 >nul",
            # 不用 tasklist /FI "IMAGENAME eq %EXE_NAME%"：EXE_NAME 含空格时
            # filter 值无法用嵌套引号正确传递。直接全量 tasklist 后用
            # findstr /B 按行首匹配映像名称，含空格也安全。
            'tasklist 2>nul | findstr /I /B /C:"%EXE_NAME%" >nul',
            "if errorlevel 1 (",
            'call :log "probe failed: new version exited"',
            'call :do_rollback "probe_failed" "probe_rollback_failed"',
            "goto cleanup",
            ")",
            'call :log "update success"',
            'del /f /q "%STATE%" >nul 2>&1',
            'del /f /q "%OLD%" >nul 2>&1',
            "goto cleanup",
            "",
            ":do_rollback",
            'call :log "rollback: restore old (reason=%~1)"',
            'move /y "%OLD%" "%EXE%" >nul 2>>"%LOG%"',
            "if errorlevel 1 (",
            'call :log "rollback failed - cannot restore old"',
            'call :write_state "%~2"',
            "goto :eof",
            ")",
            'call :log "rollback: start old"',
            'call :write_state "%~1"',
            'start "" "%EXE%"',
            "goto :eof",
            "",
            ":write_state",
            '> "%STATE%" (',
            "echo version=%VER%",
            "echo reason=%~1",
            'echo new_exe="%NEW%"',
            'echo log_path="%LOG%"',
            ")",
            "goto :eof",
            "",
            ":cleanup",
            'del /f /q "%NEW%" >nul 2>&1',
            'del "%~f0" >nul 2>&1',
            "exit /b 0",
            "",
            ":log",
            'echo [%DATE% %TIME%] %~1 >> "%LOG%"',
            "goto :eof",
        ]
        return "\r\n".join(lines) + "\r\n"

    # [FIX] 单次下载（支持 Range 续传）；返回 (total, start) 或 None。
    #       慢速检测：连续 slow_abort_windows 个窗口速度低于阈值时抛
    #       _SlowDownload。调用方据 has_next 决定"切换下一源"还是
    #       "转成终态错误"，本函数只负责判定与抛出。
    def _download_once(
        self, url: str, dest: str, resume_from: int,
        *, allow_slow_abort: bool = False,
        slow_abort_windows: int = 1,
    ):
        headers = {"User-Agent": "DLC-Updater"}
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
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
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_expected:
                            pct = min(99, downloaded * 100 // total_expected)
                            if pct != last_pct:
                                last_pct = pct
                                self.progress.emit(pct)

                        # [FIX] 慢速检测：有 Content-Length 时用
                        #       downloaded < total_expected 排除"已下完"
                        #       误判；无 Content-Length（chunked / 代理剥离
                        #       长度）时同样检测——窗口只看增量字节。
                        #       每个窗口结束都重置窗口，以"连续窗口数"计数。
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
                # [FIX] 无论成功、失败、取消，都记录本 URL 实测速度，
                #       便于用户反馈"慢"时定位是主 URL 还是镜像。
                #       整个日志块吞掉 OSError：慢速/取消路径下主线程
                #       cleanup_partial 可能已删 dest，这里 getsize 抛错
                #       会覆盖正在传播的 _SlowDownload / _DownloadCancelled，
                #       导致切换分类错误。诊断日志失败不得影响控制流。
                try:
                    elapsed = time.monotonic() - t0
                    if os.path.exists(dest):
                        actual = os.path.getsize(dest)
                    else:
                        actual = downloaded
                    added = max(0, actual - resume_from)
                    speed = added / max(elapsed, 0.001)
                    logger.info(
                        "URL 下载结束: %s, %.0f KB/s, %.1f s, %d/%d bytes",
                        url, speed / 1024, elapsed, actual,
                        total_expected or actual)
                except OSError:
                    logger.debug("记录下载速度失败: %r", dest, exc_info=True)

        return (total_expected, resume_from) if total_expected else None

    # [FIX] 多 URL fallback + 单 URL 内退避重试 + 续传 + sha 校验。
    def _download_and_verify(self, dest: str) -> None:
        last_exc: Optional[BaseException] = None
        for idx, url in enumerate(self._urls):
            has_next = idx + 1 < len(self._urls)
            # 有备选源：1 个慢窗口（8s）即切，快速 fallback；
            # 无备选源：2 个慢窗口（16s）才中止，避免抖动误杀。
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
                        slow_abort_windows=slow_windows)
                    if info is not None:
                        total_expected, _ = info
                        actual = os.path.getsize(dest)
                        if actual < total_expected:
                            raise _IncompleteDownload(
                                f"更新包不完整（期望 {total_expected}，"
                                f"实际 {actual}），将续传重试")
                        if actual > total_expected:
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
                        # 不重试同一 URL，直接切下一个。已下载字节
                        # 保留在 dest 中，下一个 URL 用 Range 续传。
                        last_exc = e
                        logger.warning(
                            "下载过慢，切换下一个地址: %s: %s", url, e)
                        break
                    # 无备选源：慢速中止即终态。转成面向用户的错误，
                    # 附主下载地址，避免只有一行底层异常让用户无从下手。
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
        new_exe = os.path.join(tempfile.gettempdir(), _tmp_exe_name(self._pid))
        self._partial_path = new_exe
        bat_path = os.path.join(tempfile.gettempdir(), _tmp_bat_name(self._pid))
        log_path = os.path.join(tempfile.gettempdir(), _tmp_log_name(self._pid))
        old_exe = exe_path + _OLD_EXE_SUFFIX
        state_path = _state_file_path()

        try:
            for p in (new_exe, bat_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            _clear_state_file()

            # [FIX] 下载段整体替换为多 URL fallback + 退避重试 + 续传。
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

            # 无 BOM 的 UTF-8：带 BOM 会让 cmd 把 EF BB BF 当成命令的一部分，
            # 首行 @echo off 可能失效甚至整段脚本被误解析。
            with open(bat_path, "w", encoding="utf-8", newline="") as f:
                f.write(self._build_bat_script())

            env = os.environ.copy()
            env.update({
                "DLC_PID": str(self._pid),
                "DLC_EXE": exe_path,
                "DLC_NEW": new_exe,
                "DLC_OLD": old_exe,
                "DLC_LOG": log_path,
                "DLC_WAIT": str(_WAIT_EXIT_MAX_SEC),
                "DLC_PROBE": str(_NEW_VERSION_PROBE_SEC + 1),
                "DLC_STATE": state_path,
                "DLC_VERSION": self._target_version,
            })

            if self._cancelled.is_set():
                raise _DownloadCancelled()

            proc = subprocess.Popen(
                ["cmd", "/c", os.path.basename(bat_path)],
                cwd=os.path.dirname(bat_path),
                creationflags=(
                    subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP),
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
            logger.info(f"更新包下载并校验完成，替换脚本已启动；日志: {log_path}")
        except _DownloadCancelled:
            result["cancelled"] = True
            result["error"] = "下载已取消"
            logger.info("下载被用户取消")
        except Exception as e:
            result["error"] = f"下载更新失败: {e}"
            logger.error(result["error"], exc_info=True)
        finally:
            # 先清 _partial_path：主线程 shutdown 的 cleanup_partial
            # 拿到 None 会短路，避免与本函数竞争同一文件。
            self._partial_path = None
            if not result["ok"]:
                # 正常 / 取消 / 失败三种非成功路径都要清临时文件。
                # 缺这段时 sha256 不匹配、网络中断等路径会永久残留
                # new_exe 与 bat（state 文件在下载阶段未写，下次启动
                # _cleanup_leftover_new_exe 找不到它们）。
                for p in (new_exe, bat_path):
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except OSError:
                        logger.debug("清理临时文件失败: %r", p, exc_info=True)
                _clear_state_file()

        self.finished_download.emit(result)


# ===================== 管理器 =====================
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
                logger.warning(f"重试目标版本 {retry_version} 在远程已不可用，放弃")
            else:
                logger.debug("当前已是最新版本")
            return

        info = result.get("info", {})
        if not isinstance(info, dict):
            logger.warning(f"version.json info 非 dict: {type(info).__name__}")
            return

        required = ("version", "download_url", "sha256")
        missing = [k for k in required if not info.get(k)]
        if missing:
            logger.warning(
                f"version.json 缺少必填字段 {missing}，忽略本次更新。"
                f"请在清单中补齐后重试。")
            return
        if not _is_safe_download_url(info.get("download_url", "")):
            logger.warning(
                f"download_url 协议非法或格式错误: "
                f"{info.get('download_url')!r}")
            return

        # 过滤非法镜像，统一落到 download_url_mirrors（列表），并让
        # download_url_mirror 指向第一个以保持旧逻辑一致。放在
        # retry/正常两条路径分叉之前，两处都受益。
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
        if not _is_packaged():
            logger.warning("非打包环境，拒绝执行自动替换")
            return False
        if sys.platform != "win32":
            logger.warning("自动替换仅支持 Windows，当前平台为 %s", sys.platform)
            return False
        if not self._pending_info:
            logger.warning("无待下载的更新信息")
            return False
        if self._downloader is not None and self._downloader.isRunning():
            logger.debug("下载进行中，忽略重复请求")
            return False

        url = self._pending_info.get("download_url")
        sha = self._pending_info.get("sha256", "")
        version = str(self._pending_info.get("version", "")).strip()
        if not url:
            logger.warning("version.json 缺少 download_url")
            return False
        if not sha:
            logger.warning("version.json 缺少 sha256，拒绝下载")
            return False
        # 防 cmd 注入：version 会被拼进 bat 的 echo version=%VER%。
        # 这里拒绝的是含危险字符的版本，不是"非 X.Y.Z 格式"。
        if not _SAFE_VERSION_RE.fullmatch(version):
            logger.warning(
                f"version.json 的 version 字段含非法字符，拒绝下载: "
                f"{version!r}")
            return False

        # 镜像按 manifest 顺序优先，直链兜底；跳过与主 URL 相同的项。
        urls = [
            m for m in _collect_mirrors(self._pending_info) if m != url
        ]
        urls.append(url)

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
            # [FIX] 附带主下载地址，UI 可据此提供"手动下载"入口
            #       （浏览器走另一条 TLS 路径常能绕过被 RST 的连接）。
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
                # 线程卡在网络 read 等无法及时响应 cancel 的位置，
                # 进程即将退出，finally 不会执行。主线程尽力删
                # 半成品；Windows 上若线程仍持有文件句柄会 OSError，
                # 被 cleanup_partial 吞掉，属于已知的尽力而为。
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