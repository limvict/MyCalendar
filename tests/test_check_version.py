# coding: utf-8
"""check_version 补充：collect_* 各来源、main 各种失败路径。"""
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import scripts.check_version as cv  # noqa: E402


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """把 cv.ROOT 指向 tmp_path，隔离真实工作区。"""
    monkeypatch.setattr(cv, "ROOT", tmp_path)
    return tmp_path


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------------- collect_pyproject ----------------
class TestCollectPyproject:
    def test_found(self, fake_root):
        _write(fake_root, cv.PYPROJECT_REL,
               '[project]\nname = "x"\nversion = "1.2.3"\n')
        sources, errors = [], []
        cv.collect_pyproject(sources, errors)
        assert errors == []
        assert sources == [("pyproject.toml [project].version", "1.2.3")]

    def test_missing_file(self, fake_root):
        sources, errors = [], []
        cv.collect_pyproject(sources, errors)
        assert sources == []
        assert any("missing" in e for e in errors)

    def test_no_version_line(self, fake_root):
        _write(fake_root, cv.PYPROJECT_REL, '[project]\nname = "x"\n')
        sources, errors = [], []
        cv.collect_pyproject(sources, errors)
        assert sources == []
        assert any("not found" in e for e in errors)

    def test_version_outside_project_ignored(self, fake_root):
        _write(fake_root, cv.PYPROJECT_REL,
               '[tool.x]\nversion = "9.9.9"\n[project]\nname = "x"\n')
        sources, errors = [], []
        cv.collect_pyproject(sources, errors)
        assert sources == []


# ---------------- collect_updater ----------------
class TestCollectUpdater:
    def test_found(self, fake_root):
        _write(fake_root, cv.UPDATER_PY_REL,
               'CURRENT_VERSION = "2.0.0"\n')
        sources, errors = [], []
        cv.collect_updater(sources, errors)
        assert sources == [(f"{cv.UPDATER_PY_REL} CURRENT_VERSION", "2.0.0")]

    def test_missing(self, fake_root):
        sources, errors = [], []
        cv.collect_updater(sources, errors)
        assert any("missing" in e for e in errors)

    def test_not_found(self, fake_root):
        _write(fake_root, cv.UPDATER_PY_REL, "# nothing\n")
        sources, errors = [], []
        cv.collect_updater(sources, errors)
        assert any("not found" in e for e in errors)


# ---------------- collect_installer ----------------
class TestCollectInstaller:
    def test_found(self, fake_root):
        _write(fake_root, cv.INSTALLER_ISS_REL,
               '#define MyAppVersion "3.1.4"\n')
        sources, errors = [], []
        cv.collect_installer(sources, errors)
        assert sources == [("installer.iss MyAppVersion", "3.1.4")]

    def test_missing(self, fake_root):
        sources, errors = [], []
        cv.collect_installer(sources, errors)
        assert errors


# ---------------- collect_init ----------------
class TestCollectInit:
    def test_hardcoded_version(self, fake_root):
        _write(fake_root, "src/desktop_calendar/__init__.py",
               "__version__ = '1.2.3'\n")
        sources, errors = [], []
        cv.collect_init(sources, errors)
        assert sources == [("__init__.py __version__", "1.2.3")]

    def test_no_version_ignored(self, fake_root):
        _write(fake_root, "src/desktop_calendar/__init__.py",
               "# no version\n")
        sources, errors = [], []
        cv.collect_init(sources, errors)
        assert sources == [] and errors == []

    def test_file_missing_ok(self, fake_root):
        sources, errors = [], []
        cv.collect_init(sources, errors)
        assert sources == [] and errors == []


