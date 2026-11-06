# coding: utf-8
"""update_bat：bat 脚本生成、遗留清理、孤儿 log 清理。

consume_state_file 的基础 roundtrip 由 test_update_manager.py 覆盖；
本文件聚焦 update_manager 未覆盖的 build_bat_script / 清理函数细节。
"""
import pytest

from desktop_calendar.infrastructure.network import update_bat


# ===================== build_bat_script =====================
class TestBuildBatScript:
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
            ":write_state", ":cleanup", ":log",
        ):
            assert token in script, f"missing {token}"

    def test_state_written_with_echo(self):
        script = update_bat.build_bat_script()
        assert "echo version=%VER%" in script
        assert "echo reason=%~1" in script
        assert 'echo new_exe="%NEW%"' in script
        assert 'echo log_path="%LOG%"' in script


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
