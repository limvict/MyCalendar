from PyQt6.QtCore import QRectF, QSizeF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap

from desktop_calendar.ui.calendar_wallpaper import (
    draw_wallpaper,
    load_wallpaper,
    store_wallpaper,
)
from desktop_calendar.ui.calendar_widget import LunarCalendarWidget
from desktop_calendar.ui.theme.manager import ThemeManager


def test_store_wallpaper_copies_and_loads_image(qapp, tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    image = QImage(32, 24, QImage.Format.Format_RGB32)
    image.fill(QColor("#4488CC"))
    assert image.save(str(source))
    data_dir = tmp_path / "app-data"
    monkeypatch.setattr(
        "desktop_calendar.ui.calendar_wallpaper.get_app_data_dir", lambda: str(data_dir)
    )

    stored = store_wallpaper(str(source))

    assert stored.startswith(str(data_dir))
    assert load_wallpaper(stored).size() == image.size()
    assert load_wallpaper("") is None


def test_draw_wallpaper_preserves_theme_color(qapp):
    wallpaper = QPixmap(20, 20)
    wallpaper.fill(QColor("#336699"))
    surface = QImage(40, 40, QImage.Format.Format_ARGB32)
    surface.fill(Qt.GlobalColor.transparent)
    painter = QPainter(surface)
    color = QColor("#FFFFFF")

    assert draw_wallpaper(painter, QRectF(0, 0, 40, 40), QSizeF(40, 40), wallpaper, color, 50)

    painter.end()
    assert color.alpha() == 255
    assert surface.pixelColor(20, 20).alpha() == 255


def test_month_calendar_paints_wallpaper(qapp, fresh_config_manager, qtbot):
    bundle = ThemeManager(fresh_config_manager).current
    calendar = LunarCalendarWidget(None, bundle, [])
    qtbot.addWidget(calendar)
    calendar.resize(420, 320)
    wallpaper = QPixmap(32, 24)
    wallpaper.fill(QColor("#4488CC"))
    calendar.set_wallpaper(wallpaper, 58)
    calendar.show()
    qtbot.wait(10)

    assert not calendar.grab().isNull()
