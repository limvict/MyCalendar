# coding: utf-8
"""check_i18n.validate_source_keys：扫描规则 + 空扫描检测。"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from check_i18n import validate_source_keys  # noqa: E402


def _write(root: Path, name: str, content: str) -> None:
    (root / name).write_text(content, encoding="utf-8")


def test_detects_missing_key(tmp_path):
    _write(tmp_path, "a.py", 'tr("app.title")\ntr("nope.missing")\n')
    report = validate_source_keys(tmp_path)
    assert "nope.missing" in report["missing"]
    assert "app.title" not in report["missing"]
    assert report["scanned"] == 2


def test_known_key_not_reported(tmp_path):
    _write(tmp_path, "a.py", 'tr("app.title")\n')
    assert validate_source_keys(tmp_path)["missing"] == []


def test_empty_dir_flagged(tmp_path):
    report = validate_source_keys(tmp_path)
    assert report["empty"] is True
    assert report["scanned"] == 0


def test_skips_self_tr(tmp_path):
    """self.tr(...) 是 QObject.tr，不是 i18n key。"""
    _write(tmp_path, "a.py",
           'class X:\n    def f(self):\n        self.tr("whatever")\n')
    assert validate_source_keys(tmp_path)["scanned"] == 0


def test_skips_fstring(tmp_path):
    _write(tmp_path, "a.py", 'key = "x"\ntr(f"{key}")\n')
    assert validate_source_keys(tmp_path)["scanned"] == 0


def test_parse_error_recorded(tmp_path):
    _write(tmp_path, "bad.py", "def f(:\n    pass\n")
    report = validate_source_keys(tmp_path)
    assert report["parse_errors"]