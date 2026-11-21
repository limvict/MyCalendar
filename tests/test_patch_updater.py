# coding: utf-8
"""patch_updater 补充：URL 解析、manifest 生成、环境变量校验。"""

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import scripts.patch_updater as pu  # noqa: E402


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    monkeypatch.setattr(pu, "ROOT", tmp_path)
    return tmp_path


# ---------------- _join_url ----------------
class TestJoinUrl:
    def test_no_placeholder(self):
        assert pu._join_url("https://x.com/dist", "1.0", "a.exe") == "https://x.com/dist/a.exe"

    def test_with_placeholder(self):
        assert pu._join_url("https://x.com/{ver}", "1.0", "a.exe") == "https://x.com/1.0/a.exe"

    def test_trailing_slash_trimmed(self):
        assert pu._join_url("https://x.com/", "1.0", "a.exe") == "https://x.com/a.exe"

    def test_multiple_placeholder_occurrences(self):
        assert (
            pu._join_url("https://x.com/{ver}/{ver}", "1.0", "a.exe")
            == "https://x.com/1.0/1.0/a.exe"
        )

    def test_literal_braces_in_base_not_treated_as_format(self):
        # 源码用 replace 而非 format：base 里的 {other} 应原样保留
        assert (
            pu._join_url("https://x.com/{other}", "1.0", "a.exe") == "https://x.com/{other}/a.exe"
        )


# ---------------- _resolve_download_urls ----------------
class TestResolveDownloadUrls:
    def test_github_default(self, monkeypatch):
        monkeypatch.delenv("DOWNLOAD_BASE_URL", raising=False)
        monkeypatch.delenv("DOWNLOAD_MIRROR_BASE_URL", raising=False)
        urls = pu._resolve_download_urls("1.0.0", "owner/repo")
        name = pu.installer_exe_name("1.0.0")
        assert urls == [f"https://github.com/owner/repo/releases/download/v1.0.0/{name}"]

    def test_custom_base(self, monkeypatch):
        monkeypatch.setenv("DOWNLOAD_BASE_URL", "https://cdn.x.com/{ver}")
        monkeypatch.delenv("DOWNLOAD_MIRROR_BASE_URL", raising=False)
        urls = pu._resolve_download_urls("1.0.0", "owner/repo")
        name = pu.installer_exe_name("1.0.0")
        assert urls == [f"https://cdn.x.com/1.0.0/{name}"]

    def test_with_mirror(self, monkeypatch):
        monkeypatch.setenv("DOWNLOAD_BASE_URL", "https://a.com/{ver}")
        monkeypatch.setenv("DOWNLOAD_MIRROR_BASE_URL", "https://b.com/{ver}")
        urls = pu._resolve_download_urls("1.0.0", "owner/repo")
        name = pu.installer_exe_name("1.0.0")
        assert urls == [
            f"https://a.com/1.0.0/{name}",
            f"https://b.com/1.0.0/{name}",
        ]

    def test_multi_mirrors_env(self, monkeypatch):
        """DOWNLOAD_MIRROR_BASE_URLS 逗号分隔多个镜像。"""
        monkeypatch.setenv("DOWNLOAD_BASE_URL", "https://a.com/{ver}")
        monkeypatch.setenv("DOWNLOAD_MIRROR_BASE_URLS", "https://b.com/{ver},https://c.com/{ver}")
        monkeypatch.delenv("DOWNLOAD_MIRROR_BASE_URL", raising=False)
        urls = pu._resolve_download_urls("1.0.0", "owner/repo")
        assert len(urls) == 3
        assert urls[0] == (f"https://a.com/1.0.0/{pu.installer_exe_name('1.0.0')}")
        assert urls[1].startswith("https://b.com/")
        assert urls[2].startswith("https://c.com/")

    def test_dedupe(self, monkeypatch):
        """主通道与镜像指向同一地址时去重。"""
        monkeypatch.setenv("DOWNLOAD_BASE_URL", "https://a.com/{ver}")
        monkeypatch.setenv("DOWNLOAD_MIRROR_BASE_URLS", "https://a.com/{ver}")
        monkeypatch.delenv("DOWNLOAD_MIRROR_BASE_URL", raising=False)
        urls = pu._resolve_download_urls("1.0.0", "owner/repo")
        assert len(urls) == 1

    def test_bad_mirror_dies(self, monkeypatch):
        """镜像非 https 时 _die(SystemExit)，不写 manifest。"""
        monkeypatch.setenv("DOWNLOAD_BASE_URL", "https://a.com/{ver}")
        monkeypatch.setenv("DOWNLOAD_MIRROR_BASE_URLS", "http://bad")
        monkeypatch.delenv("DOWNLOAD_MIRROR_BASE_URL", raising=False)
        with pytest.raises(SystemExit):
            pu._resolve_download_urls("1.0.0", "owner/repo")


