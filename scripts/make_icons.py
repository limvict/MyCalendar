#!/usr/bin/env python3
# coding: utf-8
"""生成应用图标：一套几何（日历卡 + 日期 + 弯月），三套主题配色。

设计要点：
- 主体是「日历卡」：圆角页 + 顶部色带 + 两个装订环，16px 下仍能认出是日历；
- 页面上是当天日期数字（15），顶栏右侧一枚弯月，点出「农历」这个项目特色；
- 三套配色跟随应用主题（light / dark / sakura），几何完全一致，切换主题只换色。

用法（仅开发期需要 Pillow，运行时不依赖）：
    python scripts/make_icons.py
产物：
    assets/<theme>/icon_<name>.png        256×256 预览图
    assets/<theme>/theme_<size>.ico       16/32/48 单尺寸 + 256 多尺寸
    assets/app.ico                        light 主题多尺寸（PyInstaller / 安装器兜底图标）
    assets/app.png                        512×512 高清图（文档 / 商店用）
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

MASTER = 1024
PREVIEW = 256
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# 配色取自 config/constants.py 的主题色（bg_main / date_text_color / today_bg / border_color），
# 主色 today_bg 用作顶部色带，保证与应用内强调色一致。
THEMES: dict[str, dict[str, str]] = {
    "light": {
        "name": "icon_light",
        "page": "#FBF8F3",
        "bar": "#7C947E",
        "ink": "#33302B",
        "border": "#D8D2C5",
        "moon": "#E9B45C",
        "ring": "#BCB4A6",
    },
    "dark": {
        "name": "icon_dark",
        "page": "#232327",
        "bar": "#10B981",
        "ink": "#F4F4F5",
        "border": "#4A4A52",
        "moon": "#F0C24E",
        "ring": "#3F3F47",
    },
    "sakura": {
        "name": "sakura",
        "page": "#FFF7F9",
        "bar": "#D9788E",
        "ink": "#5C2E3A",
        "border": "#F0CAD3",
        "moon": "#E7A96A",
        "ring": "#E6BCC6",
    },
}

FONT_CANDIDATES = ("seguibl.ttf", "seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "msyhbd.ttc")
WINDOWS_FONTS = pathlib.Path("C:/Windows/Fonts")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in FONT_CANDIDATES:
        path = WINDOWS_FONTS / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def render(palette: dict[str, str]) -> Image.Image:
    """按调色板渲染 1024×1024 主图。"""
    img = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    card = (112, 104, 912, 920)
    radius = 168

    # 装订环先画：卡片会盖住下半部分，只露出顶部两个小耳朵
    ring_w, ring_top, ring_bottom = 46, 40, 226
    for cx in (340, 684):
        draw.rounded_rectangle(
            (cx - ring_w // 2, ring_top, cx + ring_w // 2, ring_bottom),
            radius=ring_w // 2,
            fill=palette["ring"],
        )

    # 卡片单独一层：色带 + 纸张 + 弯月，最后统一按圆角裁切，
    # 避免“咬月牙”的圆越过圆角画到图标外面
    card_layer = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card_layer)
    bar_bottom = 300
    cd.rounded_rectangle(card, radius=radius, fill=palette["bar"])
    cd.rounded_rectangle(
        (card[0], bar_bottom, card[2], card[3]),
        radius=radius,
        fill=palette["page"],
    )
    # 页面顶部两角要方：把圆角弧线那段用纸张色补成直角
    cd.rectangle((card[0], bar_bottom, card[2], bar_bottom + radius), fill=palette["page"])

    # 弯月：顶栏右侧，用「两个圆的差」切出月牙
    moon_cx, moon_cy, moon_r = 784, 212, 60
    cd.ellipse(
        (moon_cx - moon_r, moon_cy - moon_r, moon_cx + moon_r, moon_cy + moon_r),
        fill=palette["moon"],
    )
    cut_dx, cut_dy = 34, -28
    cd.ellipse(
        (
            moon_cx - moon_r + cut_dx,
            moon_cy - moon_r + cut_dy,
            moon_cx + moon_r + cut_dx,
            moon_cy + moon_r + cut_dy,
        ),
        fill=palette["bar"],
    )

    mask = Image.new("L", (MASTER, MASTER), 0)
    ImageDraw.Draw(mask).rounded_rectangle(card, radius=radius, fill=255)
    card_layer.putalpha(
        Image.composite(card_layer.getchannel("A"), Image.new("L", (MASTER, MASTER), 0), mask)
    )
    img.alpha_composite(card_layer)

    # 日期数字：页面上居中，字重足够粗，缩小到 16px 仍有辨识度
    draw.text(
        ((card[0] + card[2]) // 2, 640),
        "15",
        font=_font(420),
        fill=palette["ink"],
        anchor="mm",
    )

    # 描边：浅色桌面上也能和背景分开
    draw.rounded_rectangle(card, radius=radius, outline=palette["border"], width=6)
    return img


def save_theme(theme: str, palette: dict[str, str], master: Image.Image) -> None:
    theme_dir = ASSETS / theme
    theme_dir.mkdir(parents=True, exist_ok=True)

    preview = master.resize((PREVIEW, PREVIEW), Image.LANCZOS)
    preview.save(theme_dir / f"{palette['name']}.png")

    # 单尺寸 ico：保持 IconManager 既有文件名
    for size in (16, 32, 48):
        icon = master.resize((size, size), Image.LANCZOS)
        icon.save(theme_dir / f"theme_{size}x{size}.ico", sizes=[(size, size)])

    # 256 文件名保留，但内部含全部尺寸：任务栏/Alt+Tab 各档都清晰
    multi = master.resize((256, 256), Image.LANCZOS)
    multi.save(theme_dir / "theme_256x256.ico", sizes=[(s, s) for s in ICO_SIZES])


def main() -> int:
    masters: dict[str, Image.Image] = {}
    for theme, palette in THEMES.items():
        master = render(palette)
        masters[theme] = master
        save_theme(theme, palette, master)
        print(f"wrote assets/{theme}/")

    # 兜底图标（IconManager 最后一级 / PyInstaller / Inno Setup 都用它）
    light = masters["light"]
    light.resize((512, 512), Image.LANCZOS).save(ASSETS / "app.png")
    light.resize((256, 256), Image.LANCZOS).save(
        ASSETS / "app.ico", sizes=[(s, s) for s in ICO_SIZES]
    )
    print("wrote assets/app.ico, assets/app.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
