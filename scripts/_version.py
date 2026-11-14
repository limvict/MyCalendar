# file: _version.py
# coding: utf-8
"""版本号注入的单一实现。

patch_updater.py、scripts/build.py、check_version.py 共用本模块：
版本源路径、正则、注入函数只有这一份，避免多处漂移。
此外，sha256 计算、https 校验、stdio 重定向也集中于此，
避免 check_version 与 patch_updater 各自重复实现。

本模块不解析 CLI、不打印"下一步"提示，纯函数式注入。
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys
from urllib.parse import urlparse

# --- 版本源路径（相对项目根）---
UPDATER_PY_REL = (
    "src/desktop_calendar/infrastructure/network/update_checker.py"
)
INSTALLER_ISS_REL = "build/installer.iss"
PYPROJECT_REL = "pyproject.toml"

# --- 发布产物路径 / 名称（check_version.py 与 patch_updater.py 共用）---
RELEASE_DIR_REL = "release"
MANIFEST_NAME = "version.json"

# --- 正则（要求值非空：空版本源属于配置错误）---
CURRENT_VERSION_RE = re.compile(
    r"""CURRENT_VERSION\s*(?::\s*[^=\n]+?)?\s*=\s*[rR]?(?P<q>['"])(?P<val>[^'"]+)(?P=q)"""
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

# --- Inno Setup 安装包命名 ---
# 必须与 build/installer.iss 的
#   OutputBaseFilename=DesktopCalendar_Setup_{#MyAppVersion}
# 一致。版本号是文件名的一部分，因此不能是单一常量，由
# installer_exe_name() 按版本拼接。manifest 的 download_url 与 sha256
# 都指向这个文件；release/<APP_EXE_NAME> 只是安装包的输入，不上传。
INSTALLER_EXE_PREFIX = "DesktopCalendar_Setup_"
INSTALLER_EXE_SUFFIX = ".exe"


def installer_exe_name(ver: str) -> str:
    """返回指定版本的 Inno Setup 安装包文件名。

    不做版本校验：调用方（patch_updater / check_version / build）
    已通过 validate_ver 校验过，重复校验只会让错误来源模糊。
    """
    return f"{INSTALLER_EXE_PREFIX}{ver}{INSTALLER_EXE_SUFFIX}"


class VersionPatchError(RuntimeError):
    """版本注入失败：路径缺失、正则未匹配、读写失败等。"""


# ===================== 跨脚本共享工具 =====================
def sha256_of_file(path: pathlib.Path) -> str:
    """分块读取，避免大文件一次性读入内存。

    应用侧 update_downloader._sha256_of_file 是同一实现（应用代码不能
    import scripts/ 下的本模块），改动算法时请同步。
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def is_safe_https_url(url) -> bool:
    """https 且 host 非空——与 update_checker._is_safe_download_url 同构。

    不能只用 url.startswith("https://")：``https://`` 与 ``https:///x``
    都能通过前缀检查，但运行时 urlparse 后 netloc 为空会被拒绝，表现为
    "发现更新 → 下载失败"。两处判定必须一致，改动时请同步
    src/desktop_calendar/infrastructure/network/update_checker.py。
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        p = urlparse(url)
    except Exception:
        return False
    return p.scheme == "https" and bool(p.netloc)


def reconfigure_stdio() -> None:
    """把 stdout/stderr 切到 UTF-8，Windows 控制台打印中文不乱码。"""
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")


# ===================== 版本注入 =====================
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
    这类最常见错误不会留下半更新的工作区。

    三个源的 plan 各自 try/except，收集所有错误后一次性抛出。
    原实现是列表字面量立即求值：第一个源失败就抛，用户修完再跑
    又发现第二个源没匹配，修复体验差。收集后一次报全，且仍保持
    "全部 plan 成功才写入"的原子性。

    写入阶段若发生 IO 失败，可能已有部分文件被写入——这是可接受
    的，因为 IO 失败本身是异常路径，CI 会失败并重新 checkout。
    """
    ver = validate_ver(ver)

    plans: list[tuple[str, tuple[pathlib.Path, str] | None]] = []
    errors: list[str] = []
    planners = (
        ("CURRENT_VERSION",
         lambda: _plan_version(root / UPDATER_PY_REL,
                               CURRENT_VERSION_RE, ver, "CURRENT_VERSION")),
        ("MyAppVersion",
         lambda: _plan_version(root / INSTALLER_ISS_REL,
                               INSTALLER_VERSION_RE, ver, "MyAppVersion")),
        ("[project].version",
         lambda: _plan_pyproject_version(root / PYPROJECT_REL, ver)),
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
            path.write_text(text, encoding="utf-8")
        except OSError as e:
            raise VersionPatchError(
                f"write failed: {path}: {e}") from e
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
        out.write_text(content, encoding="utf-8")
    except OSError as e:
        raise VersionPatchError(f"write failed: {out}: {e}") from e
    return out


__all__ = [
    "VersionPatchError", "validate_ver", "patch_all", "write_version_info",
    "sha256_of_file", "is_safe_https_url", "reconfigure_stdio",
    "installer_exe_name",
    "CURRENT_VERSION_RE", "INSTALLER_VERSION_RE",
    "PYPROJECT_VERSION_LINE_RE",
    "UPDATER_PY_REL", "INSTALLER_ISS_REL", "PYPROJECT_REL",
    "RELEASE_DIR_REL", "MANIFEST_NAME",
    "APP_PUBLISHER", "APP_DISPLAY_NAME", "APP_INTERNAL_NAME", "APP_EXE_NAME",
    "INSTALLER_EXE_PREFIX", "INSTALLER_EXE_SUFFIX",
]