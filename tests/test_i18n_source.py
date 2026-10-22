# coding: utf-8
"""i18n 静态检查：语言包一致 + 源码 tr() 字面量 key 已定义。

纯 Python 测试，不依赖 Qt / QApplication，可在 offscreen 外直接跑。
"""
import os
import sys

import pytest

from desktop_calendar.config.i18n import validate_keys
from scripts.check_i18n import validate_source_keys

def test_package_keys_consistent():
    """各非默认语言相对 zh_CN：无 missing / extra / 占位符不一致。"""
    # strict=True 时存在不一致会抛 KeyError，pytest 直接捕获为失败
    validate_keys(strict=True)


def test_source_tr_keys_defined():
    """源码里 tr("字面量") 使用的 key 必须存在于语言包。

    回归保护：曾出现 tr("setting.memorial_mgr")（正确 key 为
    setting.manage_memorial），构造期显示字面量，只有切语言后
    才被 retranslate_ui 纠正。
    """
    rep = validate_source_keys(strict=False)
    missing = rep["missing"]
    if missing:
        lines = []
        for key, locs in sorted(missing.items()):
            where = ", ".join(f"{p}:{n}" for p, n in locs)
            lines.append(f"  {key!r}  {where}")
        pytest.fail(
            f"源码使用了未定义的 i18n key（共 {len(missing)} 个）：\n"
            + "\n".join(lines)
        )


def test_source_tr_keys_scan_not_empty():
    """扫描必须真的读到 tr() 调用。

    防御 validate_source_keys 的 root_dir 因目录调整而扫到空目录，
    让上面两个测试变成永远通过的空壳。
    """
    from desktop_calendar.config import i18n as i18n_mod
    from scripts.check_i18n import _iter_source_tr_keys

    root = os.path.dirname(
        os.path.dirname(os.path.abspath(i18n_mod.__file__)))
    assert os.path.isdir(root), f"扫描根目录不存在: {root}"
    found = list(_iter_source_tr_keys(root))
    assert len(found) > 50, (
        f"仅扫描到 {len(found)} 处 tr() 字面量调用，"
        f"疑似 root_dir 配置错误: {root}"
    )