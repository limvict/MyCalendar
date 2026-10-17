# coding: utf-8
"""
自动更新管理器：版本检查、下载、替换、重启。

职责：
  - 后台线程检查远程 version.json
  - 有新版本时通过 event_bus 广播 UPDATE_AVAILABLE
  - 下载新 exe 到临时目录、校验 SHA-256、写 bat 完成替换
  - 下载中通过 UPDATE_PROGRESS 广播进度（0-100）

边界：
  - 不弹窗（UI 由订阅者负责），只广播事件；
  - 不依赖主窗口，可在任意时刻被构造；
  - 非 Windows / 非打包环境静默禁用。

线程模型：
  - 所有网络 IO 在 UpdateChecker / UpdateDownloader (QThread) 内；
  - download_and_apply_async 立即返回，通过 finished_download 信号
    通知结果；调用方（MainWindow）在收到 UPDATE_READY 后退出主程序。
  - 线程对象在 finished 信号上连接 deleteLater，槽里将
    self._checker / self._downloader 置 None，避免对象悬挂。
"""
import os
import sys
import json
import hashlib
import tempfile
import subprocess
import threading
from typing import Optional
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import URLError

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from desktop_calendar.config.config import get_logger, get_config_path, config
from desktop_calendar.services.event_bus import event_bus, EventType

logger = get_logger()

# ===================== 更新配置 =====================
# 部署时改成你自己的版本清单地址
UPDATE_MANIFEST_URL = "https://github.com/limvict/MyCalendar/releases/latest/download/version.json"

# 当前程序版本，与打包时 installer.iss 的 AppVersion 保持一致
# CI 建议加脚本校验（见 scripts/check_version.py）
CURRENT_VERSION = "3.0.4"

# 网络超时（秒）
CHECK_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 120

# 主程序退出后，bat 等待的轮询上限（秒）。
# 超过后强制 move —— 覆盖"用户从下载完成到点确定"耗时过长的情况。
_WAIT_EXIT_MAX_SEC = 60

# 新版本启动后，bat 观察其存活多少秒再确认更新成功。
# 若期间进程消失，视为启动即崩，自动回滚旧版本。
_NEW_VERSION_PROBE_SEC = 5

# ===================== 更新失败状态标记 =====================
# bat 在失败路径写、Python 在下次启动读。
# 必须放在应用数据目录：backup_failed 的典型原因是安装目录不可写，
# 若把标记也放在 exe 同目录就会跟着失败。
_STATE_FILE_NAME = "update_state.txt"


def _state_file_path() -> str:
    return os.path.join(
        os.path.dirname(get_config_path()), _STATE_FILE_NAME)


def _clear_state_file() -> None:
    p = _state_file_path()
    try:
        if os.path.exists(p):
            os.remove(p)
    except OSError:
        logger.debug("清除更新状态标记失败", exc_info=True)


def consume_state_file() -> Optional[dict]:
    """
    读取并删除状态标记。

    返回 None 表示无标记（正常启动）。
    返回 dict 表示上次更新失败，字段：
      version / reason / new_exe / old_exe / log_path

    文件格式是 bat 写的 key=value 行（路径用双引号包裹以规避
    cmd 对 & 等特殊字符的解释），不是 JSON。
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
                # 路径写入时用双引号包了，读回来要剥掉
                result[k.strip()] = v.strip().strip('"')
    except Exception:
        logger.warning("读取更新状态标记失败", exc_info=True)
        result = {}
    # 无论解析成败都删掉，避免下次启动重复弹窗
    _clear_state_file()
    return result or None

# 临时文件按 PID 命名，避免多实例 / 多次重试互相覆盖。
def _tmp_exe_name(pid: int) -> str:
    return f"DLC_update_new_{pid}.exe"


def _tmp_bat_name(pid: int) -> str:
    return f"DLC_update_apply_{pid}.bat"


def _tmp_log_name(pid: int) -> str:
    return f"DLC_update_{pid}.log"


_OLD_EXE_SUFFIX = ".old"


class _DownloadCancelled(Exception):
    """内部使用：表示用户主动取消了下载。"""
    pass


# ===================== 版本比较 =====================
def _parse_version(v: str) -> tuple:
    """
    把 "3.1.2" 解析为 (3, 1, 2)，非数字段按 0 处理。
    比 tuple 直接比较更宽容，避免 "3.1" vs "3.1.0" 误判。
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
    """
    判断当前是否为"已打包"运行环境。

    覆盖主流打包器：
      - PyInstaller / cx_Freeze / py2exe: sys.frozen = True
      - 部分工具仅设 sys._MEIPASS
      - Nuitka: sys.nuitka_version
    源码运行（python main.py）三者皆为假，拒绝自动替换。
    """
    return (
        getattr(sys, "frozen", False)
        or getattr(sys, "_MEIPASS", None) is not None
        or hasattr(sys, "nuitka_version")
    )


