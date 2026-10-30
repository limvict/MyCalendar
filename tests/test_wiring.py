# coding: utf-8
"""wiring 订阅表与 MainWindow 方法的契约检查。"""
from unittest.mock import MagicMock


def test_subscriptions_len():
    """订阅表覆盖所有事件，数量变化需同步更新本测试。

    `== 13` 是有意的精确断言：wiring 新增 / 删除事件时必须显式改本
    测试，让 PR 作者确认"订阅数量变化"是刻意的而非误操作。
    """
    from desktop_calendar import wiring

    entries = wiring._subscriptions(MagicMock())
    assert len(entries) == 13


def test_subscriptions_all_callable():
    """每条订阅的 callback 必须 callable。

    注意：本测试用 MagicMock 作为 window，`window._on_xxx` 返回的
    MagicMock 子对象恒为 callable——**它只验证 wiring._subscriptions
    返回结构正确，测不到真实 MainWindow 上的方法存在性**。
    后者由 test_wiring_methods_exist_on_main_window 覆盖。
    """
    from desktop_calendar import wiring

    window = MagicMock()
    for evt, cb in wiring._subscriptions(window):
        assert isinstance(evt, str) and evt
        assert callable(cb)


class _AttrRecorder:
    """记录属性访问的轻量替身。

    MagicMock 的公开接口 mock_calls / method_calls 只记录"调用"，
    纯属性访问（window._on_xxx）只落在私有的 _mock_children 里。
    本测试需要的是"wiring 看过哪些属性名"，用 __getattr__ 精确
    记录，不依赖私有 API，也不受 MagicMock 内部行为变化影响。
    """

    def __init__(self):
        self.accessed: set = set()

    def __getattr__(self, name):
        # self.accessed 已在 __init__ 赋值，不会递归触发本方法
        self.accessed.add(name)
        return MagicMock()


def test_wiring_methods_exist_on_main_window():
    """MainWindow 上确实存在 wiring 订阅的 _on_xxx 方法。

    用 _AttrRecorder 记录 wiring._subscriptions 访问了哪些属性，
    再对照 MainWindow 类上是否有这些方法。不硬编码方法名——wiring
    新增事件时本测试自动跟进，避免清单与实现漂移。

    用 dir(MainWindow) 而非实例化：避免 QApplication / 依赖检查 /
    主题构建等副作用。
    """
    from desktop_calendar import wiring
    from desktop_calendar.ui.main_window import MainWindow

    probes = _AttrRecorder()
    wiring._subscriptions(probes)

    accessed = {n for n in probes.accessed if n.startswith("_on_")}
    assert accessed, (
        "未能从 wiring._subscriptions 提取任何 _on_xxx 方法访问，"
        "wiring 的实现可能变了（如改成 getattr(window, name)），"
        "需同步更新本测试"
    )

    names = set(dir(MainWindow))
    missing = accessed - names
    assert not missing, (
        f"MainWindow 缺少 wiring 依赖的方法: {sorted(missing)}"
    )