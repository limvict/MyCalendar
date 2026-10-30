# file: patch_updater.py
# coding: utf-8
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
from typing import NoReturn

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _version import (  # noqa: E402
    APP_EXE_NAME,
    MANIFEST_NAME,
    RELEASE_DIR_REL,
    VersionPatchError,
    patch_all,
    validate_ver,
    write_version_info,
)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 路径常量统一来自 _version，避免与 check_version.py 漂移。
RELEASE_REL = pathlib.Path(RELEASE_DIR_REL)
# 复用 _version.APP_EXE_NAME，避免 exe 名在两处漂移。
EXE_REL = RELEASE_REL / APP_EXE_NAME


def _die(msg: str) -> NoReturn:
    print(f"[patch_updater] {msg}", file=sys.stderr)
    raise SystemExit(1)


def _require_ver(ver: str) -> str:
    if not ver:
        _die("env VER not set, e.g. VER=3.0.2 python scripts/patch_updater.py")
    try:
        return validate_ver(ver)
    except VersionPatchError as e:
        _die(str(e))


def _sha256_of_file(path: pathlib.Path) -> str:
    """分块读取，避免大 exe 一次性读入内存。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _join_url(base: str, ver: str, name: str) -> str:
    """把 {ver} 占位替换后拼上文件名；用 replace 而非 format，
    避免 base 里出现字面花括号时抛异常。"""
    return base.replace("{ver}", ver).rstrip("/") + "/" + name


def _resolve_download_urls(ver: str, repo: str) -> list[str]:
    """返回 [主 URL, 镜像1, 镜像2, ...]，去重保序。

    主通道：
      - 设了 DOWNLOAD_BASE_URL：用它（支持 {ver} 占位），末尾拼 exe 名
      - 否则：GitHub Releases（要求 repo 形如 owner/name）
    镜像通道（可选，按顺序写入 manifest）：
      - DOWNLOAD_MIRROR_BASE_URLS：逗号分隔，支持多个（推荐）
      - DOWNLOAD_MIRROR_BASE_URL：单个（向后兼容）

    镜像地址原样保留顺序（不重新排序），因为运行时按列表顺序
    fallback，先试的源应当更快/更稳。重复地址去重，避免浪费重试次数。
    """
    base = os.environ.get("DOWNLOAD_BASE_URL", "").strip()
    if base:
        primary = _join_url(base, ver, APP_EXE_NAME)
    else:
        primary = (
            f"https://github.com/{repo}/releases/download/v{ver}/{APP_EXE_NAME}"
        )
    raw = os.environ.get("DOWNLOAD_MIRROR_BASE_URLS", "").strip()
    if not raw:
        raw = os.environ.get("DOWNLOAD_MIRROR_BASE_URL", "").strip()
    urls = [primary]
    for m in raw.split(","):
        m = m.strip()
        if m:
            urls.append(_join_url(m, ver, APP_EXE_NAME))
    seen: set = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _default_release_notes(ver: str) -> str:
    """从 git log 读最近 commit 作为 release notes。

    CI 里 release.yml 不设 RELEASE_NOTES，硬编码 "See release page."
    会让用户更新弹窗显示无意义文本。git log 在 checkout 后的 workspace
    里始终可用（actions/checkout@v4 默认 fetch-depth=1，只能读最新
    commit；如需更完整的历史，需在 CI 里 fetch-depth: 0）。

    注意：Windows runner 上 subprocess 的 text=True 默认按 cp1252 解码，
    git log 里的 UTF-8 / 中文 commit 会触发 UnicodeDecodeError，而它是在
    读取子线程里抛的，外层 try/except 接不到，随后 stdout 变成 None 导致
    .strip() 报 AttributeError。这里显式指定 encoding + errors="replace"。
    """
    try:
        out = subprocess.check_output(
            [
                "git",
                "-c", "i18n.logOutputEncoding=UTF-8",
                "log", "--oneline", "-5", "--no-merges",
            ],
            timeout=5,
            cwd=ROOT,
            encoding="utf-8",   # 关键：不要走 cp1252
            errors="replace",   # 关键：非法字节替换为 �，不抛异常
        )
        out = (out or "").strip()   # 兜底，防止极端情况下仍为 None
        return out or f"Release v{ver}"
    except (subprocess.SubprocessError, OSError):
        return f"Release v{ver}"


def patch_versions(ver: str) -> None:
    """注入版本号并打印每项状态。失败以 SystemExit 退出。"""
    try:
        results = patch_all(ROOT, ver)
    except VersionPatchError as e:
        _die(str(e))
    for label, changed in results:
        print(f"{'Patched' if changed else 'Unchanged'} {label} -> {ver}")


def write_manifest(ver: str) -> None:
    """生成 release/version.json，字段名与 update_manager.py 消费方一致。

    字段：version / download_url / sha256 / release_notes
          （可选）download_url_mirror       单镜像（旧客户端兼容）
          （可选）download_url_mirrors      多镜像列表（新客户端）

    下载地址来源：
      - DOWNLOAD_BASE_URL 优先（支持 {ver} 占位），适合对象存储 / CDN
      - 否则回落到 GitHub Releases，此时必须设置 GITHUB_REPOSITORY
      - 镜像：DOWNLOAD_MIRROR_BASE_URLS（逗号分隔多个）优先，
              DOWNLOAD_MIRROR_BASE_URL（单个）兼容旧用法
    拒绝写出占位 URL：废产物让 CI / 本地构建早失败更划算。
    """
    exe = ROOT / EXE_REL
    if not exe.exists():
        _die(f"exe not found: {exe} (run build first)")

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    base = os.environ.get("DOWNLOAD_BASE_URL", "").strip()
    if not base and (not repo or "/" not in repo):
        _die(
            "env GITHUB_REPOSITORY is empty or malformed and "
            "DOWNLOAD_BASE_URL is not set; refusing to write manifest "
            "with a placeholder download_url. Set GITHUB_REPOSITORY "
            "(e.g. limvict/MyCalendar) or DOWNLOAD_BASE_URL."
        )

    urls = _resolve_download_urls(ver, repo)
    try:
        sha256 = _sha256_of_file(exe)
    except OSError as e:
        _die(f"hash failed: {exe}: {e}")

    manifest = {
        "version": ver,
        "download_url": urls[0],
        "sha256": sha256,
        "release_notes": (
            os.environ.get("RELEASE_NOTES", "").strip()
            or _default_release_notes(ver)
        ),
    }
    if len(urls) > 1:
        # 兼容旧客户端：第一个镜像写单数字段
        manifest["download_url_mirror"] = urls[1]
        # 新客户端：完整镜像列表（顺序 = fallback 顺序）
        manifest["download_url_mirrors"] = urls[1:]

    out = ROOT / RELEASE_REL / MANIFEST_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        out.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        _die(f"write manifest failed: {out}: {e}")
    mirror_desc = (
        f", mirrors={len(urls) - 1}" if len(urls) > 1 else "")
    print(f"Wrote {out.relative_to(ROOT).as_posix()} "
          f"(version={ver}, sha256={sha256[:12]}...{mirror_desc})")


def main(argv: list[str]) -> int:
    ver = _require_ver(os.environ.get("VER", "").strip())
    if "--manifest" in argv:
        write_manifest(ver)
        return 0
    patch_versions(ver)
    if "--version-info" in argv:
        try:
            out = write_version_info(ROOT, ver)
        except (VersionPatchError, OSError) as e:
            _die(str(e))
        print(f"Wrote {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))