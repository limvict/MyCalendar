# coding: utf-8
"""scripts/_version：validate_ver、patch_all、write_version_info。"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from _version import (  # noqa: E402
    VersionPatchError, validate_ver, patch_all, write_version_info,
    UPDATER_PY_REL, INSTALLER_ISS_REL, PYPROJECT_REL,
    APP_EXE_NAME, APP_INTERNAL_NAME, APP_PUBLISHER, APP_DISPLAY_NAME,
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


class TestWriteVersionInfo:
    def test_creates_file_at_expected_path(self, tmp_path):
        out = write_version_info(tmp_path, "1.2.3")
        assert out == tmp_path / "build" / "version_info.txt"
        assert out.exists()

    def test_contains_four_part_version(self, tmp_path):
        content = write_version_info(tmp_path, "2.5.7").read_text(
            encoding="utf-8")
        assert "filevers=(2, 5, 7, 0)" in content
        assert "prodvers=(2, 5, 7, 0)" in content
        assert "'FileVersion', '2.5.7.0'" in content
        assert "'ProductVersion', '2.5.7.0'" in content

    def test_contains_metadata(self, tmp_path):
        content = write_version_info(tmp_path, "1.0.0").read_text(
            encoding="utf-8")
        assert APP_PUBLISHER in content
        assert APP_DISPLAY_NAME in content
        assert APP_INTERNAL_NAME in content
        assert APP_EXE_NAME in content

    def test_build_dir_created(self, tmp_path):
        assert not (tmp_path / "build").exists()
        write_version_info(tmp_path, "1.0.0")
        assert (tmp_path / "build").is_dir()

    def test_invalid_version_raises(self, tmp_path):
        with pytest.raises(VersionPatchError):
            write_version_info(tmp_path, "1.2")

    def test_write_failure_wrapped(self, tmp_path, monkeypatch):
        """写盘失败包装为 VersionPatchError。"""
        def boom(*a, **k):
            raise OSError(28, "No space left on device")
        monkeypatch.setattr(Path, "write_text", boom)
        with pytest.raises(VersionPatchError):
            write_version_info(tmp_path, "1.0.0")


def test_patch_all_reports_all_errors_at_once(tmp_path):
    """两阶段 plan 收集所有错误后一次性抛出，而非遇到第一个就退。

    用户修完 installer.iss 再跑，不必再发现 pyproject 也没匹配——
    错误信息必须两条都包含。
    """
    root = _make_root(tmp_path)
    (root / INSTALLER_ISS_REL).unlink()
    (root / PYPROJECT_REL).write_text("[tool.x]\n", encoding="utf-8")

    with pytest.raises(VersionPatchError) as ei:
        patch_all(root, "2.0.0")

    msg = str(ei.value)
    assert "file not found" in msg            # installer 缺失
    assert "[project].version not found" in msg   # pyproject 无匹配
