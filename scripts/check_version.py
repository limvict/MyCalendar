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

# Windows 控制台默认 cp1252/cp437，中文 print 会 UnicodeEncodeError。
# 强制 stdout/stderr 走 UTF-8，errors=replace 兜底。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"file not found: {path}")
    return path.read_text(encoding="utf-8")


def _grab(path: Path, pattern: str, label: str) -> str:
    m = re.search(pattern, _read(path))
    if not m:
        raise SystemExit(f"pattern not found in {path.name}: {label}")
    return m.group(1)


def _iss_exe_names() -> tuple[str, list[str]]:
    """返回 (MyAppExeName, [Files] Source 中所有 .exe 文件名)。"""
    text = _read(ROOT / "build" / "installer.iss")

    m1 = re.search(r'#define\s+MyAppExeName\s+"([^"]+)"', text)
    if not m1:
        raise SystemExit("MyAppExeName not found in build/installer.iss")

    exes = re.findall(r'Source:\s*"[^"]*[\\/]([^"\\/]+\.exe)"', text)
    if not exes:
        raise SystemExit(
            "no .exe Source line found in build/installer.iss [Files]")

    return m1.group(1), exes


def _build_exe_name() -> str:
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
        print(f"ERROR: version mismatch: updater.py={py_ver} installer.iss={iss_ver}")
        return 1

    # 2. installer.iss 内部 exe 名一致
    app_exe, iss_exes = _iss_exe_names()
    if app_exe not in iss_exes:
        print(f"ERROR: MyAppExeName={app_exe} not in [Files] Source exes: {iss_exes}")
        return 1

    # 3. build.py 的 exe 名一致
    build_exe = _build_exe_name()
    if app_exe != build_exe:
        print(f"ERROR: exe name mismatch: MyAppExeName={app_exe} build.py={build_exe}")
        return 1

    print(f"OK: version={py_ver}, exe={app_exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())