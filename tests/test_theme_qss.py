# coding: utf-8
"""theme/qss：字体族、SVG data URI、深色 compact、三 kind。"""

import re
from pathlib import Path

import pytest

from desktop_calendar.config.constants import DEFAULT_THEME, THEME_PRESETS
from desktop_calendar.ui.theme import qss
from desktop_calendar.ui.theme.qss import palette as qss_palette
from desktop_calendar.ui.theme.resolver import ThemeResolver


def _r(overrides=None):
    theme = dict(DEFAULT_THEME)
    if overrides:
        theme.update(overrides)
    return ThemeResolver(theme)


class TestFontFamily:
    def test_quoted(self):
        r = _r({"font_family": "微软雅黑,SimHei"})
        result = qss_palette._font_family(r)
        assert '"微软雅黑"' in result
        assert '"SimHei"' in result

    def test_generic_unquoted(self):
        r = _r({"font_family": "sans-serif"})
        assert qss_palette._font_family(r) == "sans-serif"

    def test_mixed(self):
        r = _r({"font_family": "微软雅黑,sans-serif"})
        result = qss_palette._font_family(r)
        assert '"微软雅黑"' in result
        assert "sans-serif" in result
        # 通用族不应被引号
        assert '"sans-serif"' not in result

    def test_empty_falls_back(self):
        r = _r({"font_family": ""})
        assert qss_palette._font_family(r) == "sans-serif"


class TestSvgUri:
    def test_format(self):
        # QSS 不认 data URI：可写时返回文件 url(...)，只读目录时降级为空串
        uri = qss_palette._svg_uri("<svg></svg>")
        assert uri == "" or uri.startswith('url("')


class TestDialogButtons:
    def test_light_no_compact(self):
        r = _r({"bg_main": "#FFFFFF"})
        css = qss.dialog_buttons(r)
        assert "QPushButton" in css
        assert "QPushButton:hover" in css
        assert "QPushButton:pressed" in css

    def test_dark_compact(self):
        r = _r({"bg_main": "#000000"})
        css = qss.dialog_buttons(r)
        assert "QPushButton" in css


class TestMessageBox:
    @pytest.mark.parametrize("kind", ["info", "warn", "error"])
    def test_three_kinds(self, kind):
        r = _r()
        css = qss.message_box(r, kind)
        assert "QMessageBox" in css
        assert "QMessageBox QPushButton" in css


class TestKeySections:
    def test_calendar(self):
        assert "QCalendarWidget" in qss.calendar(_r())

    def test_nav_buttons_use_theme_color_for_hover_and_focus(self):
        css = qss.nav_buttons(_r())
        assert "QPushButton:hover" in css
        assert "QPushButton:focus" in css
        assert "border-color:" in css

    def test_dialog_inputs_has_svg_arrows(self):
        css = qss.dialog_inputs(_r())
        assert "QComboBox::down-arrow" in css
        # 时间/日期编辑框同样使用主题箭头
        assert "QAbstractSpinBox::up-arrow" in css
        assert "QAbstractSpinBox::down-arrow" in css

    def test_checkbox_indicator(self):
        css = qss.dialog_checkboxes(_r())
        assert "QCheckBox::indicator" in css
        assert "QRadioButton::indicator:checked" in css

    def test_menu(self):
        assert "QMenu::item:selected" in qss.menu(_r())


_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _rule_body(css: str, selector: str) -> str:
    for raw_selector, body in _RULE.findall(css):
        if selector in raw_selector:
            return body.lower()
    raise AssertionError(f"没有找到规则 {selector}")


def _hover_bodies(css: str) -> list[tuple[str, str]]:
    return [
        (raw_selector.strip(), body.lower())
        for raw_selector, body in _RULE.findall(css)
        if ":hover" in raw_selector
    ]


class TestUnifiedHover:
    """悬停统一约定见 qss._hover_accent 的 docstring。"""

    def _blocks(self):
        r = _r()
        return {
            "nav_buttons": qss.nav_buttons(r),
            "today_button": qss.today_button(r),
            "message_box": qss.message_box(r, "info"),
            "dialog_buttons": qss.dialog_buttons(r),
            "dialog_inputs": qss.dialog_inputs(r),
            "dialog_checkboxes": qss.dialog_checkboxes(r),
            "dialog_list": qss.dialog_list(r),
            "schedule_panel": qss.schedule_panel(r),
            "sidebar_services": qss.sidebar_services(r),
            "weather_panel": qss.weather_panel(r),
            "calendar": qss.calendar(r),
            "scrollbar": qss.scrollbar(r),
        }

    def test_hover_border_uses_one_accent(self):
        accent = DEFAULT_THEME["today_bg"].lower()
        legacy = DEFAULT_THEME["msg_info_btn"].lower()
        for name, css in self._blocks().items():
            rules = _hover_bodies(css)
            assert rules, f"{name} 没有任何 hover 规则"
            for selector, body in rules:
                assert legacy not in body, (name, selector)
                if "border-color" in body:
                    assert accent in body, (name, selector, body)

    def test_hover_never_repaints_text(self):
        # 只有纯文字控件（侧边栏标题）允许在悬停时改文字色
        text_only = {"sidebar_services_toggle"}
        for name, css in self._blocks().items():
            for selector, body in _hover_bodies(css):
                if any(token in selector for token in text_only):
                    continue
                assert "color:" not in body.replace("background-color", "").replace(
                    "border-color", ""
                ), (name, selector, body)

    def test_items_hover_share_menu_hover(self):
        hover = DEFAULT_THEME["menu_hover"].lower()
        r = _r()
        checks = (
            ("menu_selected", qss.menu(r), "QMenu::item:selected"),
            ("dialog_list", qss.dialog_list(r), "QListWidget::item:hover"),
            ("schedule_list", qss.schedule_panel(r), "QListWidget::item:hover"),
            ("combo_items", qss.dialog_inputs(r), "QComboBox QAbstractItemView::item:hover"),
        )
        for name, css, selector in checks:
            body = _rule_body(css, selector)
            assert hover in body, (name, body)
            assert "color:" not in body.replace("background-color", ""), name


