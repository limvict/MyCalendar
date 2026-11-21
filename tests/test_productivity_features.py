from datetime import date, datetime

import pytest
from PyQt6.QtCore import QDate, Qt, QTime

from desktop_calendar.config.constants import DEFAULT_THEME, THEME_LIGHT
from desktop_calendar.config.manager import normalize_config
from desktop_calendar.core.focus_log import FocusLog
from desktop_calendar.core.pomodoro import Phase, PomodoroTimer
from desktop_calendar.core.schedule import Schedule, ScheduleManager
from desktop_calendar.core.schedule_reminder import ScheduleReminder
from desktop_calendar.infrastructure.network.weather_source import codes as weather_codes
from desktop_calendar.infrastructure.network.weather_source.parsing import (
    parse_cities_in_province,
    parse_districts,
    parse_met_no,
    parse_uapis,
)
from desktop_calendar.ui.cell_presenter import CellPresenter
from desktop_calendar.ui.dialogs.pomodoro import PomodoroDialog
from desktop_calendar.ui.dialogs.schedule import ScheduleDialog
from desktop_calendar.ui.dialogs.schedule_remind import ScheduleRemindDialog
from desktop_calendar.ui.info_panel import format_weather
from desktop_calendar.ui.panel.schedule_panel import SchedulePanel
from desktop_calendar.ui.theme.bundle import build_bundle
from desktop_calendar.ui.widgets.weather_cities import valid_city
from desktop_calendar.ui.widgets.weather_icons import weather_icon_for
from desktop_calendar.ui.widgets.weather_widget import WeatherWidget


def bundle_for_scale(scale: float):
    return build_bundle(THEME_LIGHT, dict(DEFAULT_THEME), scale=scale)


def test_schedule_persistence_recurrence_and_visible_dates(tmp_path):
    path = tmp_path / "schedules.json"
    manager = ScheduleManager(path)
    manager.add(
        title="Weekly sync",
        date="2024-06-03",
        time="09:30",
        repeat="weekly",
    )

    assert set(manager.markers_between(date(2024, 6, 1), date(2024, 6, 17))) == {
        "2024-06-03",
        "2024-06-10",
        "2024-06-17",
    }
    assert ScheduleManager(path).on(date(2024, 6, 10))[0].title == "Weekly sync"