def _is_placeholder_url(url: str) -> bool:
    """占位符 URL 检测：避免发版前误把别人的 version.json 拉下来。"""
    if not url:
        return True
    lowered = url.lower()
    return "yourname" in lowered or "yourrepo" in lowered


def _is_safe_download_url(url: str) -> bool:
    """
    下载地址必须是 http(s) 且带 host。
    防止被劫持的 version.json 把 download_url 指向 file:// 等本地协议。
    """
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def _sha256_of_file(path: str) -> str:
    """分块读取计算 SHA-256，避免一次性把大文件读进内存。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


# ===================== 版本检查线程 =====================
class UpdateChecker(QThread):
    """后台检查版本，完成后通过信号回传结果。"""

    # payload: {"has_update": bool, "info": dict, "error": str | None}
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
    """
    后台下载新版本、校验 SHA-256、写 bat 并启动。

    替换脚本设计要点：
      - bat 以 UTF-8-SIG 写入，cmd 能识别中文路径（国区用户目录常含中文）；
      - 路径通过环境变量传入，不做字符串插值，规避 %/&/^ 转义坑；
      - move 失败 / 新版本启动即崩 → 自动回滚旧版本并重新启动；
      - 全过程写日志到 %TEMP%\\DLC_update_{pid}.log，便于事后定位。
    """

    # payload: {"ok": bool, "error": str | None, "cancelled": bool}
    finished_download = pyqtSignal(dict)
    # 0-100；Content-Length 缺失时不发
    progress = pyqtSignal(int)

    def __init__(self, download_url: str, expected_sha256: str,
             target_pid: int, target_version: str = "", parent=None):
        super().__init__(parent)
        self._url = download_url
        self._expected_sha = (expected_sha256 or "").strip().lower()
        self._pid = int(target_pid)
        self._target_version = str(target_version or "").strip()
        self._cancelled = threading.Event()

    # ---------- 外部取消 ----------
    def cancel(self):
        """线程安全地请求中止下载。shutdown 时由 UpdateManager 调用。"""
        self._cancelled.set()

        # ---------- bat 脚本生成 ----------
    @staticmethod
    def _build_bat_script() -> str:
        """
        返回 bat 脚本。路径 / PID / 日志位置通过环境变量传入
        （DLC_PID / DLC_EXE / DLC_NEW / DLC_OLD / DLC_LOG / DLC_WAIT /
        DLC_PROBE / DLC_STATE / DLC_VERSION），脚本里是 %DLC_*% 占位符，
        避免在 Python 侧做 cmd 转义。

        关键顺序（不可调换）：
            1. move /y "%EXE%" "%OLD%"   ← 先备份，否则 .old 变新文件
            2. move /y "%NEW%" "%EXE%"   ← 再顶上新 exe
            3. start "" "%EXE%"          ← 启动新版本
            4. 探测 %DLC_PROBE% 秒：进程存活 → 删 .old；
               进程已死 → 视为启动即崩，回滚 .old 并重启旧版本

        失败路径设计：
            - 所有"更新未完成"的分支都会调 :write_state 写标记；
            - 标记由下次启动的 Python 侧消费（弹窗 + 重试/忽略）；
            - 成功路径显式 del 标记，避免下次误报；
            - backup_failed 分支保留 %NEW%（用户点重试时复用文件系统缓存），
              并 start 旧版 —— 旧版此时还在原位，重启不会失败。

        `start "" "%EXE%"` 在正常路径、探测失败回滚路径、安装失败
        回滚路径、backup_failed 路径各出现一次，四条路径互斥。若做
        自动化检查，不能用"只出现一次"作为约束。
        """
        return (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "setlocal enableextensions\r\n"
            'set "TARGET_PID=%DLC_PID%"\r\n'
            'set "EXE=%DLC_EXE%"\r\n'
            'set "NEW=%DLC_NEW%"\r\n'
            'set "OLD=%DLC_OLD%"\r\n'
            'set "LOG=%DLC_LOG%"\r\n'
            'set "STATE=%DLC_STATE%"\r\n'
            'set "VER=%DLC_VERSION%"\r\n'
            "set /a WAIT_MAX=%DLC_WAIT%\r\n"
            "set /a WAIT_COUNT=0\r\n"
            "set /a PROBE=%DLC_PROBE%\r\n"
            'for %%F in ("%EXE%") do set "EXE_NAME=%%~nxF"\r\n'
            "\r\n"
            'call :log "updater start pid=%TARGET_PID% ver=%VER%"\r\n'
            "\r\n"
            ":waitloop\r\n"
            'tasklist /FI "PID eq %TARGET_PID%" 2>nul | find "%TARGET_PID%" >nul\r\n'
            "if errorlevel 1 goto do_move\r\n"
            "set /a WAIT_COUNT+=1\r\n"
            "if %WAIT_COUNT% GEQ %WAIT_MAX% goto do_move\r\n"
            "ping -n 2 127.0.0.1 >nul\r\n"
            "goto waitloop\r\n"
            "\r\n"
            ":do_move\r\n"
            'call :log "backup old"\r\n'
            'move /y "%EXE%" "%OLD%" >nul 2>>"%LOG%"\r\n'
            "if errorlevel 1 (\r\n"
            '    call :log "backup old failed - restart old, keep new"\r\n'
            '    call :write_state "backup_failed"\r\n'
            '    start "" "%EXE%"\r\n'
            "    goto cleanup_keep_new\r\n"
            ")\r\n"
            'call :log "install new"\r\n'
            'move /y "%NEW%" "%EXE%" >nul 2>>"%LOG%"\r\n'
            "if errorlevel 1 (\r\n"
            '    call :log "install new failed - rollback"\r\n'
            "    goto rollback\r\n"
            ")\r\n"
            'call :log "start new"\r\n'
            'start "" "%EXE%"\r\n'
            'call :log "probe new version for %PROBE% seconds"\r\n'
            "ping -n %PROBE% 127.0.0.1 >nul\r\n"
            'tasklist /FI "IMAGENAME eq %EXE_NAME%" /FO CSV /NH 2>nul'
            ' | find /I "%EXE_NAME%" >nul\r\n'
            "if errorlevel 1 (\r\n"
            '    call :log "probe failed - new version died, rollback"\r\n'
            '    del /f /q "%EXE%" >nul 2>>"%LOG%"\r\n'
            '    move /y "%OLD%" "%EXE%" >nul 2>>"%LOG%"\r\n'
            "    if errorlevel 1 (\r\n"
            '        call :log "probe rollback failed - cannot restore old"\r\n'
            '        call :write_state "probe_rollback_failed"\r\n'
            "        goto cleanup\r\n"
            "    )\r\n"
            '    call :log "probe rollback: start old"\r\n'
            '    call :write_state "probe_failed"\r\n'
            '    start "" "%EXE%"\r\n'
            "    goto cleanup\r\n"
            ")\r\n"
            'call :log "new version alive - drop old backup"\r\n'
            'del /f /q "%OLD%" >nul 2>&1\r\n'
            'del /f /q "%STATE%" >nul 2>&1\r\n'
            'call :log "update success"\r\n'
            "goto cleanup\r\n"
            "\r\n"
            ":rollback\r\n"
            'call :log "rollback: restore old"\r\n'
            'move /y "%OLD%" "%EXE%" >nul 2>>"%LOG%"\r\n'
            "if errorlevel 1 (\r\n"
            '    call :log "rollback failed - cannot restore old"\r\n'
            '    call :write_state "rollback_failed"\r\n'
            "    goto cleanup\r\n"
            ")\r\n"
            'call :log "rollback: start old"\r\n'
            'call :write_state "install_failed"\r\n'
            'start "" "%EXE%"\r\n'
            "goto cleanup\r\n"
            "\r\n"
            ":write_state\r\n"
            '> "%STATE%" (\r\n'
            "    echo version=%VER%\r\n"
            "    echo reason=%~1\r\n"
            '    echo new_exe="%NEW%"\r\n'
            '    echo old_exe="%EXE%"\r\n'
            '    echo log_path="%LOG%"\r\n'
            ")\r\n"
            "goto :eof\r\n"
            "\r\n"
            ":cleanup\r\n"
            'del /f /q "%NEW%" >nul 2>&1\r\n'
            'del "%~f0" >nul 2>&1\r\n'
            "exit /b 0\r\n"
            "\r\n"
            ":cleanup_keep_new\r\n"
            'del "%~f0" >nul 2>&1\r\n'
            "exit /b 0\r\n"
            "\r\n"
            ":log\r\n"
            'echo [%DATE% %TIME%] %~1 >> "%LOG%"\r\n'
            "goto :eof\r\n"
        )
    
    # ---------- 主流程 ----------
    def run(self):
        result = {"ok": False, "error": None, "cancelled": False}
        exe_path = sys.executable
        new_exe = os.path.join(
            tempfile.gettempdir(), _tmp_exe_name(self._pid))
        bat_path = os.path.join(
            tempfile.gettempdir(), _tmp_bat_name(self._pid))
        log_path = os.path.join(
            tempfile.gettempdir(), _tmp_log_name(self._pid))
        old_exe = exe_path + _OLD_EXE_SUFFIX
        state_path = _state_file_path()

        try:
            # 清理上一次失败残留（同 PID 重试场景）
            for p in (new_exe, bat_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

            # 清掉可能残留的旧标记：用户在上次失败后没重启、
            # 直接在旧版本里再次点"立即更新"的场景。下次 bat 失败
            # 会重新写这个文件，所以提前删是安全的。
            _clear_state_file()

            logger.info(f"开始下载更新包: {self._url}")
            req = Request(self._url, headers={"User-Agent": "DLC-Updater"})
            with urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
                total = resp.headers.get("Content-Length")
                total = int(total) if total and total.isdigit() else 0
                downloaded = 0
                last_pct = -1
                with open(new_exe, "wb") as f:
                    while True:
                        if self._cancelled.is_set():
                            raise _DownloadCancelled()
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            if pct != last_pct:
                                last_pct = pct
                                self.progress.emit(pct)

            if self._cancelled.is_set():
                raise _DownloadCancelled()

            if not os.path.exists(new_exe) or os.path.getsize(new_exe) == 0:
                raise IOError("下载文件为空")

            # SHA-256 校验：挡住 CDN 劫持 / 半途截断 / 错误页冒充 exe
            if self._expected_sha:
                actual = _sha256_of_file(new_exe)
                if actual != self._expected_sha:
                    raise IOError(
                        "更新包校验失败（期望 "
                        f"{self._expected_sha[:12]}...，实际 "
                        f"{actual[:12]}...），已中止更新")
            else:
                logger.warning(
                    "更新清单未提供 sha256，跳过完整性校验。"
                    "请尽快在 version.json 中补充该字段。")

            # UTF-8-SIG：带 BOM，让 cmd 按 UTF-8 解析，中文路径不乱码
            with open(bat_path, "w", encoding="utf-8-sig", newline="") as f:
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

            subprocess.Popen(
                ["cmd", "/c", bat_path],
                creationflags=(
                    subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                ),
                close_fds=True,
                env=env,
            )
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
            if not result["ok"]:
                for p in (new_exe, bat_path):
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
                # Python 侧自身失败（下载/校验/Popen 报错），bat 根本没
                # 启动，不会写标记；此时把"预清理"过的标记重新删一次兜底。
                _clear_state_file()

        self.finished_download.emit(result)


# ===================== 管理器 =====================
class UpdateManager(QObject):
    """
    自动更新调度器：对外的唯一入口。

    使用方式（在 MainWindow.__init__ 中）：
        self.update_mgr = UpdateManager(self)
        QTimer.singleShot(3000, self.update_mgr.check_async)

    事件订阅方（可选，用于自定义 UI）：
        event_bus.subscribe(EventType.UPDATE_AVAILABLE, on_update_available)
        event_bus.subscribe(EventType.UPDATE_FAILED,    on_update_failed)
        event_bus.subscribe(EventType.UPDATE_READY,     on_update_ready)
        event_bus.subscribe(EventType.UPDATE_PROGRESS,  on_update_progress)
    """

    def __init__(self, parent=None, manifest_url: str = UPDATE_MANIFEST_URL):
        super().__init__(parent)
        self._manifest_url = manifest_url
        self._checker: Optional[UpdateChecker] = None
        self._downloader: Optional[UpdateDownloader] = None
        self._pending_info: dict = {}
        self._orphan_threads: list = []
        # 用户在"上次更新失败"弹窗里点了重试时，这里保存期望的版本号；
        # 下一次 _on_checked 若远程版本与之匹配，跳过二次确认直接下载。
        self._retry_version: str = ""

    def check_async(self, retry_version: str = "") -> bool:
        """
        发起一次异步版本检查。
        :param retry_version: 非空时表示这是用户点过"重试"发起的检查；
            远程版本匹配该值时跳过二次确认，直接下载。
        :return: True 表示已发起；False 表示当前环境不支持。
        """
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
        # 取出后立即清空：避免残留到下一次普通检查时误触发自动下载
        retry_version = self._retry_version
        self._retry_version = ""

        if result.get("error"):
            logger.debug(f"版本检查未命中: {result['error']}")
            return
        if not result.get("has_update"):
            if retry_version:
                logger.warning(
                    f"重试目标版本 {retry_version} 在远程已不可用，"
                    f"本次重试放弃")
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

        version = str(info.get("version", "")).strip()

        # 用户点过"重试"且远程版本一致 → 跳过二次确认，直接下载。
        # 放在"忽略此版本"检查之前：用户显式选择重试，应当覆盖之前
        # 可能存在的忽略记录。
        if retry_version and version and (
                _parse_version(version) == _parse_version(retry_version)):
            logger.info(f"按用户重试意图直接下载版本 {version}")
            self._pending_info = info
            if not self.download_and_apply_async():
                event_bus.publish(
                    EventType.UPDATE_FAILED,
                    stage="download",
                    error=f"retry download start failed for {version}",
                )
            return

        # 用户之前点过"忽略此版本"：版本号相等则静默跳过。
        skipped = config.get("update_skipped_version", "") or ""
        if skipped and version and (
                _parse_version(version) == _parse_version(skipped)):
            logger.info(f"版本 {version} 已被用户忽略，跳过提示")
            return

        self._pending_info = info
        logger.info(
            f"发现新版本 {version}（当前 {CURRENT_VERSION}）")
        event_bus.publish(EventType.UPDATE_AVAILABLE, info=info)

    # ---------- 下载 ----------
    def download_and_apply_async(self) -> bool:
        """
        下载当前 pending 的更新包。完成后由调用方负责退出主程序。

        典型调用链：
            event_bus UPDATE_AVAILABLE
              → MainWindow 弹窗询问用户
              → 用户确认 → update_mgr.download_and_apply_async()
              → 下载完成信号 → MainWindow.quit_app()
        :return: True 已发起；False 无更新 / 正在下载 / 非打包环境。
        """
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
            # _on_checked 已拦截，这里再兜一次防止内部误调
            logger.warning("version.json 缺少 sha256，拒绝下载")
            return False

        # 主程序 PID：交给 bat 轮询等待本进程退出后再做 move
        target_pid = os.getpid()
        self._downloader = UpdateDownloader(
            url, sha, target_pid, target_version=version, parent=self)
        self._downloader.finished.connect(self._downloader.deleteLater)
        self._downloader.finished_download.connect(self._on_downloaded)
        self._downloader.progress.connect(self._on_progress)
        self._downloader.start()
        return True

    # ---------- 取消下载（可选，UI 侧若加取消按钮可调用） ----------
    def cancel_download(self) -> bool:
        if self._downloader is None or not self._downloader.isRunning():
            return False
        self._downloader.cancel()
        return True

    def _on_progress(self, pct: int):
        # 转发为事件，UI 侧订阅即可，不需要直接持有 downloader
        event_bus.publish(EventType.UPDATE_PROGRESS, percent=int(pct))

    def _on_downloaded(self, result: dict):
        # 线程即将结束，清引用；对象由 deleteLater 回收
        self._downloader = None

        if result.get("cancelled"):
            logger.info("更新下载已取消")
            return
        if not result.get("ok"):
            logger.error(f"更新下载失败: {result.get('error')}")
            event_bus.publish(
                EventType.UPDATE_FAILED,
                stage="download",
                error=result.get("error", "unknown"),
            )
            return
        logger.info("更新已就绪，等待主程序退出")
        event_bus.publish(EventType.UPDATE_READY)

    # ---------- 上次更新失败标记 ----------
    def consume_pending_failure(self) -> Optional[dict]:
        """
        读取并清除上次更新失败的标记。返回 None 表示无标记。

        返回字段：version / reason / new_exe / old_exe / log_path。
        reason 取值：backup_failed / install_failed / probe_failed /
                    rollback_failed / probe_rollback_failed。
        """
        return consume_state_file()
    
    # ---------- 关闭 ----------
    def shutdown(self):
        """退出时等待线程收尾，避免 Qt 报 QThread destroyed while running。"""
        # 下载线程阻塞在 urlopen().read()，quit() 无效；必须靠 cancel()
        d = self._downloader
        if d is not None:
            try:
                d.cancel()
            except Exception:
                pass
            if d.isRunning() and not d.wait(8000):
                logger.warning(
                    "下载线程未在 8s 内退出，保留引用交由进程退出清理")
                self._orphan_threads.append(d)
            self._downloader = None

        c = self._checker
        if c is not None:
            if c.isRunning() and not c.wait(3000):
                logger.warning(
                    "检查线程未在 3s 内退出，保留引用交由进程退出清理")
                self._orphan_threads.append(c)
            self._checker = None