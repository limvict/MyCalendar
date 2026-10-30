# coding: utf-8
"""共享 fixture：路径隔离、ConfigManager 单例重置、语言重置。"""
from __future__ import annotations

import pytest

from desktop_calendar.config import manager as mgr_module
from desktop_calendar.config import i18n
from desktop_calendar.infrastructure.network import update_manager as um_module


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """把所有落盘路径重定向到 tmp_path。

    同时 patch manager 模块与 update_manager 模块各自的 get_config_path
    —— 两个模块都是 `from X import get_config_path` 形式的绑定，
    patch 一处不会穿透另一处。

    _state_file_path：update_manager 的升级 state 文件路径。若实现
    从 get_config_path 派生，patch 是冗余的；若实现是独立路径（如
    基于 __file__），不 patch 会写到真实目录。raising=False 兜底
    兼容"模块暂未定义该函数"的过渡期。
    """
    cfg_path = tmp_path / "config.json"
    hc_path = tmp_path / "holiday_cache.json"
    state_path = tmp_path / "update_state"

    monkeypatch.setattr(mgr_module, "get_config_path", lambda: str(cfg_path))
    monkeypatch.setattr(mgr_module, "get_holiday_cache_path",
                        lambda: str(hc_path))
    monkeypatch.setattr(um_module, "get_config_path", lambda: str(cfg_path))
    monkeypatch.setattr(um_module, "_state_file_path",
                        lambda: str(state_path), raising=False)

    return tmp_path, cfg_path, hc_path


@pytest.fixture
def fresh_config_manager(isolated_paths):
    """构造一个独立的 ConfigManager 实例。

    重置类级别 _instance，避免与模块导入时已构造的 config 单例混淆。
    """
    old = mgr_module.ConfigManager._instance
    mgr_module.ConfigManager._instance = None
    try:
        yield mgr_module.ConfigManager()
    finally:
        mgr_module.ConfigManager._instance = old


@pytest.fixture(autouse=True)
def reset_i18n():
    """每个测试前后都恢复到 zh_CN，防止用例间相互污染。"""
    old_lang = i18n.get_language()
    i18n.set_language("zh_CN")
    yield
    try:
        i18n.set_language(old_lang)
    except Exception:
        pass