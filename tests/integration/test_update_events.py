# coding: utf-8
"""更新事件接线集成测试。

补 test_event_wiring.py 的漏洞：后者只查"事件类型 → 方法名"的映射表，
不实际触发事件。如果 MainWindow._on_update_* 的方法名拼错 / 属性缺失
（如调用了已删除的 _close_update_progress），测试发现不了。

本文件通过 event_bus.publish 实际触发，确认：
  - 回调不被 AttributeError 打断
  - payload 非法时静默忽略而非崩溃

不测 UPDATE_READY——它会调 quit_app，副作用太大。
"""
import pytest

from desktop_calendar.contracts.event_bus import event_bus
from desktop_calendar.contracts.events import EventType


@pytest.fixture
def main_window(qapp, monkeypatch, config_instance):
    """构造 MainWindow。

    - monkeypatch QApplication.quit：拦截 quit_app 最后的退出，避免
      破坏 session 级 qapp fixture
    - 不 patch 配置目录：conftest 的 APPDATA 环境隔离已覆盖
    """
    from PyQt6.QtWidgets import QApplication
    from desktop_calendar.ui.main_window import MainWindow

    monkeypatch.setattr(QApplication, "quit", lambda: None)

    win = MainWindow()
    try:
        yield win
    finally:
        try:
            win.quit_app()
        except Exception:
            pass


class TestUpdateProgressEvents:
    def test_progress_valid_payload(self, main_window):
        event_bus.publish(EventType.UPDATE_PROGRESS, percent=50)

    def test_progress_empty_payload(self, main_window):
        event_bus.publish(EventType.UPDATE_PROGRESS)

    def test_progress_invalid_percent(self, main_window):
        event_bus.publish(EventType.UPDATE_PROGRESS, percent="abc")
        event_bus.publish(EventType.UPDATE_PROGRESS, percent=-1)
        event_bus.publish(EventType.UPDATE_PROGRESS, percent=None)


class TestUpdateFailedEvents:
    def test_failed_download_stage(self, main_window):
        event_bus.publish(
            EventType.UPDATE_FAILED,
            stage="download",
            error="模拟下载失败",
        )

    def test_failed_other_stage(self, main_window):
        event_bus.publish(
            EventType.UPDATE_FAILED,
            stage="check",
            error="模拟检查失败",
        )

    def test_failed_empty_payload(self, main_window):
        event_bus.publish(EventType.UPDATE_FAILED)


class TestUpdateAvailableEvents:
    def test_available_with_info(self, main_window):
        event_bus.publish(
            EventType.UPDATE_AVAILABLE,
            info={
                "version": "9.9.9",
                "download_url": "https://example.com/test.exe",
                "sha256": "0" * 64,
                "release_notes": "test",
            },
        )

    def test_available_empty_payload(self, main_window):
        event_bus.publish(EventType.UPDATE_AVAILABLE)

    def test_available_non_dict_payload(self, main_window):
        event_bus.publish(EventType.UPDATE_AVAILABLE, info=None)


class TestNoAttributeErrors:
    """回归保护：集中触发所有 update 事件。"""

    def test_all_update_events_triggerable(self, main_window):
        event_bus.publish(EventType.UPDATE_PROGRESS, percent=0)
        event_bus.publish(EventType.UPDATE_FAILED, stage="x", error="y")
        event_bus.publish(EventType.UPDATE_AVAILABLE)