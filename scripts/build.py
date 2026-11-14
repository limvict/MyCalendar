# coding: utf-8
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
RELEASE = ROOT / "release"

# _version 与 patch_updater 都在 scripts/ 下，且 patch_updater 用
# `from _version import ...`（支持 `python scripts/patch_updater.py`
# 直接运行）。这里必须用同一导入方式，否则 scripts/_version.py 会被
# 加载两次，产生两套 VersionPatchError 类，跨模块 except 捕获会漏。
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _version import (  # noqa: E402
    APP_EXE_NAME, VersionPatchError, installer_exe_name,
    validate_ver, write_version_info,
)
from patch_updater import patch_versions, write_manifest  # noqa: E402

EXE = RELEASE / APP_EXE_NAME
ISS = BUILD / "installer.iss"

# Inno Setup 6 默认安装路径；ISCC.exe 也常在 PATH 中。
_ISCC_CANDIDATES = tuple(
    p for p in (
        shutil.which("ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ) if p
)


def _find_iscc() -> str:
    for p in _ISCC_CANDIDATES:
        if os.path.isfile(p):
            return p
    raise SystemExit(
        "找不到 ISCC.exe，请安装 Inno Setup 6.3+ 并确保它在 PATH 或 "
        "默认安装路径下。下载：https://jrsoftware.org/isdl.php")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("用法：python scripts/build.py <version>，如 3.0.4")
    try:
        version = validate_ver(sys.argv[1])
    except VersionPatchError as e:
        raise SystemExit(str(e))

    print(f"[1/6] 同步版本号：{version}")
    patch_versions(version)

    print("[2/6] 生成 exe 版本资源…")
    # 与 patch_updater.main 对齐：write_version_info 会抛
    # VersionPatchError / OSError，未捕获时 traceback 会淹没
    # "下一步"提示，用户难以定位是版本格式错还是 build/ 不可写。
    try:
        write_version_info(ROOT, version)
    except (VersionPatchError, OSError) as e:
        raise SystemExit(str(e))

    print("[3/6] PyInstaller 打包中…")
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
             "--distpath", str(RELEASE),
             str(BUILD / "app.spec")],
            cwd=ROOT, check=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            f"PyInstaller 失败（exit={e.returncode}）。常见原因："
            f"app.spec 路径错误、依赖缺失、杀毒软件拦截；"
            f"详见上方 PyInstaller 输出。")

    if not EXE.exists():
        raise SystemExit(f"未生成 exe：{EXE}")

    print("[4/6] Inno Setup 编译安装包…")
    if not ISS.exists():
        raise SystemExit(f"未找到 Inno Setup 脚本：{ISS}")
    iscc = _find_iscc()
    try:
        # cwd 必须是 iss 所在目录：iss 内用相对路径
        # ..\release\ / ..\assets\ / .\ChineseSimplified.isl。
        subprocess.run([iscc, str(ISS)], cwd=ISS.parent, check=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            f"Inno Setup 编译失败（exit={e.returncode}）。常见原因："
            f"installer.iss 路径错误、[Files] 源文件缺失、"
            f"中文 MessagesFile 路径错误；详见上方输出。")

    installer_name = installer_exe_name(version)
    installer = RELEASE / installer_name
    if not installer.exists():
        raise SystemExit(
            f"未生成安装包：{installer}（检查 installer.iss 的 "
            f"OutputDir / OutputBaseFilename）")

    print("[5/6] 生成 version.json…")
    write_manifest(version)

    print("[6/6] 一致性检查…")
    check_rc = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_version.py"),
         "--manifest-required", "--verify-sha256"],
        cwd=ROOT).returncode
    if check_rc != 0:
        raise SystemExit(
            f"一致性检查失败（exit={check_rc}），"
            f"请修复 release/version.json 或版本源后重试")

    print("\n下一步：")
    print(f"  1. 上传 release/{installer_name} 到 GitHub Release v{version}")
    print("  2. 把 release/version.json 也上传到同一个 Release（作为资产）")
    print("     注意：不要提交 version.json 到 main 分支——")
    print("     update_manager.py 拉的是 releases/latest/download/version.json，")
    print("     GitHub 会自动指向最新非预发布 Release 的资产。")
    print(f"     注意：release/{APP_EXE_NAME} 不上传，它只是安装包的输入。")


if __name__ == "__main__":
    main()