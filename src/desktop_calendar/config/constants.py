# coding: utf-8
from __future__ import annotations

REFERENCE_LEAP_YEAR = 2024

DEFAULT_THEME = {
    # ==================== 原有键（保留） ====================
    "window_width": 440,
    "window_height": 520,
    "font_family": "微软雅黑,SimHei,sans-serif",
    "font_size": 13,
    "small_font_size": 9,
    "week_header_font_size": 12,
    "bg_main": "#F7F3ED",
    "border_color": "#D8D2C5",
    "date_text_color": "#5A5A5A",
    "lunar_text_color": "#5A5A5A",
    "solar_term_text_color": "#2E7D32",
    "corner_radius": 20,
    "shadow_size": 0,
    "shadow_color": "#00000040",
    "calendar_header_bg": "#A7B8A1",
    "calendar_header_text": "#000000",
    "weekend_header_red": "#C96068",
    "select_bg": "#B8AAA0",
    "select_text_color": "#ffffff",
    "today_bg": "#7C947E",
    "today_text_color": "#ffffff",
    "festival_red": "#C96068",
    "workday_orange": "#D47026",
    "memorial_orange": "#D47026",
    "normal_cell_bg": "#F9F6F1",
    "normal_num_color": "#555555",
    "normal_lunar_color": "#808080",
    "btn_bg": "#b4c3b0",
    "btn_hover": "#98aa93",
    "btn_pressed": "#82947d",
    "btn_text": "#ffffff",
    "adjacent_cell_bg": "#E9E6E1",
    "adjacent_text_color": "#BBBBBB",
    "cell_corner_radius": 8,
    "dot_size": 6,
    "tag_size": 14,
    "tag_bg": "#222222",
    "tag_text_color": "#FFFFFF",

    # ==================== 对话框 / 弹窗 / 菜单颜色 ====================
    "dialog_radius": 16,
    "dialog_text": "#333333",
    "dialog_btn_bg": "#a7b8a1",
    "dialog_btn_hover": "#8fa089",
    "dialog_btn_pressed": "#82947d",
    "dialog_btn_text": "#ffffff",
    "input_bg": "#ffffff",
    "slider_handle": "#a7b8a1",
    "slider_groove": "#dddddd",
    "menu_bg": "#f7f3ed",
    "menu_border": "#d8d2c5",
    "menu_text": "#444444",
    "menu_hover": "#d9e2d6",
    "menu_radius": 12,
    "msg_box_bg": "#f8f6f2",
    "msg_info_btn": "#a7b8a1",
    "msg_info_btn_hover": "#8fa089",
    "msg_warn_btn": "#d4a76a",
    "msg_warn_btn_hover": "#c99856",
    "msg_error_btn": "#c87878",
    "msg_error_btn_hover": "#b45c5c",

    # ==================== 【新增】对话框尺寸 ====================
    "dialog_new_width": 340,
    "dialog_new_height": 380,
    "dialog_manage_width": 620,
    "dialog_manage_height": 420,
    "dialog_remind_width": 300,
    "dialog_remind_height": 240,
    "dialog_picker_width": 280,
    "dialog_picker_height": 170,
    "dialog_settings_width": 440,
    "dialog_settings_height": 460,

    # ==================== 【新增】通用间距 / 边距 ====================
    "dialog_margin": 16,
    "dialog_spacing": 10,
    "dialog_margin_wide": 20,
    "dialog_spacing_wide": 12,

    # ==================== 【新增】按钮尺寸 / 字号 ====================
    "btn_min_width": 80,
    "btn_min_width_narrow": 75,
    "btn_min_width_wide": 86,
    "btn_padding_v": 6,
    "btn_padding_h": 12,
    "dialog_btn_font_size": 12,

    # ==================== 【新增】圆角 / 滑块 ====================
    "btn_radius": 10,
    "btn_radius_small": 8,
    "input_radius": 6,
    "slider_handle_radius": 8,
    "slider_groove_radius": 3,
    "slider_handle_size": 16,
    "slider_groove_height": 6,

    # ==================== 【新增】主窗口控件固定尺寸 ====================
    "nav_btn_width": 36,
    "info_label_height": 76,

    # ==================== 【新增】对话框字号 ====================
    "cal_title_font_size": 15,
    "info_label_font_size": 12,
    "dialog_title_font_size": 16,
    "dialog_content_font_size": 14,
}

