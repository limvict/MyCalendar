# coding: utf-8
"""load_theme 类型归一化回归测试。

覆盖 bug：脏 theme.json（字符串数字、bool 冒充 int、非法字符串）
穿透到 setPointSize/setFixedSize/int() 等构造期调用，启动崩溃。

修复：load_theme 按 DEFAULT_THEME[key] 默认值类型归一化，
非法值保留默认并记录 warning。
"""
import json

import pytest

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.ui.style_manager import load_theme, _coerce_theme_value


# ===========================================================================
# _coerce_theme_value 单元测试
# ===========================================================================
class TestCoerceThemeValue:
    @pytest.mark.parametrize("key,raw,expected", [
        # int 键
        ("font_size", "13", 13),
        ("font_size", 13.7, 13),
        ("font_size", "abc", None),
        ("font_size", True, None),          # bool 是 int 子类，必须拦
        ("font_size", False, None),
        ("font_size", None, None),
        ("font_size", [13], None),
        # str 键
        ("font_family", "微软雅黑,SimHei,sans-serif", "微软雅黑,SimHei,sans-serif"),
        ("font_family", 123, None),
        ("font_family", None, None),
        # 主题里的 int 尺寸
        ("shadow_size", "0", 0),
        ("window_width", "440", 440),
        ("dot_size", "6.5", None),          # int("6.5") 失败 → 默认
        ("tag_size", "14", 14),
    ])
    def test_coerce(self, key, raw, expected):
        assert _coerce_theme_value(key, raw) == expected

    def test_int_key_returns_int_type(self):
        # 断言类型而非仅值：13.7 转 int 后必须是 int，不能是 float
        assert type(_coerce_theme_value("font_size", 13.7)) is int


# ===========================================================================
# load_theme 集成测试：脏文件不崩溃、正确回退
# ===========================================================================
def _write_theme(tmp_path, data):
    p = tmp_path / "theme.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_load_theme_dirty_types_no_crash(tmp_path):
    """核心回归：脏值不应让 load_theme 抛异常，且合法值被救回。"""
    path = _write_theme(tmp_path, {
        "font_size": "15",           # 救回为 15
        "window_width": "500",       # 救回为 500
        "shadow_size": "0",          # 救回为 0（否则 `"0" > 0` TypeError）
        "dot_size": "abc",           # 非法 → 默认
        "font_family": 123,          # 非法 → 默认
        "unknown_key": "ignored",    # 未知键忽略
    })
    theme = load_theme(path)

    assert theme["font_size"] == 15
    assert type(theme["font_size"]) is int
    assert theme["window_width"] == 500
    assert theme["shadow_size"] == 0
    assert theme["dot_size"] == DEFAULT_THEME["dot_size"]
    assert theme["font_family"] == DEFAULT_THEME["font_family"]
    assert "unknown_key" not in theme


def test_load_theme_all_defaults_on_bad_json(tmp_path):
    """JSON 语法错误 → 整体回退默认，不崩溃。"""
    p = tmp_path / "theme.json"
    p.write_text("{not json", encoding="utf-8")
    theme = load_theme(str(p))
    assert theme == dict(DEFAULT_THEME)


def test_load_theme_missing_file(tmp_path):
    theme = load_theme(str(tmp_path / "nope.json"))
    assert theme == dict(DEFAULT_THEME)


def test_load_theme_root_not_dict(tmp_path):
    """根节点是 list / 数字 → 回退默认。"""
    for bad in ([1, 2, 3], 42, "str", None):
        p = tmp_path / "theme.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        theme = load_theme(str(p))
        assert theme == dict(DEFAULT_THEME), f"根节点 {bad!r} 未回退默认"


def test_load_theme_none_value_keeps_default(tmp_path):
    """显式 None 值保留默认（原逻辑，防回归）。"""
    path = _write_theme(tmp_path, {"font_size": None, "bg_main": None})
    theme = load_theme(path)
    assert theme["font_size"] == DEFAULT_THEME["font_size"]
    assert theme["bg_main"] == DEFAULT_THEME["bg_main"]


def test_load_theme_valid_values_override(tmp_path):
    """合法值必须覆盖默认（防过度归一化把好值也丢了）。"""
    path = _write_theme(tmp_path, {
        "font_size": 18,
        "bg_main": "#000000",
        "window_width": 600,
    })
    theme = load_theme(path)
    assert theme["font_size"] == 18
    assert theme["bg_main"] == "#000000"
    assert theme["window_width"] == 600


def test_theme_keys_never_missing(tmp_path):
    """任何输入下返回的 theme 必须包含 DEFAULT_THEME 全部键且类型一致。"""
    path = _write_theme(tmp_path, {
        k: "garbage" for k in DEFAULT_THEME
    })
    theme = load_theme(path)
    assert set(theme) == set(DEFAULT_THEME)
    for k, v in theme.items():
        assert type(v) is type(DEFAULT_THEME[k]), (
            f"key={k!r} 类型 {type(v).__name__} != "
            f"{type(DEFAULT_THEME[k]).__name__}")


def test_boolean_like_int_rejected(tmp_path):
    """True 被写成 font_size 时不能变成 1（bool 是 int 子类）。"""
    path = _write_theme(tmp_path, {"font_size": True})
    theme = load_theme(path)
    assert theme["font_size"] == DEFAULT_THEME["font_size"]
    assert theme["font_size"] != 1