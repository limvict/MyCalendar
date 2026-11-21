from types import SimpleNamespace
from unittest.mock import Mock

from desktop_calendar.config.constants import THEME_DARK, THEME_LIGHT
from desktop_calendar.ui.controllers import settings_controller
from desktop_calendar.ui.theme.manager import ThemeManager


def test_imported_theme_selection_replaces_live_preview(qapp, fresh_config_manager, monkeypatch):
    config = fresh_config_manager
    theme_manager = ThemeManager(config)
    assert theme_manager.preview_theme(THEME_DARK)

    dialog = Mock()
    dialog.cfg = config.snapshot()
    dialog.get_theme_name.return_value = THEME_LIGHT
    dialog.get_auto_theme_enabled.return_value = False
    dialog.get_opacity.return_value = 0.9
    dialog.get_memorial_list.return_value = []
    dialog.get_mem_remind.return_value = True
    dialog.get_mem_sound.return_value = True
    dialog.get_att_remind.return_value = True
    dialog.get_att_auto_punch.return_value = False
    dialog.get_auto_start_status.return_value = False

    window = SimpleNamespace(
        theme_mgr=theme_manager,
        set_calendar_wallpaper=Mock(),
        window_state=SimpleNamespace(set_opacity=Mock()),
        attendance_reminder=SimpleNamespace(reschedule=Mock()),
        attendance_auto_punch=SimpleNamespace(reschedule=Mock()),
        _update_attendance_ui=Mock(),
    )
    monkeypatch.setattr(settings_controller, "config", config)
    monkeypatch.setattr(settings_controller, "event_bus", Mock())
    monkeypatch.setattr(settings_controller, "check_auto_start", lambda: False)

    settings_controller.apply_settings(window, dialog)

    assert theme_manager.current.name == THEME_LIGHT
    assert config.get("theme_name") == THEME_LIGHT
