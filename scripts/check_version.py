# file: check_version.py
# coding: utf-8
"""版本一致性检查。

检查 pyproject.toml / CURRENT_VERSION / installer.iss / __init__.py / version.json
版本一致；校验 MyAppPublisher 同步、manifest URL 合法、sha256 与实际安装包匹配。

参数：
  VER 环境变量          额外断言所有来源等于 VER
  --manifest-required   version.json 必须存在
  --verify-sha256       断言 manifest.sha256 与安装包实际哈希一致
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _version import (  # noqa: E402
    APP_PUBLISHER,
    CURRENT_VERSION_RE,
    INSTALLER_ISS_REL,
    INSTALLER_VERSION_RE,
    MANIFEST_NAME,
    PYPROJECT_REL,
    PYPROJECT_VERSION_LINE_RE,
    RELEASE_DIR_REL,
    UPDATER_PY_REL,
    VersionPatchError,
    installer_exe_name,
    is_safe_https_url,
    reconfigure_stdio,
    sha256_of_file,
    validate_ver,
)

reconfigure_stdio()

ROOT = pathlib.Path(__file__).resolve().parent.parent

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INIT_VERSION_RE = re.compile(r"""__version__\s*=\s*['"]([^'"]+)['"]""")
_PUBLISHER_RE = re.compile(
    r"""#define\s+MyAppPublisher\s+(?P<q>["'])(?P<val>[^"']+)(?P=q)""")

_MANIFEST_REL = pathlib.Path(RELEASE_DIR_REL) / MANIFEST_NAME


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def collect_pyproject(
    sources: list[tuple[str, str]], errors: list[str],
) -> None:
    path = ROOT / PYPROJECT_REL
    if not path.exists():
        errors.append(f"missing: {path.relative_to(ROOT).as_posix()}")
        return
    in_project = False
    for line in _read(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = (stripped == "[project]")
            continue
        if not in_project:
            continue
        m = PYPROJECT_VERSION_LINE_RE.match(line)
        if m:
            sources.append(
                ("pyproject.toml [project].version", m.group("val")))
            return
    errors.append("pyproject.toml: [project].version not found")


def collect_updater(
    sources: list[tuple[str, str]], errors: list[str],
) -> None:
    path = ROOT / UPDATER_PY_REL
    if not path.exists():
        errors.append(f"missing: {path.relative_to(ROOT).as_posix()}")
        return
    m = CURRENT_VERSION_RE.search(_read(path))
    if not m:
        errors.append(f"{UPDATER_PY_REL}: CURRENT_VERSION not found")
        return
    sources.append((f"{UPDATER_PY_REL} CURRENT_VERSION", m.group("val")))


def collect_installer(
    sources: list[tuple[str, str]], errors: list[str],
) -> None:
    path = ROOT / INSTALLER_ISS_REL
    if not path.exists():
        errors.append(f"missing: {path.relative_to(ROOT).as_posix()}")
        return
    m = INSTALLER_VERSION_RE.search(_read(path))
    if not m:
        errors.append("installer.iss: #define MyAppVersion not found")
        return
    sources.append(("installer.iss MyAppVersion", m.group("val")))


def collect_init(
    sources: list[tuple[str, str]], errors: list[str],
) -> None:
    path = ROOT / "src" / "desktop_calendar" / "__init__.py"
    if not path.exists():
        return  # 可选来源
    text = _read(path)
    # 动态版本：版本真源是 pyproject.toml，fallback 里的 "0.0.0" 不算版本源。
    if "importlib.metadata" in text or "importlib_metadata" in text:
        print("note: __init__.py uses importlib.metadata, skipped")
        return
    m = _INIT_VERSION_RE.search(text)
    if m:
        sources.append(("__init__.py __version__", m.group(1)))
    else:
        print("note: __init__.py has no hardcoded __version__, skipped")


def verify_publisher_sync(errors: list[str]) -> None:
    """installer.iss MyAppPublisher 必须与 _version.APP_PUBLISHER 一致。"""
    path = ROOT / INSTALLER_ISS_REL
    if not path.exists():
        return
    m = _PUBLISHER_RE.search(_read(path))
    if not m:
        return
    actual = m.group("val")
    if actual != APP_PUBLISHER:
        errors.append(
            f"installer.iss MyAppPublisher={actual!r} != "
            f"_version.APP_PUBLISHER={APP_PUBLISHER!r}"
        )


def collect_manifest(
    required: bool,
    sources: list[tuple[str, str]],
    errors: list[str],
) -> None:
    path = ROOT / _MANIFEST_REL
    rel = path.relative_to(ROOT).as_posix()
    if not path.exists():
        if required:
            errors.append(f"version.json not found (expected: {rel})")
        return
    try:
        data = json.loads(_read(path))
    except Exception as e:
        errors.append(f"{rel}: invalid JSON: {e}")
        return
    if not isinstance(data, dict):
        errors.append(f"{rel}: root is not an object")
        return

    v = data.get("version")
    if not isinstance(v, str) or not v:
        errors.append(f"{rel}: missing string field 'version'")
        return
    sources.append((f"{rel} version", v))

    url = data.get("download_url")
    if not is_safe_https_url(url):
        errors.append(
            f"{rel}: download_url must be https:// with non-empty host")

    mirror = data.get("download_url_mirror")
    if mirror is not None and not is_safe_https_url(mirror):
        errors.append(
            f"{rel}: download_url_mirror must be https:// with "
            f"non-empty host")

    mirrors = data.get("download_url_mirrors")
    if mirrors is not None:
        if not isinstance(mirrors, list):
            errors.append(f"{rel}: download_url_mirrors must be a list")
        else:
            for i, m in enumerate(mirrors):
                if not is_safe_https_url(m):
                    errors.append(
                        f"{rel}: download_url_mirrors[{i}] must be "
                        f"https:// with non-empty host")

    # 单数字段必须等于镜像列表第一个（patch_updater 生成契约）。
    if (mirror is not None and isinstance(mirrors, list) and mirrors
            and mirror != mirrors[0]):
        errors.append(
            f"{rel}: download_url_mirror ({mirror!r}) 与 "
            f"download_url_mirrors[0] ({mirrors[0]!r}) 不一致；"
            f"patch_updater 契约要求两者相等（旧/新客户端兼容）")

    sha = data.get("sha256")
    if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha.lower()):
        errors.append(f"{rel}: sha256 must be 64 hex chars")

    notes = data.get("release_notes")
    if notes is not None and not isinstance(notes, str):
        errors.append(f"{rel}: release_notes must be a string if present")


