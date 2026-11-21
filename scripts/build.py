# coding: utf-8
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
RELEASE = ROOT / "release"

# 与 patch_updater 用同一导入方式（`from _version import ...`），
# 避免 scripts/_version.py 被加载两次产生两套 VersionPatchError。
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _version import (  # noqa: E402
    APP_EXE_NAME,
    VersionPatchError,
    installer_exe_name,
    validate_ver,
    write_version_info,
)
from patch_updater import patch_versions, write_manifest  # noqa: E402

EXE = RELEASE / APP_EXE_NAME
ISS = BUILD / "installer.iss"


def _find_iscc() -> str:
    """每次调用动态探测，兼容用户在当前 shell 中临时加入 PATH。"""
    candidates = (
        shutil.which("ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    )
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    raise SystemExit(
        "找不到 ISCC.exe，请安装 Inno Setup 6.3+ 并确保它在 PATH 或 "
        "默认安装路径下。下载：https://jrsoftware.org/isdl.php"
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("用法：python scripts/build.py <version>，如 3.0.4")
    try:
        version = validate_ver(sys.argv[1])
    except VersionPatchError as e:
        raise SystemExit(str(e)) from None

    print(f"[1/6] 同步版本号：{version}")
    patch_versions(version)

    print("[2/6] 生成 exe 版本资源…")
    try:
        write_version_info(ROOT, version)
    except (VersionPatchError, OSError) as e:
        raise SystemExit(str(e)) from None

    print("[3/6] PyInstaller 打包中…")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--clean",
                "--noconfirm",
                "--distpath",
                str(RELEASE),
                str(BUILD / "app.spec"),
            ],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            f"PyInstaller 失败（exit={e.returncode}）。常见原因："
            f"app.spec 路径错误、依赖缺失、杀毒软件拦截；"
            f"详见上方 PyInstaller 输出。"
        ) from None

    if not EXE.exists():
        raise SystemExit(f"未生成 exe：{EXE}")

    print("[4/6] Inno Setup 编译安装包…")
    if not ISS.exists():
        raise SystemExit(f"未找到 Inno Setup 脚本：{ISS}")
    iscc = _find_iscc()
    try:
        # cwd 必须是 iss 所在目录：iss 内用相对路径。
        subprocess.run([iscc, str(ISS)], cwd=ISS.parent, check=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            f"Inno Setup 编译失败（exit={e.returncode}）。常见原因："
            f"installer.iss 路径错误、[Files] 源文件缺失、"
            f"中文 MessagesFile 路径错误；详见上方输出。"
        ) from None

    installer_name = installer_exe_name(version)
    installer = RELEASE / installer_name
    if not installer.exists():
        raise SystemExit(
            f"未生成安装包：{installer}（检查 installer.iss 的 OutputDir / OutputBaseFilename）"
        )

    print("[5/6] 生成 version.json…")
    write_manifest(version)

    print("[6/6] 一致性检查…")
    # 显式传 VER=version：check_version 会额外断言每个版本源都等于它，
    # 避免继承外部 shell 中可能残留的旧 VER。
    env = os.environ.copy()
    env["VER"] = version
    check_rc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_version.py"),
            "--manifest-required",
            "--verify-sha256",
        ],
        cwd=ROOT,
        env=env,
    ).returncode
    if check_rc != 0:
        raise SystemExit(
            f"一致性检查失败（exit={check_rc}），请修复 release/version.json 或版本源后重试"
        )

    print("\n下一步：")
    print(f"  1. 上传 release/{installer_name} 到 GitHub Release v{version}")
    print("  2. 把 release/version.json 也上传到同一个 Release（作为资产）")
    print("     不要提交 version.json 到 main 分支。")
    print(f"     注意：release/{APP_EXE_NAME} 不上传，它只是安装包的输入。")


if __name__ == "__main__":
    main()
