# coding: utf-8
# PyInstaller spec：单文件 + 无控制台 + 带图标
# 用法：pyinstaller build/app.spec

from pathlib import Path

# spec 里 __file__ 不可靠，用 SPECPATH（PyInstaller 注入）
ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # 把资源打进包内；get_resource_path 用 sys._MEIPASS 定位
        (str(ROOT / "assets"), "assets"),
        (str(ROOT / "theme.json"), "."),
    ],
    hiddenimports=[
        # cnlunar / chinese_calendar 是可选依赖，静态分析抓不全
        "cnlunar",
        "chinese_calendar",
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
    upx=False,           # UPX 会被部分杀软误报，关掉
    console=False,       # GUI 程序；sys.executable 即 exe 本体
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "app.ico"),
)