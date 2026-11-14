# coding: utf-8
"""update_bat：bat 脚本生成、遗留清理、孤儿 log 清理。

consume_state_file 的基础 roundtrip 由 test_update_manager.py 覆盖；
本文件聚焦 update_manager 未覆盖的 build_bat_script / 清理函数细节。
"""
import os
import time
from pathlib import Path

import pytest

from desktop_calendar.infrastructure.network import update_bat


# ===================== build_bat_script =====================
class TestBuildBatScript:
    # ---------- 基础形态 ----------
    def test_returns_str(self):
        script = update_bat.build_bat_script()
        assert isinstance(script, str)
        assert script.endswith("\r\n")

    def test_line_endings_crlf(self):
        script = update_bat.build_bat_script()
        assert "\r\n" in script
        assert not script.replace("\r\n", "").endswith("\n")

    def test_key_sections(self):
        script = update_bat.build_bat_script()
        for token in (
            "@echo off", "chcp 65001", "setlocal enableextensions",
            ":waitloop", ":do_move", ":retry_backup", ":backup_ok",
            ":retry_install", ":install_ok", ":do_rollback",
            ":retry_rollback", ":rollback_ok", ":probe_writable",
            ":write_state", ":cleanup", ":missing_env", ":log",
        ):
            assert token in script, f"missing {token}"

    def test_state_written_with_echo(self):
        script = update_bat.build_bat_script()
        assert "echo version=%VER%" in script
        assert "echo reason=%~1" in script
        assert 'echo new_exe="%NEW%"' in script
        assert 'echo log_path="%LOG%"' in script

    def test_probe_uses_tasklist_filter(self):
        """修复点：probe 用 /FI 精确过滤，不再受 tasklist 映像名列宽截断影响。"""
        script = update_bat.build_bat_script()
        assert 'tasklist /FI "IMAGENAME eq %EXE_NAME%" /NH' in script
        # 旧实现（裸 tasklist + findstr /B）会被列宽截断误判
        assert 'findstr /I /B /C:"%EXE_NAME%"' not in script

    # ---------- 修复点 1：管道 find 挂死 ----------
    def test_no_pipe_find(self):
        """修复点：tasklist | find 在 DETACHED_PROCESS + chcp 65001 下会挂死
        （find 读管道 stdin 不退出）。"""
        script = update_bat.build_bat_script()
        assert "| find" not in script
        assert "|find" not in script

    def test_wait_uses_tasklist_exit_code(self):
        """修复点：waitloop 用 tasklist 退出码判断，不再依赖管道。"""
        script = update_bat.build_bat_script()
        assert 'tasklist /FI "PID eq %TARGET_PID%" >nul 2>&1' in script
        assert "if errorlevel 1 goto do_move" in script

    # ---------- 修复点 2：必填 env 防御 ----------
    def test_missing_env_checks_all_required(self):
        """修复点：DLC_OLD 也是必填（backup 目标），缺失会让 move 误报
        locked/permission。"""
        script = update_bat.build_bat_script()
        for var in ("DLC_PID", "DLC_EXE", "DLC_NEW",
                    "DLC_OLD", "DLC_LOG", "DLC_STATE"):
            assert f"if not defined {var} goto missing_env" in script

    def test_missing_env_exit_branch(self):
        """修复点：env 缺失时 LOG 可能未定义，不能 call :log，直接 exit 2。"""
        script = update_bat.build_bat_script()
        assert ":missing_env" in script
        assert "exit /b 2" in script
        # 确认 missing_env 分支里没有 call :log
        idx = script.index(":missing_env")
        tail = script[idx:]
        assert "call :log" not in tail.split(":log")[0]

    # ---------- 修复点 3：WAIT/PROBE 安全默认值 ----------
    def test_wait_probe_have_safe_defaults(self):
        """修复点：DLC_WAIT/DLC_PROBE 未定义或非正数时 `set /a` 会报
        "缺少操作数" 并让后续 `if ... GEQ ` 语法中断。"""
        script = update_bat.build_bat_script()
        assert 'if not defined DLC_WAIT set "DLC_WAIT=60"' in script
        assert 'if not defined DLC_PROBE set "DLC_PROBE=12"' in script
        assert 'if not defined WAIT_MAX set "WAIT_MAX=60"' in script
        assert 'if not defined PROBE_SEC set "PROBE_SEC=12"' in script
        assert 'if %WAIT_MAX% LEQ 0 set "WAIT_MAX=60"' in script
        assert 'if %PROBE_SEC% LEQ 0 set "PROBE_SEC=12"' in script

    # ---------- 修复点 4：等待心跳日志 ----------
    def test_heartbeat_present(self):
        """修复点：等待循环加心跳，避免日志停在两行被误判为卡死。"""
        script = update_bat.build_bat_script()
        assert 'if not defined DLC_HEARTBEAT set "DLC_HEARTBEAT=10"' in script
        assert "still waiting pid=%TARGET_PID%" in script

    def test_logs_startup_params(self):
        """诊断：启动时记录等待/探活参数，便于事后排查。"""
        script = update_bat.build_bat_script()
        assert "WAIT_MAX=%WAIT_MAX% PROBE=%PROBE_SEC%" in script

    # ---------- 修复点 5：start 指定工作目录 ----------
    def test_start_uses_workdir(self):
        """修复点：bat 自身在 %TEMP% 下运行，不指定 /D 会让新进程工作目录
        落在 Temp，破坏依赖相对路径的配置/资源。"""
        script = update_bat.build_bat_script()
        assert 'for %%F in ("%EXE%") do set "EXE_DIR=%%~dpF"' in script
        # 新版本启动 + 回滚启动，共 2 处
        assert script.count('start "" /D "%EXE_DIR%." "%EXE%"') == 2

    # ---------- 修复点 6：probe_writable 用 if exist ----------
    def test_probe_writable_uses_if_exist(self):
        """修复点：用 if exist 判断 wtest 是否创建成功，比 errorlevel 直观，
        也避免旧实现 `2>nul > "%EXE%.wtest" echo x` 的重定向顺序依赖。"""
        script = update_bat.build_bat_script()
        assert '>"%EXE%.wtest" echo x 2>nul' in script
        assert 'if exist "%EXE%.wtest" (' in script
        assert 'call :write_state "%~1_locked"' in script
        assert 'call :write_state "%~1_permission"' in script

    def test_old_redirect_order_removed(self):
        """旧的 `2>nul > ...` 重定向顺序已废弃。"""
        script = update_bat.build_bat_script()
        assert '2>nul > "%EXE%.wtest" echo x' not in script


