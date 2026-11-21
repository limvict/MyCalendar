from datetime import date
from types import SimpleNamespace

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QColor, QPixmap

from desktop_calendar.ui.calendar_views import (
    CalendarWeekView,
    CalendarYearView,
    week_start,
)
from desktop_calendar.ui.main_window import MainWindow
from desktop_calendar.ui.theme.manager import ThemeManager


def test_week_start_uses_monday_and_handles_sunday():
    assert week_start(QDate(2024, 6, 10)) == QDate(2024, 6, 10)
    assert week_start(QDate(2024, 6, 16)) == QDate(2024, 6, 10)


def test_week_navigation_advances_seven_days():
    class Calendar:
        selected = QDate(2024, 6, 10)

        def selectedDate(self):
            return self.selected

        def setSelectedDate(self, value):
            self.selected = value

        def showSelectedDate(self):
            pass

    window = SimpleNamespace(
        view_selector=SimpleNamespace(currentData=lambda: "week"),
        cal=Calendar(),
        _refresh_overview_views=lambda: None,
        update_calendar_title=lambda: None,
    )

    MainWindow._navigate_calendar(window, 1)

    assert window.cal.selected == QDate(2024, 6, 17)


def test_year_navigation_clamps_leap_day():
    class Calendar:
        selected = QDate(2024, 2, 29)

        def selectedDate(self):
            return self.selected

        def setSelectedDate(self, value):
            self.selected = value

        def setCurrentPage(self, year, month):
            self.page = (year, month)

    window = SimpleNamespace(
        view_selector=SimpleNamespace(currentData=lambda: "year"),
        cal=Calendar(),
        _refresh_overview_views=lambda: None,
        _refresh_schedule_markers=lambda: None,
        update_calendar_title=lambda: None,
    )

    MainWindow._navigate_calendar(window, 1)

    assert window.cal.selected == QDate(2025, 2, 28)
    assert window.cal.page == (2025, 2)


def test_year_view_loads_schedule_markers_for_the_full_year():
    captured = []
    calendar = SimpleNamespace(
        selectedDate=lambda: QDate(2024, 6, 10),
        set_schedule_markers=lambda markers: None,
    )
    window = SimpleNamespace(
        cal=calendar,
        view_selector=SimpleNamespace(currentData=lambda: "year"),
        _schedule_mgr=SimpleNamespace(
            markers_between=lambda start, end: captured.append((start, end)) or {}
        ),
        _refresh_overview_views=lambda: None,
    )

    MainWindow._refresh_schedule_markers(window)

    assert captured == [(date(2024, 1, 1), date(2024, 12, 31))]


def test_year_view_hit_testing_selects_month_day(qapp, fresh_config_manager, qtbot):
    calendar = SimpleNamespace(
        selectedDate=lambda: QDate(2024, 6, 10),
        cell_data_for=lambda _day: SimpleNamespace(
            lunar_text="初一", is_legal_hol=False, has_schedule=False, schedule_color=None
        ),
    )
    view = CalendarYearView(calendar, ThemeManager(fresh_config_manager).current)
    qtbot.addWidget(view)
    view.resize(420, 300)
    wallpaper = QPixmap(64, 48)
    wallpaper.fill(QColor("#7799BB"))
    view.set_wallpaper(wallpaper, 58)
    view.show()
    qtbot.wait(10)
    assert not view.grab().isNull()

    margin, gap = 4, 6
    month_width = (view.width() - margin * 2 - gap * 2) / 3
    month_height = (view.height() - margin * 2 - gap * 3) / 4
    title_height = min(18, month_height * 0.2)
    weekday_height = min(12, month_height * 0.14)
    day_height = (month_height - title_height - weekday_height) / 6
    day_width = (month_width - 8) / 7
    month_left = margin + 2 * (month_width + gap)
    month_top = margin + month_height + gap
    x = month_left + 4 + day_width * 1.5
    y = month_top + title_height + weekday_height + day_height * 3.5

    assert view._date_at(x, y) == QDate(2024, 6, 18)
    assert view._month_at(month_left + month_width / 2, month_top + title_height / 2) == 6
    assert view._date_at(0, 0) is None


def test_year_view_tooltip_reports_holidays_and_schedules(qapp, fresh_config_manager):
    calendar = SimpleNamespace(
        selectedDate=lambda: QDate(2024, 6, 10),
        cell_data_for=lambda _day: SimpleNamespace(
            lunar_text="端午节", is_legal_hol=True, has_schedule=True, schedule_color="#4A90D9"
        ),
    )
    view = CalendarYearView(calendar, ThemeManager(fresh_config_manager).current)

    tooltip = view._tooltip_for(QDate(2024, 6, 10))

    assert "2024-06-10" in tooltip
    assert "端午节" in tooltip
    assert "节假日" in tooltip
    assert "有日程" in tooltip


def test_week_view_paints_and_selects_day(qapp, fresh_config_manager, qtbot):
    selected_date = QDate(2024, 6, 10)
    calendar = SimpleNamespace(
        selectedDate=lambda: selected_date,
        cell_data_for=lambda _day: SimpleNamespace(is_legal_hol=False, lunar_text="初一"),
    )
    manager = SimpleNamespace(on=lambda _day: [])
    view = CalendarWeekView(calendar, manager, ThemeManager(fresh_config_manager).current)
    qtbot.addWidget(view)
    view.resize(420, 280)
    wallpaper = QPixmap(64, 48)
    wallpaper.fill(QColor("#7799BB"))
    view.set_wallpaper(wallpaper, 58)
    view.show()
    qtbot.wait(10)

    selected = []
    view.date_selected.connect(selected.append)
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=view.rect().center())
    assert selected == [QDate(2024, 6, 13)]


def test_week_view_tooltip_shows_full_schedule_details(qapp, fresh_config_manager):
    selected_date = QDate(2024, 6, 10)
    schedule = SimpleNamespace(time="09:30", title="Planning session")
    calendar = SimpleNamespace(
        selectedDate=lambda: selected_date,
        cell_data_for=lambda _day: SimpleNamespace(is_legal_hol=False, lunar_text="初一"),
    )
    manager = SimpleNamespace(on=lambda _day: [schedule])
    view = CalendarWeekView(calendar, manager, ThemeManager(fresh_config_manager).current)

    tooltip = view._tooltip_for(selected_date)

    assert "2024-06-10" in tooltip
    assert "09:30  Planning session" in tooltip
