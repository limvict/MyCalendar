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
        assert sources == [("update_manager.py CURRENT_VERSION", "2.0.0")]

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