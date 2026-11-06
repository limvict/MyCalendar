# coding: utf-8
"""logging_setup：级别解析、单例、log_exception 上下文。"""
import logging

import pytest

from desktop_calendar.utils import logging_setup


class TestResolveLevel:
    def test_default_info(self, monkeypatch):
        monkeypatch.delenv("MYCALENDAR_LOG_LEVEL", raising=False)
        assert logging_setup._resolve_level() == logging.INFO

    @pytest.mark.parametrize("env,expected", [
        ("DEBUG", logging.DEBUG),
        ("WARNING", logging.WARNING),
        ("debug", logging.DEBUG),
        ("TRACE", logging_setup.TRACE_LEVEL),
        ("trace", logging_setup.TRACE_LEVEL),
        ("  DEBUG  ", logging.DEBUG),
    ])
    def test_known(self, monkeypatch, env, expected):
        monkeypatch.setenv("MYCALENDAR_LOG_LEVEL", env)
        assert logging_setup._resolve_level() == expected

    def test_unknown_falls_back(self, monkeypatch):
        monkeypatch.setenv("MYCALENDAR_LOG_LEVEL", "NOPE")
        assert logging_setup._resolve_level() == logging.INFO


class TestGetLogger:
    def test_singleton(self):
        a = logging_setup.get_logger()
        b = logging_setup.get_logger()
        assert a is b


class TestLogException:
    def test_with_exception_context(self, app_logger_propagate, caplog):
        with caplog.at_level(logging.ERROR):
            try:
                raise ValueError("boom")
            except ValueError:
                logging_setup.log_exception("ctx")
        recs = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert recs and recs[-1].exc_info is not None

    def test_without_exception_context(self, app_logger_propagate, caplog):
        with caplog.at_level(logging.ERROR):
            logging_setup.log_exception("plain")
        recs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert recs and recs[-1].exc_info is None


class TestTraceLevel:
    def test_registered(self):
        assert logging.getLevelName(logging_setup.TRACE_LEVEL) == "TRACE"

    def test_trace_method_exists(self):
        assert hasattr(logging_setup.get_logger(), "trace")
