# coding: utf-8
"""config_normalizer.normalize_memorial_days 单测。

P2-1 后归一化责任从 ConfigManager 迁到本模块。本文件直接测
归一化逻辑，覆盖边界场景，不依赖 Qt / QApplication。
"""
import pytest

from desktop_calendar.core.memorial import (
    normalize_memorial_days,
)


class TestNonListInput:
    """非 list 输入统一返回 ([], 0)。"""

    @pytest.mark.parametrize("raw", [None, "", "not a list", 123, 4.5, {}, (1, 2)])
    def test_returns_empty_on_non_list(self, raw):
        result, skipped = normalize_memorial_days(raw)
        assert result == []
        assert skipped == 0


class TestEmptyList:
    def test_empty_returns_empty(self):
        result, skipped = normalize_memorial_days([])
        assert result == []
        assert skipped == 0


class TestAllDirty:
    """全脏数据：全部跳过，返回 ([], N)。"""

    def test_non_dict_items_all_skipped(self):
        result, skipped = normalize_memorial_days([1, "x", None, [1, 2]])
        assert result == []
        assert skipped == 4

    def test_normalize_failure_counted_as_skipped(self, monkeypatch):
        """normalize_memorial 抛异常时计入 skipped，不中断整体。"""
        import desktop_calendar.core.memorial as mod

        def _boom(_item):
            raise ValueError("boom")

        monkeypatch.setattr(mod, "normalize_memorial", _boom)

        result, skipped = normalize_memorial_days([{"name": "a"}])
        assert result == []
        assert skipped == 1


class TestAllValid:
    """全正常数据：全部保留，skipped == 0。"""

    def test_solar_memorial(self):
        raw = [{
            "name": "元旦",
            "type": "solar",
            "month": 1,
            "day": 1,
            "repeat_type": "year",
            "advance_days": 0,
            "enabled": True,
        }]
        result, skipped = normalize_memorial_days(raw)
        assert skipped == 0
        assert len(result) == 1
        assert result[0]["name"] == "元旦"
        assert result[0]["type"] == "solar"

    def test_empty_dict_gets_defaults(self):
        """空 dict 是合法的——normalize_memorial 会给默认值。"""
        result, skipped = normalize_memorial_days([{}])
        assert skipped == 0
        assert len(result) == 1
        # normalize_memorial 的默认值
        assert result[0]["type"] == "solar"
        assert result[0]["repeat_type"] == "year"
        assert result[0]["enabled"] is True

    def test_preserves_order(self):
        raw = [
            {"name": "A", "type": "solar", "month": 1, "day": 1},
            {"name": "B", "type": "solar", "month": 2, "day": 2},
            {"name": "C", "type": "solar", "month": 3, "day": 3},
        ]
        result, skipped = normalize_memorial_days(raw)
        assert skipped == 0
        assert [r["name"] for r in result] == ["A", "B", "C"]


class TestMixed:
    """混合数据：脏跳过，正常保留，顺序不变。"""

    def test_mixed_keeps_valid_only(self):
        raw = [
            1,
            {"name": "A", "type": "solar", "month": 1, "day": 1},
            "bad",
            {"name": "B", "type": "lunar", "month": 8, "day": 15},
            None,
        ]
        result, skipped = normalize_memorial_days(raw)
        assert skipped == 3
        assert [r["name"] for r in result] == ["A", "B"]

    def test_one_failure_does_not_stop_others(self, monkeypatch):
        """单条 normalize 失败不影响后续条目。"""
        import desktop_calendar.core.memorial as mod

        calls = []

        def _fake_normalize(item):
            calls.append(item.get("name"))
            if item.get("name") == "bad":
                raise ValueError("boom")
            return {**item, "type": "solar", "repeat_type": "year",
                    "enabled": True}

        monkeypatch.setattr(mod, "normalize_memorial", _fake_normalize)

        raw = [
            {"name": "good1"},
            {"name": "bad"},
            {"name": "good2"},
        ]
        result, skipped = normalize_memorial_days(raw)
        assert calls == ["good1", "bad", "good2"]
        assert skipped == 1
        assert [r["name"] for r in result] == ["good1", "good2"]


class TestIdempotent:
    """重复调用不应改变已归一化的结果（内容一致）。"""

    def test_repeated_call_stable(self):
        raw = [
            {"name": "A", "type": "solar", "month": 1, "day": 1},
            {"name": "B", "type": "lunar", "month": 8, "day": 15},
        ]
        first, _ = normalize_memorial_days(raw)
        second, _ = normalize_memorial_days(first)
        assert first == second


class TestOriginalNotMutated:
    """输入不应被原地修改（返回的是新列表）。"""

    def test_input_dict_not_mutated(self):
        item = {"name": "A", "type": "solar", "month": 1, "day": 1}
        original = dict(item)
        raw = [item]
        normalize_memorial_days(raw)
        # item 本身不应被改
        assert item == original
        # raw 列表也不应被改
        assert raw == [item]