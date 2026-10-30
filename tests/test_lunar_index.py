# coding: utf-8
"""lunar 索引 single-flight：并发构建同一农历年只算一次。"""
import threading
import time

import pytest

from desktop_calendar.core import lunar as lunar_mod

pytestmark = pytest.mark.skipif(
    not lunar_mod.HAS_CNLUNAR, reason="需要 cnlunar")


def test_single_flight_concurrent(monkeypatch):
    lunar_mod.clear_lunar_caches()
    calls = []
    orig = lunar_mod._compute_lunar_index

    def counting(year):
        calls.append(year)
        time.sleep(0.05)          # 放大竞态窗口
        return orig(year)

    monkeypatch.setattr(lunar_mod, "_compute_lunar_index", counting)

    results, errors = [], []

    def worker():
        try:
            results.append(lunar_mod._build_lunar_index(2024))
        except Exception as e:      # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert calls == [2024]                     # 只算一次
    assert all(r is results[0] for r in results)  # 缓存返回同一对象


def test_clear_caches_does_not_break_locks():
    """clear_lunar_caches 不清 _index_locks（避免等锁线程永久阻塞）。"""
    lunar_mod.clear_lunar_caches()
    locks_before = dict(lunar_mod._index_locks)
    lunar_mod.clear_lunar_caches()
    assert lunar_mod._index_locks == locks_before