# ---------------- write_manifest ----------------
class TestWriteManifest:
    def _setup_exe(self, root, ver="1.0.0"):
        exe = root / pu.RELEASE_REL / pu.installer_exe_name(ver)
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"fake exe content")
        return exe

    def _load(self, root):
        return json.loads((root / pu.RELEASE_REL / pu.MANIFEST_NAME).read_text(encoding="utf-8"))

    def test_missing_exe_dies(self, fake_root, monkeypatch):
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("DOWNLOAD_BASE_URL", raising=False)
        with pytest.raises(SystemExit) as ei:
            pu.write_manifest("1.0.0")
        assert ei.value.code == 1

    def test_no_repo_and_no_base_dies(self, fake_root, monkeypatch):
        self._setup_exe(fake_root, "1.0.0")
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("DOWNLOAD_BASE_URL", raising=False)
        with pytest.raises(SystemExit) as ei:
            pu.write_manifest("1.0.0")
        assert ei.value.code == 1

    def test_malformed_repo_dies(self, fake_root, monkeypatch):
        self._setup_exe(fake_root, "1.0.0")
        monkeypatch.setenv("GITHUB_REPOSITORY", "noslash")
        monkeypatch.delenv("DOWNLOAD_BASE_URL", raising=False)
        with pytest.raises(SystemExit):
            pu.write_manifest("1.0.0")

    def test_success_github(self, fake_root, monkeypatch):
        self._setup_exe(fake_root, "2.0.0")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.delenv("DOWNLOAD_BASE_URL", raising=False)
        monkeypatch.delenv("DOWNLOAD_MIRROR_BASE_URL", raising=False)
        monkeypatch.delenv("RELEASE_NOTES", raising=False)
        pu.write_manifest("2.0.0")
        data = self._load(fake_root)
        assert data["version"] == "2.0.0"
        assert data["download_url"].startswith("https://github.com/")
        assert len(data["sha256"]) == 64
        assert "download_url_mirror" not in data

    def test_custom_base_url(self, fake_root, monkeypatch):
        self._setup_exe(fake_root, "2.0.0")
        monkeypatch.setenv("DOWNLOAD_BASE_URL", "https://cdn.x.com/{ver}")
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("DOWNLOAD_MIRROR_BASE_URL", raising=False)
        pu.write_manifest("2.0.0")
        data = self._load(fake_root)
        assert data["download_url"] == (f"https://cdn.x.com/2.0.0/{pu.installer_exe_name('2.0.0')}")

    def test_mirror_present(self, fake_root, monkeypatch):
        self._setup_exe(fake_root, "2.0.0")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.delenv("DOWNLOAD_BASE_URL", raising=False)
        monkeypatch.setenv("DOWNLOAD_MIRROR_BASE_URL", "https://mirror.com/{ver}")
        pu.write_manifest("2.0.0")
        data = self._load(fake_root)
        assert "download_url_mirror" in data
        assert "2.0.0" in data["download_url_mirror"]

    def test_release_notes_from_env(self, fake_root, monkeypatch):
        self._setup_exe(fake_root, "2.0.0")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.delenv("DOWNLOAD_BASE_URL", raising=False)
        monkeypatch.setenv("RELEASE_NOTES", "自定义说明")
        pu.write_manifest("2.0.0")
        assert self._load(fake_root)["release_notes"] == "自定义说明"

    def test_release_notes_fallback_no_git(self, fake_root, monkeypatch):
        """无 git / 非 repo 环境下 _default_release_notes 回退。"""
        self._setup_exe(fake_root, "2.0.0")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.delenv("DOWNLOAD_BASE_URL", raising=False)
        monkeypatch.delenv("RELEASE_NOTES", raising=False)
        pu.write_manifest("2.0.0")
        # 回退文本以 "Release v" 开头
        assert self._load(fake_root)["release_notes"].startswith("Release v")

    def test_mirrors_list_written(self, fake_root, monkeypatch):
        """多镜像时 mirror = mirrors[0] 且 mirrors 长度 = 镜像数。"""
        self._setup_exe(fake_root, "2.0.0")
        monkeypatch.setenv("DOWNLOAD_BASE_URL", "https://a.com/{ver}")
        monkeypatch.setenv("DOWNLOAD_MIRROR_BASE_URLS", "https://b.com/{ver},https://c.com/{ver}")
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("DOWNLOAD_MIRROR_BASE_URL", raising=False)
        pu.write_manifest("2.0.0")
        data = self._load(fake_root)
        assert data["download_url_mirror"] == data["download_url_mirrors"][0]
        assert len(data["download_url_mirrors"]) == 2


