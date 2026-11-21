# coding: utf-8
"""应用图标资源：存在性、尺寸与多尺寸 ICO 结构（不依赖 Pillow）。"""

import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

ICO_SIZES = {16, 24, 32, 48, 64, 128, 256}
THEME_PNGS = {
    "light": "assets/light/icon_light.png",
    "dark": "assets/dark/icon_dark.png",
    "sakura": "assets/sakura/sakura.png",
}


def _ico_sizes(path: Path) -> set[int]:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1), f"{path} 不是 ICO 文件"
    sizes = set()
    for index in range(count):
        width, height = struct.unpack_from("<BB", data, 6 + index * 16)
        assert width == height, f"{path} 第 {index} 张不是正方形"
        sizes.add(256 if width == 0 else width)
    return sizes


def _png_size(path: Path) -> tuple[int, int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} 不是 PNG"
    width, height = struct.unpack(">II", data[16:24])
    color_type = data[25]  # 6 = RGBA
    return width, height, color_type


@pytest.mark.parametrize(("theme", "rel"), sorted(THEME_PNGS.items()))
def test_theme_icon_assets(theme, rel):
    png = ROOT / rel
    assert png.exists(), f"缺少 {rel}"
    width, height, color_type = _png_size(png)
    assert (width, height) == (256, 256)
    assert color_type == 6, "主题图标必须带 alpha 通道"

    theme_dir = png.parent
    for size in (16, 32, 48):
        ico = theme_dir / f"theme_{size}x{size}.ico"
        assert ico.exists(), f"{theme} 缺少 theme_{size}x{size}.ico"
        assert _ico_sizes(ico) == {size}

    multi = theme_dir / "theme_256x256.ico"
    assert multi.exists()
    assert ICO_SIZES <= _ico_sizes(multi), "256 图标应包含全部常用尺寸"


def test_fallback_icon_for_build_and_installer():
    """PyInstaller spec / Inno Setup / IconManager 兜底都用 assets/app.ico。"""
    ico = ASSETS / "app.ico"
    assert ico.exists(), "缺少 assets/app.ico（打包与安装器图标会失效）"
    assert ICO_SIZES <= _ico_sizes(ico)

    app_png = ASSETS / "app.png"
    assert app_png.exists()
    assert _png_size(app_png)[:2] == (512, 512)


def test_icon_manager_maps_to_existing_files():
    from desktop_calendar.ui.icon_manager import IconManager

    for theme, info in IconManager.THEME_ICON_MAP.items():
        path = ASSETS / info["dir"] / info["file"]
        assert path.exists(), f"主题 {theme} 的图标文件缺失: {path}"
        assert (ASSETS / info["dir"] / "theme_256x256.ico").exists()