# （LUNAR_FESTIVALS / SOLAR_FESTIVALS / MONTH_CN / NUM_CN_MAP 等保持不变）
# 农历传统节日（月,日）-> 名称，只对这些文字标红
LUNAR_FESTIVALS = {
    (1, 1): "春节", (1, 15): "元宵节", (2, 2): "龙抬头",
    (5, 5): "端午节", (7, 7): "七夕节", (7, 15): "中元节",
    (8, 15): "中秋节", (9, 9): "重阳节", (12, 8): "腊八节",
    (12, 23): "北方小年", (12, 24): "南方小年",
}

# 公历节日（正常灰色显示）
SOLAR_FESTIVALS = {
    (1, 1): "元旦", (3, 8): "妇女节", (3, 12): "植树节",
    (4, 1): "愚人节", (5, 1): "劳动节", (5, 4): "青年节",
    (6, 1): "儿童节", (7, 1): "建党节", (8, 1): "建军节",
    (9, 10): "教师节", (10, 1): "国庆节",
    (12, 24): "平安夜", (12, 25): "圣诞节",
}

# 节日名称归一化映射
FESTIVAL_NAME_MAP = {
    "元旦节": "元旦",
    "国际劳动节": "劳动节",
    "春节": "春节",
    "清明节": "清明节",
    "端午节": "端午节",
    "中秋节": "中秋节",
    "国庆节": "国庆节",
}

# 法定节日里需要标红的名称。RED_TEXT_SET 需同时包含农历传统节日
# 与法定节日，否则「清明节」（不在农历传统节日表里）会被当成灰色。
LEGAL_HOLIDAY_RED = {
    "元旦", "春节", "清明节", "劳动节",
    "端午节", "中秋节", "国庆节",
}

RED_TEXT_SET = set(LUNAR_FESTIVALS.values()) | LEGAL_HOLIDAY_RED

# 农历月份中文
MONTH_CN = ["", "正月", "二月", "三月", "四月", "五月", "六月",
            "七月", "八月", "九月", "十月", "冬月", "腊月"]

# 农历日期中文映射
NUM_CN_MAP = {
    "1": "初一", "2": "初二", "3": "初三", "4": "初四", "5": "初五",
    "6": "初六", "7": "初七", "8": "初八", "9": "初九", "10": "初十",
    "11": "十一", "12": "十二", "13": "十三", "14": "十四", "15": "十五",
    "16": "十六", "17": "十七", "18": "十八", "19": "十九", "20": "二十",
    "21": "廿一", "22": "廿二", "23": "廿三", "24": "廿四", "25": "廿五",
    "26": "廿六", "27": "廿七", "28": "廿八", "29": "廿九", "30": "三十",
}
# ==================== 主题预设 ====================
# 预设主题只写"差异项"，加载时叠加到 DEFAULT_THEME 之上，
# 这样 DEFAULT_THEME 永远是完整无缺的基线。
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_SAKURA = "sakura"

THEME_PRESETS_ORDER = (THEME_LIGHT, THEME_DARK, THEME_SAKURA)

