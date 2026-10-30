# coding: utf-8
"""_version 补充：write_version_info 输出格式与路径。"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from scripts. _version import (  # noqa: E402
    APP_EXE_NAME, APP_INTERNAL_NAME, APP_PUBLISHER, APP_DISPLAY_NAME,
    VersionPatchError, write_version_info,
)


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