# coding: utf-8
"""
CI helper: 版本注入与发布清单生成。

子命令（默认 = patch 版本源）:
  (默认)      把 VER 写入版本源：
                - pyproject.toml              [project].version
                - updater.py                  CURRENT_VERSION
                - build/installer.iss         #define MyAppVersion
  --manifest  在 build 产物就绪后生成 release/version.json
              （需要 dist/DesktopCalendar.exe 存在以计算 sha256）

Does NOT touch UPDATE_MANIFEST_URL -- it is fixed to
releases/latest/download/version.json, independent of version.

Usage:
    VER=3.0.2 python scripts/patch_updater.py
    VER=3.0.2 python scripts/patch_updater.py --manifest
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
VER = os.environ.get("VER", "").strip()

MANIFEST_NAME = "version.json"                          
EXE_REL = pathlib.Path("dist") / "DesktopCalendar.exe"


def _die(msg: str) -> None:
    print(f"[patch_updater] {msg}", file=sys.stderr)
    raise SystemExit(1)


def _require_ver() -> str:
    if not VER:
        _die("env VER not set, e.g. VER=3.0.2 python scripts/patch_updater.py")
    if not re.fullmatch(r"\d+\.\d+\.\d+", VER):
        _die(f"VER format invalid (expect X.Y.Z): {VER}")
    return VER


def patch(path: pathlib.Path, pattern: str, repl: str, label: str) -> None:
    if not path.exists():
        _die(f"file not found: {path}")
    s = path.read_text(encoding="utf-8")
    s2, n = re.subn(pattern, repl, s, count=1)
    if n == 0:
        _die(f"pattern not found in {path.name}: {label}")
    if s2 != s:
        path.write_text(s2, encoding="utf-8")
        print(f"Patched {label} in {path.name} -> {VER}")
    else:
        print(f"Unchanged {label} in {path.name} (already {VER})")


def patch_toml_project_version(path: pathlib.Path, ver: str) -> None:
    """只改 [project] 段内的 version 行，避免误伤其它 section。

    TOML 里 [project] 内可能有列表值（如 authors = [ ... ]），
    所以不能用"匹配到下一个 [ 为止"的正则，逐行扫描最稳。
    """
    if not path.exists():
        _die(f"file not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_project = False
    target = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = (stripped == "[project]")
            continue
        if in_project and re.match(r"^version\s*=", stripped):
            target = i
            break
    if target < 0:
        _die(f"[project].version not found in {path.name}")
    old = lines[target]
    new = re.sub(r'"[^"]*"', f'"{ver}"', old, count=1)
    if new != old:
        lines[target] = new
        path.write_text("".join(lines), encoding="utf-8")
        print(f"Patched [project].version in {path.name} -> {ver}")
    else:
        print(f"Unchanged [project].version in {path.name} (already {ver})")


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def write_manifest(ver: str) -> None:
    """生成 dist/version.json，字段名与 services/updater.py 消费方一致。

    字段：version / download_url / sha256 / release_notes
    —— 与旧 CI heredoc 完全同构，避免更新器解析 KeyError。
    """
    exe = ROOT / EXE_REL                      # dist/DesktopCalendar.exe
    if not exe.exists():
        _die(f"exe not found: {exe} (run build first)")
    data = exe.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip() or "<org>/<repo>"
    # tag 带 v 前缀：releases/download/v3.0.4/...
    download_url = (
        f"https://github.com/{repo}/releases/download/v{ver}/DesktopCalendar.exe"
    )

    manifest = {
        "version": ver,
        "download_url": download_url,
        "sha256": sha256,
        "release_notes": os.environ.get("RELEASE_NOTES", "See release page.").strip()
                         or "See release page.",
    }
    out = ROOT / "dist" / MANIFEST_NAME       # MANIFEST_NAME = "version.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {out.relative_to(ROOT)} "
          f"(version={ver}, sha256={sha256[:12]}...)")


def main(argv: list[str]) -> int:
    ver = _require_ver()

    if "--manifest" in argv:
        write_manifest(ver)
        return 0

    patch(
        ROOT / "src" / "desktop_calendar" / "infrastructure" / "network" / "updater.py",
        r'CURRENT_VERSION\s*=\s*"[^"]*"',
        f'CURRENT_VERSION = "{ver}"',
        "CURRENT_VERSION",
    )
    patch(
        ROOT / "build" / "installer.iss",
        r'#define\s+MyAppVersion\s+"[^"]*"',
        f'#define MyAppVersion "{ver}"',
        "MyAppVersion",
    )
    patch_toml_project_version(ROOT / "pyproject.toml", ver)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))