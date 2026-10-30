import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
RELEASE = ROOT / "release"
EXE = RELEASE / "DesktopCalendar.exe"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._version import (  # noqa: E402
    VersionPatchError, validate_ver, write_version_info,
)
from scripts.patch_updater import patch_versions, write_manifest  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("用法：python build/build.py <version>，如 3.0.1")
    try:
        version = validate_ver(sys.argv[1])
    except VersionPatchError as e:
        raise SystemExit(str(e))

    print(f"[1/4] 同步版本号：{version}")
    patch_versions(version)

    print("[2/4] 生成 exe 版本资源…")
    write_version_info(ROOT, version)

    print("[3/4] PyInstaller 打包中…")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
         "--distpath", str(RELEASE),
         str(BUILD / "app.spec")],
        cwd=ROOT, check=True)

    if not EXE.exists():
        raise SystemExit(f"未生成 exe：{EXE}")

    print("[4/4] 生成 version.json…")
    write_manifest(version)

    print("\n下一步：")
    print("  1. iscc build/installer.iss   （编译安装包，输出到 release/）")
    print(f"  2. 上传 release/DesktopCalendar.exe 到 GitHub Release v{version}")
    print("  3. 把 release/version.json 也上传到同一个 Release（作为资产）")
    print("     注意：不要提交 version.json 到 main 分支——")
    print("     update_manager.py 拉的是 releases/latest/download/version.json，")
    print("     GitHub 会自动指向最新非预发布 Release 的资产。")


if __name__ == "__main__":
    main()