# coding: utf-8
"""语言包。key 使用 "模块.用途" 命名，避免扁平化冲突。

单语言（简体中文）：移除 EN_US 与 LANGUAGES 注册表。tr() 缺失
回退到 key 本身，便于开发期发现漏配。
"""

ZH_CN = {
    # ---- 通用 ----
    "app.title": "桌面日历",
    "btn.ok": "确定",
    "btn.cancel": "取消",
    "btn.close": "关闭",
    "btn.today": "今天",
    "btn.add": "新增",
    "btn.edit": "编辑选中",
    "btn.delete": "删除选中",
    "btn.all_enable": "全部启用",
    "btn.all_disable": "全部禁用",
    "btn.pick_month": "跳转到月份",

    # ---- 设置 ----
    "setting.title": "设置",
    "setting.general": "通用设置",
    "setting.autostart": "Windows开机自启",
    "setting.memorial_remind": "启用纪念日提醒",
    "setting.memorial_sound": "提醒时播放提示音",
    "setting.opacity": "窗口透明度：",
    "setting.data": "数据管理",
    "setting.export": "导出配置",
    "setting.import": "导入配置",
    "setting.manage_memorial": "纪念日管理",
    "setting.attendance_remind": "启用上下班打卡提醒",
    # P1 后提醒时间由 work_rule 决定，不再固定 08:00/17:00
    "setting.attendance_remind_tip": "工作日按考勤规则中的上下班时间提醒未打卡",
    "setting.year_label": "年：",
    "setting.month_label": "月：",
    "setting.save_failed": (
    "设置保存失败\n{error}\n"
    "请检查磁盘空间或文件权限；修复后再次打开设置点「确定」即可补存。"
),
    # ---- 考勤规则（P1）----
    "setting.attendance_rule": "考勤规则…",
    "setting.attendance_rule_title": "考勤规则",
    "setting.work_start": "上班时间",
    "setting.work_end": "下班时间",
    "setting.lunch_enable": "启用午休扣除",
    "setting.lunch_start": "午休开始",
    "setting.lunch_end": "午休结束",
    "setting.standard_hours": "标准工时（小时）",
    "setting.late_grace": "迟到宽限（分钟）",
    "setting.overtime_granularity": "加班取整（分钟）",
    "setting.overtime_granularity_tip": "0 表示不取整；30 表示按半小时向下取整",
    "setting.rule_invalid": "下班时间必须晚于上班时间；午休结束必须晚于开始",

    # ---- 纪念日 ----
    "memorial.title_new": "新增/编辑纪念日",
    "memorial.title_manage": "纪念日管理",
    "memorial.name": "名称",
    "memorial.name_placeholder": "纪念日名称（如：生日）",
    "memorial.solar": "公历日期",
    "memorial.lunar": "农历日期",
    "memorial.leap": "闰月（仅农历生效）",
    "memorial.repeat": "重复周期",
    "memorial.repeat_year": "每年重复",
    "memorial.repeat_month": "每月重复",
    "memorial.repeat_week": "每周重复",
    "memorial.month": "月份",
    "memorial.day": "日期/星期",
    "memorial.advance": "提前几天提醒(0=当天提醒)",
    "memorial.enabled": "启用该纪念日提醒",
    "memorial.remind_title": "纪念日提醒",
    "memorial.remind_heading": "今日纪念日提醒",
    "memorial.remind_ok": "知道了",
    "memorial.confirm_delete": "确定删除这条纪念日？",
    "memorial.weekday_suffix": "  (1=周一, 7=周日)",
    "memorial.default_name": "未命名纪念日",

    # ---- 纪念日表单校验 ----
    "memorial.warn_solar_day": "{month}月没有{day}日，请输入 1~{max_day} 之间的日期",
    "memorial.warn_lunar_day_max": "农历日期最大为 30 日（农历每月最多 30 天）",
    "memorial.warn_lunar_day_max_short": "农历日期最大为 30 日",
    "memorial.warn_leap_rare": (
        "闰月纪念日仅在对应闰月出现的年份显示。\n"
        "若该闰月间隔超过 5 年，个别年份可能不提醒。\n"
        "是否继续？"
    ),
    "memorial.warn_day_overflow": (
        "每月 {day} 日在部分月份不存在，"
        "届时将自动按该月最后一天提醒。\n是否继续？"
    ),

    # ---- 纪念日管理 ----
    "memorial.manage.select_first": "请先选中一条纪念日",
    "memorial.manage.empty": "暂无纪念日",
    "memorial.manage.confirm_delete_title": "确认删除",
    "memorial.manage.confirm_enable_all": "确定将所有纪念日【启用提醒】？",
    "memorial.manage.confirm_disable_all": "确定将所有纪念日【禁用提醒】？",
    "memorial.manage.repeat_prefix_year": "每年",
    "memorial.manage.repeat_prefix_month": "每月",
    "memorial.manage.repeat_prefix_week": "每周",
    "memorial.manage.status_enabled": "✅启用",
    "memorial.manage.status_disabled": "❌禁用",
    "memorial.manage.type_solar": "公历",
    "memorial.manage.type_lunar": "农历",
    "memorial.manage.leap_prefix": "闰",
    "memorial.manage.type_date_fmt": "{type}{leap}{date}",
    "memorial.manage.advance_fmt": "提前{advance}天提醒",
    "memorial.manage.week_fmt": "周{week}",
    "memorial.manage.date_fmt": "{month}月{day}日",
    "memorial.repeat_once": "仅一次",
    "memorial.year": "年份",
    "memorial.warn_once_date": "{year}年{month}月没有{day}日，请输入 1~{max_day} 之间的日期",
    "memorial.manage.repeat_prefix_once": "仅一次",
    "memorial.manage.once_date_fmt": "{year}年{month}月{day}日",
    "info.memorial_countdown_today": "{name}（今天）",
    "info.memorial_countdown_fmt": "{name}（还有{days}天）",

    # ---- 星期短名（1=周一 ... 7=周日）----
    "weekday.short.1": "一",
    "weekday.short.2": "二",
    "weekday.short.3": "三",
    "weekday.short.4": "四",
    "weekday.short.5": "五",
    "weekday.short.6": "六",
    "weekday.short.7": "日",

    # ---- 提醒命中文本 ----
    "memorial.remind.hit_fmt": "{name}，还有{days}天",
    "memorial.remind.hit_fmt_one": "{name}，还有1天",

    # ---- 提示 / 错误 ----
    "msg.hint": "提示",
    "msg.error": "错误",
    "msg.success": "成功",
    "msg.name_empty": "名称不能为空",
    "msg.confirm": "确认",

    # ---- 配置导入/导出 ----
    "msg.export_title": "导出配置",
    "msg.export_success": "配置已导出",
    "msg.export_failed": "导出失败\n{error}",
    "msg.import_title": "导入配置",
    "msg.import_success": '配置已载入，点"确定"后生效',
    "msg.import_format_error": "导入失败，文件格式错误\n{error}",

    # ---- 纪念日备份/恢复 ----
    "backup.dialog_title": "备份纪念日数据",
    "backup.dialog_restore_title": "恢复纪念日数据",
    "backup.success": "已备份 {count} 条纪念日",
    "backup.failed": "备份失败\n{error}",
    "backup.restore_success": "已恢复 {count} 条纪念日{tail}",
    "backup.restore_skipped": "（跳过 {count} 条无效数据）",
    "backup.read_failed": "读取备份文件失败\n{error}",
    "backup.write_failed": "备份文件读取成功，但保存配置失败（磁盘空间 / 权限？）\n{error}",
    "backup.format_error": "文件格式错误：未找到 memorial_days 字段",
    "backup.confirm_restore_title": "确认恢复",
    "backup.confirm_restore": (
        "当前有 {count} 条纪念日，恢复将完全覆盖现有数据。\n"
        "现有数据不会被自动备份。是否继续？"
    ),

    # ---- 依赖 ----
    "dep.missing_title": "依赖缺失",
    "dep.missing_cnlunar": "cnlunar未安装，农历、节气功能不可用",
    "dep.missing_chinese_cal": "chinese_calendar未安装，本地节假日判断不可用",
    "dep.install_hint": "pip install cnlunar chinese_calendar",

    # ---- 主窗口 ----
    "cal.title_format": "{year}年{month}月",
    "info.solar_term": "节气",
    "info.festival": "节日",
    "info.memorial": "纪念日",
    "info.no_cnlunar": "农历库未安装，详情不可用",
    "info.lunar_unavailable": "暂无农历详情",
    "info.no_events": "今日无节日 / 纪念日",
    "info.memorial_more": "等{count}项",

    # ---- 托盘 ----
    "tray.show": "恢复窗口",
    "tray.backup": "备份纪念日数据",
    "tray.restore": "恢复纪念日数据",
    "tray.settings": "设置",
    "tray.quit": "完全退出",

    # ---- 上下文菜单 ----
    "ctxmenu.minimize": "最小化到托盘",
    "ctxmenu.backup": "备份纪念日数据",
    "ctxmenu.restore": "恢复纪念日数据",
    "ctxmenu.settings": "设置",
    "ctxmenu.quit": "完全退出",

    # ---- 开机自启 ----
    "autostart.windows_only": "开机自启仅支持Windows",
    "autostart.enabled": "✅ 已开启开机自启",
    "autostart.disabled": "✅ 已关闭开机自启",
    "autostart.permission_error": "注册表权限不足，请尝试以管理员运行程序",
    "autostart.failed": "设置开机自启失败：{error}",
    "autostart.window_title_hint": "提示",
    "autostart.window_title_success": "成功",
    "autostart.window_title_error": "错误",
    "autostart.window_title_permission": "权限错误",

    # ----- 除夕 / 班 -----
    "cell.leap_prefix": "闰",
    "cell.workday_tag": "班",

    # ---- 自动更新 ----
    "update.title": "软件更新",
    "update.available": "发现新版本 {version}，是否立即下载？",
    "update.download": "立即更新",
    "update.later": "稍后再说",
    "update.applying": "更新已下载完成，程序将自动重启以完成安装。",
    "update.failed": "更新失败\n{error}",
    "update.downloading": "正在下载更新…",
    "update.cannot_start": "当前环境不支持自动更新",

    # 上次更新失败提示（方案 B）
    "update.prev_failed": "上次更新到 {version} 未完成",
    "update.prev_failed_detail": (
        "原因：{reason}\n"
        "日志：{log}\n\n"
        "选择“重试”将重新下载；选择“忽略”后，该版本在下次启动时不再提示。"
    ),
    "update.retry": "重试",
    "update.ignore_version": "忽略此版本",
    "update.reason.backup_failed": "无法备份旧版本（安装目录可能不可写）",
    "update.reason.install_failed": "无法替换程序文件",
    "update.reason.probe_failed": "新版本启动后立即退出",
    "update.reason.rollback_failed": "替换失败，且无法恢复旧版本",
    "update.reason.probe_rollback_failed": "新版本崩溃，且无法恢复旧版本",
    "update.reason.backup_failed_permission": (
        "无法备份旧版本：安装目录不可写。"
        "请以管理员身份运行程序后重试，或手动下载安装包"
    ),
    "update.reason.backup_failed_locked": (
        "无法备份旧版本：程序文件被其他进程占用"
        "（杀毒软件 / 系统索引），请稍后重试"
    ),
    "update.reason.install_failed_permission": (
        "无法替换程序文件：安装目录不可写。"
        "请以管理员身份运行程序后重试，或手动下载安装包"
    ),
    "update.reason.install_failed_locked": (
        "无法替换程序文件：目标文件被其他进程占用，请稍后重试"
    ),
    "update.old_exe_hint": (
        "旧版本备份：{old_exe}\n"
        "若新版本无法启动，可手动把该文件改名为原程序文件名后启动。"
    ),
    "update.precheck_failed": "更新前检查失败\n{error}",

    # ---- 主题 ----
    "setting.theme": "主题",
    "theme.light": "浅色",
    "theme.dark": "深色",
    "theme.sakura": "樱花",

    # ---- 考勤打卡 ----
    "btn.attendance": "考勤",
    "ctxmenu.attendance": "考勤统计",
    "attendance.title": "考勤统计",
    "attendance.punch_in": "上班打卡",
    "attendance.punch_out": "下班打卡",
    "attendance.punch_in_done": "上班打卡成功：{time}",
    "attendance.punch_out_done": "下班打卡成功：{time}",
    "attendance.punch_in_update": "已更新上班时间：{time}",
    "attendance.punch_out_update": "已更新下班时间：{time}",
    "attendance.save_failed": "考勤数据保存失败\n{error}",
    "attendance.menu_status_none": "今日未打卡",
    "attendance.menu_status_in": "已上班 {time}，尚未打下班卡",
    "attendance.menu_status_out": "已下班 {time}",
    "attendance.menu_status_done": "上班 {in_time} / 下班 {out_time}",
    "attendance.stats_week": "周统计",
    "attendance.stats_month": "月统计",
    "attendance.mode_week": "周统计",
    "attendance.mode_month": "月统计",
    "attendance.col_date": "日期",
    "attendance.col_weekday": "星期",
    "attendance.col_in": "上班",
    "attendance.col_out": "下班",
    "attendance.col_hours": "工时",
    "attendance.col_overtime": "加班",
    "attendance.col_status": "状态",
    "attendance.status_ok": "正常",
    "attendance.status_incomplete": "未打下班卡",
    "attendance.status_abnormal": "异常",
    "attendance.status_absent": "未打卡",
    "attendance.status_rest": "休息",
    "attendance.status_pending": "待出勤",
    "attendance.status_late": "迟到",
    "attendance.status_early": "早退",
    "attendance.status_late_early": "迟到/早退",
    "attendance.mark_late": "迟到",
    "attendance.mark_early": "早退",
    "attendance.status_with_mark": "{base}（{marks}）",
    "attendance.week_range": "{start} ~ {end}",
    "attendance.month_range": "{year}年{month}月",
    "attendance.summary_week": (
        "本周出勤 {attended} 天，完整记录 {complete} 天，"
        "合计 {total}，日均 {avg}"
    ),
    "attendance.summary_month": (
        "本月出勤 {attended}/{workdays} 天，完整记录 {complete} 天，"
        "合计 {total}，日均 {avg}"
    ),
    "attendance.remind_start_title": "该上班打卡了",
    "attendance.remind_start_body": "现在是上班时间，记得打上班卡。点击本提示可打开主窗口。",
    "attendance.remind_end_title": "该下班打卡了",
    "attendance.remind_end_body": "现在是下班时间，记得打下班卡。点击本提示可打开主窗口。",
    "attendance.summary_overtime": "加班 {total}",
    "attendance.summary_late": "迟到 {count} 次",
    "attendance.summary_early": "早退 {count} 次",
    "attendance.duration_hm": "{h}小时{m}分",
    "attendance.duration_h": "{h}小时",
    "attendance.duration_m": "{m}分钟",
    "attendance.export": "导出 CSV",
    "attendance.export_title": "导出考勤记录",
    "attendance.export_filter": "CSV 文件 (*.csv)",
    "attendance.export_success": "已导出 {count} 天考勤记录",
    "attendance.export_failed": "导出失败\n{error}",
    "attendance.export_name_week": "考勤_{start}_{end}.csv",
    "attendance.export_name_month": "考勤_{year}-{month:02d}.csv",
    "attendance.csv_col_hours": "工时(小时)",
    "attendance.csv_col_overtime": "加班(小时)",
    "attendance.none": "—",

    # 上班打卡 11:00 截止：未打卡且过截止时的菜单文案
    "attendance.punch_in_expired": "上班打卡（已过 {deadline}）",
    # 已打卡时菜单项文案（仍可点，走覆盖二次确认）
    "attendance.punch_in_done_label": "上班打卡（已 {time}）",
    "attendance.punch_out_done_label": "下班打卡（已 {time}）",
    # 覆盖二次确认（保留补卡，防误触）
    "attendance.punch_in_update_confirm": (
        "今天已打过上班卡：{old}\n"
        "确定改为当前时间 {new} 吗？"
    ),
    "attendance.punch_out_update_confirm": (
        "今天已打过下班卡：{old}\n"
        "确定改为当前时间 {new} 吗？"
    ),
}