THEME_PRESETS = {
    THEME_LIGHT: {},  # 空 overrides == DEFAULT_THEME

    THEME_DARK: {
        # 基础背景（采用带一点蓝调的深灰，比纯黑更高级）
        "bg_main": "#18181B",               # 主窗口背景
        "border_color": "#27272A",          # 边框线（不要用太亮的颜色）
        "date_text_color": "#F4F4F5",       # 主文字（接近纯白，高对比）
        "lunar_text_color": "#A1A1AA",      # 农历等次要文字（偏灰）
        "solar_term_text_color": "#4ADE80", # 节气用亮绿色
        
        # 日历表头
        "calendar_header_bg": "#27272A",
        "calendar_header_text": "#E4E4E7",
        "weekend_header_red": "#F87171",    # 周末表头用柔和亮红
        
        # 日历单元格（用不同深浅的灰色拉开层次）
        "normal_cell_bg": "#27272A",        # 正常格子背景（比主背景稍亮）
        "normal_num_color": "#FAFAFA",      # 正常公历数字
        "normal_lunar_color": "#A1A1AA",    # 正常农历数字
        "adjacent_cell_bg": "#1C1C1F",      # 非本月格子（退回最暗）
        "adjacent_text_color": "#52525B",   # 非本月文字（极暗）
        
        # 选中与今日（用青色/绿色作为高亮点缀）
        "select_bg": "#3B82F6",             # 选中背景（换成蓝色，更现代）
        "select_text_color": "#FFFFFF",     # 选中文字
        "today_bg": "#10B981",              # 今天背景（亮绿/翡翠色）
        "today_text_color": "#FFFFFF",      # 今天文字
        
        # 节日与调休
        "festival_red": "#F87171",          # 节日红
        "workday_orange": "#FBBF24",        # 调休橙
        "memorial_orange": "#FBBF24",       # 纪念日橙
        
        # 按钮与导航条
        "btn_bg": "#27272A",                # 导航按钮背景
        "btn_hover": "#3F3F46",             # 悬停
        "btn_pressed": "#52525B",           # 按下
        "btn_text": "#E4E4E7",              # 按钮文字
        
        # 标签与角标（比如“班”字）
        "tag_bg": "#3F3F46",
        "tag_text_color": "#F4F4F5",
        
        # ==================== 对话框 / 弹窗 ====================
        "dialog_text": "#F4F4F5",
        "dialog_btn_bg": "#3F3F46",   # 深灰色按钮，更低调
        "dialog_btn_hover": "#52525B",
        "dialog_btn_pressed": "#71717A",
        "input_bg": "#27272A",              # 输入框背景
        "slider_handle": "#3B82F6",
        "slider_groove": "#3F3F46",
        
        # 菜单
        "menu_bg": "#27272A",
        "menu_border": "#3F3F46",
        "menu_text": "#F4F4F5",
        "menu_hover": "#3F3F46",
        
        # 消息框
        "msg_box_bg": "#27272A",
        "msg_info_btn": "#3B82F6",
        "msg_info_btn_hover": "#2563EB",
        "msg_warn_btn": "#F59E0B",
        "msg_warn_btn_hover": "#D97706",
        "msg_error_btn": "#EF4444",
        "msg_error_btn_hover": "#DC2626",
    },

    THEME_SAKURA: {
        "bg_main": "#FFF5F7",
        "border_color": "#F0CAD3",
        "calendar_header_bg": "#F4B7C4",
        "calendar_header_text": "#5C2E3A",
        "weekend_header_red": "#C2185B",
        "select_bg": "#E89AAE",
        "select_text_color": "#FFFFFF",
        "today_bg": "#D9788E",
        "today_text_color": "#FFFFFF",
        "festival_red": "#C2185B",
        "workday_orange": "#E65100",
        "memorial_orange": "#E65100",
        "normal_cell_bg": "#FFF0F3",
        "normal_num_color": "#5C2E3A",
        "normal_lunar_color": "#8A5C6B",
        "btn_bg": "#E89AAE",
        "btn_hover": "#DB8598",
        "btn_pressed": "#CC7083",
        "btn_text": "#FFFFFF",
        "adjacent_cell_bg": "#FCE6EB",
        "adjacent_text_color": "#C0A0AA",
        "dialog_btn_bg": "#E89AAE",
        "dialog_btn_hover": "#DB8598",
        "dialog_btn_pressed": "#CC7083",
        "input_bg": "#FFFFFF",
        "slider_handle": "#E89AAE",
        "slider_groove": "#F4D4DC",
        "menu_bg": "#FFF5F7",
        "menu_border": "#F0CAD3",
        "menu_hover": "#FCE6EB",
        "msg_box_bg": "#FFF5F7",
        "lunar_text_color": "#8A5C6B",        
        "solar_term_text_color": "#2E7D32",
        "date_text_color": "#5C2E3A",
        "dialog_text": "#5C2E3A",
        "menu_text": "#5C2E3A",
        "tag_bg": "#5C2E3A",
        "tag_text_color": "#FFF5F7",
        "shadow_color": "#00000040",
        "msg_info_btn": "#E89AAE",
        "msg_info_btn_hover": "#DB8598",
        "msg_warn_btn": "#E0A060",
        "msg_warn_btn_hover": "#CC8C4C",
        "msg_error_btn": "#C87A7A",
        "msg_error_btn_hover": "#B46464",
    },
}