# ---------------- main ----------------
class TestMain:
    def test_missing_ver_dies(self, fake_root, monkeypatch):
        monkeypatch.delenv("VER", raising=False)
        with pytest.raises(SystemExit) as ei:
            pu.main([])
        assert ei.value.code == 1

    def test_bad_ver_dies(self, fake_root, monkeypatch):
        monkeypatch.setenv("VER", "invalid")
        with pytest.raises(SystemExit) as ei:
            pu.main([])
        assert ei.value.code == 1


# ---------------- 生产清单只读 ----------------
class TestManifestReadOnly:
    def _setup(self, root, monkeypatch, ver="2.0.0"):
        exe = root / pu.RELEASE_REL / pu.installer_exe_name(ver)
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"fake installer")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.delenv("DOWNLOAD_BASE_URL", raising=False)
        monkeypatch.delenv("DOWNLOAD_MIRROR_BASE_URL", raising=False)
        return root / pu.RELEASE_REL / pu.MANIFEST_NAME

    def test_manifest_is_read_only_after_write(self, fake_root, monkeypatch):
        import os

        path = self._setup(fake_root, monkeypatch)
        pu.write_manifest("2.0.0")
        assert path.exists()
        assert os.access(path, os.W_OK) is False, "生产清单应被标记为只读"

    def test_regenerate_clears_readonly_first(self, fake_root, monkeypatch):
        """只读不是死锁：重新生成时会先解锁再覆盖。"""
        import json
        import os

        path = self._setup(fake_root, monkeypatch)
        pu.write_manifest("2.0.0")
        pu.write_manifest("2.0.0")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == "2.0.0"
        assert os.access(path, os.W_OK) is False


# ---------------- release_notes 去掉提交哈希前缀 ----------------
class TestReleaseNotesPrefixes:
    def test_strips_short_hash(self):
        raw = "e2e05ae 更新了上下班考勤\n7d9213a 更新了主题图标\n"
        assert pu._strip_commit_prefixes(raw) == "更新了上下班考勤\n更新了主题图标"

    def test_strips_full_hash(self):
        raw = "a" * 40 + " 修复一个 bug"
        assert pu._strip_commit_prefixes(raw) == "修复一个 bug"

    def test_keeps_lines_without_hash(self):
        assert pu._strip_commit_prefixes("Release/v3.0.8") == "Release/v3.0.8"
        assert (
            pu._strip_commit_prefixes("修复：abc1234 这种不是前缀") == "修复：abc1234 这种不是前缀"
        )

    def test_drops_blank_and_hash_only_lines(self):
        assert pu._strip_commit_prefixes("abc1234 \n\n   \nfix") == "fix"

    def test_default_notes_use_stripped_log(self, fake_root, monkeypatch):
        monkeypatch.setattr(
            pu.subprocess, "check_output", lambda *a, **k: "e2e05ae 更新了上下班考勤\n"
        )
        assert pu._default_release_notes("1.2.3") == "更新了上下班考勤"

    def test_default_notes_fallback_when_log_empty(self, fake_root, monkeypatch):
        monkeypatch.setattr(pu.subprocess, "check_output", lambda *a, **k: "  \n")
        assert pu._default_release_notes("1.2.3") == "Release v1.2.3"
