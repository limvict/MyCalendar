# coding: utf-8
"""auto_start._build_cmd 单元测试。

不触碰注册表；只验证"打包 / 源码 / python -m"三种形态的命令拼装。
"""
import sys

import pytest

from app import auto_start


@pytest.fixture
def clean_meipass(monkeypatch):
    """显式保证 _MEIPASS 未设置（防 PyInstaller 运行环境里误命中）。"""
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)


class TestBuildCmd:
    def test_frozen_exe(self, monkeypatch):
        """打包环境：只有 exe，无脚本参数。"""
        monkeypatch.setattr(sys, "_MEIPASS", "/tmp/_MEI123", raising=False)
        monkeypatch.setattr(sys, "executable", "/opt/app/DesktopCalendar.exe")
        monkeypatch.setattr(sys, "argv", ["/opt/app/DesktopCalendar.exe"])
        assert auto_start._build_cmd() == '"/opt/app/DesktopCalendar.exe"'

    def test_source_py_script(self, monkeypatch, tmp_path, clean_meipass):
        """源码环境：python + script.py。"""
        monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
        script = str(tmp_path / "main.py")
        monkeypatch.setattr(sys, "argv", [script])
        assert auto_start._build_cmd() == f'"/usr/bin/python3" "{script}"'

    def test_relative_script_is_absolutized(
            self, monkeypatch, tmp_path, clean_meipass):
        monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
        monkeypatch.setattr(sys, "argv", ["main.py"])
        monkeypatch.chdir(tmp_path)
        cmd = auto_start._build_cmd()
        assert cmd == f'"/usr/bin/python3" "{tmp_path / "main.py"}"'
        assert str(tmp_path) in cmd

    def test_python_m_fallback(self, monkeypatch, clean_meipass):
        """python -m 形式：argv[0] 不以 .py 结尾 → 只记录 python。"""
        monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
        monkeypatch.setattr(sys, "argv", ["-m", "some.module"])
        assert auto_start._build_cmd() == '"/usr/bin/python3"'

    def test_frozen_takes_priority_over_py(self, monkeypatch):
        """即使 argv[0] 是 .py，只要 _MEIPASS 在，就优先 exe。"""
        monkeypatch.setattr(sys, "_MEIPASS", "/tmp/x", raising=False)
        monkeypatch.setattr(sys, "executable", "/opt/app.exe")
        monkeypatch.setattr(sys, "argv", ["/opt/app.py"])
        assert auto_start._build_cmd() == '"/opt/app.exe"'

    def test_script_is_quoted(self, monkeypatch, clean_meipass):
        """路径含空格时必须被双引号包住（否则 Run 键会被截断）。"""
        monkeypatch.setattr(
            sys, "executable", r"C:\Program Files\Py\python.exe")
        monkeypatch.setattr(
            sys, "argv", [r"C:\Users\me\my app\main.py"])
        cmd = auto_start._build_cmd()
        assert cmd.count('"') == 4
        assert cmd.startswith('"C:\\Program Files\\Py\\python.exe"')