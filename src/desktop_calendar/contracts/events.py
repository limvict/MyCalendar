# coding: utf-8
"""事件类型常量。

必须是纯常量模块：不 import 任何 desktop_calendar 模块，
core / application / infrastructure / presentation 都可安全依赖。
"""


class EventType:
    HOLIDAY_UPDATED = "holiday_updated"
    MEMORIAL_CHANGED = "memorial_changed"
    MEMORIAL_REMIND_TRIGGERED = "memorial_remind_triggered"  # Step 3 已加

    WINDOW_SHOW = "window_show"
    WINDOW_QUIT = "window_quit"
    WINDOW_TOGGLE_TOPMOST = "window_toggle_topmost"
    OPEN_SETTINGS = "open_settings"
    SETTINGS_CHANGED = "settings_changed"
    BACKUP_MEMORIAL = "backup_memorial"
    RESTORE_MEMORIAL = "restore_memorial"

    # 自动更新
    UPDATE_AVAILABLE = "update_available"
    UPDATE_FAILED = "update_failed"
    UPDATE_READY = "update_ready"
    UPDATE_PROGRESS = "update_progress"