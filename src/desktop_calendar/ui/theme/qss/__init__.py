# coding: utf-8
"""QSS 纯函数集合：ThemeResolver → str，不接触任何 QWidget。

按界面区域拆成子模块，本文件只做汇总导出，调用方仍按
`qss.content_widget(...)` 的方式使用：

- `palette`  ：颜色计算（对比度、明暗、SVG 包装），不产出 QSS
- `shell`    ：窗口外壳、工具提示、菜单、滚动条
- `header`   ：顶部栏、月份导航、窗口按钮
- `calendar` ：日历网格
- `sidebar`  ：快捷侧栏
- `panels`   ：日程列表、侧栏信息服务、天气卡
- `dialogs`  ：对话框与消息框
"""

from __future__ import annotations

from .calendar import calendar
from .dialogs import (
    dialog_base,
    dialog_buttons,
    dialog_checkboxes,
    dialog_groupbox,
    dialog_inputs,
    dialog_list,
    dialog_slider,
    message_box,
)
from .header import (
    cal_title,
    header_combo,
    header_separator,
    info_label,
    nav_buttons,
    today_button,
    window_buttons,
)
from .palette import MessageKind, transparent_widget
from .panels import schedule_panel, sidebar_services, weather_panel
from .shell import (
    TRANSPARENT_SCROLL_AREA,
    WINDOW_SHELL,
    content_widget,
    content_widget_with_sidebar,
    menu,
    scrollbar,
    tooltip,
)
from .sidebar import (
    sidebar_action_button,
    sidebar_close_button,
    sidebar_panel,
    sidebar_section_title,
    sidebar_status_card,
    sidebar_subtitle,
    sidebar_title,
)

__all__ = [
    "MessageKind",
    # 外壳
    "WINDOW_SHELL",
    "TRANSPARENT_SCROLL_AREA",
    "content_widget",
    "content_widget_with_sidebar",
    "tooltip",
    "menu",
    "scrollbar",
    "transparent_widget",
    # 顶部栏
    "info_label",
    "nav_buttons",
    "today_button",
    "cal_title",
    "header_combo",
    "window_buttons",
    "header_separator",
    # 日历
    "calendar",
    # 侧栏
    "sidebar_panel",
    "sidebar_close_button",
    "sidebar_action_button",
    "sidebar_section_title",
    "sidebar_status_card",
    "sidebar_title",
    "sidebar_subtitle",
    # 面板
    "schedule_panel",
    "sidebar_services",
    "weather_panel",
    # 对话框
    "message_box",
    "dialog_base",
    "dialog_buttons",
    "dialog_inputs",
    "dialog_checkboxes",
    "dialog_groupbox",
    "dialog_slider",
    "dialog_list",
]
