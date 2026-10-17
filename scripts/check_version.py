# coding: utf-8
"""
版本一致性检查。

默认断言以下来源版本一致（存在即检查）：
  - pyproject.toml                          [project].version
  - src/desktop_calendar/services/updater.py  CURRENT_VERSION
  - build/installer.iss                       #define MyAppVersion
  - src/desktop_calendar/__init__.py          __version__（若硬编码）
  - release/version.json                      "version"（默认跳过，见 --manifest-required）

可选参数：
  VER 环境变量          若设置，额外断言所有来源都等于 VER（CI 打 tag 时用）
  --manifest-required   release/version.json 必须存在（CI 发布前用）

Usage:
    python scripts/check_version.py
    VER=3.0.2 python scripts/check_version.py --manifest-required
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXPECTED = os.environ.get("VER", "").strip()

sources: list[tuple[str, str]] = []
errors: list[str] = []


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def collect_pyproject() -> None:
    path = ROOT / "pyproject.toml"
    if not path.exists():
        errors.append(f"missing: {path.relative_to(ROOT)}")
        return
    in_project = False
    for line in _read(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = (stripped == "[project]")
            continue
        if in_project:
            m = re.match(r'^version\s*=\s*"([^"]+)"', stripped)
            if m:
                sources.append(("pyproject.toml [project].version", m.group(1)))
                return
    errors.append("pyproject.toml: [project].version not found")


def collect_updater() -> None:
    path = ROOT / "src" / "desktop_calendar" / "services" / "updater.py"
    if not path.exists():
        errors.append(f"missing: {path.relative_to(ROOT)}")
        return
    m = re.search(r'CURRENT_VERSION\s*=\s*"([^"]+)"', _read(path))
    if not m:
        errors.append("updater.py: CURRENT_VERSION not found")
        return
    sources.append(("updater.py CURRENT_VERSION", m.group(1)))


def collect_installer() -> None:
    path = ROOT / "build" / "installer.iss"
    if not path.exists():
        errors.append(f"missing: {path.relative_to(ROOT)}")
        return
    m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', _read(path))
    if not m:
        errors.append("installer.iss: #define MyAppVersion not found")
        return
    sources.append(("installer.iss MyAppVersion", m.group(1)))


def collect_init() -> None:
    path = ROOT / "src" / "desktop_calendar" / "__init__.py"
    if not path.exists():
        return  # 可选来源
    m = re.search(r"""__version__\s*=\s*['"]([^'"]+)['"]""", _read(path))
    if m:
        sources.append(("__init__.py __version__", m.group(1)))
    # 未匹配视为使用 importlib.metadata，不算错误


def collect_manifest(required: bool) -> None:
    # CI 产物在 dist/，本地归档可能在 release/；取第一个存在的
    candidates = [
        ROOT / "dist" / "version.json",
        ROOT / "release" / "version.json",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        if required:
            tried = ", ".join(str(p.relative_to(ROOT)) for p in candidates)
            errors.append(f"version.json not found (tried: {tried})")
        return
    try:
        data = json.loads(_read(path))
    except Exception as e:
        errors.append(f"{path.relative_to(ROOT)}: invalid JSON: {e}")
        return
    if not isinstance(data, dict):
        errors.append(f"{path.relative_to(ROOT)}: root is not an object")
        return
    v = data.get("version")
    if not isinstance(v, str) or not v:
        errors.append(f"{path.relative_to(ROOT)}: missing string field 'version'")
        return
    sources.append((f"{path.relative_to(ROOT)} version", v))


def main(argv: list[str]) -> int:
    if EXPECTED and not re.fullmatch(r"\d+\.\d+\.\d+", EXPECTED):
        errors.append(f"env VER format invalid (expect X.Y.Z): {EXPECTED}")
    manifest_required = "--manifest-required" in argv

    collect_pyproject()
    collect_updater()
    collect_installer()
    collect_init()
    collect_manifest(manifest_required)

    print("Version sources:")
    width = max((len(name) for name, _ in sources), default=0)
    for name, ver in sources:
        print(f"  {name.ljust(width)}  {ver}")

    if not sources:
        errors.append("no version source found")

    versions = {ver for _, ver in sources}
    if len(versions) > 1:
        errors.append(f"version mismatch across sources: {sorted(versions)}")

    if EXPECTED:
        for name, ver in sources:
            if ver != EXPECTED:
                errors.append(f"{name}: expected {EXPECTED}, got {ver}")

    if errors:
        print("\nFAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"\nOK: all sources agree on {next(iter(versions))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))