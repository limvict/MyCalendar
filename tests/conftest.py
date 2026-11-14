# coding: utf-8
"""共享 fixture：路径隔离、ConfigManager 单例重置、语言重置。"""
from __future__ import annotations

import tempfile

import pytest

from desktop_calendar.config import manager as mgr_module
from desktop_calendar.config import i18n


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    hc_path = tmp_path / "holiday_cache.json"

    monkeypatch.setattr(mgr_module, "get_config_path", lambda: str(cfg_path))
    monkeypatch.setattr(mgr_module, "get_holiday_cache_path",
                        lambda: str(hc_path))

    # 考勤数据隔离：AttendanceStore._default_path 走 get_app_data_dir()，
    # 不隔离会读写真实用户目录下的 attendance.json。
    from desktop_calendar.core import attendance as att_mod
    monkeypatch.setattr(att_mod, "get_app_data_dir", lambda: str(tmp_path))

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


@pytest.fixture
def tmp_tmpdir(tmp_path, monkeypatch):
    """把 tempfile.gettempdir 重定向到 tmp_path/tmp。
    """
    tdir = tmp_path / "tmp"
    tdir.mkdir(parents=True, exist_ok=True)

    def _fake_gettempdir():
        return str(tdir)

    monkeypatch.setattr(tempfile, "gettempdir", _fake_gettempdir)
    return tdir


@pytest.fixture(autouse=True)
def reset_i18n():
    """每个测试前后清理 tr() 格式化失败记录，防止用例间相互污染。"""
    try:
        yield
    finally:
        i18n.clear_format_failures()


@pytest.fixture
def app_logger_propagate():
    import logging
    logger = logging.getLogger("MyCalendarApp")
    old = logger.propagate
    logger.propagate = True
    try:
        yield logger
    finally:
        logger.propagate = old


@pytest.fixture
def opacity_quantized():
    """Qt windowOpacity 8-bit alpha 量化的容差断言。

    用法：
        assert w.windowOpacity() == opacity_quantized(0.92)
    """
    def _approx(target: float):
        return pytest.approx(target, abs=1.0 / 255.0 + 1e-9)
    return _approx