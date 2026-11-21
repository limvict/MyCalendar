# file: patch_updater.py
# coding: utf-8
from __future__ import annotations

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
    MANIFEST_NAME,
    RELEASE_DIR_REL,
    VersionPatchError,
    installer_exe_name,
    is_safe_https_url,
    patch_all,
    reconfigure_stdio,
    sha256_of_file,
    validate_ver,
    write_version_info,
)

reconfigure_stdio()

ROOT = pathlib.Path(__file__).resolve().parent.parent

RELEASE_REL = pathlib.Path(RELEASE_DIR_REL)


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


def _join_url(base: str, ver: str, name: str) -> str:
    """把 {ver} 占位替换后拼上文件名。用 replace 避免 base 含字面花括号。"""
    return base.replace("{ver}", ver).rstrip("/") + "/" + name


def _resolve_download_urls(ver: str, repo: str) -> list[str]:
    """返回 [主 URL, 镜像1, ...]，去重保序。

    主通道：DOWNLOAD_BASE_URL（支持 {ver}）或 GitHub Releases。
    镜像：DOWNLOAD_MIRROR_BASE_URLS（逗号分隔）优先，DOWNLOAD_MIRROR_BASE_URL 兼容。
    每个 URL 拼接后立即校验 https + host 非空，不合法直接 _die。
    """
    name = installer_exe_name(ver)
    base = os.environ.get("DOWNLOAD_BASE_URL", "").strip()
    if base:
        primary = _join_url(base, ver, name)
    else:
        primary = f"https://github.com/{repo}/releases/download/v{ver}/{name}"
    if not is_safe_https_url(primary):
        _die(
            f"download_url must be https:// with non-empty host: "
            f"{primary!r}（检查 DOWNLOAD_BASE_URL 或 GITHUB_REPOSITORY）"
        )

    raw = os.environ.get("DOWNLOAD_MIRROR_BASE_URLS", "").strip()
    if not raw:
        raw = os.environ.get("DOWNLOAD_MIRROR_BASE_URL", "").strip()
    urls = [primary]
    for m in raw.split(","):
        m = m.strip()
        if not m:
            continue
        u = _join_url(m, ver, name)
        if not is_safe_https_url(u):
            _die(
                f"mirror URL must be https:// with non-empty host: "
                f"{u!r}（检查 DOWNLOAD_MIRROR_BASE_URLS）"
            )
        urls.append(u)
    seen: set = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _default_release_notes(ver: str) -> str:
    """从 git log 读最近 commit 作为 release notes。

    显式指定 encoding="utf-8" + errors="replace"：Windows runner 上
    text=True 默认 cp1252，中文 commit 会触发 UnicodeDecodeError。
    """
    try:
        out = subprocess.check_output(
            [
                "git",
                "-c",
                "i18n.logOutputEncoding=UTF-8",
                "log",
                "--oneline",
                "-5",
                "--no-merges",
            ],
            timeout=5,
            cwd=ROOT,
            encoding="utf-8",
            errors="replace",
        )
        out = (out or "").strip()
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


def _clear_readonly(path: pathlib.Path) -> None:
    """清掉只读属性，让重新生成能覆盖旧清单。

    清单写好后会被标记只读（见 _mark_readonly）；本地重跑构建时需要先解锁，
    否则 Windows 上 write_text 会直接 PermissionError。
    """
    try:
        if path.exists():
            path.chmod(0o644)
    except OSError:
        pass


def _mark_readonly(path: pathlib.Path) -> None:
    """把生产清单标记为只读：它是发布产物，后续步骤只应校验、不应改写。"""
    try:
        path.chmod(0o444)
    except OSError as e:  # 只读失败不影响发布，但要让人看见
        print(f"WARNING: cannot mark {path} read-only: {e}", file=sys.stderr)


def write_manifest(ver: str) -> None:
    """生成 release/version.json（字段与 update_manager 消费方一致）。

    sha256 / download_url 指向 Inno Setup 安装包，不是裸 exe。
    安装包不存在时报错而不是退回哈希裸 exe（否则 manifest 与发布物脱节）。

    写完后把文件标记为只读：之后只允许读取与校验（check_version.py），
    任何"顺手修正清单"的做法都会失败在写盘上，避免生产文件被静默篡改。
    """
    installer = ROOT / RELEASE_REL / installer_exe_name(ver)
    if not installer.exists():
        _die(
            f"installer not found: {installer} "
            f"(run build first; manifest sha256 must match the Inno Setup "
            f"package, not the bare exe)"
        )

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
        sha256 = sha256_of_file(installer)
    except OSError as e:
        _die(f"hash failed: {installer}: {e}")

    manifest = {
        "version": ver,
        "download_url": urls[0],
        "sha256": sha256,
        "release_notes": (
            os.environ.get("RELEASE_NOTES", "").strip() or _default_release_notes(ver)
        ),
    }
    if len(urls) > 1:
        # 单数字段供旧客户端，列表供新客户端。
        manifest["download_url_mirror"] = urls[1]
        manifest["download_url_mirrors"] = urls[1:]

    out = ROOT / RELEASE_REL / MANIFEST_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    _clear_readonly(out)
    try:
        out.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        _die(f"write manifest failed: {out}: {e}")
    _mark_readonly(out)
    mirror_desc = f", mirrors={len(urls) - 1}" if len(urls) > 1 else ""
    print(
        f"Wrote {out.relative_to(ROOT).as_posix()} "
        f"(version={ver}, sha256={sha256[:12]}...{mirror_desc}, read-only)"
    )


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
