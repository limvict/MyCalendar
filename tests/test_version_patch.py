# coding: utf-8
"""_version.patch_all：校验 + 两阶段原子性。"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from _version import (  # noqa: E402
    VersionPatchError, validate_ver, patch_all,
    UPDATER_PY_REL, INSTALLER_ISS_REL, PYPROJECT_REL,
)


def _make_root(tmp_path, *, updater="1.0.0", installer="1.0.0",
               pyproject="1.0.0"):
    root = tmp_path
    (root / UPDATER_PY_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / UPDATER_PY_REL).write_text(
        f'CURRENT_VERSION = "{updater}"\n', encoding="utf-8")
    (root / INSTALLER_ISS_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / INSTALLER_ISS_REL).write_text(
        f'#define MyAppVersion "{installer}"\n', encoding="utf-8")
    (root / PYPROJECT_REL).write_text(
        f'[project]\nname = "x"\nversion = "{pyproject}"\n',
        encoding="utf-8")
    return root


class TestValidateVer:
    @pytest.mark.parametrize("ver", ["1.2.3", "  1.2.3  ", "0.0.0"])
    def test_valid(self, ver):
        assert validate_ver(ver) == ver.strip()

    @pytest.mark.parametrize("ver", ["1.2", "v1.2.3", "", "1.2.3.4"])
    def test_invalid(self, ver):
        with pytest.raises(VersionPatchError):
            validate_ver(ver)

    def test_non_str(self):
        with pytest.raises(VersionPatchError):
            validate_ver(123)


def test_patch_all_updates_three_sources(tmp_path):
    root = _make_root(tmp_path)
    results = patch_all(root, "2.0.0")
    assert all(changed for _, changed in results)
    assert 'CURRENT_VERSION = "2.0.0"' in (root / UPDATER_PY_REL).read_text()
    assert '#define MyAppVersion "2.0.0"' in (root / INSTALLER_ISS_REL).read_text()
    assert 'version = "2.0.0"' in (root / PYPROJECT_REL).read_text()


def test_patch_all_unchanged_when_same_version(tmp_path):
    root = _make_root(tmp_path)
    results = patch_all(root, "1.0.0")
    assert all(not changed for _, changed in results)


def test_patch_all_atomic_on_missing_file(tmp_path):
    """一个文件缺失时不得写任何文件（两阶段：先 plan 后写）。"""
    root = _make_root(tmp_path)
    (root / INSTALLER_ISS_REL).unlink()
    with pytest.raises(VersionPatchError):
        patch_all(root, "2.0.0")
    # updater 未被改写
    assert 'CURRENT_VERSION = "1.0.0"' in (root / UPDATER_PY_REL).read_text()


def test_patch_all_atomic_on_regex_miss(tmp_path):
    """pyproject 缺 [project].version 时不得写任何文件。"""
    root = _make_root(tmp_path)
    (root / PYPROJECT_REL).write_text(
        '[tool.other]\nversion = "1.0.0"\n', encoding="utf-8")
    with pytest.raises(VersionPatchError):
        patch_all(root, "2.0.0")
    assert 'CURRENT_VERSION = "1.0.0"' in (root / UPDATER_PY_REL).read_text()