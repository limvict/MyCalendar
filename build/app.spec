# coding: utf-8
# PyInstaller spec：单文件 + 无控制台 + 带图标
# 用法：pyinstaller build/app.spec --distpath release
#
# 输出路径契约：
#   - 本 spec 不写死输出目录，由 CLI 的 --distpath 决定；
#     build/build.py 与 .github/workflows/release.yml 均传 --distpath release。
#   - 单文件模式 EXE 直接落在 <distpath>/DesktopCalendar.exe，无 COLLECT 阶段。

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent          # 项目根
SRC  = ROOT / "src"
PKG  = SRC / "desktop_calendar"

# collect_submodules 在 Analysis(...) 参数求值时立即执行，
# 依赖当前 sys.path；必须先把 src/ 加进去，否则 pip install -e .
# 未装的环境（CI）会扫不到 desktop_calendar 子模块。
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(SRC)],
    binaries=[],
    datas=[
        (str(ROOT / "assets"), "assets"),
    ],
    hiddenimports=[
        "cnlunar",
        "chinese_calendar",
        # 排除 tests 子包：避免把测试文件及其可选依赖拖进产物
        *collect_submodules(
            "desktop_calendar",
            filter=lambda name: ".tests" not in name,
        ),
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 标准库 / 第三方：本项目不用
        "tkinter", "matplotlib", "numpy", "pandas",
        # PyQt6 可选组件：体积大且未使用
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebChannel",
        "PyQt6.QtQml",
        "PyQt6.QtQuick",
        "PyQt6.QtQuickWidgets",
        "PyQt6.QtBluetooth",
        "PyQt6.QtMultimedia",
        "PyQt6.QtMultimediaWidgets",
        "PyQt6.QtPdf",
        "PyQt6.QtPdfWidgets",
        "PyQt6.Qt3DCore",
        "PyQt6.Qt3DRender",
        "PyQt6.Qt3DInput",
        "PyQt6.Qt3DLogic",
        "PyQt6.Qt3DAnimation",
        "PyQt6.Qt3DExtras",
        "PyQt6.QtCharts",
        "PyQt6.QtDataVisualization",
        "PyQt6.QtDesigner",
        "PyQt6.QtHelp",
        "PyQt6.QtOpenGL",
        "PyQt6.QtOpenGLWidgets",
        "PyQt6.QtSql",
        "PyQt6.QtTest",
        "PyQt6.QtXml",
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
    # exe 文件属性版本；与 installer.iss 的 AppVersion 保持一致。
    # 需先由 build/build.py 生成 build/version_info.txt（见下方说明）；
    # 若暂不生成该文件，删掉本行即可，不影响打包。
    version=str(ROOT / "build" / "version_info.txt"),
)