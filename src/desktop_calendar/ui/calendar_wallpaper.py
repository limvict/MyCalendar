"""Calendar wallpaper loading, storage, and clipped painting helpers."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

from PyQt6.QtCore import QRectF, QSizeF, Qt
from PyQt6.QtGui import (
    QColor,
    QImage,
    QImageReader,
    QPainter,
    QPainterPath,
    QPixmap,
)

from desktop_calendar.utils.paths import get_app_data_dir

_SUPPORTED_FORMATS = {
    b"bmp": "bmp",
    b"jpeg": "jpg",
    b"jpg": "jpg",
    b"png": "png",
    b"webp": "webp",
}
_WALLPAPER_PREFIX = "calendar-wallpaper."
_STORED_NAME = re.compile(r"^calendar-wallpaper-[0-9a-f]{16}\.(?:bmp|jpg|png|webp)$")
_MAX_IMAGE_EDGE = 2560


def _read_image(path: str) -> tuple[QImage, bytes, str]:
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    image_format = bytes(reader.format()).lower()
    size = reader.size()
    if not size.isEmpty() and max(size.width(), size.height()) > _MAX_IMAGE_EDGE:
        reader.setScaledSize(
            size.scaled(_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE, Qt.AspectRatioMode.KeepAspectRatio)
        )
    image = reader.read()
    return image, image_format, reader.errorString()


def load_wallpaper(path: str | None) -> QPixmap | None:
    if not isinstance(path, str) or not path:
        return None
    image, _image_format, _error = _read_image(path)
    pixmap = QPixmap.fromImage(image)
    return pixmap if not pixmap.isNull() else None


def store_wallpaper(source: str) -> str:
    image, image_format, error = _read_image(source)
    if image.isNull():
        raise ValueError(f"无法读取图片：{error}")

    extension = _SUPPORTED_FORMATS.get(image_format)
    if extension is None:
        raise ValueError(f"不支持的图片格式：{image_format.decode(errors='replace')}")

    target_dir = Path(get_app_data_dir())
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with open(source, "rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    target = target_dir / (f"calendar-wallpaper-{digest.hexdigest()[:16]}.{extension}")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target_dir, prefix=_WALLPAPER_PREFIX, suffix=".tmp", delete=False
        ) as temp:
            temp_path = Path(temp.name)
        shutil.copyfile(source, temp_path)
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
    return str(target)


def remove_stored_wallpaper(path: str | None) -> None:
    if not isinstance(path, str) or not path:
        return
    target = Path(path)
    app_data = Path(get_app_data_dir())
    if target.parent.resolve() != app_data.resolve() or not _STORED_NAME.fullmatch(target.name):
        return
    try:
        target.unlink()
    except FileNotFoundError:
        pass


def draw_wallpaper(
    painter: QPainter,
    rect: QRectF,
    canvas_size: QSizeF,
    pixmap: QPixmap | None,
    overlay_color,
    overlay_percent: int,
    *,
    radius: float = 0,
) -> bool:
    if pixmap is None or pixmap.isNull() or canvas_size.isEmpty():
        return False

    source_width = pixmap.width()
    source_height = pixmap.height()
    scale = max(
        canvas_size.width() / source_width,
        canvas_size.height() / source_height,
    )
    scaled_width = source_width * scale
    scaled_height = source_height * scale
    offset_x = (canvas_size.width() - scaled_width) / 2
    offset_y = (canvas_size.height() - scaled_height) / 2
    source_rect = QRectF(
        (rect.x() - offset_x) / scale,
        (rect.y() - offset_y) / scale,
        rect.width() / scale,
        rect.height() / scale,
    )

    painter.save()
    if radius > 0:
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
    painter.drawPixmap(rect, pixmap, source_rect)
    overlay = QColor(overlay_color)
    overlay.setAlpha(round(255 * max(0, min(100, overlay_percent)) / 100))
    painter.fillRect(rect, overlay)
    painter.restore()
    return True
