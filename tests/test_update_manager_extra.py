# coding: utf-8
"""update_manager 补充：残留清理、可重试错误判定。"""
import http.client
import os
import socket
import tempfile
from pathlib import Path

from desktop_calendar.infrastructure.network import update_manager as um


def test_cleanup_leftover_rejects_bad_path(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("x", encoding="utf-8")
    um._cleanup_leftover_new_exe(str(victim))
    assert victim.exists()      # 非 %TEMP%/DLC_update_new_*.exe，拒绝删


def test_cleanup_leftover_removes_tmp_files():
    tmp = tempfile.gettempdir()
    pid = 999999
    new_exe = os.path.join(tmp, f"DLC_update_new_{pid}.exe")
    bat = os.path.join(tmp, f"DLC_update_apply_{pid}.bat")
    Path(new_exe).write_bytes(b"x")
    Path(bat).write_bytes(b"x")
    try:
        um._cleanup_leftover_new_exe(new_exe)
        assert not os.path.exists(new_exe)
        assert not os.path.exists(bat)
    finally:
        for p in (new_exe, bat):
            try:
                os.remove(p)
            except OSError:
                pass


def test_is_retryable_network_error():
    assert um._is_retryable_network_error(ConnectionResetError("x"))
    assert um._is_retryable_network_error(ConnectionAbortedError("x"))
    assert um._is_retryable_network_error(socket.timeout())
    assert um._is_retryable_network_error(
        http.client.IncompleteRead(b"x", 10))
    assert not um._is_retryable_network_error(ValueError("x"))


def test_parse_version_negative_and_empty_segment():
    assert um._parse_version("1.-2.3") == (1, -2, 3)
    assert um._parse_version("1..3") == (1, 0, 3)