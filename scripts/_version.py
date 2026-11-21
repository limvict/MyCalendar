# file: _version.py
# coding: utf-8
"""版本号注入的单一实现，供 patch_updater / build / check_version 共用。

版本源路径、正则、注入函数、sha256、https 校验、stdio 重定向集中于此。
本模块不解析 CLI、不打印提示。
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import sys
from urllib.parse import urlparse

UPDATER_PY_REL = "src/desktop_calendar/infrastructure/network/update_checker.py"
INSTALLER_ISS_REL = "build/installer.iss"
PYPROJECT_REL = "pyproject.toml"

RELEASE_DIR_REL = "release"
MANIFEST_NAME = "version.json"

# 值必须非空：空版本源属于配置错误。
CURRENT_VERSION_RE = re.compile(
    r"""CURRENT_VERSION\s*(?::\s*[^=\n]+?)?\s*=\s*[rR]?(?P<q>['"])(?P<val>[^'"]+)(?P=q)"""
)
INSTALLER_VERSION_RE = re.compile(r"""#define\s+MyAppVersion\s+(?P<q>["'])(?P<val>[^"']+)(?P=q)""")
PYPROJECT_VERSION_LINE_RE = re.compile(r"""^(\s*version\s*=\s*)(?P<q>["'])(?P<val>[^"']+)(?P=q)""")

_VALID_VER_RE = re.compile(r"\d+\.\d+\.\d+")

# 与 build/installer.iss 的 MyAppPublisher 同步（check_version.py 会校验）。
APP_PUBLISHER = "limvict"
APP_DISPLAY_NAME = "桌面日历"
APP_INTERNAL_NAME = "DesktopCalendar"
APP_EXE_NAME = "DesktopCalendar.exe"

# 与 installer.iss 的 OutputBaseFilename=DesktopCalendar_Setup_{#MyAppVersion} 一致。
INSTALLER_EXE_PREFIX = "DesktopCalendar_Setup_"
INSTALLER_EXE_SUFFIX = ".exe"


def installer_exe_name(ver: str) -> str:
    """返回指定版本的安装包文件名（调用方已校验 ver）。"""
    return f"{INSTALLER_EXE_PREFIX}{ver}{INSTALLER_EXE_SUFFIX}"


class VersionPatchError(RuntimeError):
    """版本注入失败：路径缺失、正则未匹配、读写失败等。"""


def sha256_of_file(path: pathlib.Path) -> str:
    """分块读取，避免大文件一次性载入内存。

    应用侧 update_downloader._sha256_of_file 是同一实现，改动时请同步。
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def is_safe_https_url(url) -> bool:
    """https 且 host 非空。

    不能只用 startswith("https://")：``https://`` 与 ``https:///x``
    都能通过前缀检查但 netloc 为空。与 update_checker._is_safe_download_url
    同构，改动时请同步。
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        p = urlparse(url)
    except Exception:
        return False
    return p.scheme == "https" and bool(p.netloc)


def reconfigure_stdio() -> None:
    """stdout/stderr 切到 UTF-8，Windows 控制台打印中文不乱码。"""
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")


def validate_ver(ver: str) -> str:
    """校验 X.Y.Z 格式，返回 stripped 值；格式错抛 VersionPatchError。"""
    if not isinstance(ver, str):
        raise VersionPatchError(f"VER must be a string, got {type(ver).__name__}")
    ver = ver.strip()
    if not _VALID_VER_RE.fullmatch(ver):
        raise VersionPatchError(f"VER format invalid (expect X.Y.Z): {ver!r}")
    return ver


def _atomic_write_text(path: pathlib.Path, text: str) -> None:
    """同目录临时文件 + os.replace，保证单文件写入原子性。

    写入中途崩溃 / 磁盘满时，原文件保持旧内容，不会留下截断的版本源。
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _plan_version(
    path: pathlib.Path,
    regex: re.Pattern,
    ver: str,
    label: str,
) -> tuple[pathlib.Path, str] | None:
    """计算替换后内容；无需改动返回 None。只读不写。"""
    if not path.exists():
        raise VersionPatchError(f"file not found: {path}")
    try:
        s = path.read_text(encoding="utf-8")
    except OSError as e:
        raise VersionPatchError(f"read failed: {path}: {e}") from e
    m = regex.search(s)
    if not m:
        raise VersionPatchError(f"{label} not found in {path.name}")
    if m.group("val") == ver:
        return None
    prefix = s[m.start() : m.start("q")]
    new_text = s[: m.start()] + prefix + f'"{ver}"' + s[m.end() :]
    return path, new_text


def _plan_pyproject_version(
    path: pathlib.Path,
    ver: str,
) -> tuple[pathlib.Path, str] | None:
    """只改 [project] 段内的 version 行；无需改动返回 None。"""
    if not path.exists():
        raise VersionPatchError(f"file not found: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as e:
        raise VersionPatchError(f"read failed: {path}: {e}") from e
    in_project = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        if not in_project:
            continue
        m = PYPROJECT_VERSION_LINE_RE.match(line)
        if not m:
            continue
        if m.group("val") == ver:
            return None
        lines[i] = m.group(1) + f'"{ver}"' + line[m.end() :]
        return path, "".join(lines)
    raise VersionPatchError(f"[project].version not found in {path.name}")


def patch_all(root: pathlib.Path, ver: str) -> list[tuple[str, bool]]:
    """把 ver 注入全部版本源。返回 [(label, changed), ...]。

    两阶段：先对所有源 plan（收集全部错误，任一失败则不写任何文件），
    全部成功后再统一写入。单文件写入走 _atomic_write_text，避免截断。
    多文件仍可能部分成功，但 patch_all 幂等（已等于 ver 的源 plan 返回
    None），重跑即可补齐。
    """
    ver = validate_ver(ver)

    plans: list[tuple[str, tuple[pathlib.Path, str] | None]] = []
    errors: list[str] = []
    planners = (
        (
            "CURRENT_VERSION",
            lambda: _plan_version(
                root / UPDATER_PY_REL, CURRENT_VERSION_RE, ver, "CURRENT_VERSION"
            ),
        ),
        (
            "MyAppVersion",
            lambda: _plan_version(
                root / INSTALLER_ISS_REL, INSTALLER_VERSION_RE, ver, "MyAppVersion"
            ),
        ),
        ("[project].version", lambda: _plan_pyproject_version(root / PYPROJECT_REL, ver)),
    )
    for label, fn in planners:
        try:
            plans.append((label, fn()))
        except VersionPatchError as e:
            errors.append(str(e))
    if errors:
        raise VersionPatchError("\n".join(errors))

    results: list[tuple[str, bool]] = []
    for label, plan in plans:
        if plan is None:
            results.append((label, False))
            continue
        path, text = plan
        try:
            _atomic_write_text(path, text)
        except OSError as e:
            raise VersionPatchError(f"write failed: {path}: {e}") from e
        results.append((label, True))
    return results


def write_version_info(root: pathlib.Path, ver: str) -> pathlib.Path:
    ver = validate_ver(ver)
    build_dir = root / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    out = build_dir / "version_info.txt"

    parts = [int(x) for x in ver.split(".")]
    while len(parts) < 4:
        parts.append(0)
    vtuple = tuple(parts[:4])
    vstr = ".".join(str(p) for p in parts[:4])

    content = f"""\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vtuple},
    prodvers={vtuple},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [StringStruct('CompanyName', '{APP_PUBLISHER}'),
         StringStruct('FileDescription', '{APP_DISPLAY_NAME}'),
         StringStruct('FileVersion', '{vstr}'),
         StringStruct('InternalName', '{APP_INTERNAL_NAME}'),
         StringStruct('OriginalFilename', '{APP_EXE_NAME}'),
         StringStruct('ProductName', '{APP_DISPLAY_NAME}'),
         StringStruct('ProductVersion', '{vstr}')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    try:
        _atomic_write_text(out, content)
    except OSError as e:
        raise VersionPatchError(f"write failed: {out}: {e}") from e
    return out


__all__ = [
    "VersionPatchError",
    "validate_ver",
    "patch_all",
    "write_version_info",
    "sha256_of_file",
    "is_safe_https_url",
    "reconfigure_stdio",
    "installer_exe_name",
    "CURRENT_VERSION_RE",
    "INSTALLER_VERSION_RE",
    "PYPROJECT_VERSION_LINE_RE",
    "UPDATER_PY_REL",
    "INSTALLER_ISS_REL",
    "PYPROJECT_REL",
    "RELEASE_DIR_REL",
    "MANIFEST_NAME",
    "APP_PUBLISHER",
    "APP_DISPLAY_NAME",
    "APP_INTERNAL_NAME",
    "APP_EXE_NAME",
    "INSTALLER_EXE_PREFIX",
    "INSTALLER_EXE_SUFFIX",
]