class TestMessageIcon:
    """消息框图标改由主题色绘制，不再用系统原生图标。"""

    @pytest.mark.parametrize(
        ("kind", "fill_key"),
        [
            ("info", "msg_info_btn"),
            ("warn", "msg_warn_btn"),
            ("error", "msg_error_btn"),
        ],
    )
    def test_icon_fill_follows_theme(self, qapp, kind, fill_key):
        from desktop_calendar.ui.dialog_styles import build_message_icon

        pixmap = build_message_icon(dict(DEFAULT_THEME), kind)
        assert not pixmap.isNull()
        image = pixmap.toImage()
        size = pixmap.width()
        # 四角透明（圆形），圆内是消息框按钮的同色填充
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(2, size // 2).name() == (DEFAULT_THEME[fill_key].lower())

    def test_icon_rejects_unknown_kind(self, qapp):
        from desktop_calendar.ui.dialog_styles import build_message_icon

        with pytest.raises(KeyError):
            build_message_icon(dict(DEFAULT_THEME), "nope")


class TestSvgAssets:
    """QSS 的 image 只认文件路径，图标必须先落盘。"""

    def test_asset_written_and_url_returned(self, tmp_path):
        from desktop_calendar.ui.theme import svg_assets

        url = svg_assets.asset_url(
            "<svg xmlns='http://www.w3.org/2000/svg'/>", directory=str(tmp_path)
        )

        assert url.startswith('url("')
        path = url[len('url("') : -2]
        assert Path(path).is_file()
        assert "<svg" in Path(path).read_text(encoding="utf-8")

    def test_write_failure_degrades_to_empty(self, tmp_path, monkeypatch):
        from desktop_calendar.ui.theme import svg_assets

        def boom(*_args, **_kwargs):
            raise OSError("denied")

        monkeypatch.setattr(svg_assets.os, "makedirs", boom)
        assert svg_assets.asset_url("<svg/>", directory=str(tmp_path / "denied")) == ""


class TestScrollbar:
    def test_handle_colors_come_from_theme(self):
        theme = dict(DEFAULT_THEME)
        theme["scrollbar_handle"] = "#123456"
        theme["scrollbar_handle_hover"] = "#654321"
        css = qss.scrollbar(ThemeResolver(theme)).lower()
        assert "#123456" in css
        assert "#654321" in css

    def test_every_preset_defines_scrollbar_colors(self):
        for name in THEME_PRESETS:
            theme = dict(DEFAULT_THEME)
            theme.update(THEME_PRESETS[name])
            resolver = ThemeResolver(theme)
            assert resolver.color("scrollbar_handle")
            assert resolver.color("scrollbar_handle_hover")


class TestTransparentSurface:
    """裸声明样式表会级联到 QToolTip，必须带选择器。"""

    def test_rule_is_scoped_to_object_name(self):
        rule = qss.transparent_widget("sidebar_viewport")
        assert rule.startswith("#sidebar_viewport {")
        assert rule.endswith("}")

    def test_tooltip_keeps_background_below_scoped_surface(self, qapp):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QPushButton, QToolTip, QWidget

        app = qapp
        previous = app.styleSheet()
        app.setStyleSheet("QToolTip { background-color: #FFFFFF; color: #000000; }")
        host = QWidget()
        inner = QWidget(host)
        inner.setObjectName("inner")
        inner.setStyleSheet(qss.transparent_widget("inner"))
        button = QPushButton("x", inner)
        host.show()
        app.processEvents()

        def _tooltip_colors() -> set[str]:
            app.processEvents()
            for top in app.topLevelWidgets():
                if type(top).__name__ == "QLabel" and top.text() == "提示":
                    image = top.grab().toImage()
                    return {
                        image.pixelColor(x, y).name()
                        for y in range(image.height())
                        for x in range(image.width())
                    }
            return set()

        try:
            QToolTip.showText(QPoint(10, 10), "提示", button)
            assert "#ffffff" in _tooltip_colors()
        finally:
            QToolTip.hideText()
            app.setStyleSheet(previous)
            host.close()

    def test_main_window_has_no_bare_declaration_stylesheets(self):
        """裸声明（无选择器）会被 Qt 级联到 tooltip，历史上让提示框变黑。"""
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(
                (
                    Path(__file__).resolve().parents[1]
                    / "src"
                    / "desktop_calendar"
                    / "ui"
                    / "main_window"
                ).glob("*.py")
            )
        )
        bare = re.findall(r"setStyleSheet\(\s*[\"'](background|border|color):", source)
        assert bare == []