# ---------------- collect_manifest ----------------
class TestCollectManifest:
    def _payload(self, **over):
        p = {
            "version": "1.2.3",
            "download_url": "https://example.com/x.exe",
            "sha256": "a" * 64,
        }
        p.update(over)
        return p

    def _write_manifest(self, root, payload):
        _write(root, "release/version.json", json.dumps(payload))

    def test_valid(self, fake_root):
        self._write_manifest(fake_root, self._payload())
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert errors == []
        assert sources == [("release/version.json version", "1.2.3")]

    def test_required_but_missing(self, fake_root):
        sources, errors = [], []
        cv.collect_manifest(True, sources, errors)
        assert any("version.json not found" in e for e in errors)

    def test_optional_missing_ok(self, fake_root):
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert sources == [] and errors == []

    def test_invalid_json(self, fake_root):
        _write(fake_root, "release/version.json", "{not json")
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert any("invalid JSON" in e for e in errors)

    def test_root_not_object(self, fake_root):
        _write(fake_root, "release/version.json", "[]")
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert any("not an object" in e for e in errors)

    def test_missing_version_field(self, fake_root):
        self._write_manifest(fake_root, {"download_url": "https://x"})
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert any("missing string field 'version'" in e for e in errors)

    def test_non_https_download_url(self, fake_root):
        self._write_manifest(fake_root,
                             self._payload(download_url="http://x"))
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert any("must be https" in e for e in errors)

    def test_non_https_mirror(self, fake_root):
        self._write_manifest(fake_root,
                             self._payload(download_url_mirror="http://x"))
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert any("download_url_mirror" in e for e in errors)

    def test_valid_mirror_https(self, fake_root):
        self._write_manifest(
            fake_root,
            self._payload(download_url_mirror="https://m.example.com/x"))
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert errors == []

    def test_short_sha(self, fake_root):
        self._write_manifest(fake_root, self._payload(sha256="abc"))
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert any("sha256" in e for e in errors)

    def test_uppercase_sha_accepted(self, fake_root):
        # 源码对 sha.lower() 做匹配，大写十六进制应通过
        self._write_manifest(fake_root, self._payload(sha256="A" * 64))
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert errors == []

    def test_valid_label_uses_posix_separator(self, fake_root):
        """跨平台一致：sources 标签不应含 os.sep（Windows 上是 '\\'）。"""
        import os
        self._write_manifest(fake_root, self._payload())
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert errors == []
        label = sources[0][0]
        assert label == "release/version.json version"
        assert "\\" not in label
        if os.sep != "/":
            assert os.sep not in label

    # ---- download_url_mirrors（多镜像新格式）----
    def test_mirrors_list_valid(self, fake_root):
        self._write_manifest(
            fake_root,
            self._payload(download_url_mirrors=[
                "https://m1.example.com/x", "https://m2.example.com/x"]))
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert errors == []

    def test_mirrors_not_list(self, fake_root):
        self._write_manifest(
            fake_root, self._payload(download_url_mirrors="https://x"))
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert any("must be a list" in e for e in errors)

    def test_mirrors_element_non_https(self, fake_root):
        self._write_manifest(
            fake_root,
            self._payload(download_url_mirrors=[
                "https://ok", "http://bad"]))
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert any("download_url_mirrors[1]" in e for e in errors)

    def test_mirror_inconsistent_with_mirrors_first(self, fake_root):
        """单数字段必须等于 mirrors[0]，否则旧/新客户端走不同源。"""
        self._write_manifest(fake_root, self._payload(
            download_url_mirror="https://a",
            download_url_mirrors=["https://b", "https://a"]))
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert any("不一致" in e for e in errors)

    def test_release_notes_non_string(self, fake_root):
        self._write_manifest(fake_root, self._payload(release_notes=123))
        sources, errors = [], []
        cv.collect_manifest(False, sources, errors)
        assert any("release_notes must be a string" in e for e in errors)


# ---------------- main ----------------
class TestMain:
    def _write_all(self, root, *, pyproject="1.0.0", updater="1.0.0",
                   installer="1.0.0"):
        _write(root, cv.PYPROJECT_REL,
               f'[project]\nversion = "{pyproject}"\n')
        _write(root, cv.UPDATER_PY_REL,
               f'CURRENT_VERSION = "{updater}"\n')
        _write(root, cv.INSTALLER_ISS_REL,
               f'#define MyAppVersion "{installer}"\n')

    def test_all_agree(self, fake_root, monkeypatch, capsys):
        monkeypatch.delenv("VER", raising=False)
        self._write_all(fake_root)
        assert cv.main([]) == 0
        assert "OK" in capsys.readouterr().out

    def test_mismatch(self, fake_root, monkeypatch):
        monkeypatch.delenv("VER", raising=False)
        self._write_all(fake_root, pyproject="1.0.0", updater="1.0.1")
        assert cv.main([]) == 1

    def test_expected_matches(self, fake_root, monkeypatch):
        self._write_all(fake_root)
        monkeypatch.setenv("VER", "1.0.0")
        assert cv.main([]) == 0

    def test_expected_mismatch(self, fake_root, monkeypatch):
        self._write_all(fake_root)
        monkeypatch.setenv("VER", "2.0.0")
        assert cv.main([]) == 1

    def test_expected_invalid_format(self, fake_root, monkeypatch):
        self._write_all(fake_root)
        monkeypatch.setenv("VER", "not-a-version")
        assert cv.main([]) == 1

    def test_manifest_required_without_file(self, fake_root, monkeypatch):
        monkeypatch.delenv("VER", raising=False)
        self._write_all(fake_root)
        assert cv.main(["--manifest-required"]) == 1

# ===================== verify_publisher_sync =====================
def test_publisher_mismatch(fake_root):
    _write(fake_root, cv.INSTALLER_ISS_REL,
           '#define MyAppVersion "1.0.0"\n'
           '#define MyAppPublisher "someone_else"\n')
    errors = []
    cv.verify_publisher_sync(errors)
    assert any("MyAppPublisher" in e for e in errors)


