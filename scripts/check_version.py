# coding: utf-8
"""
CI 校验：
1. updater.py 的 CURRENT_VERSION 与 build/installer.iss 的 MyAppVersion 一致；
2. build/installer.iss 的 MyAppExeName 出现在 [Files] Source 的 exe 列表中；
3. build/build.py 的 EXE 文件名与 MyAppExeName 一致。

注意：CI 在跑本脚本前，必须已把 tag 版本号 patch 进
      updater.py 和 build/installer.iss（见 scripts/patch_updater.py）。

用法：
    python scripts/check_version.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def _grab(path: Path, pattern: str, label: str) -> str:
    m = re.search(pattern, _read(path))
    if not m:
        raise SystemExit(f"未在 {path.name} 中匹配到 {label}")
    return m.group(1)


def _iss_exe_names() -> tuple[str, list[str]]:
    """返回 (MyAppExeName, [Files] Source 中所有 .exe 文件名)。"""
    text = _read(ROOT / "build" / "installer.iss")

    m1 = re.search(r'#define\s+MyAppExeName\s+"([^"]+)"', text)
    if not m1:
        raise SystemExit("未在 installer.iss 中找到 #define MyAppExeName")

    # 放宽：只要 Source: "...\xxx.exe" 就抓，不限 ..\dist\ 前缀
    exes = re.findall(r'Source:\s*"[^"]*[\\/]([^"\\/]+\.exe)"', text)
    if not exes:
        raise SystemExit(
            "未在 installer.iss 的 [Files] 中找到任何 .exe 的 Source 行")

    return m1.group(1), exes


def _build_exe_name() -> str:
    """从 build/build.py 提取 EXE = DIST / "xxx.exe" 的文件名。"""
    return _grab(
        ROOT / "build" / "build.py",
        r'EXE\s*=\s*DIST\s*/\s*"([^"]+)"',
        'EXE = DIST / "..."',
    )


def main() -> int:
    # 1. 版本号一致
    py_ver = _grab(
        ROOT / "updater.py",
        r'CURRENT_VERSION\s*=\s*"([^"]+)"',
        "CURRENT_VERSION",
    )
    iss_ver = _grab(
        ROOT / "build" / "installer.iss",
        r'#define\s+MyAppVersion\s+"([^"]+)"',
        "MyAppVersion",
    )
    if py_ver != iss_ver:
        print(f"ERROR: 版本不一致 updater.py={py_ver} installer.iss={iss_ver}")
        return 1

    # 2. installer.iss 内部 exe 名一致
    app_exe, iss_exes = _iss_exe_names()
    if app_exe not in iss_exes:
        print(f"ERROR: MyAppExeName={app_exe} 未出现在 [Files] Source 的 "
              f"exe 列表中: {iss_exes}")
        return 1

    # 3. build.py 的 exe 名一致
    build_exe = _build_exe_name()
    if app_exe != build_exe:
        print(f"ERROR: exe 名不一致 "
              f"MyAppExeName={app_exe} build.py={build_exe}")
        return 1

    print(f"OK: 版本一致 {py_ver}，exe 名一致 {app_exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())