# ===================== consume_state_file（补充：无副作用用例） =====================
class TestConsumeStateFile:
    """用户 test_update_manager.py 已覆盖基础 roundtrip；这里补充
    无状态副作用场景（避免 new_exe / log_path 触发真实清理）。"""

    def _patch_state_path(self, monkeypatch, path):
        monkeypatch.setattr(update_bat, "_state_file_path", lambda: str(path))

    def test_ignores_lines_without_eq(self, monkeypatch, tmp_path):
        p = tmp_path / "state.txt"
        p.write_text("garbage\nversion=3.0.1\nfoo bar\n", encoding="utf-8")
        self._patch_state_path(monkeypatch, p)
        result = update_bat.consume_state_file()
        assert result == {"version": "3.0.1"}

    def test_strips_quotes(self, monkeypatch, tmp_path):
        # new_exe 形状不匹配（/tmp/x.exe 不以 DLC_update_new_ 开头）
        # → 只记 warning，不删任何文件，无副作用
        p = tmp_path / "state.txt"
        p.write_text('new_exe="/tmp/x.exe"\n', encoding="utf-8")
        self._patch_state_path(monkeypatch, p)
        result = update_bat.consume_state_file()
        assert result["new_exe"] == "/tmp/x.exe"

    def test_no_state_still_cleans_old_logs(self, isolated_paths, tmp_tmpdir):
        """修复点：成功更新后 state 已被 bat 删除，仍需清理历史日志。

        isolated_paths 的 state 文件不存在 → 走「无 state」分支，只清理
        超过 max_age_sec 的旧日志，不误删当前更新正在写的日志。
        """
        old_log = tmp_tmpdir / "DLC_update_999.log"
        old_log.write_text("x", encoding="utf-8")
        t = time.time() - 3600 * 48
        os.utime(old_log, (t, t))

        assert update_bat.consume_state_file() is None
        assert not old_log.exists(), "超龄历史日志应被清理"

    def test_no_state_keeps_fresh_log(self, isolated_paths, tmp_tmpdir):
        """无 state 分支只删超龄日志：新写的日志必须保留。"""
        fresh_log = tmp_tmpdir / "DLC_update_100.log"
        fresh_log.write_text("x", encoding="utf-8")

        assert update_bat.consume_state_file() is None
        assert fresh_log.exists(), "未超龄日志不应删除（可能是当前更新在写）"

    def test_present_state_keeps_own_log(self, isolated_paths, tmp_tmpdir):
        """state 引用的日志必须保留供排查；失败遗留的 new_exe 应清理。"""
        log = tmp_tmpdir / "DLC_update_1.log"
        log.write_text("x", encoding="utf-8")
        new_exe = tmp_tmpdir / "DLC_update_new_1.exe"
        new_exe.write_text("x", encoding="utf-8")

        state = Path(update_bat._state_file_path())
        state.write_text(
            'version=9.9.9\n'
            'reason=install_failed\n'
            f'new_exe="{new_exe}"\n'
            'old_exe="x"\n'
            f'log_path="{log}"\n',
            encoding="utf-8",
        )

        result = update_bat.consume_state_file()

        assert result and result["reason"] == "install_failed"
        assert log.exists(), "state 引用的日志必须保留供排查"
        assert not new_exe.exists(), "失败遗留的 new_exe 应被清理"
        assert not state.exists(), "state 读取后应删除"