def test_monthly_schedule_occurs_on_short_month_end(tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")
    manager.add(title="Month end", date="2024-01-31", repeat="monthly")

    assert len(manager.on(date(2024, 2, 29))) == 1
    assert len(manager.on(date(2024, 4, 30))) == 1


def test_yearly_schedule_clamps_leap_day_and_updates_are_validated(tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")
    schedule = manager.add(title="Leap day", date="2024-02-29", repeat="yearly")

    assert len(manager.on(date(2024, 2, 29))) == 1
    assert len(manager.on(date(2025, 2, 28))) == 1
    assert len(manager.on(date(2025, 3, 1))) == 0

    with pytest.raises(ValueError):
        manager.update(schedule.id, date="2024-02-30")
    assert manager.all()[0].date == "2024-02-29"


def test_schedule_load_keeps_valid_items_when_one_record_is_invalid(tmp_path):
    path = tmp_path / "schedules.json"
    path.write_text(
        '{"items": ['
        '{"id":"valid","title":"保留","date":"2024-06-10","time":"09:00","repeat":"none"},'
        '{"id":"invalid","title":"","date":"bad-date","repeat":"none"}'
        "]}",
        encoding="utf-8",
    )

    manager = ScheduleManager(path)

    assert [schedule.title for schedule in manager.all()] == ["保留"]


def test_schedule_color_persists_and_combines_markers(tmp_path):
    path = tmp_path / "schedules.json"
    manager = ScheduleManager(path)
    manager.add(title="Default", date="2024-06-10")
    manager.add(title="Colored", date="2024-06-10", color="#4A90D9")
    manager.add(title="Other", date="2024-06-11", color="#E8564B")

    assert manager.markers_between(date(2024, 6, 10), date(2024, 6, 11)) == {
        "2024-06-10": "#4A90D9",
        "2024-06-11": "#E8564B",
    }
    assert set(manager.markers_between(date(2024, 6, 10), date(2024, 6, 11))) == {
        "2024-06-10",
        "2024-06-11",
    }
    assert ScheduleManager(path).all()[1].color == "#4A90D9"


def test_schedule_color_rejects_invalid_values(tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")

    with pytest.raises(ValueError, match="#RRGGBB"):
        manager.add(title="Invalid color", date="2024-06-10", color="#123")
    assert manager.all() == []


def test_schedule_dialog_adds_selected_color(qapp, tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")
    dialog = ScheduleDialog(manager, date(2024, 6, 10))
    try:
        dialog._title.setText("Colored meeting")
        dialog._colors._buttons[1].setChecked(True)
        dialog._add_schedule()

        assert manager.on(date(2024, 6, 10))[0].color == "#4A90D9"
    finally:
        dialog.deleteLater()


def test_schedule_dialog_edits_schedule_and_searches_notes(qapp, tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")
    schedule = manager.add(
        title="Planning", date="2024-06-10", time="09:00", note="Project kickoff"
    )
    dialog = ScheduleDialog(manager, date(2024, 6, 10))
    try:
        dialog._table.selectRow(0)
        dialog._edit_selected()
        dialog._title.setText("Project planning")
        dialog._date_edit.setDate(QDate(2024, 6, 11))
        dialog._note.setText("Updated agenda")
        dialog._time.setTime(QTime(10, 30))
        dialog._save_edit()

        updated = manager.all()[0]
        assert updated.id == schedule.id
        assert updated.title == "Project planning"
        assert updated.date == "2024-06-11"
        assert updated.time == "10:30"
        assert updated.note == "Updated agenda"

        dialog._date = date(2024, 6, 11)
        dialog._refresh()
        dialog._search.setText("updated agenda")
        assert not dialog._table.isRowHidden(0)
        dialog._search.setText("missing")
        assert dialog._table.isRowHidden(0)
    finally:
        dialog.deleteLater()


def test_schedule_dialog_discloses_search_date_scope(qapp, tmp_path):
    dialog = ScheduleDialog(ScheduleManager(tmp_path / "schedules.json"), date(2024, 6, 10))
    try:
        assert "2024-06-10 当天" in dialog._scope_label.text()
        assert "所选日期内搜索" in dialog._search.placeholderText()
        assert dialog.minimumWidth() >= 680
    finally:
        dialog.deleteLater()


def test_schedule_dialog_allows_inline_completion(qapp, tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")
    manager.add(title="One-off", date="2024-06-10")
    dialog = ScheduleDialog(manager, date(2024, 6, 10))
    try:
        status = dialog._table.item(0, 3)
        status.setCheckState(Qt.CheckState.Checked)
        assert manager.on(date(2024, 6, 10))[0].done
        assert dialog._table.item(0, 3).checkState() == Qt.CheckState.Checked
    finally:
        dialog.deleteLater()


def test_schedule_panel_allows_inline_completion(qapp, tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")
    manager.add(title="Quick task", date="2024-06-10")
    panel = SchedulePanel(manager)
    panel.apply_theme(build_bundle(THEME_LIGHT, dict(DEFAULT_THEME)))
    panel.refresh(date(2024, 6, 10))
    changes = []
    panel.changed.connect(lambda: changes.append(True))
    try:
        panel._list.item(0).setCheckState(Qt.CheckState.Checked)
        assert manager.on(date(2024, 6, 10))[0].done
        assert changes == [True]
    finally:
        panel.deleteLater()


def test_schedule_load_migrates_records_without_new_fields(tmp_path):
    path = tmp_path / "schedules.json"
    path.write_text(
        '{"version": 1, "items": ['
        '{"id":"legacy","title":"Legacy","date":"2024-06-10","repeat":"none"}'
        "]}",
        encoding="utf-8",
    )

    manager = ScheduleManager(path)

    assert manager.all()[0].color == ""
    assert manager.all()[0].snoozed_until == ""


def test_schedule_rejects_invalid_date_and_time(tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")

    with pytest.raises(ValueError):
        manager.add(title="Bad date", date="not-a-date")
    with pytest.raises(ValueError):
        manager.add(title="Bad time", date="2024-06-10", time="25:99")
    assert manager.all() == []


def test_schedule_save_failure_rolls_back_in_memory(tmp_path, monkeypatch):
    manager = ScheduleManager(tmp_path / "schedules.json")

    def fail_save():
        raise OSError("disk full")

    monkeypatch.setattr(manager, "save", fail_save)
    with pytest.raises(OSError, match="disk full"):
        manager.add(title="Meeting", date="2024-06-10")
    assert manager.all() == []


def test_cell_presenter_marks_schedule_day():
    presenter = CellPresenter()
    presenter.set_schedule_markers({"2024-06-10": "#4A90D9"})

    marked = presenter.compute(QDate(2024, 6, 10))
    assert marked.has_schedule
    assert marked.schedule_color == "#4A90D9"
    assert not presenter.compute(QDate(2024, 6, 11)).has_schedule


def test_weather_config_defaults_and_normalizes_invalid_values():
    cfg = normalize_config(
        {
            "weather_city": "  ",
            "weather_lat": 120,
            "weather_lon": float("nan"),
            "weather_refresh_minutes": 1,
            "weather_enabled": "false",
        }
    )

    assert cfg["weather_city"] == "杭州"
    assert cfg["weather_lat"] == 30.2741
    assert cfg["weather_lon"] == 120.1551
    assert cfg["weather_refresh_minutes"] == 5
    assert cfg["weather_enabled"] is False


def test_weather_config_normalizes_saved_cities():
    cfg = normalize_config(
        {
            "weather_city": "杭州",
            "weather_lat": 30.2741,
            "weather_lon": 120.1551,
            "weather_cities": [
                {"name": "北京", "lat": 39.9, "lon": 116.4, "label": "北京，北京市"},
                {"name": "重复", "lat": 39.9, "lon": 116.4},
                {"name": "无效", "lat": float("nan"), "lon": 120},
                None,
            ],
        }
    )

    assert cfg["weather_cities"] == [
        {"name": "杭州", "lat": 30.2741, "lon": 120.1551},
        {"name": "北京", "lat": 39.9, "lon": 116.4, "label": "北京，北京市"},
    ]


def test_weather_widget_fetches_and_formats_status(qapp):
    class FakeSource:
        def fetch(self, city, lat, lon, on_ok, on_err):
            self.fetch_args = (city, lat, lon)
            self.on_ok = on_ok
            self.on_err = on_err

    source = FakeSource()
    widget = WeatherWidget(
        source,
        {
            "weather_enabled": True,
            "weather_city": "杭州",
            "weather_lat": 30.2741,
            "weather_lon": 120.1551,
            "weather_refresh_minutes": 30,
        },
    )
    source.on_ok(
        type(
            "Info",
            (),
            {
                "city": "杭州",
                "temperature": 24.4,
                "description": "多云",
                "humidity": 60,
                "wind_speed": 5.2,
                "updated_at": "2026-11-17T15:00",
            },
        )()
    )

    assert source.fetch_args == ("杭州", 30.2741, 120.1551)
    assert widget._label.text() == "杭州 24℃ 多云"
    assert widget._weather_icon.text() == "☁️"
    assert widget._label.toolTip() == "湿度 60%"
    assert widget._details_label.text() == "湿度 60%"
    widget.stop()
    widget.deleteLater()


@pytest.mark.parametrize(
    ("code", "description", "expected"),
    [
        (0, "晴", "☀️"),
        (61, "小雨", "🌧️"),
        (500, "雾", "🌫️"),
        (999, "未知", "🌡️"),
    ],
)
def test_weather_icon_matches_provider_weather_data(code, description, expected):
    info = type("Info", (), {"code": code, "description": description})()

    assert weather_icon_for(info) == expected


def test_weather_city_carousel_uses_theme_stylesheet(qapp):
    class FakeSource:
        def fetch(self, city, lat, lon, on_ok, on_err):
            pass

    widget = WeatherWidget(
        FakeSource(),
        {
            "weather_enabled": True,
            "weather_refresh_minutes": 30,
        },
    )
    bundle = build_bundle(THEME_LIGHT, DEFAULT_THEME)

    widget.apply_theme(bundle)

    # 样式已统一由 bundle.qss.weather_panel 提供并设置在组件自身，
    # 子控件不再各自持有 stylesheet，这里断言组件级 QSS 的规则内容。
    css = widget.styleSheet()
    assert "QLabel#weather_city_name" in css
    assert "font-weight: 700" in css
    assert bundle.resolver.color("border_color") in css
    widget.stop()
    widget.deleteLater()


def test_weather_widget_clears_old_data_when_disabled(qapp):
    class FakeSource:
        def fetch(self, city, lat, lon, on_ok, on_err):
            pass

    cfg = {
        "weather_enabled": True,
        "weather_city": "杭州",
        "weather_lat": 30.2741,
        "weather_lon": 120.1551,
        "weather_refresh_minutes": 30,
    }
    widget = WeatherWidget(FakeSource(), cfg)
    widget._show_info(
        type(
            "Info",
            (),
            {
                "city": "杭州",
                "temperature": 24,
                "description": "多云",
                "humidity": 60,
                "wind_speed": 5,
                "code": 2,
            },
        )()
    )

    cfg["weather_enabled"] = False
    widget.refresh()

    assert widget._label.text() == "天气未启用"
    assert widget._weather_icon.text() == "—"
    assert widget._label.toolTip() == ""
    widget.stop()
    widget.deleteLater()


def test_weather_widget_switches_and_persists_city(qapp):
    class FakeSource:
        def __init__(self):
            self.requests = []

        def get_cached(self, city, lat, lon):
            return None

        def fetch(self, city, lat, lon, on_ok, on_err):
            self.requests.append((city, lat, lon, on_ok, on_err))

    cfg = {
        "weather_enabled": True,
        "weather_city": "杭州",
        "weather_lat": 30.2741,
        "weather_lon": 120.1551,
        "weather_cities": [
            {"name": "杭州", "lat": 30.2741, "lon": 120.1551},
            {"name": "北京", "lat": 39.9, "lon": 116.4},
        ],
        "weather_refresh_minutes": 30,
    }
    source = FakeSource()
    widget = WeatherWidget(source, cfg)
    assert source.requests[0][:3] == ("杭州", 30.2741, 120.1551)

    widget._btn_next.click()
    assert source.requests[1][:3] == ("北京", 39.9, 116.4)
    assert widget._city_name.text() == "北京"
    assert widget._city_pages.text() == "●  2 / 2"
    assert cfg["weather_city"] == "北京"
    assert cfg["weather_lat"] == 39.9
    assert cfg["weather_lon"] == 116.4

    old_success = source.requests[0][3]
    new_success = source.requests[1][3]
    old_success(
        type(
            "Info",
            (),
            {
                "city": "杭州",
                "temperature": 24,
                "description": "晴",
                "humidity": None,
                "wind_speed": None,
            },
        )()
    )
    assert widget._label.text() != "杭州 24℃ 晴"
    new_success(
        type(
            "Info",
            (),
            {
                "city": "北京",
                "temperature": 18,
                "description": "多云",
                "humidity": None,
                "wind_speed": None,
            },
        )()
    )
    assert widget._label.text() == "北京 18℃ 多云"
    widget._remove_city()
    assert cfg["weather_city"] == "杭州"
    assert len(cfg["weather_cities"]) == 1

    widget._on_city_selected(
        {
            "name": "上海市",
            "lat": 31.2304,
            "lon": 121.4737,
        }
    )
    assert cfg["weather_city"] == "上海市"
    assert cfg["weather_cities"][-1] == {
        "name": "上海市",
        "lat": 31.2304,
        "lon": 121.4737,
    }

    widget.stop()
    widget.deleteLater()


def test_weather_widget_shows_cached_data_and_keeps_it_on_failure(qapp):
    class FakeSource:
        def get_cached(self, city, lat, lon):
            return type(
                "Info",
                (),
                {
                    "city": city,
                    "temperature": 20,
                    "description": "晴",
                    "humidity": None,
                    "wind_speed": None,
                },
            )()

        def fetch(self, city, lat, lon, on_ok, on_err):
            self.fetch_count = getattr(self, "fetch_count", 0) + 1
            self.on_ok = on_ok
            self.on_err = on_err

    source = FakeSource()
    widget = WeatherWidget(
        source,
        {
            "weather_enabled": True,
            "weather_city": "杭州",
            "weather_lat": 30.2741,
            "weather_lon": 120.1551,
            "weather_refresh_minutes": 30,
        },
    )

    assert widget._label.text() == "杭州 20℃ 晴"
    widget.refresh()
    assert source.fetch_count == 1
    source.on_err("offline")
    assert widget._label.text() == "杭州 20℃ 晴"

    widget.stop()
    widget.deleteLater()


def test_weather_source_persists_and_reads_location_cache(qapp, tmp_path, monkeypatch):
    from desktop_calendar.contracts.weather_source import WeatherInfo
    from desktop_calendar.infrastructure.network.weather_source import (
        OpenMeteoSource,
    )

    cache_path = tmp_path / "weather_cache.json"
    monkeypatch.setattr(OpenMeteoSource, "_cache_path", staticmethod(lambda: str(cache_path)))
    source = OpenMeteoSource()
    info = WeatherInfo(
        city="杭州",
        temperature=20,
        code=0,
        description="晴",
        humidity=45,
        wind_speed=3.5,
        updated_at="2026-11-17T15:00",
    )
    source._save_cache(30.2741, 120.1551, info)

    cached = source.get_cached("杭州", 30.2741, 120.1551)
    assert cached == info
    assert source.get_cached("北京", 39.9, 116.4) is None
    source.deleteLater()


def test_weather_city_district_parser(qapp):

    cities = parse_districts(
        "杭州",
        {
            "results": [
                {
                    "name": "杭州市",
                    "level": "city",
                    "country": "中国",
                    "province": "浙江省",
                    "city": "杭州市",
                    "center": {"lat": 30.246566, "lng": 120.209903},
                },
                {
                    "name": "杭州街道",
                    "level": "street",
                    "center": {"lat": 30.2, "lng": 120.1},
                },
                {
                    "name": "无效坐标",
                    "level": "district",
                    "center": {"lat": float("nan"), "lng": 120},
                },
            ],
        },
    )

    assert cities == [
        {
            "name": "杭州市",
            "label": "杭州市，浙江省，中国",
            "lat": 30.246566,
            "lon": 120.209903,
        }
    ]
    with pytest.raises(ValueError, match="没有找到城市"):
        parse_districts("未知", {"results": []})
    with pytest.raises(ValueError, match="数据格式无效"):
        parse_districts("无效", [])


def test_weather_source_falls_back_to_met_no_after_primary_failure(qapp, monkeypatch):
    import json

    from PyQt6.QtCore import QUrl
    from PyQt6.QtNetwork import QNetworkReply

    from desktop_calendar.infrastructure.network.weather_source import (
        OpenMeteoSource,
    )

    class FakeReply:
        def __init__(self, *, error, payload=b"", url="https://weather.test/"):
            self._error = error
            self._payload = payload
            self._url = QUrl(url)

        def deleteLater(self):
            pass

        def error(self):
            return self._error

        def errorString(self):
            return "primary offline"

        def readAll(self):
            return self._payload

        def url(self):
            return self._url

    source = OpenMeteoSource()
    attempts = []
    monkeypatch.setattr(source, "_fetch_provider", lambda *args: attempts.append(args))
    monkeypatch.setattr(source, "_save_cache", lambda *_args: None)
    results = []
    errors = []
    source.fetch("杭州", 30.2741, 120.1551, results.append, errors.append)
    assert attempts[0][5] == 0

    source._on_reply(
        FakeReply(error=QNetworkReply.NetworkError.HostNotFoundError),
        "杭州",
        30.2741,
        120.1551,
        results.append,
        errors.append,
        "open_meteo",
        0,
        [],
    )
    assert attempts[-1][5] == 1
    assert attempts[-1][6] == ["open_meteo: primary offline"]

    source._on_reply(
        FakeReply(error=QNetworkReply.NetworkError.HostNotFoundError),
        "杭州",
        30.2741,
        120.1551,
        results.append,
        errors.append,
        "met_no",
        1,
        ["open_meteo: primary offline"],
    )
    assert attempts[-1][5] == 2
    assert attempts[-1][6] == ["open_meteo: primary offline", "met_no: primary offline"]

    met_payload = {
        "properties": {
            "timeseries": [
                {
                    "time": "2026-11-17T07:00:00Z",
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": 18,
                                "relative_humidity": 70,
                                "wind_speed": 2,
                            }
                        },
                        "next_1_hours": {
                            "summary": {"symbol_code": "partlycloudy_day"},
                        },
                    },
                }
            ],
        },
    }
    met_info = parse_met_no("杭州", met_payload)
    assert met_info.temperature == 18
    assert met_info.description == "局部多云"
    assert met_info.wind_speed == pytest.approx(7.2)

    uapi_payload = {
        "province": "浙江省",
        "city": "杭州市",
        "district": "临安区",
        "weather": "雾",
        "weather_icon": "500",
        "temperature": 14,
        "humidity": 84,
        "report_time": "8 分钟前发布",
    }
    source._on_reply(
        FakeReply(
            error=QNetworkReply.NetworkError.NoError,
            payload=json.dumps(uapi_payload, ensure_ascii=False).encode(),
        ),
        "杭州",
        30.2741,
        120.1551,
        results.append,
        errors.append,
        "uapis",
        2,
        ["open_meteo: primary offline", "met_no: primary offline"],
    )

    assert len(results) == 1
    assert results[0].city == "杭州市"
    assert results[0].temperature == 14
    assert results[0].description == "雾"
    assert results[0].humidity == 84
    assert results[0].wind_speed is None
    assert errors == []
    source.deleteLater()


def test_schedule_panel_and_dialog_display_selected_date(qapp, tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")
    manager.add(title="Review", date="2024-06-10", time="14:00")
    panel = SchedulePanel(manager)
    panel.refresh(date(2024, 6, 10))
    dialog = ScheduleDialog(manager, date(2024, 6, 10))

    assert panel._list.count() == 1
    assert "Review" in panel._list.item(0).text()
    assert not panel._list.item(0).icon().isNull()
    assert "06月10日" in panel._date_label.text()
    assert "星期一" in panel._date_label.text()
    assert "1 项日程" in panel._date_label.text()
    assert not panel._list.isHidden()
    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 1).text() == "Review"
    panel.deleteLater()
    dialog.deleteLater()


def test_schedule_panel_hides_empty_list_until_schedule_exists(qapp, tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")
    panel = SchedulePanel(manager)
    try:
        panel.show()
        qapp.processEvents()
        assert panel._list.isHidden()
        assert "暂无日程" in panel._date_label.text()

        manager.add(title="Review", date=date.today().isoformat())
        panel.refresh(date.today())
        assert not panel._list.isHidden()
        assert panel._list.count() == 1

        manager.remove(manager.all()[0].id)
        panel.refresh(date.today())
        assert panel._list.isHidden()
    finally:
        panel.deleteLater()


def test_schedule_panel_quick_add_button_emits_request(qapp, tmp_path):
    panel = SchedulePanel(ScheduleManager(tmp_path / "schedules.json"))
    requests = []
    panel.quick_add_requested.connect(lambda: requests.append(True))

    panel._quick_add.click()

    assert requests == [True]
    assert panel._quick_add.toolTip() == "快速添加所选日期的全天日程"
    panel.deleteLater()


def test_pomodoro_state_machine_uses_configured_durations(qapp):
    timer = PomodoroTimer(1, 2, 3, rounds_before_long=2)
    finished = []
    timer.round_finished.connect(finished.append)

    timer.start()
    assert timer.phase is Phase.WORK
    assert timer.remaining == 60
    timer._remaining = 1
    timer._on_tick()
    assert timer.phase is Phase.SHORT_BREAK
    assert timer.remaining == 120
    timer.skip()
    assert timer.phase is Phase.WORK
    timer._remaining = 1
    timer._on_tick()
    assert timer.phase is Phase.LONG_BREAK
    assert timer.remaining == 180
    assert finished == [1, 2]
    timer.stop()


def test_pomodoro_logs_only_naturally_completed_work(qapp):
    timer = PomodoroTimer(1, 1, 1, rounds_before_long=2)
    completed = []
    timer.work_completed.connect(
        lambda round_index, seconds: completed.append((round_index, seconds))
    )

    timer.start()
    timer.skip()
    assert completed == []

    timer.skip()
    timer._remaining = 1
    timer._on_tick()
    assert completed == [(2, 60)]
    timer.stop()


def test_focus_log_persists_and_aggregates_by_day(tmp_path):
    path = tmp_path / "focus_log.json"
    log = FocusLog(str(path))
    log.add(25, started_at=datetime(2024, 6, 10, 9, 0))
    log.add(25, started_at=datetime(2024, 6, 10, 10, 0))
    log.add(15, started_at=datetime(2024, 6, 9, 10, 0))

    reloaded = FocusLog(str(path))

    assert reloaded.today_count(date(2024, 6, 10)) == 2
    assert reloaded.today_minutes(date(2024, 6, 10)) == 50
    assert reloaded.recent(2, date(2024, 6, 10)) == [
        (date(2024, 6, 9), 1, 15),
        (date(2024, 6, 10), 2, 50),
    ]


def test_pomodoro_rejects_non_positive_duration():
    with pytest.raises(ValueError):
        PomodoroTimer(work_min=0)


def test_pomodoro_dialog_controls_timer(qapp):
    timer = PomodoroTimer(1, 1, 1, rounds_before_long=2)
    dialog = PomodoroDialog(timer)

    dialog._btn_start.click()
    assert timer.phase is Phase.WORK
    assert dialog._btn_start.text() == "暂停"
    dialog._btn_start.click()
    assert timer.paused
    assert dialog._btn_start.text() == "继续"
    dialog._btn_reset.click()
    assert timer.phase is Phase.IDLE
    assert dialog._btn_start.text() == "开始"

    timer.stop()
    dialog.close()
    dialog.deleteLater()


def test_pomodoro_dialog_shows_focus_log_summary(qapp, tmp_path):
    log = FocusLog(str(tmp_path / "focus_log.json"))
    timer = PomodoroTimer(1, 1, 1, rounds_before_long=2)
    timer.work_completed.connect(lambda _round, seconds: log.add(max(1, round(seconds / 60))))
    dialog = PomodoroDialog(timer, focus_log=log)
    try:
        assert dialog._lbl_stats.text() == "今日尚未开始专注"
        timer.start()
        timer._remaining = 1
        timer._on_tick()
        assert dialog._lbl_stats.text() == "今日专注 1 次 · 0h01m"
    finally:
        timer.stop()
        dialog.deleteLater()


def test_schedule_remind_dialog_returns_snooze_choice(qapp):
    dialog = ScheduleRemindDialog("Review meeting")
    try:
        dialog._choose_snooze(15)
        assert dialog.snooze_minutes == 15
    finally:
        dialog.deleteLater()


def test_weather_text_is_rendered_for_info_panel():
    assert format_weather("杭州", 24.4, "多云") == "杭州 24℃ 多云"


def test_recurring_schedule_reminder_uses_occurrence_date(qapp, monkeypatch):
    import desktop_calendar.core.schedule_reminder as reminder_module

    fixed_now = datetime(2024, 6, 10, 8, 55, 30)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    class Manager:
        def on(self, _day):
            return [
                Schedule(
                    id="daily-1",
                    title="Daily reminder",
                    date="2024-06-01",
                    time="09:00",
                    repeat="daily",
                    remind_minutes=5,
                )
            ]

    monkeypatch.setattr(reminder_module, "datetime", FixedDateTime)
    reminder = ScheduleReminder(Manager(), interval_ms=60_000)
    due = []
    reminder.due.connect(lambda schedule_id, title: due.append((schedule_id, title)))

    reminder._check()
    reminder._check()

    assert due == [("daily-1", "Daily reminder")]
    reminder.stop()


def test_schedule_reminder_snooze_persists_and_fires_after_deadline(qapp, tmp_path, monkeypatch):
    import desktop_calendar.core.schedule_reminder as reminder_module

    now = datetime(2024, 6, 10, 8, 55)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(reminder_module, "datetime", FixedDateTime)
    manager = ScheduleManager(tmp_path / "schedules.json")
    schedule = manager.add(
        title="Standup",
        date="2024-06-10",
        time="09:00",
        remind_minutes=5,
    )
    reminder = ScheduleReminder(manager, interval_ms=60_000)
    due = []
    reminder.due.connect(lambda schedule_id, title: due.append((schedule_id, title)))

    reminder._check()
    assert due == [(schedule.id, "Standup")]
    assert reminder.snooze(schedule.id, 5)
    assert manager.all()[0].snoozed_until == "2024-06-10T09:00:00"
    reminder._check()
    assert len(due) == 1

    now = datetime(2024, 6, 10, 9, 0)
    reminder._check()
    assert len(due) == 2
    assert manager.all()[0].snoozed_until == ""
    reminder.stop()


def test_weather_city_picker_loads_and_selects_province_city(qapp):
    from desktop_calendar.ui.dialogs.city_picker import CityPickerDialog

    class FakeSource:
        def __init__(self):
            self.requests = []

        def list_cities(self, province, adcode, on_ok, on_err):
            self.requests.append((province, adcode, on_ok, on_err))

    source = FakeSource()
    dialog = CityPickerDialog(source)
    selected = []
    dialog.city_selected.connect(selected.append)
    try:
        assert source.requests[0][:2] == ("北京市", "110000")

        dialog.province_combo.setCurrentIndex(dialog.province_combo.findData("330000"))
        assert source.requests[1][:2] == ("浙江省", "330000")

        source.requests[1][2](
            [
                {"name": "杭州市", "lat": 30.246566, "lon": 120.209903},
                {"name": "宁波市", "lat": 29.860258, "lon": 121.62454},
            ]
        )
        dialog.city_combo.setCurrentIndex(1)
        dialog.accept()

        assert selected == [
            {
                "name": "宁波市",
                "lat": 29.860258,
                "lon": 121.62454,
            }
        ]
    finally:
        dialog.deleteLater()


def test_weather_city_picker_is_styled_with_opaque_background(qapp):
    from desktop_calendar.ui.dialogs.city_picker import CityPickerDialog

    class FakeSource:
        def list_cities(self, province, adcode, on_ok, on_err):
            on_ok([])

    bundle = build_bundle("dark", dict(DEFAULT_THEME))
    dialog = CityPickerDialog(FakeSource(), bundle=bundle)
    try:
        assert dialog.autoFillBackground()
        assert dialog.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        assert "border: 1px solid" in dialog.styleSheet()
        assert "background:" in dialog.styleSheet()
    finally:
        dialog.deleteLater()


def test_weather_city_directory_parser_filters_non_city_results():

    cities = parse_cities_in_province(
        "浙江省",
        {
            "results": [
                {"name": "浙江省", "level": "province", "center": {"lat": 30.2, "lng": 120.1}},
                {
                    "name": "杭州市",
                    "level": "city",
                    "province": "浙江省",
                    "country": "中国",
                    "center": {"lat": 30.2, "lng": 120.1},
                },
                {
                    "name": "上城区",
                    "level": "district",
                    "province": "浙江省",
                    "center": {"lat": 30.2, "lng": 120.1},
                },
            ],
        },
    )

    assert cities == [
        {
            "name": "杭州市",
            "lat": 30.2,
            "lon": 120.1,
            "label": "杭州市，浙江省，中国",
        }
    ]
    with pytest.raises(ValueError, match="没有找到城市"):
        parse_cities_in_province("浙江省", {"results": []})


def test_weather_district_parser_keeps_adcode_for_same_name():

    cities = parse_districts(
        "朝阳区",
        {
            "results": [
                {
                    "name": "朝阳区",
                    "level": "district",
                    "province": "北京市",
                    "city": "北京城区",
                    "adcode": "110105",
                    "center": {"lat": 39.921444, "lng": 116.443136},
                },
                {
                    "name": "朝阳区",
                    "level": "district",
                    "province": "吉林省",
                    "city": "长春市",
                    "adcode": "220104",
                    "center": {"lat": 43.833845, "lng": 125.288168},
                },
                {
                    "name": "朝阳区街道",
                    "level": "street",
                    "adcode": "231282",
                    "center": {"lat": 46.07, "lng": 125.99},
                },
            ],
        },
    )

    # 街道级结果被过滤，同名区县靠 adcode 区分
    assert [(city["name"], city["adcode"]) for city in cities] == [
        ("朝阳区", "110105"),
        ("朝阳区", "220104"),
    ]


def test_weather_city_keeps_valid_adcode_only():
    assert (
        valid_city(
            {
                "name": "朝阳区",
                "lat": 43.833845,
                "lon": 125.288168,
                "adcode": "220104",
            }
        )["adcode"]
        == "220104"
    )
    assert "adcode" not in valid_city(
        {
            "name": "朝阳区",
            "lat": 43.833845,
            "lon": 125.288168,
            "adcode": "../etc/passwd",
        }
    )


def test_weather_widget_forwards_adcode_to_source(qapp):
    class FakeSource:
        def __init__(self):
            self.calls = []

        def get_cached(self, city, lat, lon):
            return None

        def fetch(self, city, lat, lon, on_ok, on_err, adcode=None):
            self.calls.append((city, adcode))

    source = FakeSource()
    widget = WeatherWidget(
        source,
        {
            "weather_enabled": True,
            "weather_city": "朝阳区",
            "weather_lat": 43.833845,
            "weather_lon": 125.288168,
            "weather_cities": [
                {
                    "name": "朝阳区",
                    "lat": 43.833845,
                    "lon": 125.288168,
                    "adcode": "220104",
                }
            ],
            "weather_refresh_minutes": 30,
        },
    )
    try:
        assert source.calls[0] == ("朝阳区", "220104")
    finally:
        widget.stop()
        widget.deleteLater()


def test_elided_label_keeps_full_text(qapp):
    from desktop_calendar.ui.widgets.elided_label import ElidedLabel

    label = ElidedLabel()
    label.setFixedWidth(60)
    label.setText("巴音郭楞蒙古自治州")
    label.show()
    qapp.processEvents()

    assert label.full_text() == "巴音郭楞蒙古自治州"
    assert label.text().endswith("…")


def test_calendar_fonts_shrink_to_fit_short_cells(qapp):
    from types import SimpleNamespace

    from PyQt6.QtGui import QFont, QFontMetrics

    from desktop_calendar.ui.calendar_widget import LunarCalendarWidget

    day = QFont()
    day.setPointSize(13)
    small = QFont()
    small.setPointSize(10)
    fake = SimpleNamespace(
        _day_font=day,
        _small_font=small,
        _day_text_h=QFontMetrics(day).height(),
        _small_text_h=QFontMetrics(small).height(),
        _day_pt=13.0,
        _small_pt=10.0,
    )

    day_font, small_font, day_h, small_h = LunarCalendarWidget._fitted_fonts(fake, 20)

    # 矮格子必须缩字号，且两行加起来不超过可用高度
    assert day_h + small_h <= 20
    assert day_font.pointSizeF() < 13
    assert small_font.pointSizeF() < 10


def test_schedule_panel_list_height_grows_with_items(qapp, tmp_path):
    manager = ScheduleManager(tmp_path / "schedules.json")
    manager.add(title="评审", date="2026-11-20", time="09:00")
    panel = SchedulePanel(manager)
    panel.apply_theme(build_bundle(THEME_LIGHT, dict(DEFAULT_THEME)))
    panel.resize(420, 200)
    panel.show()
    qapp.processEvents()
    try:
        panel.refresh(date(2026, 11, 20))
        qapp.processEvents()
        one_item = panel._list.height()

        for hour in ("10:00", "11:00"):
            manager.add(title="评审", date="2026-11-20", time=hour)
        panel.refresh(date(2026, 11, 20))
        qapp.processEvents()
        three_items = panel._list.height()

        # 条目多了列表要变高（到上限后再滚动），而不是固定一行
        assert three_items > one_item
    finally:
        panel.deleteLater()


def test_weather_widget_fixed_metrics_follow_ui_scale(qapp):
    class FakeSource:
        def get_cached(self, city, lat, lon):
            return None

        def fetch(self, city, lat, lon, on_ok, on_err):
            pass

    widget = WeatherWidget(FakeSource(), {"weather_enabled": True, "weather_refresh_minutes": 30})
    try:
        at_default = bundle_for_scale(1.0)
        widget.apply_theme(at_default)
        wide = widget._btn_previous.width()

        at_small = bundle_for_scale(0.8)
        widget.apply_theme(at_small)
        narrow = widget._btn_previous.width()

        assert wide == round(28 * 1.0)
        assert narrow == round(28 * 0.8)
        assert narrow < wide
    finally:
        widget.stop()
        widget.deleteLater()


def test_uapis_fallback_request_prefers_adcode(qapp):
    from PyQt6.QtCore import QObject, pyqtSignal

    from desktop_calendar.infrastructure.network.weather_source import (
        OpenMeteoSource,
    )

    class FakeReply(QObject):
        finished = pyqtSignal()

    class FakeNam:
        def __init__(self):
            self.urls = []

        def get(self, request):
            self.urls.append(request.url())
            return FakeReply()

    source = OpenMeteoSource()
    source._nam = FakeNam()
    try:
        # provider_index=2 即 uapis 兜底
        source._fetch_provider(
            "朝阳区", 43.833845, 125.288168, lambda info: None, lambda error: None, 2, [], "220104"
        )
        query = source._nam.urls[-1].query()
    finally:
        source.deleteLater()

    assert "adcode=220104" in query
    assert "city=" in query


@pytest.mark.parametrize(
    ("icon", "text", "wmo"),
    [
        ("100", "晴", 0),
        ("150", "晴", 0),
        ("101", "多云", 2),
        ("102", "少云", 1),
        ("104", "阴", 3),
        ("300", "阵雨", 80),
        ("302", "雷阵雨", 95),
        ("305", "小雨", 61),
        ("307", "大雨", 65),
        ("313", "冻雨", 66),
        ("404", "雨夹雪", 66),
        ("407", "阵雪", 85),
        ("501", "雾", 45),
        ("509", "浓雾", 48),
        ("503", "扬沙", 45),
        ("900", "热", 0),
        ("999", "小雨", 61),  # 未知图标码回退到文本判断
        ("999", "说不清的天气", 3),  # 文本也判断不出，按阴处理
    ],
)
def test_uapis_icon_code_maps_to_wmo(icon, text, wmo):

    info = parse_uapis(
        "杭州",
        {
            "city": "杭州市",
            "temperature": 20,
            "weather": text,
            "weather_icon": icon,
            "humidity": 60,
        },
    )

    assert info.code == wmo
    assert info.description == text


def test_freeze_rain_code_is_consistent_across_providers():
    from desktop_calendar.infrastructure.network.weather_source.codes import wmo_description

    # met.no 的 sleet 与 uapis 的「冻雨」必须落到同一个 WMO 代码
    assert weather_codes._MET_WMO["lightsleet"] == 66
    assert weather_codes._MET_WMO["sleet"] == weather_codes._UAPI_WMO[313] == 66
    assert weather_codes._MET_WMO["heavysleet"] == 67
    assert wmo_description(66) == "轻度冻雨"
    assert wmo_description(67) == "强冻雨"

    met_payload = {
        "properties": {
            "timeseries": [
                {
                    "time": "2026-11-20T06:00:00Z",
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": -1,
                                "relative_humidity": 90,
                            }
                        },
                        "next_1_hours": {"summary": {"symbol_code": "sleet_day"}},
                    },
                }
            ]
        },
    }
    met_info = parse_met_no("杭州", met_payload)
    uapi_info = parse_uapis(
        "杭州",
        {
            "city": "杭州市",
            "temperature": -1,
            "weather": "冻雨",
            "weather_icon": "313",
            "humidity": 90,
        },
    )

    assert met_info.code == uapi_info.code == 66
    assert met_info.description == "轻度冻雨"
