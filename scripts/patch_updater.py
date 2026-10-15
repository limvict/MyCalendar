# coding: utf-8
"""
CI helper: patch tag version into
  - updater.py  CURRENT_VERSION
  - build/installer.iss  #define MyAppVersion

Does NOT touch UPDATE_MANIFEST_URL -- it is fixed to
releases/latest/download/version.json, independent of version.

Usage:
    VER=3.0.2 python scripts/patch_updater.py
"""
from __future__ import annotations

import os
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
VER = os.environ.get("VER", "").strip()

if not VER:
    raise SystemExit("env VER not set, e.g. VER=3.0.2 python scripts/patch_updater.py")
if not re.fullmatch(r"\d+\.\d+\.\d+", VER):
    raise SystemExit(f"VER format invalid (expect X.Y.Z): {VER}")


def patch(path: pathlib.Path, pattern: str, repl: str, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"file not found: {path}")
    s = path.read_text(encoding="utf-8")
    s2, n = re.subn(pattern, repl, s, count=1)
    if n == 0:
        raise SystemExit(f"pattern not found in {path.name}: {label}")
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