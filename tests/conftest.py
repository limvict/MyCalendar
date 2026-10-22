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
import pytest
from PyQt6.QtWidgets import QApplication,QMessageBox
from desktop_calendar.config import config as config_mod
from desktop_calendar.utils import paths as paths_mod

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

def pytest_sessionfinish(session, exitstatus):
    """整场跑完后清理临时目录。"""
    import shutil
    shutil.rmtree(_TMP_HOME, ignore_errors=True)


@pytest.fixture(scope="session")
def qapp():
    
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _kill_modals(monkeypatch):
    """封杀所有 QMessageBox 弹窗，避免 offscreen 下 .exec() 永久阻塞。"""
   

    NOOP = lambda *a, **k: None                      # noqa: E731
    YES = lambda *a, **k: QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "information", NOOP)
    monkeypatch.setattr(QMessageBox, "warning", NOOP)
    monkeypatch.setattr(QMessageBox, "critical", NOOP)
    monkeypatch.setattr(QMessageBox, "question", YES)

    # PyQt6 只有 exec，没有 exec_（PyQt5 遗留别名已移除）
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "open", lambda self: None)


# ---------- 修改 isolated_config ----------
@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """每个测试使用独立临时配置目录，并重置 ConfigManager 单例。

    yield 一个二元组 (config_mod, config_instance)：
      - config_mod:    desktop_calendar.config.config 模块本身，
                       用于 monkeypatch 模块级函数（get_config_path 等）
      - config_instance: ConfigManager 单例，用于 crud 测试
    """
    monkeypatch.setattr(paths_mod, "get_base_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        config_mod, "_get_app_data_dir",
        lambda: str(tmp_path / "MyCalendarApp"),
    )
    monkeypatch.setattr(config_mod.ConfigManager, "_instance", None)

    yield config_mod, config_mod.config


# ---------- 新增：单对象版本，给其他测试用 ----------
@pytest.fixture
def config_instance(isolated_config):
    """只取 ConfigManager 实例的便捷 fixture。

    与 isolated_config 共享隔离逻辑，只是省略了 mod 部分。
    历史代码若用 `config` fixture 拿单实例，推荐迁移到此。
    """
    _, cm = isolated_config
    return cm

# ---------- 保持 config 兼容：改为委托 config_instance ----------
@pytest.fixture
def config(config_instance):
    """兼容历史测试：config 即 ConfigManager 实例的别名。

    改自原 `config = isolated_config` —— 原先 isolated_config 返回
    单对象，现在返回二元组，所以这里改为委托 config_instance。
    """
    return config_instance

@pytest.fixture(autouse=True)
def _some_fixture():
    from desktop_calendar.contracts.event_bus import event_bus
    from desktop_calendar.config import i18n
    from desktop_calendar.config.translations import ZH_CN

    # i18n 的 _current_lang / _current_table 是模块级 global，
    # 测试间共享会让 set_language 提前 return（new_lang == _current_lang），
    # 从而不通知监听者，造成"语言切换后 UI 没刷新"的假失败。
    event_bus.clear_all()
    i18n._listeners.clear()
    i18n._current_lang = "zh_CN"
    i18n._current_table = ZH_CN
    yield
    event_bus.clear_all()
    i18n._listeners.clear()
    i18n._current_lang = "zh_CN"
    i18n._current_table = ZH_CN

# ---------- 共享测试替身 ----------

@pytest.fixture
def fake_lunar():
    """构造假 cnlunar 对象的工厂。"""
    class FakeLunar:
        def __init__(self, **attrs):
            for k, v in attrs.items():
                setattr(self, k, v)
    return FakeLunar
