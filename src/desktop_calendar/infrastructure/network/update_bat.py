# coding: utf-8
"""更新脚本（bat）生成与 state 文件读写。"""
import os
import tempfile
import time

from desktop_calendar.config.manager import get_config_path, get_logger

logger = get_logger()

_STATE_FILE_NAME = "update_state.txt"
_OLD_EXE_SUFFIX = ".old"
_WAIT_EXIT_MAX_SEC = 60
_NEW_VERSION_PROBE_SEC = 12
_ORPHAN_LOG_MAX_AGE_SEC = 86400


def _state_file_path() -> str:
    return os.path.join(os.path.dirname(get_config_path()), _STATE_FILE_NAME)


def _clear_state_file() -> None:
    p = _state_file_path()
    try:
        if os.path.exists(p):
            os.remove(p)
    except OSError:
        logger.debug("清除更新状态标记失败", exc_info=True)


def _tmp_exe_name(pid: int) -> str:
    return f"DLC_update_new_{pid}.exe"


def _tmp_bat_name(pid: int) -> str:
    return f"DLC_update_apply_{pid}.bat"


def _tmp_log_name(pid: int) -> str:
    return f"DLC_update_{pid}.log"


def _cleanup_leftover_new_exe(path: str | None) -> None:
    """清理上次更新失败遗留的临时更新包（及对应的 bat）。

    只接受 %TEMP%/DLC_update_new_<pid>.exe 形状，防止 state 被篡改后
    诱导删除任意文件。清理 log 不做：update.prev_failed_detail 里向
    用户展示的诊断日志路径指向它。
    """
    if not path:
        return
    try:
        norm = os.path.normpath(path)
        tmp_dir = os.path.normpath(tempfile.gettempdir())
        base = os.path.basename(norm)
        if (os.path.normcase(os.path.dirname(norm))
                != os.path.normcase(tmp_dir)
                or not base.startswith("DLC_update_new_")
                or not base.endswith(".exe")):
            logger.warning("state 中 new_exe 路径不合规，跳过清理: %r", path)
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


def _cleanup_orphan_update_logs(keep: str | None,
                                max_age_sec: float | None = None) -> None:
    """清理 %TEMP% 下所有 DLC_update_*.log，保留 keep 指定的文件。"""
    keep_norm = os.path.normpath(keep) if keep else None
    tmp_dir = tempfile.gettempdir()
    now = time.time()
    try:
        names = os.listdir(tmp_dir)
    except OSError:
        logger.debug("扫描临时目录失败", exc_info=True)
        return
    for name in names:
        if not (name.startswith("DLC_update_") and name.endswith(".log")):
            continue
        full = os.path.normpath(os.path.join(tmp_dir, name))
        if keep_norm is not None and (
                os.path.normcase(full) == os.path.normcase(keep_norm)):
            continue
        if max_age_sec is not None:
            try:
                if now - os.path.getmtime(full) < max_age_sec:
                    continue
            except OSError:
                continue
        try:
            os.remove(full)
            logger.info("清理历史更新日志: %s", full)
        except OSError:
            logger.debug("清理更新日志失败: %r", full, exc_info=True)


def consume_state_file() -> dict | None:
    """读取并删除上次更新失败标记。文件为 bat 写的 key=value 行。"""
    p = _state_file_path()
    if not os.path.exists(p):
        _cleanup_orphan_update_logs(
            keep=None, max_age_sec=_ORPHAN_LOG_MAX_AGE_SEC)
        return None

    result: dict = {}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if line and "=" in line:
                    k, _, v = line.partition("=")
                    result[k.strip()] = v.strip().strip('"')
    except Exception:
        logger.warning("读取更新状态标记失败", exc_info=True)

    _clear_state_file()
    _cleanup_leftover_new_exe(result.get("new_exe"))
    keep = result.get("log_path")
    _cleanup_orphan_update_logs(
        keep=keep,
        max_age_sec=None if keep else _ORPHAN_LOG_MAX_AGE_SEC,
    )
    return result or None


