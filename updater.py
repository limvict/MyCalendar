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

from config import get_logger
from event_bus import event_bus, EventType

logger = get_logger()

# ===================== 更新配置 =====================
# 部署时改成你自己的版本清单地址
UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/yourname/yourrepo/main/version.json"

# 当前程序版本，与打包时 installer.iss 的 AppVersion 保持一致
# CI 建议加脚本校验（见 scripts/check_version.py）
CURRENT_VERSION = "3.0.1"

# 网络超时（秒）
CHECK_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 120

# 主程序退出后，bat 等待的轮询上限（秒）。
# 超过后强制 move —— 覆盖"用户从下载完成到点确定"耗时过长的情况。
_WAIT_EXIT_MAX_SEC = 60

# 新版本启动后，bat 观察其存活多少秒再确认更新成功。
# 若期间进程消失，视为启动即崩，自动回滚旧版本。
_NEW_VERSION_PROBE_SEC = 5


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
                 target_pid: int, parent=None):
        super().__init__(parent)
        self._url = download_url
        self._expected_sha = (expected_sha256 or "").strip().lower()
        self._pid = int(target_pid)
        self._cancelled = threading.Event()

    # ---------- 外部取消 ----------
    def cancel(self):
        """线程安全地请求中止下载。shutdown 时由 UpdateManager 调用。"""
        self._cancelled.set()

    # ---------- bat 脚本生成 ----------
    @staticmethod
    def _build_bat_script() -> str:
        """
        返回 bat 脚本。路径 / PID / 日志位置通过环境变量传入，
        不在 Python 侧做任何字符串插值，避开 cmd 转义坑。
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
            "set /a WAIT_MAX=%DLC_WAIT%\r\n"
            "set /a WAIT_COUNT=0\r\n"
            "\r\n"
            'call :log "updater start pid=%TARGET_PID%"\r\n'
            'call :log "exe=%EXE%"\r\n'
            'call :log "new=%NEW%"\r\n'
            "\r\n"
            ":waitloop\r\n"
            'tasklist /FI "PID eq %TARGET_PID%" 2>nul | find "%TARGET_PID%" >nul\r\n'
            "if errorlevel 1 goto do_move\r\n"
            "set /a WAIT_COUNT+=1\r\n"
            "if %WAIT_COUNT% GEQ %WAIT_MAX% (\r\n"
            '    call :log "wait timeout, force move"\r\n'
            "    goto do_move\r\n"
            ")\r\n"
            "ping -n 2 127.0.0.1 >nul\r\n"
            "goto waitloop\r\n"
            "\r\n"
            ":do_move\r\n"
            'call :log "backup old"\r\n'
            'move /y "%EXE%" "%OLD%" >nul 2>>"%LOG%"\r\n'
            "if errorlevel 1 (\r\n"
            '    call :log "backup old failed - abort and restart old"\r\n'
            '    start "" "%EXE%"\r\n'
            "    goto cleanup\r\n"
            ")\r\n"
            'call :log "install new"\r\n'
            'move /y "%NEW%" "%EXE%" >nul 2>>"%LOG%"\r\n'
            "if errorlevel 1 (\r\n"
            '    call :log "install new failed - rollback"\r\n'
            "    goto rollback\r\n"
            ")\r\n"
            'call :log "start new"\r\n'
            'start "" "%EXE%"\r\n'
            'call :log "probe new version alive..."\r\n'
            "ping -n %DLC_PROBE% 127.0.0.1 >nul\r\n"
            'set "EXE_NAME="\r\n'
            'for %%F in ("%EXE%") do set "EXE_NAME=%%~nxF"\r\n'
            'tasklist /FI "IMAGENAME eq %EXE_NAME%" 2>nul | find /I "%EXE_NAME%" >nul\r\n'
            "if errorlevel 1 (\r\n"
            '    call :log "new version not running - rollback"\r\n'
            "    goto rollback\r\n"
            ")\r\n"
            'call :log "update success"\r\n'
            'del /f /q "%OLD%" >nul 2>&1\r\n'
            "goto cleanup\r\n"
            "\r\n"
            ":rollback\r\n"
            'set "EXE_NAME="\r\n'
            'for %%F in ("%EXE%") do set "EXE_NAME=%%~nxF"\r\n'
            'taskkill /F /IM "%EXE_NAME%" >nul 2>&1\r\n'
            'call :log "rollback: restore old"\r\n'
            'del /f /q "%EXE%" >nul 2>&1\r\n'
            'move /y "%OLD%" "%EXE%" >nul 2>>"%LOG%"\r\n'
            'call :log "rollback: start old"\r\n'
            'start "" "%EXE%"\r\n'
            "goto cleanup\r\n"
            "\r\n"
            ":cleanup\r\n"
            'del /f /q "%NEW%" >nul 2>&1\r\n'
            'call :log "cleanup done"\r\n'
            '(goto) 2>nul & del "%~f0"\r\n'
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

        try:
            # 清理上一次失败残留（同 PID 重试场景）
            for p in (new_exe, bat_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

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
            })

            # DETACHED_PROCESS + NEW_PROCESS_GROUP：
            # 让 bat 完全脱离主进程，主程序退出后仍能继续执行
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
            # 失败路径清理临时文件；成功路径里：
            #   - new_exe 已经被 bat move 到 exe_path（不存在）
            #   - bat_path 被 bat 自身 del（不存在）
            # 因此这里的判断是安全的
            if not result["ok"]:
                for p in (new_exe, bat_path):
                    if os.path.exists(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass

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
        # 保存最近一次检查得到的更新信息，供下载时使用
        self._pending_info: dict = {}

    # ---------- 检查 ----------
    def check_async(self) -> bool:
        """
        发起一次异步版本检查。
        :return: True 表示已发起；False 表示当前环境不支持（未打包 /
                 正在检查 / 占位符 URL 未替换）。
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

        self._checker = UpdateChecker(self._manifest_url, self)
        # 线程结束后由 Qt 自动 deleteLater；槽里只清 self 的引用
        self._checker.finished.connect(self._checker.deleteLater)
        self._checker.checked.connect(self._on_checked)
        self._checker.start()
        return True

    def _on_checked(self, result: dict):
        # 无论结果如何都先清引用：线程即将结束，对象由 deleteLater 回收
        self._checker = None

        if result.get("error"):
            logger.debug(f"版本检查未命中: {result['error']}")
            return
        if not result.get("has_update"):
            logger.debug("当前已是最新版本")
            return

        info = result.get("info", {})
        if not isinstance(info, dict):
            logger.warning(f"version.json info 非 dict: {type(info).__name__}")
            return

        # 必填字段校验：缺失即拒绝更新，避免后续流程出错
        required = ("version", "download_url", "sha256")
        missing = [k for k in required if not info.get(k)]
        if missing:
            logger.warning(
                f"version.json 缺少必填字段 {missing}，忽略本次更新。"
                f"请在清单中补齐后重试。")
            return

        # 协议校验：download_url 必须 http(s)，挡住 file:// 等本地路径注入
        if not _is_safe_download_url(info.get("download_url", "")):
            logger.warning(
                f"download_url 协议非法或格式错误: "
                f"{info.get('download_url')!r}")
            return

        self._pending_info = info
        logger.info(
            f"发现新版本 {info.get('version')}（当前 {CURRENT_VERSION}）")
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
        if not self._pending_info:
            logger.warning("无待下载的更新信息")
            return False
        if self._downloader is not None and self._downloader.isRunning():
            logger.debug("下载进行中，忽略重复请求")
            return False

        url = self._pending_info.get("download_url")
        sha = self._pending_info.get("sha256", "")
        if not url:
            logger.warning("version.json 缺少 download_url")
            return False
        if not sha:
            # _on_checked 已拦截，这里再兜一次防止内部误调
            logger.warning("version.json 缺少 sha256，拒绝下载")
            return False

        # 主程序 PID：交给 bat 轮询等待本进程退出后再做 move
        target_pid = os.getpid()

        self._downloader = UpdateDownloader(url, sha, target_pid, self)
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
                logger.warning("下载线程未在 8s 内退出，放弃等待")
            self._downloader = None

        c = self._checker
        if c is not None:
            if c.isRunning() and not c.wait(3000):
                logger.warning("检查线程未在 3s 内退出，放弃等待")
            self._checker = None