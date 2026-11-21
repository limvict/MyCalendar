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
        "open_attendance_menu",
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


def test_attendance_button_label_tracks_next_action(monkeypatch):
    monkeypatch.setattr("desktop_calendar.ui.main_window.attendance.tr", lambda key: key)

    assert MainWindow._attendance_button_text({}) == "attendance.punch_in"
    assert MainWindow._attendance_button_text({"in": "09:00"}) == ("attendance.punch_out")
    assert (
        MainWindow._attendance_button_text(
            {
                "in": "09:00",
                "out": "18:00",
            }
        )
        == "btn.attendance"
    )


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
