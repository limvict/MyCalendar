# coding: utf-8
"""UpdateUIController 进度条生命周期回归测试。

覆盖 bug：取消下载后再发起下载，进度条不再出现。

根因：_on_progress_canceled 置 _progress_dismissed=True；取消路径
不发 UPDATE_FAILED，on_failed/on_ready 都不调 close_progress()，
标志永不复位，下次 on_progress 被守卫吞掉。

修复：on_available 用户点"立即更新"成功（download_and_apply_async
返回 True）后复位 _progress_dismissed=False。
"""
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QMessageBox

from desktop_calendar.ui.controllers.update_ui import UpdateUIController


@pytest.fixture
def ctrl(qapp):
    """构造 controller。

    parent 用 MagicMock：controller 只把它当 QMessageBox/QProgressDialog
    的 parent 传给 Qt，Qt 对非 QWidget parent 的处理路径在测试里不触发
    （我们 patch 掉了所有 exec/show）。
    """
    update_mgr = MagicMock()
    update_mgr.download_and_apply_async.return_value = True
    update_mgr.cancel_download.return_value = True
    controller = UpdateUIController(
        parent_widget=None,          # 见下方 patch，避免 MagicMock parent
        update_mgr=update_mgr,
        window_quit_cb=lambda: None,
    )
    yield controller
    # 清理可能残留的进度对话框
    try:
        controller.close_progress()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 核心回归：取消后再次下载，进度条必须出现
# ---------------------------------------------------------------------------
def test_progress_shown_after_cancel(ctrl):
    """1. 首次下载进度条出现
       2. 点取消 → 进度条关闭、标志置 True
       3. 再次发起下载（走 on_available 成功分支）→ 标志复位
       4. 新进度事件 → 进度条必须重新出现
    """
    # ---- 1. 首次进度 ----
    ctrl.on_progress({"percent": 10})
    assert ctrl._progress_dlg is not None, "首次进度条未创建"

    # ---- 2. 取消 ----
    ctrl._on_progress_canceled()
    assert ctrl._progress_dlg is None
    assert ctrl._progress_dismissed is True
    ctrl._update_mgr.cancel_download.assert_called_once()

    # ---- 3. 再次发起下载：模拟用户在 QMessageBox 点 Yes ----
    with patch.object(QMessageBox, "exec",
                      return_value=QMessageBox.StandardButton.Yes), \
         patch.object(QMessageBox, "setWindowTitle"), \
         patch.object(QMessageBox, "setText"), \
         patch.object(QMessageBox, "setInformativeText"), \
         patch.object(QMessageBox, "setIcon"), \
         patch.object(QMessageBox, "setStandardButtons"), \
         patch.object(QMessageBox, "button"):
        ctrl.on_available({"info": {"version": "9.9.9"}})

    ctrl._update_mgr.download_and_apply_async.assert_called_once()
    assert ctrl._progress_dismissed is False, (
        "on_available 成功分支未复位 _progress_dismissed，"
        "下次下载进度条会被吞掉")

    # ---- 4. 新进度必须重新建对话框 ----
    ctrl.on_progress({"percent": 5})
    assert ctrl._progress_dlg is not None, "取消后再次下载进度条丢失"


# ---------------------------------------------------------------------------
# 取消路径本身：只置标志，不弹错误
# ---------------------------------------------------------------------------
def test_cancel_only_dismisses_no_error(ctrl):
    ctrl.on_progress({"percent": 50})
    with patch("desktop_calendar.ui.controllers.update_ui.msg_error") as err:
        ctrl._on_progress_canceled()
    err.assert_not_called()
    assert ctrl._progress_dismissed is True
    assert ctrl._progress_dlg is None


# ---------------------------------------------------------------------------
# 取消二次进入：dlg.close() 若再 emit canceled 不应崩
# ---------------------------------------------------------------------------
def test_cancel_idempotent(ctrl):
    ctrl.on_progress({"percent": 20})
    ctrl._on_progress_canceled()
    # 再次调用（模拟 Qt close 内部二次 emit）
    ctrl._on_progress_canceled()
    assert ctrl._progress_dlg is None


# ---------------------------------------------------------------------------
# 失败 / 就绪路径仍走 close_progress（不回归）
# ---------------------------------------------------------------------------
def test_failed_closes_progress_and_resets_flag(ctrl):
    ctrl.on_progress({"percent": 30})
    ctrl._progress_dismissed = True  # 模拟之前取消过
    with patch("desktop_calendar.ui.controllers.update_ui.msg_error"):
        ctrl.on_failed({"stage": "download", "error": "boom"})
    assert ctrl._progress_dlg is None
    assert ctrl._progress_dismissed is False


def test_ready_closes_progress_and_resets_flag(ctrl):
    ctrl.on_progress({"percent": 100})
    ctrl._progress_dismissed = True
    with patch("desktop_calendar.ui.controllers.update_ui.QMessageBox") as box, \
         patch.object(ctrl, "_quit_cb") as quit_cb:
        ctrl.on_ready()
    assert ctrl._progress_dlg is None
    assert ctrl._progress_dismissed is False
    quit_cb.assert_called_once()


# ---------------------------------------------------------------------------
# 进度事件健壮性：非法 payload 不应崩
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("payload", [
    None,
    {},
    {"percent": None},
    {"percent": "abc"},
    {"percent": -1},
    {"percent": 1e309},  # inf，int() 抛 OverflowError
])
def test_on_progress_invalid_payload(ctrl, payload):
    ctrl.on_progress(payload)
    # 非法 payload 不应该建出对话框
    assert ctrl._progress_dlg is None


# ---------------------------------------------------------------------------
# download_and_apply_async 返回 False：不复位、弹错误（保持原语义）
# ---------------------------------------------------------------------------
def test_on_available_download_rejected(ctrl):
    ctrl._update_mgr.download_and_apply_async.return_value = False
    ctrl._progress_dismissed = True  # 之前取消过

    with patch.object(QMessageBox, "exec",
                      return_value=QMessageBox.StandardButton.Yes), \
         patch.object(QMessageBox, "setWindowTitle"), \
         patch.object(QMessageBox, "setText"), \
         patch.object(QMessageBox, "setInformativeText"), \
         patch.object(QMessageBox, "setIcon"), \
         patch.object(QMessageBox, "setStandardButtons"), \
         patch.object(QMessageBox, "button"), \
         patch("desktop_calendar.ui.controllers.update_ui.msg_error") as err:
        ctrl.on_available({"info": {"version": "9.9.9"}})

    # 下载根本没起来，不应复位标志（下次进 on_progress 仍应被忽略）
    assert ctrl._progress_dismissed is True
    err.assert_called_once()