def build_bat_script() -> str:
    """生成替换脚本（含 backup/install/rollback 重试、probe_writable 细分）。"""
    lines = [
        "@echo off", "chcp 65001 >nul 2>&1", "setlocal enableextensions",
        # 必填 env 防御：缺失时 tasklist 的 filter 会畸形，且 :log 无有效路径可写。
        "if not defined DLC_PID goto missing_env",
        "if not defined DLC_EXE goto missing_env",
        "if not defined DLC_NEW goto missing_env",
        # [FIX] OLD 是 backup 目标，缺失会让 move 误报 locked/permission。
        "if not defined DLC_OLD goto missing_env",
        "if not defined DLC_LOG goto missing_env",
        "if not defined DLC_STATE goto missing_env",
        'set "TARGET_PID=%DLC_PID%"', 'set "EXE=%DLC_EXE%"',
        'set "NEW=%DLC_NEW%"', 'set "OLD=%DLC_OLD%"',
        'set "LOG=%DLC_LOG%"', 'set "STATE=%DLC_STATE%"',
        # VERSION 只用于日志，缺失不致命。
        'if not defined DLC_VERSION set "DLC_VERSION=unknown"',
        'set "VER=%DLC_VERSION%"', "",
        # [FIX] WAIT/PROBE/HEARTBEAT 安全默认值：未定义或非正数时回落到内置值，
        # 避免 `set /a WAIT_MAX=` 报错导致后续 `if ... GEQ ` 语法中断。
        'if not defined DLC_WAIT set "DLC_WAIT=60"',
        "set /a WAIT_MAX=%DLC_WAIT% 2>nul",
        'if not defined WAIT_MAX set "WAIT_MAX=60"',
        'if %WAIT_MAX% LEQ 0 set "WAIT_MAX=60"',
        'if not defined DLC_PROBE set "DLC_PROBE=12"',
        "set /a PROBE_SEC=%DLC_PROBE% 2>nul",
        'if not defined PROBE_SEC set "PROBE_SEC=12"',
        'if %PROBE_SEC% LEQ 0 set "PROBE_SEC=12"',
        'if not defined DLC_HEARTBEAT set "DLC_HEARTBEAT=10"',
        "set /a HB_INTERVAL=%DLC_HEARTBEAT% 2>nul",
        'if not defined HB_INTERVAL set "HB_INTERVAL=10"',
        'if %HB_INTERVAL% LEQ 0 set "HB_INTERVAL=10"', "",
        "set /a WAIT_COUNT=0", "set /a HB_COUNT=0",
        "set /a MOVE_RETRY=0",
        'for %%F in ("%EXE%") do set "EXE_NAME=%%~nxF"',
        'for %%F in ("%EXE%") do set "EXE_DIR=%%~dpF"', "",
        'call :log "updater start pid=%TARGET_PID% ver=%VER%"',
        'call :log "script entered, cmd environment ok"',
        'call :log "WAIT_MAX=%WAIT_MAX% PROBE=%PROBE_SEC% HB=%HB_INTERVAL%"',
        "",
        ":waitloop",
        # [FIX] 原 `tasklist | find` 在 DETACHED + chcp 65001 下 find 会挂死。
        # tasklist 无匹配时退出码为 1，直接用它判断。
        'tasklist /FI "PID eq %TARGET_PID%" >nul 2>&1',
        "if errorlevel 1 goto do_move", "set /a WAIT_COUNT+=1",
        "if %WAIT_COUNT% GEQ %WAIT_MAX% goto do_move",
        # [NEW] 心跳：每 HB_INTERVAL 次循环写一条，避免无日志疑似卡死。
        "set /a HB_COUNT+=1",
        "if %HB_COUNT% GEQ %HB_INTERVAL% (",
        "set /a HB_COUNT=0",
        'call :log "still waiting pid=%TARGET_PID% count=%WAIT_COUNT%"',
        ")",
        "ping -n 2 127.0.0.1 >nul", "goto waitloop", "",
        ":do_move", 'call :log "backup old"', "set /a MOVE_RETRY=0",
        ":retry_backup", 'move /y "%EXE%" "%OLD%" >nul 2>>"%LOG%"',
        "if not errorlevel 1 goto backup_ok",
        "set /a MOVE_RETRY+=1",
        "if %MOVE_RETRY% GEQ 5 (",
        'call :log "backup old failed after 5 retries"',
        'call :probe_writable "backup_failed"', "goto cleanup", ")",
        'call :log "backup old retry"', "ping -n 2 127.0.0.1 >nul",
        "goto retry_backup", ":backup_ok", "",
        'call :log "install new"', "set /a MOVE_RETRY=0",
        ":retry_install", 'move /y "%NEW%" "%EXE%" >nul 2>>"%LOG%"',
        "if not errorlevel 1 goto install_ok",
        "set /a MOVE_RETRY+=1",
        "if %MOVE_RETRY% GEQ 5 (",
        'call :log "install new failed after 5 retries - rollback"',
        'call :do_rollback "install_failed" "rollback_failed"',
        "goto cleanup", ")", 'call :log "install new retry"',
        "ping -n 2 127.0.0.1 >nul", "goto retry_install", ":install_ok", "",
        'call :log "start new"',
        # [FIX] 指定工作目录为 exe 所在目录；`%EXE_DIR%.` 避免尾反斜杠转义引号。
        'start "" /D "%EXE_DIR%." "%EXE%"',
        'call :log "probe new version (%PROBE_SEC%s)"',
        "ping -n %PROBE_SEC% 127.0.0.1 >nul",
        'tasklist /FI "IMAGENAME eq %EXE_NAME%" /NH >nul 2>&1',
        "if errorlevel 1 (",
        'call :log "probe failed: new version exited"',
        'call :do_rollback "probe_failed" "probe_rollback_failed"',
        "goto cleanup", ")", 'call :log "update success"',
        'del /f /q "%STATE%" >nul 2>&1', 'del /f /q "%OLD%" >nul 2>&1',
        "goto cleanup", "",
        ":do_rollback", 'call :log "rollback: restore old (reason=%~1)"',
        "set /a MOVE_RETRY=0", ":retry_rollback",
        'move /y "%OLD%" "%EXE%" >nul 2>>"%LOG%"',
        "if not errorlevel 1 goto rollback_ok",
        "set /a MOVE_RETRY+=1",
        "if %MOVE_RETRY% GEQ 5 (",
        'call :log "rollback failed after 5 retries - cannot restore old"',
        'call :write_state "%~2"', "goto :eof", ")",
        'call :log "rollback retry"', "ping -n 2 127.0.0.1 >nul",
        "goto retry_rollback", ":rollback_ok",
        'call :log "rollback: start old"', 'call :write_state "%~1"',
        'start "" /D "%EXE_DIR%." "%EXE%"', "goto :eof", "",
        ":probe_writable",
        # [FIX] 用 if exist 判断文件是否创建成功，比 errorlevel 更直观，
        # 也避免重定向顺序问题。能创建→目录可写但 move 失败=locked；
        # 不能创建→permission。
        '>"%EXE%.wtest" echo x 2>nul',
        'if exist "%EXE%.wtest" (',
        'del /f /q "%EXE%.wtest" >nul 2>&1',
        'call :write_state "%~1_locked"',
        ") else (",
        'call :write_state "%~1_permission"',
        ")",
        "goto :eof", "",
        ":write_state", '> "%STATE%" (', "echo version=%VER%",
        "echo reason=%~1", 'echo new_exe="%NEW%"',
        'echo old_exe="%OLD%"', 'echo log_path="%LOG%"', ")",
        "goto :eof", "", ":cleanup",
        'del /f /q "%NEW%" >nul 2>&1', 'del "%~f0" >nul 2>&1',
        "exit /b 0", "",
        # env 缺失退出路径：此时 LOG 可能未定义，不能 call :log。
        ":missing_env", 'del "%~f0" >nul 2>&1', "exit /b 2", "",
        ":log", 'echo [%DATE% %TIME%] %~1 >> "%LOG%"', "goto :eof",
    ]
    return "\r\n".join(lines) + "\r\n"