def test_publisher_match_ok(fake_root):
    _write(fake_root, cv.INSTALLER_ISS_REL,
           '#define MyAppVersion "1.0.0"\n'
           f'#define MyAppPublisher "{cv.APP_PUBLISHER}"\n')
    errors = []
    cv.verify_publisher_sync(errors)
    assert errors == []


# ===================== --verify-sha256 =====================
def _setup_release_assets(root, *, tampered=False):
    """在 root 下造 release/exe + release/version.json，返回 (exe, sha)。"""
    import hashlib
    exe = root / cv._EXE_REL
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"fake exe content")
    sha = hashlib.sha256(b"fake exe content").hexdigest()
    _write(root, "release/version.json", json.dumps({
        "version": "1.0.0",
        "download_url": "https://x.example.com/a.exe",
        "sha256": ("0" * 64) if tampered else sha,
    }))
    return exe, sha


def _write_three_sources(root, version="1.0.0"):
    _write(root, cv.PYPROJECT_REL,
           f'[project]\nname = "x"\nversion = "{version}"\n')
    _write(root, cv.UPDATER_PY_REL,
           f'CURRENT_VERSION = "{version}"\n')
    _write(root, cv.INSTALLER_ISS_REL,
           f'#define MyAppVersion "{version}"\n')


def test_verify_sha256_ok(fake_root, monkeypatch):
    monkeypatch.delenv("VER", raising=False)
    _write_three_sources(fake_root)
    _setup_release_assets(fake_root)
    assert cv.main(["--verify-sha256"]) == 0


def test_verify_sha256_mismatch(fake_root, monkeypatch):
    monkeypatch.delenv("VER", raising=False)
    _write_three_sources(fake_root)
    _setup_release_assets(fake_root, tampered=True)
    assert cv.main(["--verify-sha256"]) == 1


def test_verify_sha256_missing_exe(fake_root, monkeypatch):
    """启用 --verify-sha256 后 exe 缺失必须报错（不能静默通过）。"""
    monkeypatch.delenv("VER", raising=False)
    _write_three_sources(fake_root)
    # 只造 manifest，不造 exe
    _write(fake_root, "release/version.json", json.dumps({
        "version": "1.0.0",
        "download_url": "https://x.example.com/a.exe",
        "sha256": "a" * 64,
    }))
    assert cv.main(["--verify-sha256"]) == 1


# ===================== _sha256_of_file 与 patch_updater 一致性 =====================
def test_sha256_consistent_with_patch_updater(tmp_path):
    """两处独立实现必须对同一文件给出相同哈希。"""
    from scripts import patch_updater as pu
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello world")
    assert cv._sha256_of_file(f) == pu._sha256_of_file(f)
  

# ===================== --verify-sha256：manifest sha256 字段异常 =====================
@pytest.mark.parametrize("bad_sha", [
    "abc",              # 长度不对
    "Z" * 64,           # 长度对但非 hex
    123,                # 非 str
    None,               # 非 str
])
def test_verify_sha256_malformed_manifest(fake_root, monkeypatch, bad_sha):
    """--verify-sha256 在 manifest sha256 字段异常时必须失败。

    覆盖 verify_manifest_sha256 的两个分支：
      - collect_manifest 里的 `sha256 must be 64 hex chars`
      - verify_manifest_sha256 里的 `sha256 missing or malformed`
    两者任一报错都让 main 返回 1。
    """
    monkeypatch.delenv("VER", raising=False)
    _write_three_sources(fake_root)

    exe = fake_root / cv._EXE_REL
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"fake content")

    _write(fake_root, "release/version.json", json.dumps({
        "version": "1.0.0",
        "download_url": "https://x.example.com/a.exe",
        "sha256": bad_sha,
    }))

    assert cv.main(["--verify-sha256"]) == 1


def test_verify_sha256_uppercase_accepted(fake_root, monkeypatch):
    """大写十六进制 sha256 在 collect_manifest 被接受（sha.lower()）。

    verify_manifest_sha256 也做 lower() 后再比较，实际哈希是小写，
    因此实际不会走到这里；本测试锁定"大写输入不因格式被拒"。
    """
    import hashlib
    monkeypatch.delenv("VER", raising=False)
    _write_three_sources(fake_root)

    content = b"fake content"
    exe = fake_root / cv._EXE_REL
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(content)
    sha_lower = hashlib.sha256(content).hexdigest()

    _write(fake_root, "release/version.json", json.dumps({
        "version": "1.0.0",
        "download_url": "https://x.example.com/a.exe",
        "sha256": sha_lower.upper(),
    }))
    assert cv.main(["--verify-sha256"]) == 0
