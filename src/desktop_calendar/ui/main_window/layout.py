# coding: utf-8
"""控件搭建：窗口外壳、侧栏与日历布局、快捷键、尺寸与阴影。"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_calendar.config.constants import DEFAULT_THEME
from desktop_calendar.config.i18n import tr
from desktop_calendar.config.manager import config
from desktop_calendar.infrastructure.platform import dwm
from desktop_calendar.ui.calendar_views import (
    CalendarWeekView,
    CalendarYearView,
)
from desktop_calendar.ui.calendar_widget import LunarCalendarWidget
from desktop_calendar.ui.controllers import settings_controller
from desktop_calendar.ui.dialogs import (
    msg_error,
)
from desktop_calendar.ui.icon_manager import IconManager
from desktop_calendar.ui.panel import SchedulePanel
from desktop_calendar.ui.theme import ThemeBundle, qss
from desktop_calendar.ui.theme.bundle import LAYOUT
from desktop_calendar.ui.widgets import SidebarServicesWidget, WeatherWidget
from desktop_calendar.utils.logging_setup import APP_LOGGER_NAME

logger = logging.getLogger(APP_LOGGER_NAME)


class MainWindowLayoutMixin:
    """控件搭建：窗口外壳、侧栏与日历布局、快捷键、尺寸与阴影。"""

    def _setup_window(self):
        b = self.theme_mgr.current
        self.resize(DEFAULT_THEME["window_width"], DEFAULT_THEME["window_height"])
        flags = (
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setObjectName("MainWindow")
        self.setStyleSheet(qss.WINDOW_SHELL)
        bg = QColor(b.theme.get("bg_main", "#ffffff"))
        is_dark = bg.isValid() and bg.lightness() < 128
        dwm.apply_dwm_fix(self, dark_mode=is_dark)
        self.setFont(b.fonts.global_)

        self._apply_window_icon(b)

    def _apply_window_icon(self, bundle: ThemeBundle) -> None:
        # 1. 获取当前主题对应的图标
        icon = IconManager.get_app_icon(bundle)

        # 2. 设置给主窗口（影响窗口左上角）
        self.setWindowIcon(icon)

        # 3. 设置给 QApplication（影响任务栏、Alt+Tab、弹窗）
        IconManager.apply_global_icon(bundle)

    def build_ui(self):
        b = self.theme_mgr.current
        self._build_shell()

        self._build_top_bar(b)
        self._build_calendar_panel(b)

        self._build_sidebar_cards()
        self._finish_layout(b)

    def _build_shell(self) -> None:
        """窗口骨架：根布局、内容区、侧栏容器与标题行。"""
        self._root_layout = QHBoxLayout(self)
        self._root_layout.setSpacing(0)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("content_widget")
        self.sidebar = QWidget(self)
        self.sidebar.setObjectName("quick_sidebar")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar_scroll = QScrollArea(self.sidebar)
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_content = QWidget()
        self._sidebar_layout = QVBoxLayout(self.sidebar_content)
        self.sidebar_scroll.setWidget(self.sidebar_content)
        sidebar_layout.addWidget(self.sidebar_scroll)
        self.sidebar_title = QLabel("快捷中心")
        self.sidebar_title.setObjectName("sidebar_title")
        self.sidebar_title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.sidebar_subtitle = QLabel("天气 · 今日状态 · 常用功能")
        self.sidebar_subtitle.setObjectName("sidebar_subtitle")
        self.btn_sidebar_close = QPushButton("×", self.sidebar)
        self.btn_sidebar_close.setObjectName("sidebar_close")
        self.btn_sidebar_close.setToolTip("关闭侧边栏")
        self.btn_sidebar_close.clicked.connect(lambda: self.btn_sidebar.setChecked(False))
        sidebar_heading = QVBoxLayout()
        self._sidebar_heading_layout = sidebar_heading
        sidebar_heading.setContentsMargins(0, 0, 0, 0)
        sidebar_heading.setSpacing(LAYOUT["sidebar_heading_spacing"])
        sidebar_heading.addWidget(self.sidebar_title)
        sidebar_heading.addWidget(self.sidebar_subtitle)
        sidebar_header = QHBoxLayout()
        self._sidebar_header_layout = sidebar_header
        sidebar_header.setContentsMargins(0, 0, 0, 0)
        sidebar_header.setSpacing(LAYOUT["sidebar_header_spacing"])
        sidebar_header.addLayout(sidebar_heading, stretch=1)
        sidebar_header.addWidget(self.btn_sidebar_close)
        self.sidebar_weather_title = QLabel("天气")
        self.sidebar_weather_title.setObjectName("sidebar_section_title")
        self.sidebar_attendance_title = QLabel("今日状态")
        self.sidebar_attendance_title.setObjectName("sidebar_section_title")
        self.attendance_status_label = QLabel()
        self.attendance_status_label.setObjectName("attendance_status")
        self.attendance_status_label.setWordWrap(True)
        self.sidebar_focus_title = QLabel(tr("sidebar.focus_title"))
        self.sidebar_focus_title.setObjectName("sidebar_section_title")
        self.focus_status_label = QLabel()
        self.focus_status_label.setObjectName("focus_status")
        self.focus_status_label.setWordWrap(True)
        self._sidebar_layout.addLayout(sidebar_header)
        self._sidebar_layout.addWidget(self.sidebar_weather_title)

        self._content_layout = QVBoxLayout(self.content_widget)
        self._content_layout.setContentsMargins(
            LAYOUT["margin"], LAYOUT["margin"], LAYOUT["margin"], LAYOUT["margin"]
        )
        self._content_layout.setSpacing(LAYOUT["section_spacing"])

        self.calendar_container = QWidget()
        self._calendar_layout = QVBoxLayout(self.calendar_container)
        self._calendar_layout.setContentsMargins(0, 0, 0, 0)
        self._calendar_layout.setSpacing(LAYOUT["section_spacing"])

    def _build_top_bar(self, b) -> None:
        """顶部栏：月份导航、年月标题、视图选择与窗口按钮。"""
        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        self._top_layout = top_layout
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(LAYOUT["row_spacing"])
        self.btn_prev = QPushButton("<")
        self.btn_prev.setFixedWidth(b.window.nav_btn_width)
        self.btn_prev.setToolTip("上个月（PageUp）")
        self.btn_prev.setAccessibleName("上个月")
        self.btn_prev.clicked.connect(self.prev_month)
        # 标题同时是年月跳转入口（点了弹年月选择），比纯文字更容易被发现
        self.cal_title = QPushButton("")
        self.cal_title.setObjectName("cal_title")
        self.cal_title.setFlat(True)
        self.cal_title.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cal_title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cal_title.setToolTip("点击跳转到指定年月")
        self.cal_title.setAccessibleName("当前年月")
        self.cal_title.clicked.connect(self._open_month_picker)
        self.btn_next = QPushButton(">")
        self.btn_next.setFixedWidth(b.window.nav_btn_width)
        self.btn_next.setToolTip("下个月（PageDown）")
        self.btn_next.setAccessibleName("下个月")
        self.btn_next.clicked.connect(self.next_month)
        self.view_selector = QComboBox()
        self.view_selector.addItem("月", "month")
        self.view_selector.addItem("周", "week")
        self.view_selector.addItem("年", "year")
        self.view_selector.setFixedWidth(b.layout.view_selector_width)
        self.view_selector.setToolTip("切换日历视图")
        self.view_selector.setAccessibleName("日历视图")
        self.view_selector.currentIndexChanged.connect(
            lambda _index: self.set_calendar_view(self.view_selector.currentData())
        )
        top_layout.addWidget(self.btn_prev)
        top_layout.addWidget(self.cal_title, stretch=1)
        top_layout.addWidget(self.btn_next)
        top_layout.addWidget(self.view_selector)
        self.btn_sidebar = QPushButton("☰")
        self.btn_sidebar.setCheckable(True)
        self.btn_sidebar.setFixedWidth(b.window.nav_btn_width)
        self.btn_sidebar.setToolTip("打开快捷侧边栏")
        self.btn_sidebar.setAccessibleName("快捷侧边栏")
        self.btn_sidebar.toggled.connect(self._toggle_sidebar)
        top_layout.addWidget(self.btn_sidebar)

        # 细分隔线：左边是内容相关控件，右边是窗口控制
        self.header_sep = QFrame()
        self.header_sep.setObjectName("header_sep")
        self.header_sep.setFixedWidth(1)
        top_layout.addWidget(self.header_sep)

        # 无边框窗口没有系统标题栏，这里补两个窗口按钮：
        # 最小化 = 收进任务栏；关闭 = 收进托盘（程序继续后台运行）
        win_btn_width = b.layout.window_button_width
        self.btn_minimize = QPushButton("—")
        self.btn_minimize.setObjectName("win_minimize")
        self.btn_minimize.setFixedWidth(win_btn_width)
        self.btn_minimize.setToolTip("最小化到任务栏")
        self.btn_minimize.setAccessibleName("最小化")
        self.btn_minimize.clicked.connect(self._hide_or_minimize)
        top_layout.addWidget(self.btn_minimize)

        self.btn_close = QPushButton("×")
        self.btn_close.setObjectName("win_close")
        self.btn_close.setFixedWidth(win_btn_width)
        if self.tray_mgr.available:
            self.btn_close.setToolTip("关闭到托盘（程序继续后台运行）")
        else:
            self.btn_close.setToolTip("退出程序")
        self.btn_close.setAccessibleName("关闭")
        self.btn_close.clicked.connect(self.close)
        top_layout.addWidget(self.btn_close)
        self._calendar_layout.addWidget(top_bar)

    def _build_calendar_panel(self, b) -> None:
        """日历区：月/周/年视图、壁纸、日程面板、信息栏与操作行。"""
        self.calendar = LunarCalendarWidget(self, b, config.get("memorial_days", []))
        self.cal = self.calendar
        self.cal.currentPageChanged.connect(self.update_calendar_title)
        self.cal.currentPageChanged.connect(self._refresh_schedule_markers)
        self.cal.currentPageChanged.connect(lambda *_args: self._update_mood_button())
        self.cal.selectionChanged.connect(self.on_calendar_select_changed)
        self.cal.setGridVisible(False)
        self.cal.setNavigationBarVisible(False)
        self.cal.setVerticalHeaderFormat(self.cal.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar_views = QStackedWidget(self.calendar_container)
        self.calendar_views.addWidget(self.cal)
        self.week_view = CalendarWeekView(self.cal, self._schedule_mgr, b, self.calendar_views)
        self.week_view.date_selected.connect(self._select_week_date)
        self.calendar_views.addWidget(self.week_view)
        self.year_view = CalendarYearView(self.cal, b, self.calendar_views)
        self.year_view.date_selected.connect(self._select_year_date)
        self.year_view.month_selected.connect(self._select_year_month)
        self.calendar_views.addWidget(self.year_view)
        self.set_calendar_wallpaper(
            config.get("calendar_wallpaper", ""), config.get("calendar_wallpaper_overlay", 58)
        )
        self._calendar_layout.addWidget(self.calendar_views, stretch=1)

        self.schedule_panel = SchedulePanel(self._schedule_mgr, self.calendar_container)
        self.schedule_panel.manage_requested.connect(self._open_schedule_dialog)
        self.schedule_panel.quick_add_requested.connect(self._quick_add_schedule)
        self.schedule_panel.changed.connect(self._refresh_schedule_ui)
        self.schedule_panel.save_failed.connect(
            lambda error: msg_error(self, tr("msg.error"), f"无法更新日程：{error}")
        )
        self._calendar_layout.addWidget(self.schedule_panel)
        info_row = QHBoxLayout()
        self._info_row = info_row
        info_row.setSpacing(LAYOUT["row_spacing"])
        info_row.setContentsMargins(0, 0, 0, 0)

        self.info_label = QLabel()
        self.info_label.setObjectName("info_label")
        font = self.info_label.font()
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.info_label.setFont(font)
        self.info_label.setFixedHeight(b.window.info_label_height)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setWordWrap(True)
        info_row.addWidget(self.info_label, stretch=1)
        action_row = QHBoxLayout()
        self._action_row = action_row
        action_row.setSpacing(LAYOUT["row_spacing"])
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addStretch(1)
        self.btn_mood = QPushButton(tr("btn.mood"))
        self.btn_mood.clicked.connect(self._open_mood_dialog)
        action_row.addWidget(self.btn_mood, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.btn_today = QPushButton(tr("btn.today"))
        self.btn_today.setObjectName("today_btn")
        self.btn_today.clicked.connect(self.goto_today)
        action_row.addWidget(self.btn_today, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._calendar_layout.addLayout(info_row)
        self._calendar_layout.addLayout(action_row)
        self._content_layout.addWidget(self.calendar_container, stretch=1)

    def _build_sidebar_cards(self) -> None:
        """侧栏内容：天气卡、今日状态、专注统计与常用入口。"""
        self.weather_widget = WeatherWidget(self.weather_source, config, self.sidebar)
        self._sidebar_layout.addWidget(self.weather_widget)
        self.sidebar_services_widget = SidebarServicesWidget(
            self.sidebar_services_source, self.sidebar
        )
        self._sidebar_layout.addWidget(self.sidebar_services_widget)
        self._sidebar_layout.addWidget(self.sidebar_attendance_title)
        self._sidebar_layout.addWidget(self.attendance_status_label)

        # 上班 / 下班拆成两个按钮：各自独立可用状态，避免"下一步该点哪个"的猜测
        punch_row = QHBoxLayout()
        self._punch_row = punch_row
        punch_row.setContentsMargins(0, 0, 0, 0)
        punch_row.setSpacing(LAYOUT["row_spacing"])
        self.btn_punch_in = QPushButton(tr("attendance.punch_in"))
        self.btn_punch_in.setObjectName("attendance_punch")
        self.btn_punch_in.setAccessibleName(tr("attendance.punch_in"))
        self.btn_punch_in.clicked.connect(lambda: self._do_punch("in"))
        self.btn_punch_out = QPushButton(tr("attendance.punch_out"))
        self.btn_punch_out.setObjectName("attendance_punch")
        self.btn_punch_out.setAccessibleName(tr("attendance.punch_out"))
        self.btn_punch_out.clicked.connect(lambda: self._do_punch("out"))
        # 两个按钮等宽：Ignored 让布局忽略文本长度差异，按 stretch 均分
        for button in (self.btn_punch_in, self.btn_punch_out):
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        punch_row.addWidget(self.btn_punch_in, stretch=1)
        punch_row.addWidget(self.btn_punch_out, stretch=1)
        self._sidebar_layout.addLayout(punch_row)

        # 统计行：本周出勤摘要 + 「统计」入口（打开考勤统计对话框）
        stats_row = QHBoxLayout()
        self._stats_row = stats_row
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(LAYOUT["row_spacing"])
        self.attendance_summary_label = QLabel()
        self.attendance_summary_label.setObjectName("attendance_summary")
        self.btn_attendance_stats = QPushButton(tr("attendance.stats"))
        self.btn_attendance_stats.setObjectName("attendance_stats")
        self.btn_attendance_stats.setAccessibleName(tr("attendance.stats"))
        self.btn_attendance_stats.setFlat(True)
        self.btn_attendance_stats.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_attendance_stats.setToolTip(tr("attendance.stats_tip"))
        self.btn_attendance_stats.clicked.connect(lambda: self.open_attendance_dialog("week"))
        stats_row.addWidget(self.attendance_summary_label, stretch=1)
        stats_row.addWidget(self.btn_attendance_stats)
        self._sidebar_layout.addLayout(stats_row)

        self._sidebar_buttons = [self.btn_punch_in, self.btn_punch_out]
        self._sidebar_layout.addWidget(self.sidebar_focus_title)
        self._sidebar_layout.addWidget(self.focus_status_label)
        self._update_focus_label()
        self.sidebar_actions_title = QLabel("常用")
        self.sidebar_actions_title.setObjectName("sidebar_section_title")
        self._sidebar_layout.addWidget(self.sidebar_actions_title)
        # 最小化 / 退出改由标题栏的窗口按钮负责，侧栏只留功能入口
        sidebar_actions = (
            ("◉  专注", self._open_pomodoro_dialog),
            ("♫  QQ 音乐", self._open_qq_music),
            ("⚙  设置", lambda: settings_controller.open_settings_dialog(self)),
        )
        sidebar_action_grid = QGridLayout()
        self._sidebar_action_grid = sidebar_action_grid
        sidebar_action_grid.setContentsMargins(0, 0, 0, 0)
        sidebar_action_grid.setHorizontalSpacing(6)
        sidebar_action_grid.setVerticalSpacing(6)
        for index, (text, action) in enumerate(sidebar_actions):
            button = QPushButton(text)
            button.setObjectName("sidebar_action")
            button.clicked.connect(
                lambda _checked=False, callback=action: self._run_sidebar_action(callback)
            )
            sidebar_action_grid.addWidget(button, index // 2, index % 2)
            self._sidebar_buttons.append(button)
        self._sidebar_layout.addLayout(sidebar_action_grid)
        self._sidebar_layout.addStretch(1)

    def _finish_layout(self, b) -> None:
        """收尾：挂上根布局、应用尺寸/主题、启动状态刷新定时器。"""
        self.sidebar.hide()
        self._root_layout.addWidget(self.content_widget)
        self._root_layout.addWidget(self.sidebar)
        self._apply_layout_metrics(b)
        self._apply_theme_geometry(b)
        self._setup_shortcuts()
        self._refresh_styles(b)
        self._sync_row_heights()
        self._update_attendance_ui()
        self._attendance_status_timer = QTimer(self)
        self._attendance_status_timer.setInterval(60_000)
        self._attendance_status_timer.timeout.connect(self._update_attendance_ui)
        self._attendance_status_timer.start()
        self._update_mood_button()
        self._refresh_schedule_ui()

    def _setup_shortcuts(self):
        for seq, slot in (
            ("Ctrl+T", self.goto_today),
            ("Ctrl+Home", self.goto_today),
            ("PageUp", self.prev_month),
            ("PageDown", self.next_month),
            ("Ctrl+,", lambda: settings_controller.open_settings_dialog(self)),
            ("Ctrl+Q", self.quit_app),
            ("Esc", self._on_escape),
        ):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

    def _apply_theme_geometry(self, b: ThemeBundle):
        sidebar_width = b.layout.sidebar_width if self._sidebar_visible else 0
        min_content_width = b.layout.content_min_width
        self.content_widget.setMinimumWidth(min_content_width)
        self.sidebar.setFixedWidth(max(1, sidebar_width) if sidebar_width else 0)
        # 用缩放后的 bundle 尺寸，否则窗口永远停在基准尺寸：
        # 小屏下内部按 0.8 缩放、窗口却还是原尺寸，比例就乱了
        self.setFixedSize(b.window.width + sidebar_width, b.window.height)
        self.info_label.setFixedHeight(b.window.info_label_height)
        margin = b.window.shadow_size if b.window.shadow_size > 0 else 1
        if (lay := self.layout()) is not None:
            lay.setContentsMargins(margin, margin, margin, margin)
        if b.window.shadow_size > 0:
            if self._shadow_effect is None:
                eff = QGraphicsDropShadowEffect(self)
                eff.setOffset(0, 0)
                self.content_widget.setGraphicsEffect(eff)
                self._shadow_effect = eff
            self._shadow_effect.setBlurRadius(b.window.shadow_size)
            self._shadow_effect.setColor(b.window.shadow_color)
        elif self._shadow_effect is not None:
            self.content_widget.setGraphicsEffect(None)
            self._shadow_effect = None

    def _apply_layout_metrics(self, b: ThemeBundle) -> None:
        metrics = b.layout
        margin = metrics.margin
        self._content_layout.setContentsMargins(margin, margin, margin, margin)
        self._content_layout.setSpacing(metrics.section_spacing)
        self._calendar_layout.setSpacing(metrics.section_spacing)
        for layout in (self._top_layout, self._info_row, self._action_row):
            layout.setSpacing(metrics.row_spacing)
        self.schedule_panel.setMaximumHeight(metrics.schedule_panel_max_height)
        self.week_view.setMinimumHeight(metrics.week_view_min_height)
        self.year_view.setMinimumHeight(metrics.year_view_min_height)
        self.weather_widget.setMinimumWidth(metrics.weather_min_width)
        self.attendance_status_label.setMinimumHeight(metrics.attendance_status_min_height)
        self.focus_status_label.setMinimumHeight(metrics.focus_status_min_height)
        sidebar_margin = metrics.sidebar_margin
        self._sidebar_layout.setContentsMargins(
            sidebar_margin, sidebar_margin, sidebar_margin, sidebar_margin
        )
        self._sidebar_layout.setSpacing(metrics.sidebar_spacing)
        self.btn_sidebar.setFixedWidth(b.window.nav_btn_width)
        self.btn_sidebar_close.setFixedSize(metrics.sidebar_close_size, metrics.sidebar_close_size)
        for button in self._sidebar_buttons:
            button.setMinimumHeight(metrics.sidebar_button_min_height)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sidebar_heading_layout.setSpacing(metrics.sidebar_heading_spacing)
        self._sidebar_header_layout.setSpacing(metrics.sidebar_header_spacing)
        self._sidebar_action_grid.setHorizontalSpacing(metrics.sidebar_grid_spacing)
        self._sidebar_action_grid.setVerticalSpacing(metrics.sidebar_grid_spacing)
        self.schedule_panel.apply_theme(b)
        self.sidebar_services_widget.apply_theme(b)

    def _sync_row_heights(self) -> None:
        nav_h = max(
            self.btn_prev.sizeHint().height(),
            self.btn_next.sizeHint().height(),
            self.cal_title.sizeHint().height(),
        )
        for w in (
            self.btn_prev,
            self.btn_next,
            self.cal_title,
            self.btn_sidebar,
            self.btn_minimize,
            self.btn_close,
        ):
            w.setFixedHeight(nav_h)
        if hasattr(self, "header_sep"):
            self.header_sep.setFixedHeight(max(10, round(nav_h * 0.55)))

        action_buttons = (self.btn_mood, self.btn_today)
        fn_btn_h = max(btn.sizeHint().height() for btn in action_buttons)
        fn_btn_w = max(btn.sizeHint().width() for btn in action_buttons)
        for btn in action_buttons:
            btn.setFixedHeight(fn_btn_h)
            btn.setMinimumWidth(fn_btn_w)
