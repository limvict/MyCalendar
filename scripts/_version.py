# file: _version.py
# coding: utf-8
"""版本号注入的单一实现。

patch_updater.py、build/build.py、check_version.py 共用本模块：
版本源路径、正则、注入函数只有这一份，避免多处漂移。

本模块不解析 CLI、不打印"下一步"提示，纯函数式注入。
"""
from __future__ import annotations

import pathlib
import re

# --- 版本源路径（相对项目根）---
UPDATER_PY_REL = (
    "src/desktop_calendar/infrastructure/network/update_manager.py"
)
INSTALLER_ISS_REL = "build/installer.iss"
PYPROJECT_REL = "pyproject.toml"

# --- 发布产物路径 / 名称（check_version.py 与 patch_updater.py 共用）---
RELEASE_DIR_REL = "release"
MANIFEST_NAME = "version.json"

# --- 正则（要求值非空：空版本源属于配置错误）---
CURRENT_VERSION_RE = re.compile(
    r"""CURRENT_VERSION\s*=\s*[rR]?(?P<q>['"])(?P<val>[^'"]+)(?P=q)"""
)
INSTALLER_VERSION_RE = re.compile(
    r"""#define\s+MyAppVersion\s+(?P<q>["'])(?P<val>[^"']+)(?P=q)"""
)
PYPROJECT_VERSION_LINE_RE = re.compile(
    r"""^(\s*version\s*=\s*)(?P<q>["'])(?P<val>[^"']+)(?P=q)"""
)

_VALID_VER_RE = re.compile(r"\d+\.\d+\.\d+")

# --- exe 版本资源元信息 ---
# CompanyName 需与 installer.iss 的 MyAppPublisher 保持同步：两处不同源
# 会让「应用和功能」与 exe 文件属性显示不同发布者。改动时请同时更新
# build/installer.iss（check_version.py 会校验两者一致）。
APP_PUBLISHER = "limvict"
APP_DISPLAY_NAME = "桌面日历"
APP_INTERNAL_NAME = "DesktopCalendar"
APP_EXE_NAME = "DesktopCalendar.exe"


class VersionPatchError(RuntimeError):
    """版本注入失败：路径缺失、正则未匹配、读写失败等。"""


def validate_ver(ver: str) -> str:
    """校验 X.Y.Z 格式，返回 stripped 值；格式错抛 VersionPatchError。"""
    if not isinstance(ver, str):
        raise VersionPatchError(
            f"VER must be a string, got {type(ver).__name__}")
    ver = ver.strip()
    if not _VALID_VER_RE.fullmatch(ver):
        raise VersionPatchError(
            f"VER format invalid (expect X.Y.Z): {ver!r}")
    return ver


def _plan_version(
    path: pathlib.Path, regex: re.Pattern, ver: str, label: str,
) -> tuple[pathlib.Path, str] | None:
    """计算替换后的完整文件内容；无需改动返回 None。

    只读不写，供 patch_all 做"先全部匹配成功再统一写入"。
    """
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
    # 统一改写为双引号，保留原前缀（含 r/R 前缀与空白）
    prefix = s[m.start():m.start("q")]
    new_text = s[:m.start()] + prefix + f'"{ver}"' + s[m.end():]
    return path, new_text


def _plan_pyproject_version(
    path: pathlib.Path, ver: str,
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
            in_project = (stripped == "[project]")
            continue
        if not in_project:
            continue
        m = PYPROJECT_VERSION_LINE_RE.match(line)
        if not m:
            continue
        if m.group("val") == ver:
            return None
        lines[i] = m.group(1) + f'"{ver}"' + line[m.end():]
        return path, "".join(lines)
    raise VersionPatchError(
        f"[project].version not found in {path.name}")


def patch_all(root: pathlib.Path, ver: str) -> list[tuple[str, bool]]:
    """把 ver 注入全部版本源。返回 [(label, changed), ...]。

    两阶段执行：先对所有版本源做匹配/生成新内容（任一失败即抛错、
    不写任何文件），全部成功后再统一写入。这样"第二个文件正则没匹配"
    这类最常见错误不会留下半更新的工作区。写入阶段若发生 IO 失败，
    可能已有部分文件被写入——这是可接受的，因为 IO 失败本身是异常
    路径，CI 会失败并重新 checkout。
    """
    ver = validate_ver(ver)
    plans: list[tuple[str, tuple[pathlib.Path, str] | None]] = [
        ("CURRENT_VERSION",
         _plan_version(root / UPDATER_PY_REL,
                       CURRENT_VERSION_RE, ver, "CURRENT_VERSION")),
        ("MyAppVersion",
         _plan_version(root / INSTALLER_ISS_REL,
                       INSTALLER_VERSION_RE, ver, "MyAppVersion")),
        ("[project].version",
         _plan_pyproject_version(root / PYPROJECT_REL, ver)),
    ]

    results: list[tuple[str, bool]] = []
    for label, plan in plans:
        if plan is None:
            results.append((label, False))
            continue
        path, text = plan
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as e:
            raise VersionPatchError(
                f"write failed: {path}: {e}") from e
        results.append((label, True))
    return results


def write_version_info(root: pathlib.Path, ver: str) -> pathlib.Path:
    """生成 PyInstaller 的 exe 版本资源 build/version_info.txt。

    版本号与 installer.iss 同源；CompanyName 需与 installer.iss 的
    MyAppPublisher 保持同步（两处不同源会让「应用和功能」与 exe
    文件属性显示不同发布者）。
    """
    ver = validate_ver(ver)
    build_dir = root / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    out = build_dir / "version_info.txt"

    parts = [int(x) for x in ver.split(".")]
    while len(parts) < 4:          # PyInstaller 要求 4 段，补 0
        parts.append(0)
    vtuple = tuple(parts[:4])
    vstr = ".".join(str(x) for x in vtuple)

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
        out.write_text(content, encoding="utf-8")
    except OSError as e:
        raise VersionPatchError(f"write failed: {out}: {e}") from e
    return out


__all__ = [
    "VersionPatchError", "validate_ver", "patch_all", "write_version_info",
    "CURRENT_VERSION_RE", "INSTALLER_VERSION_RE",
    "PYPROJECT_VERSION_LINE_RE",
    "UPDATER_PY_REL", "INSTALLER_ISS_REL", "PYPROJECT_REL",
    "RELEASE_DIR_REL", "MANIFEST_NAME",
    "APP_PUBLISHER", "APP_DISPLAY_NAME", "APP_INTERNAL_NAME", "APP_EXE_NAME",
]