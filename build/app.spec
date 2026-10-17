# coding: utf-8
# PyInstaller spec：单文件 + 无控制台 + 带图标
# 用法：pyinstaller build/app.spec

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
SRC  = ROOT / "src"
PKG  = SRC / "desktop_calendar"

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(SRC)],
    binaries=[],
    datas=[
        (str(ROOT / "assets"), "assets"),
        (str(PKG / "config" / "theme.json"), "."),
    ],
    hiddenimports=[
        "cnlunar",
        "chinese_calendar",
        *collect_submodules("desktop_calendar"),
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas",
        "PyQt6.QtWebEngineWidgets", "PyQt6.QtBluetooth",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DesktopCalendar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "app.ico"),
)