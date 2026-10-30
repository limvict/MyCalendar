# file: check_version.py
# coding: utf-8
"""
版本一致性检查。

默认断言以下来源版本一致（存在即检查）：
  - pyproject.toml                              [project].version
  - src/desktop_calendar/infrastructure/network/update_manager.py
                                                CURRENT_VERSION
  - build/installer.iss                         #define MyAppVersion
  - src/desktop_calendar/__init__.py            __version__（若硬编码）
  - release/version.json                        "version"
                                                （默认跳过，见 --manifest-required）

同时校验 build/installer.iss 的 MyAppPublisher 与 _version.APP_PUBLISHER
一致（两处不同源会让「应用和功能」与 exe 文件属性显示不同发布者）。

manifest 中 download_url / download_url_mirror / download_url_mirrors
的 https 校验与运行时 update_manager._is_safe_download_url 同构
（scheme 为 https 且 host 非空），避免出现"CI 放行、运行时拒绝"的更新故障。

可选参数：
  VER 环境变量          若设置，额外断言所有来源都等于 VER（CI 打 tag 时用）
  --manifest-required   version.json 必须存在（CI 发布前用）
  --verify-sha256       断言 version.json 的 sha256 与
                        release/<APP_EXE_NAME> 的实际哈希一致
                        （同时要求 exe 与 manifest 均存在）
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import sys
from urllib.parse import urlparse

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _version import (  # noqa: E402
    APP_EXE_NAME,
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
    validate_ver,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INIT_VERSION_RE = re.compile(r"""__version__\s*=\s*['"]([^'"]+)['"]""")
_PUBLISHER_RE = re.compile(
    r"""#define\s+MyAppPublisher\s+(?P<q>["'])(?P<val>[^"']+)(?P=q)""")

# exe / manifest 名称统一从 _version 取，避免与 patch_updater 漂移。
_EXE_REL = pathlib.Path(RELEASE_DIR_REL) / APP_EXE_NAME
_MANIFEST_REL = pathlib.Path(RELEASE_DIR_REL) / MANIFEST_NAME


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha256_of_file(path: pathlib.Path) -> str:
    """分块读取，避免大 exe 一次性读入内存（与 patch_updater 同实现）。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _is_safe_https_url(url) -> bool:
    """https 且 host 非空——与 update_manager._is_safe_download_url 同构。

    不能只用 url.startswith("https://")：``https://`` 与 ``https:///x``
    都能通过前缀检查，但运行时 urlparse 后 netloc 为空会被拒绝，表现为
    "发现更新 → 下载失败"。两处判定必须一致，改动时请同步
    src/desktop_calendar/infrastructure/network/update_manager.py。
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        p = urlparse(url)
    except Exception:
        return False
    return p.scheme == "https" and bool(p.netloc)


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
        errors.append("update_manager.py: CURRENT_VERSION not found")
        return
    sources.append(("update_manager.py CURRENT_VERSION", m.group("val")))


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
    m = _INIT_VERSION_RE.search(_read(path))
    if m:
        sources.append(("__init__.py __version__", m.group(1)))


def verify_publisher_sync(errors: list[str]) -> None:
    """断言 installer.iss 的 MyAppPublisher 与 _version.APP_PUBLISHER 一致。

    两者不同源会让「应用和功能」显示发布者 A、exe 文件属性显示发布者 B。
    这是用户可见、CI 默认不可见的问题，因此放入一致性检查。

    installer.iss 缺失或未定义 MyAppPublisher 时跳过：缺失已由
    collect_installer 报错；未定义宏说明项目不走该宏，无对照可言。
    """
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

    # download_url 必须是 https 且 host 非空——与 update_manager 的
    # _is_safe_download_url 同构（见 _is_safe_https_url）。CI 早期发现，
    # 避免出现"发现更新→下载失败"的用户可见故障。
    url = data.get("download_url")
    if not _is_safe_https_url(url):
        errors.append(
            f"{rel}: download_url must be https:// with non-empty host")

    # 单镜像（旧格式）：存在才校验；None 视为未设置。
    mirror = data.get("download_url_mirror")
    if mirror is not None:
        if not _is_safe_https_url(mirror):
            errors.append(
                f"{rel}: download_url_mirror must be https:// with "
                f"non-empty host")

    # 多镜像列表（新格式）：必须是 list，每个元素都是 https + 非空 host。
    mirrors = data.get("download_url_mirrors")
    if mirrors is not None:
        if not isinstance(mirrors, list):
            errors.append(f"{rel}: download_url_mirrors must be a list")
        else:
            for i, m in enumerate(mirrors):
                if not _is_safe_https_url(m):
                    errors.append(
                        f"{rel}: download_url_mirrors[{i}] must be "
                        f"https:// with non-empty host")

    # sha256 必须是 64 位十六进制——与 update_manager 的校验一致。
    sha = data.get("sha256")
    if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha.lower()):
        errors.append(f"{rel}: sha256 must be 64 hex chars")


def verify_manifest_sha256(errors: list[str]) -> None:
    """断言 manifest 的 sha256 与 release/<APP_EXE_NAME> 实际哈希一致。

    仅在显式传 --verify-sha256 时调用。文件缺失一律报错（而非静默
    跳过）：启用该检查意味着"此时 exe 与 manifest 都应已就绪"，任何
    缺失都说明 CI 步骤顺序错了，应当失败。

    重复解析 version.json 而不复用 collect_manifest 的 data：两者关注点
    不同（版本源 vs 产物完整性），各自独立报错更易定位问题；文件很小，
    多读一次可忽略。
    """
    exe = ROOT / _EXE_REL
    manifest = ROOT / _MANIFEST_REL
    rel_exe = exe.relative_to(ROOT).as_posix()
    rel_manifest = manifest.relative_to(ROOT).as_posix()

    if not manifest.exists():
        errors.append(f"{rel_manifest} not found (needed for --verify-sha256)")
        return
    if not exe.exists():
        errors.append(f"{rel_exe} not found (needed for --verify-sha256)")
        return

    try:
        data = json.loads(_read(manifest))
    except Exception as e:
        errors.append(f"{rel_manifest}: invalid JSON: {e}")
        return
    expected = data.get("sha256") if isinstance(data, dict) else None
    if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected.lower()):
        errors.append(f"{rel_manifest}: sha256 missing or malformed")
        return
    expected = expected.lower()

    try:
        actual = _sha256_of_file(exe)
    except OSError as e:
        errors.append(f"{rel_exe}: read failed: {e}")
        return

    if actual != expected:
        errors.append(
            f"sha256 mismatch: {rel_manifest}={expected[:12]}..., "
            f"{rel_exe}={actual[:12]}..."
        )
        return
    print(f"sha256 OK: {rel_exe} = {actual[:12]}...")


def main(argv: list[str]) -> int:
    sources: list[tuple[str, str]] = []
    errors: list[str] = []

    expected = os.environ.get("VER", "").strip()
    if expected:
        try:
            validate_ver(expected)
        except VersionPatchError as e:
            errors.append(str(e))
            expected = ""  # 格式非法，跳过逐源比较

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