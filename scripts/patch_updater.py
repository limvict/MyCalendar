# coding: utf-8
"""
CI 专用：把 tag 版本号写进
  - updater.py 的 CURRENT_VERSION
  - build/installer.iss 的 #define MyAppVersion

不改 UPDATE_MANIFEST_URL —— 该值已固定指向
releases/latest/download/version.json，与具体版本无关。

用法：
    VER=3.0.2 python scripts/patch_updater.py
"""
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
VER = os.environ.get("VER", "").strip()

if not VER:
    raise SystemExit("环境变量 VER 未设置，例如 VER=3.0.2 python scripts/patch_updater.py")
if not re.fullmatch(r"\d+\.\d+\.\d+", VER):
    raise SystemExit(f"VER 格式错误（应为 X.Y.Z）：{VER}")


def patch(path: pathlib.Path, pattern: str, repl: str, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"文件不存在: {path}")
    s = path.read_text(encoding="utf-8")
    s2, n = re.subn(pattern, repl, s, count=1)
    if n == 0:
        raise SystemExit(f"未在 {path.name} 中匹配到 {label}")
    if s2 != s:
        path.write_text(s2, encoding="utf-8")
        print(f"Patched {label} in {path.name} -> {VER}")
    else:
        print(f"Unchanged {label} in {path.name} (already {VER})")


patch(
    ROOT / "updater.py",
    r'CURRENT_VERSION\s*=\s*"[^"]*"',
    f'CURRENT_VERSION = "{VER}"',
    "CURRENT_VERSION",
)
patch(
    ROOT / "build" / "installer.iss",
    r'#define\s+MyAppVersion\s+"[^"]*"',
    f'#define MyAppVersion "{VER}"',
    "MyAppVersion",
)