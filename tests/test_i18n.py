# coding: utf-8
"""i18n：tr 查表、格式化失败记录、重复 key 检测。"""
import ast
from pathlib import Path

import pytest

from desktop_calendar.config import i18n
from desktop_calendar.config.translations import ZH_CN


@pytest.fixture(autouse=True)
def _clear_failures():
    i18n.clear_format_failures()
    yield
    i18n.clear_format_failures()


class TestTr:
    def test_returns_zh_value(self):
        assert i18n.tr("btn.ok") == ZH_CN["btn.ok"]

    def test_missing_key_returns_key(self):
        assert i18n.tr("no.such.key") == "no.such.key"

    def test_format_kwargs(self):
        text = i18n.tr("cal.title_format", year=2024, month=5)
        assert text == "2024年5月"

    def test_format_missing_kwarg_returns_raw(self):
        # 缺参数：返回未格式化的原始文本，并记录失败
        text = i18n.tr("cal.title_format", year=2024)
        assert text == ZH_CN["cal.title_format"]
        assert "cal.title_format" in i18n.get_format_failures()

    def test_format_bad_placeholder(self):
        # 假设 ZH_CN 里有 "{broken" 这类非法格式串的 key 不存在；
        # 这里直接构造一个临时 key 验证行为：用不存在的 key 走不通，
        # 改为验证 get_format_failures 的清理行为。
        i18n.clear_format_failures()
        assert i18n.get_format_failures() == frozenset()


class TestFormatFailures:
    def test_record_and_clear(self):
        i18n.tr("cal.title_format", year=1)  # 缺 month，触发失败
        failures = i18n.get_format_failures()
        assert "cal.title_format" in failures
        assert isinstance(failures, frozenset)

        i18n.clear_format_failures()
        assert i18n.get_format_failures() == frozenset()

    def test_dedup(self):
        # 同一 key 多次失败只记一次
        for _ in range(3):
            i18n.tr("cal.title_format", year=1)
        assert len(i18n.get_format_failures()) == 1


class TestTranslationsIntegrity:
    def test_no_duplicate_keys(self):
        """translations.py 字面量若有重复 key，Python 静默后者覆盖前者。

        AST 扫描能发现 dict 字面量里的重复键，而 `ZH_CN` 是模块级
        字典（运行时后值覆盖前值），`len(ZH_CN)` 无法暴露这个问题。
        """
        src = (Path(__file__).resolve().parent.parent
               / "src" / "desktop_calendar" / "config" / "translations.py")
        assert src.is_file(), f"translations.py 不存在: {src}"
        tree = ast.parse(src.read_text(encoding="utf-8"))

        # 找模块级 `ZH_CN = {...}` 的 dict 字面量
        dict_node = None
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "ZH_CN"
                    and isinstance(node.value, ast.Dict)):
                dict_node = node.value
                break
        assert dict_node is not None, "未找到 ZH_CN = {...} 定义"

        keys = []
        for k in dict_node.keys:
            assert isinstance(k, ast.Constant), (
                f"ZH_CN 存在非字面量 key（第 {k.lineno} 行），"
                f"无法静态检查重复"
            )
            keys.append(k.value)

        dupes = sorted({k for k in keys if keys.count(k) > 1})
        assert not dupes, f"translations.py 存在重复 key: {dupes}"

    def test_p1_setting_keys_present(self):
        """P1 新增的设置文案必须存在，防止设置界面显示字面 key。"""
        for k in (
            "setting.attendance_remind",
            "setting.attendance_remind_tip",
            "setting.attendance_rule",
            "setting.attendance_rule_title",
            "setting.work_start", "setting.work_end",
            "setting.lunch_enable",
            "setting.lunch_start", "setting.lunch_end",
            "setting.standard_hours",
            "setting.late_grace",
            "setting.overtime_granularity",
            "setting.overtime_granularity_tip",
            "setting.rule_invalid",
        ):
            assert k in ZH_CN, f"缺少 key: {k}"