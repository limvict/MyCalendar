from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QWidget

from desktop_calendar.ui.main_window import MainWindow


def test_public_api_survives_mixin_split():
    """拆分 mixin 后，对外方法仍能从 MainWindow 上直接取到。

    这些名字被 `__main__`、设置对话框、托盘菜单等外部调用方使用；
    它们分散在 `ui/main_window/` 的各个 mixin 里，丢失时这里会失败。
    """
    expected = {
        "apply_theme",
        "build_ui",
        "goto_today",
        "next_month",
        "on_calendar_select_changed",
        "open_attendance_dialog",
        "prev_month",
        "quit_app",
        "set_calendar_view",
        "set_calendar_wallpaper",
        "show_normal",
        "update_calendar_title",
    }
    missing = sorted(expected - set(dir(MainWindow)))
    assert not missing, f"MainWindow 缺少对外方法: {missing}"


def test_escape_closes_sidebar_before_minimizing():
    window = MagicMock()
    window._sidebar_visible = True
    MainWindow._on_escape(window)
    window.btn_sidebar.setChecked.assert_called_once_with(False)
    window.showMinimized.assert_not_called()

    window = MagicMock()
    window._sidebar_visible = False
    MainWindow._on_escape(window)
    window.showMinimized.assert_called_once()


def test_close_hides_to_tray_when_available():
    window = MagicMock()
    window._quitting = False
    window._quitting_for_update = False
    window.tray_mgr.available = True
    event = QCloseEvent()

    MainWindow.closeEvent(window, event)

    assert not event.isAccepted()
    window._on_window_hide.assert_called_once()


def test_close_quits_when_no_tray():
    window = MagicMock()
    window._quitting = False
    window._quitting_for_update = False
    window.tray_mgr.available = False
    event = QCloseEvent()

    MainWindow.closeEvent(window, event)

    assert event.isAccepted()
    window.quit_app.assert_called_once()


def test_minimize_action_minimizes_instead_of_hiding():
    window = MagicMock()
    window._sidebar_visible = False

    # 「— 最小化」现在绑定的是真正的 showMinimized
    MainWindow._hide_or_minimize(window)

    window.showMinimized.assert_called_once()
    window.hide.assert_not_called()


def test_main_window_context_menu_does_not_open_sidebar():
    window = type(
        "Window",
        (),
        {
            "_sidebar_visible": False,
            "btn_sidebar": Mock(),
        },
    )()
    event = Mock()

    MainWindow.contextMenuEvent(window, event)

    window.btn_sidebar.setChecked.assert_not_called()
    event.accept.assert_called_once_with()


def test_quick_add_schedule_formats_date_without_locale(monkeypatch):
    captured = []
    monkeypatch.setattr(
        "desktop_calendar.ui.main_window.actions.QInputDialog.getText",
        lambda _parent, _title, prompt: (captured.append(prompt) or "", False),
    )
    window = SimpleNamespace(
        cal=SimpleNamespace(
            selectedDate=lambda: SimpleNamespace(toPyDate=lambda: date(2024, 6, 10))
        ),
    )

    MainWindow._quick_add_schedule(window)

    assert captured == ["为 2024年06月10日 添加全天日程："]


def _punch_state(rec, hour, minute=0):
    from datetime import datetime

    return MainWindow._punch_states(rec, datetime(2024, 6, 10, hour, minute))


def test_punch_buttons_split_in_and_out(monkeypatch):
    """未打卡的早上：上班可用、下班禁用（先上班再下班）。"""
    monkeypatch.setattr("desktop_calendar.ui.main_window.attendance.tr", lambda key: key)

    punch_in, punch_out = _punch_state({}, hour=9)
    assert punch_in["text"] == "attendance.punch_in"
    assert punch_in["enabled"] is True
    assert punch_out["text"] == "attendance.punch_out"
    assert punch_out["enabled"] is False


def test_punch_in_disabled_after_punching(monkeypatch):
    monkeypatch.setattr("desktop_calendar.ui.main_window.attendance.tr", lambda key: key)

    punch_in, punch_out = _punch_state({"in": "07:35"}, hour=9)
    assert punch_in["enabled"] is False
    assert punch_in["text"].startswith("attendance.punch_in_done_btn")
    assert punch_out["enabled"] is True


def test_punch_out_becomes_update_when_already_punched(monkeypatch):
    monkeypatch.setattr("desktop_calendar.ui.main_window.attendance.tr", lambda key: key)

    _punch_in, punch_out = _punch_state({"in": "07:35", "out": "18:00"}, hour=20)
    assert punch_out["text"] == "attendance.punch_out_update_short"
    assert punch_out["enabled"] is True


def test_punch_in_disabled_after_deadline(monkeypatch):
    monkeypatch.setattr("desktop_calendar.ui.main_window.attendance.tr", lambda key: key)

    punch_in, punch_out = _punch_state({}, hour=12)
    assert punch_in["enabled"] is False
    assert punch_out["enabled"] is True


def _summary_window(days, total_minutes):
    from types import SimpleNamespace

    return SimpleNamespace(
        attendance_store=SimpleNamespace(
            week_summary=lambda _day: SimpleNamespace(days=tuple(days), total_minutes=total_minutes)
        )
    )


def test_attendance_summary_text_formats_week(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("desktop_calendar.ui.main_window.attendance.tr", lambda key: key)

    day = lambda in_t, out_t: SimpleNamespace(in_time=in_t, out_time=out_t)  # noqa: E731
    # 3 天完整记录、24.5h = 1470 分钟
    done = _summary_window([day("08:00", "18:00")] * 3, 1470)
    assert MainWindow._attendance_summary_text(done) == "attendance.sidebar_week_summary"

    # 只打了上班卡：算 1 天，但工时 0 不显示小时
    partial = _summary_window([day("08:00", None)], 0)
    assert MainWindow._attendance_summary_text(partial) == "attendance.sidebar_week_days"

    # 完全没打卡
    empty = _summary_window([], 0)
    assert MainWindow._attendance_summary_text(empty) == "attendance.sidebar_week_empty"


def test_main_window_geometry_follows_bundle_and_stays_fixed(qapp):
    window = QWidget()
    window._sidebar_visible = False
    window.content_widget = QWidget(window)
    window.sidebar = QWidget(window)
    window.info_label = QWidget(window)
    window._shadow_effect = None
    # 小屏下 fit_scale 会给出 0.8，窗口尺寸应当跟着缩小
    bundle = SimpleNamespace(
        scale_factor=0.8,
        window=SimpleNamespace(
            width=368, height=528, info_label_height=26, shadow_size=0, shadow_color=None
        ),
        layout=SimpleNamespace(sidebar_width=round(260 * 0.8), content_min_width=round(360 * 0.8)),
    )
    try:
        MainWindow._apply_theme_geometry(window, bundle)

        assert window.size().width() == 368
        assert window.size().height() == 528
        assert window.minimumSize() == window.maximumSize()
        window.resize(560, 720)
        assert window.size().width() == 368
        assert window.size().height() == 528

        window._sidebar_visible = True
        MainWindow._apply_theme_geometry(window, bundle)
        assert window.size().width() == 368 + round(260 * 0.8)
        assert window.size().height() == 528
    finally:
        window.deleteLater()
