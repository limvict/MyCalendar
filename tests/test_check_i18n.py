# coding: utf-8
"""check_i18n.validate_source_keys：扫描规则 + 空扫描检测。"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from check_i18n import (  # noqa: E402
    validate_dict_i18n_keys, validate_source_keys,
    validate_tr_format_keys,
)

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


def test_tr_format_missing_kwarg_detected(tmp_path):
    (tmp_path / "a.py").write_text(
        "def f():\n"
        "    return tr('memorial.warn_solar_day').format(month=1, day=2)\n",
        encoding="utf-8")
    rep = validate_tr_format_keys(tmp_path, strict=False)
    assert rep["missing"]["memorial.warn_solar_day"] == ["max_day"]


def test_tr_format_kw_in_tr_call_detected(tmp_path):
    (tmp_path / "a.py").write_text(
        "def f():\n"
        "    return tr('memorial.warn_solar_day', month=1, day=2)\n",
        encoding="utf-8")
    rep = validate_tr_format_keys(tmp_path, strict=False)
    assert rep["missing"]["memorial.warn_solar_day"] == ["max_day"]


def test_tr_format_complete_passes(tmp_path):
    (tmp_path / "a.py").write_text(
        "def f():\n"
        "    return tr('memorial.warn_solar_day')"
        ".format(month=1, day=2, max_day=28)\n",
        encoding="utf-8")
    rep = validate_tr_format_keys(tmp_path, strict=False)
    assert rep["missing"] == {}
    assert rep["scanned"] == 1


def test_tr_format_kwargs_expansion_skipped(tmp_path):
    """** 展开无法静态分析，跳过而非误报。"""
    (tmp_path / "a.py").write_text(
        "def f(kw):\n"
        "    return tr('memorial.warn_solar_day').format(**kw)\n",
        encoding="utf-8")
    rep = validate_tr_format_keys(tmp_path, strict=False)
    assert rep["missing"] == {}


def test_tr_format_unknown_key_ignored(tmp_path):
    """ZH_CN 里没有的 key 不在此处报，由 validate_source_keys 负责。"""
    (tmp_path / "a.py").write_text(
        "def f():\n    return tr('nope.missing').format(x=1)\n",
        encoding="utf-8")
    rep = validate_tr_format_keys(tmp_path, strict=False)
    assert rep["missing"] == {}


# ===================== validate_dict_i18n_keys =====================
def test_dict_i18n_basic(tmp_path):
    _write(tmp_path, "a.py", 'REASON_I18N = {"x": "app.title"}\n')
    rep = validate_dict_i18n_keys(tmp_path)
    assert rep["scanned"] == 1
    assert rep["missing"] == []


def test_dict_i18n_missing(tmp_path):
    _write(tmp_path, "a.py", '_MY_I18N_MAP = {"k": "nope.missing"}\n')
    rep = validate_dict_i18n_keys(tmp_path)
    assert "nope.missing" in rep["missing"]
    assert "nope.missing" in rep["locations"]


def test_dict_i18n_annassign(tmp_path):
    """带类型注解的赋值也要扫描（ast.AnnAssign 分支）。"""
    _write(tmp_path, "a.py",
           'X_I18N_Y: dict[str, str] = {"k": "app.title"}\n')
    assert validate_dict_i18n_keys(tmp_path)["scanned"] == 1


def test_dict_i18n_skips_non_i18n_name(tmp_path):
    """变量名不含 I18N 的 dict 不扫描。"""
    _write(tmp_path, "a.py", 'OTHER_MAP = {"k": "app.title"}\n')
    assert validate_dict_i18n_keys(tmp_path)["scanned"] == 0


def test_dict_i18n_skips_non_str_value(tmp_path):
    """value 为数字 / tuple / 嵌套 dict 时全部跳过。"""
    _write(tmp_path, "a.py",
           'X_I18N = {"n": 1, "t": ("a",), "d": {"k": "v"}}\n')
    assert validate_dict_i18n_keys(tmp_path)["scanned"] == 0


def test_dict_i18n_skips_empty_string(tmp_path):
    _write(tmp_path, "a.py", 'X_I18N = {"k": ""}\n')
    assert validate_dict_i18n_keys(tmp_path)["scanned"] == 0


def test_dict_i18n_strict_missing_raises(tmp_path):
    _write(tmp_path, "a.py", 'X_I18N = {"k": "nope"}\n')
    with pytest.raises(KeyError):
        validate_dict_i18n_keys(tmp_path, strict=True)

# ===================== validate_source_keys strict 分支 =====================
def test_source_strict_missing_raises(tmp_path):
    _write(tmp_path, "a.py", 'tr("nope.missing")\n')
    with pytest.raises(KeyError):
        validate_source_keys(tmp_path, strict=True)


def test_source_strict_empty_raises(tmp_path):
    with pytest.raises(RuntimeError):
        validate_source_keys(tmp_path, strict=True)


def test_source_strict_empty_allowed(tmp_path):
    """allow_empty=True 是单测豁免口，严格模式下也不抛。"""
    validate_source_keys(tmp_path, strict=True, allow_empty=True)
    
# ===================== 真实 src 校验（防 CI 漏跑 scripts/check_i18n.py） =====================
def test_real_src_has_no_missing_keys():
    """对真实 src/desktop_calendar 跑三项扫描，锁定当前工作区干净。

    与 scripts/check_i18n.py CLI 的差别：pytest 默认跑 tests/，
    本测试确保"新增 tr() 忘加翻译"在本地 pytest 就暴露，
    而不是等 CI 单独跑脚本才失败。
    """
    real_src = (
        Path(__file__).resolve().parent.parent / "src" / "desktop_calendar"
    )
    assert real_src.is_dir(), f"扫描根目录不存在：{real_src}"

    # ---- 1. tr("字面量") ----
    rep = validate_source_keys(real_src, strict=False)
    assert rep["parse_errors"] == [], (
        f"源码解析失败 {len(rep['parse_errors'])} 个文件："
        f"{rep['parse_errors'][:3]}"
    )
    assert rep["missing"] == [], (
        f"源码 tr() 缺失 key：{rep['missing']}"
    )
    assert rep["scanned"] > 0, "扫描到 0 处 tr()，路径可能错误"

    # ---- 2. *I18N* 字典值 ----
    rep = validate_dict_i18n_keys(real_src, strict=False)
    assert rep["parse_errors"] == [], rep["parse_errors"]
    assert rep["missing"] == [], (
        f"i18n 字典值缺失 key：{rep['missing']}"
    )

    # ---- 3. tr().format() / tr(..., **kw) 占位符覆盖 ----
    rep = validate_tr_format_keys(real_src, strict=False)
    assert rep["parse_errors"] == [], rep["parse_errors"]
    assert rep["missing"] == {}, (
        f"tr().format() 缺占位符：{rep['missing']}"
    )
