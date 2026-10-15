# coding: utf-8
"""
一键构建：PyInstaller 打包 → 计算 sha256 → 生成 version.json。
用法：python build/build.py 3.0.1

注意：本脚本不自动上传 GitHub Release，上传由 CI 或手工完成。
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
RELEASE = ROOT / "release"
EXE = DIST / "DesktopCalendar.exe"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _sync_version(new_version: str):
    """把新版本号同步进 updater.py 和 installer.iss，避免手工漂移。"""
    # --- updater.py ---
    updater_py = ROOT / "updater.py"
    src = updater_py.read_text(encoding="utf-8")
    new_src, n = re.subn(
        r'(CURRENT_VERSION\s*=\s*)"[^"]+"',
        rf'\g<1>"{new_version}"',
        src, count=1)
    if n == 0:
        raise SystemExit(f"未在 {updater_py} 找到 CURRENT_VERSION")
    if new_src != src:
        updater_py.write_text(new_src, encoding="utf-8")

    # --- installer.iss ---
    iss = BUILD / "installer.iss"
    src = iss.read_text(encoding="utf-8")
    new_src, n = re.subn(
        r'(#define\s+MyAppVersion\s+)"[^"]+"',
        rf'\g<1>"{new_version}"',
        src, count=1)
    if n == 0:
        raise SystemExit(f"未在 {iss} 找到 MyAppVersion")
    if new_src != src:
        iss.write_text(new_src, encoding="utf-8")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("用法：python build/build.py <version>，如 3.0.1")
    version = sys.argv[1].strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"版本号格式错误：{version}")

    _sync_version(version)
    print(f"[1/4] 版本号已同步到 updater.py 和 installer.iss：{version}")

    print("[2/4] PyInstaller 打包中…")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
         str(BUILD / "app.spec")],
        cwd=ROOT, check=True)

    if not EXE.exists():
        raise SystemExit(f"未生成 exe：{EXE}")

    print(f"[3/4] 计算 sha256…")
    sha = _sha256(EXE)
    print(f"      {sha}")

    RELEASE.mkdir(exist_ok=True)
    target_exe = RELEASE / EXE.name
    target_exe.write_bytes(EXE.read_bytes())

    manifest = {
        "version": version,
        "release_notes": "",
        "download_url": (
            f"https://github.com/limvict/MyCalendar/releases/download/"
            f"v{version}/{EXE.name}"),
        "sha256": sha,
    }
    (RELEASE / "version.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"[4/4] 输出：{RELEASE}")

    print("\n下一步：")
    print("  1. iscc build/installer.iss   （编译安装包）")
    print(f"  2. 上传 release/*.exe 到 GitHub Release v{version}")
    print( "  3. 把 release/version.json 也上传到同一个 Release（作为资产）")
    print( "     注意：不要提交 version.json 到 main 分支——")
    print( "     updater.py 拉的是 releases/latest/download/version.json，")
    print( "     GitHub 会自动指向最新非预发布 Release 的资产。")


if __name__ == "__main__":
    main()