def verify_manifest_sha256(errors: list[str]) -> None:
    """断言 manifest.sha256 与 release/<installer> 实际哈希一致。"""
    manifest = ROOT / _MANIFEST_REL
    rel_manifest = manifest.relative_to(ROOT).as_posix()

    if not manifest.exists():
        errors.append(f"{rel_manifest} not found (needed for --verify-sha256)")
        return
    try:
        data = json.loads(_read(manifest))
    except Exception as e:
        errors.append(f"{rel_manifest}: invalid JSON: {e}")
        return
    if not isinstance(data, dict):
        errors.append(f"{rel_manifest}: root is not an object")
        return

    ver = data.get("version")
    if not isinstance(ver, str) or not ver:
        errors.append(f"{rel_manifest}: missing string field 'version'")
        return
    try:
        validate_ver(ver)
    except VersionPatchError as e:
        errors.append(f"{rel_manifest}: {e}")
        return

    expected = data.get("sha256")
    if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected.lower()):
        errors.append(f"{rel_manifest}: sha256 missing or malformed")
        return
    expected = expected.lower()

    installer = ROOT / pathlib.Path(RELEASE_DIR_REL) / installer_exe_name(ver)
    rel_installer = installer.relative_to(ROOT).as_posix()
    if not installer.exists():
        errors.append(
            f"{rel_installer} not found (needed for --verify-sha256)")
        return
    try:
        actual = sha256_of_file(installer)
    except OSError as e:
        errors.append(f"{rel_installer}: read failed: {e}")
        return

    if actual != expected:
        errors.append(
            f"sha256 mismatch: {rel_manifest}={expected[:12]}..., "
            f"{rel_installer}={actual[:12]}..."
        )
        return
    print(f"sha256 OK: {rel_installer} = {actual[:12]}...")


def main(argv: list[str]) -> int:
    sources: list[tuple[str, str]] = []
    errors: list[str] = []

    expected = os.environ.get("VER", "").strip()
    if expected:
        try:
            validate_ver(expected)
        except VersionPatchError as e:
            errors.append(str(e))
            expected = ""

    manifest_required = "--manifest-required" in argv
    verify_sha256 = "--verify-sha256" in argv

    collect_pyproject(sources, errors)
    collect_updater(sources, errors)
    collect_installer(sources, errors)
    collect_init(sources, errors)
    collect_manifest(manifest_required, sources, errors)
    verify_publisher_sync(errors)
    if verify_sha256:
        verify_manifest_sha256(errors)

    print("Version sources:")
    width = max((len(name) for name, _ in sources), default=0)
    for name, ver in sources:
        print(f"  {name.ljust(width)}  {ver}")

    if not sources:
        errors.append("no version source found")

    versions = {ver for _, ver in sources}
    if len(versions) > 1:
        errors.append(f"version mismatch across sources: {sorted(versions)}")

    if expected:
        for name, ver in sources:
            if ver != expected:
                errors.append(f"{name}: expected {expected}, got {ver}")

    if errors:
        print("\nFAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"\nOK: all sources agree on {next(iter(versions))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))