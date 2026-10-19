# coding: utf-8
"""pytest 全局配置。

  - 强制 Qt 离屏模式（必须在 import PyQt6 前设置）；
  - 隔离配置/日志目录，避免测试污染真实用户目录；
  - 把项目根目录加入 sys.path，保证 `from app import ...` 可直接用；
  - 全局封杀模态弹窗，避免 offscreen 下 .exec() 永久阻塞。
"""
import os
import sys
import tempfile

# --- Qt 离屏模式 ---
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# --- 隔离用户目录 ---
_TMP_HOME = tempfile.mkdtemp(prefix="calendar_tests_")
os.environ["APPDATA"] = _TMP_HOME
os.environ["XDG_DATA_HOME"] = _TMP_HOME
os.environ["HOME"] = _TMP_HOME
os.environ["USERPROFILE"] = _TMP_HOME  # Windows HOME
os.environ["MYCALENDAR_LOG_DIR"] = os.path.join(_TMP_HOME, "logs")

# --- 项目根加入 sys.path ---
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest


def pytest_sessionfinish(session, exitstatus):
    """整场跑完后清理临时目录。"""
    import shutil
    shutil.rmtree(_TMP_HOME, ignore_errors=True)


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _kill_modals(monkeypatch):
    """封杀所有 QMessageBox 弹窗，避免 offscreen 下 .exec() 永久阻塞。"""
    from PyQt6.QtWidgets import QMessageBox

    NOOP = lambda *a, **k: None                      # noqa: E731
    YES = lambda *a, **k: QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "information", NOOP)
    monkeypatch.setattr(QMessageBox, "warning", NOOP)
    monkeypatch.setattr(QMessageBox, "critical", NOOP)
    monkeypatch.setattr(QMessageBox, "question", YES)

    # PyQt6 只有 exec，没有 exec_（PyQt5 遗留别名已移除）
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "open", lambda self: None)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """每个测试使用独立临时配置目录，并重置 ConfigManager 单例。"""
    from desktop_calendar.config import config as config_mod

    monkeypatch.setattr(config_mod, "_get_base_dir", lambda: str(tmp_path))
    monkeypatch.setattr(config_mod, "CONFIG_SAVE_DEBOUNCE_MS", 10)

    config_mod.ConfigManager._instance = None
    cm = config_mod.ConfigManager()

    monkeypatch.setattr(config_mod, "config", cm)

    yield config_mod, cm

    try:
        cm.flush()
    except Exception:
        pass
    config_mod.ConfigManager._instance = None
    

@pytest.fixture(autouse=True)
def _some_fixture():
    from desktop_calendar.contracts.event_bus import event_bus
    from desktop_calendar.config import i18n

    event_bus.clear_all()
    i18n._listeners.clear()
    yield
    event_bus.clear_all()
    i18n._listeners.clear()
    
    
# ---------- 共享测试替身 ----------

@pytest.fixture
def fake_lunar():
    """构造假 cnlunar 对象的工厂。

    用法：
        lunar = fake_lunar(lunarYearCn="二〇二五年", ...)

    属性挂 lambda 时不会被绑定 self —— 这是有意为之：
    cnlunar 的 get_legalHolidays 是实例方法，mock 成 lambda 后
    调用不带 self，与被测代码"直接调 lunar.get_legalHolidays()"
    的语义一致。
    """
    class FakeLunar:
        def __init__(self, **attrs):
            for k, v in attrs.items():
                setattr(self, k, v)
    return FakeLunar

@pytest.fixture
def config(isolated_config):
    """兼容历史测试：config 即 isolated_config 的别名。"""
    return isolated_config