# ===================== _cleanup_leftover_new_exe =====================
class TestCleanupLeftoverNewExe:
    def test_ignores_empty(self):
        update_bat._cleanup_leftover_new_exe(None)
        update_bat._cleanup_leftover_new_exe("")

    def test_ignores_wrong_shape(self, tmp_tmpdir):
        bad = tmp_tmpdir / "other.exe"
        bad.write_text("x")
        update_bat._cleanup_leftover_new_exe(str(bad))
        assert bad.exists()

    def test_ignores_wrong_dir(self, tmp_tmpdir, tmp_path):
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        f = other_dir / "DLC_update_new_1.exe"
        f.write_text("x")
        update_bat._cleanup_leftover_new_exe(str(f))
        assert f.exists()

    def test_deletes_matching_exe_and_bat(self, tmp_tmpdir):
        exe = tmp_tmpdir / "DLC_update_new_42.exe"
        exe.write_text("x")
        bat = tmp_tmpdir / "DLC_update_apply_42.bat"
        bat.write_text("x")
        update_bat._cleanup_leftover_new_exe(str(exe))
        assert not exe.exists()
        assert not bat.exists()

    def test_does_not_delete_log(self, tmp_tmpdir):
        # 有意为之：state 引用的 log 用于展示诊断
        exe = tmp_tmpdir / "DLC_update_new_42.exe"
        exe.write_text("x")
        log = tmp_tmpdir / "DLC_update_42.log"
        log.write_text("x")
        update_bat._cleanup_leftover_new_exe(str(exe))
        assert log.exists()


# ===================== _cleanup_orphan_update_logs =====================
class TestCleanupOrphanUpdateLogs:
    def test_keeps_specified(self, tmp_tmpdir):
        keep = tmp_tmpdir / "DLC_update_1.log"
        keep.write_text("x")
        other = tmp_tmpdir / "DLC_update_2.log"
        other.write_text("y")
        update_bat._cleanup_orphan_update_logs(keep=str(keep))
        assert keep.exists()
        assert not other.exists()

    def test_ignores_non_matching(self, tmp_tmpdir):
        f = tmp_tmpdir / "unrelated.txt"
        f.write_text("x")
        update_bat._cleanup_orphan_update_logs(keep=None)
        assert f.exists()

    def test_keep_none_removes_all(self, tmp_tmpdir):
        a = tmp_tmpdir / "DLC_update_1.log"
        b = tmp_tmpdir / "DLC_update_2.log"
        a.write_text("x")
        b.write_text("y")
        update_bat._cleanup_orphan_update_logs(keep=None)
        assert not a.exists()
        assert not b.exists()

    def test_max_age_skips_fresh(self, tmp_tmpdir):
        """修复点：max_age_sec 非 None 时只删超龄日志，保留新写的。"""
        fresh = tmp_tmpdir / "DLC_update_fresh.log"
        stale = tmp_tmpdir / "DLC_update_stale.log"
        fresh.write_text("x")
        stale.write_text("y")
        t = time.time() - 3600 * 48
        os.utime(stale, (t, t))

        update_bat._cleanup_orphan_update_logs(keep=None, max_age_sec=86400)

        assert fresh.exists(), "未超龄的日志不应删除"
        assert not stale.exists(), "超龄日志应被清理"

    def test_max_age_none_keeps_behavior(self, tmp_tmpdir):
        """向后兼容：max_age_sec 省略（None）时保持原「删所有非 keep」行为。"""
        a = tmp_tmpdir / "DLC_update_1.log"
        a.write_text("x")
        update_bat._cleanup_orphan_update_logs(keep=None)
        assert not a.exists()