---

## 配置说明

配置文件位于系统数据目录下的 `MyCalendarApp/config.json`：

| 平台 | 路径 |
| --- | --- |
| Windows | `%APPDATA%\MyCalendarApp\config.json` |
| macOS | `~/Library/Application Support/MyCalendarApp/config.json` |
| Linux | `$XDG_DATA_HOME/MyCalendarApp/config.json`（默认 `~/.local/share/...`） |

同目录下还有：

| 文件 | 用途 |
| --- | --- |
| `holiday_cache.json` | 节假日网络数据缓存（30 天过期） |
| `calendar_log.txt` | 运行日志（轮转 5 MB × 3） |
| `update_state.txt` | 上次更新失败的临时标记，正常时不存在 |

日志目录可用环境变量 `MYCALENDAR_LOG_DIR` 覆盖；日志级别用
`MYCALENDAR_LOG_LEVEL` 控制（`DEBUG` / `INFO` / `WARNING` / `TRACE` 等，
默认 `INFO`；`TRACE` 是自定义级别，低于 `DEBUG`）。

主要字段：

| 字段 | 说明 | 默认 |
| --- | --- | --- |
| `language` | `zh_CN` / `en_US` | `zh_CN` |
| `theme_name` | `light` / `dark` / `sakura` | `light` |
| `opacity` | 窗口透明度 0.0–1.0 | `0.92` |
| `pos_x` / `pos_y` | 窗口位置记忆 | 无 |
| `memorial_days` | 纪念日列表 | `[]` |
| `memorial_cfg.enable_remind` | 提醒总开关 | `true` |
| `memorial_cfg.sound_enable` | 提醒音效开关 | `true` |
| `memorial_cfg.remind_start_hour` | 提醒时段起（**暂无 UI 入口，需手工编辑**） | `8` |
| `memorial_cfg.remind_end_hour` | 提醒时段止（同上） | `22` |
| `memorial_cfg.last_remind_sig` | **命中集合签名**，防同日重复弹窗的主机制 | `""` |
| `memorial_cfg.last_remind_date` | 上次提醒日期（诊断 + 旧版本兼容兜底） | `""` |
| `update_skipped_version` | 用户选择"忽略此版本"后记录 | `""` |

> `last_remind_sig` 是 `sha256(sorted(命中文本))[:16]` 拼日期。当天命中集合
> 不变时只弹一次；用户当天新增/删除/改名纪念日导致集合变化，会再次弹窗。
> 若想"当天重新弹提醒"，请清空 `last_remind_sig`（旧版本兼容分支还会读
> `last_remind_date`，一并清空最稳妥）。

写入策略：防抖 500 ms + 临时文件 `os.replace` 原子落盘；退出时
`config.flush()` 强制同步写，避免半写文件。

---

## 主题

内置三套主题，在 **设置 → 主题** 中切换，保存后立即生效并写入 `config.json`：

| 主题 | 特点 |
| --- | --- |
| `light` | 浅色暖调（默认，= `DEFAULT_THEME` 全量） |
| `dark` | Zinc 深灰 + 蓝色/翡翠色高亮 |
| `sakura` | 樱花粉 |

主题定义在 `config/constants.py` 的 `THEME_PRESETS`，每套只写**差异项**，
加载时叠加到 `DEFAULT_THEME` 之上（`ThemeManager._load`）。`DEFAULT_THEME`
永远是完整基线，改主题只需在预设里覆盖想变的键。

主要分组（键名与 `DEFAULT_THEME` 一致）：

| 分组 | 键举例 |
| --- | --- |
| 窗口 | `window_width` / `window_height` / `corner_radius` / `shadow_size` |
| 字体 | `font_family` / `font_size` / `small_font_size` |
| 日历单元格 | `normal_cell_bg` / `today_bg` / `select_bg` / `adjacent_cell_bg` |
| 文字 | `normal_num_color` / `normal_lunar_color` / `festival_red` / `workday_orange` |
| 按钮 | `btn_bg` / `btn_hover` / `btn_pressed` / `btn_text` |
| 标记 | `dot_size` / `tag_size` / `tag_bg` / `tag_text_color` |

`ThemeResolver` 逐 key 兜底到 `DEFAULT_THEME`，所以预设缺字段也能正常渲染。

**切换失败降级**：`ThemeManager.set_theme` 构建失败或持久化失败时返回
`False`，调用方把 `theme_name` 回滚为当前主题名，磁盘与内存保持一致。
自定义主题构建失败还会整体回退到 `light`（`ThemeManager.__init__`）。

> 目前**不支持** `theme.json` 热加载或用户自定义主题文件。想要新配色，
> 请在 `THEME_PRESETS` 里加一套，或在 `DEFAULT_THEME` 上改值，重新打包生效。

---

## 依赖降级策略

程序在依赖缺失时**不崩溃**，按下列矩阵逐级降级：

| 缺失项 | 降级行为 |
| --- | --- |
| `cnlunar` | 日历仅显示公历与公历节日；农历、节气、农历节日、除夕全部不可用；启动时弹依赖提示 |
| `chinese_calendar` | 网络数据可用时不受影响；断网时"周末即假日"，**无法识别法定调休** |
| 两者都缺 | 同上叠加，`info_label` 显示"农历库未安装，详情不可用" |
| `winreg`（非 Windows） | `check_auto_start()` 恒返回 `False`；设置里勾选自启会弹"仅支持 Windows" |
| `winsound`（非 Windows） | 音效静默跳过，提醒弹窗仍正常显示 |
| 系统托盘不可用 | 关闭窗口 = 直接退出（而非最小化）；`tray_mgr.available` 为 `False` 时自动切换行为 |
| `assets/app.ico` 不存在 | 托盘回退到 Qt 标准图标 |
| `assets/alert.wav` 不存在 | 回退到系统音效 `SystemAsterisk` |
| 所有 CDN 均失败 | 使用本地缓存 → `chinese_calendar` → 周末判断 |

启动后 `dependency_check.check_dependencies` 会延迟 100 ms 弹窗提示缺失项，
避免在窗口首次显示前打断视觉呈现。

---

## 打包发布

项目走 `build/build.py` 四步流程（`app.spec` 负责 onefile/onedir 决策），
**不要**直接调 `pyinstaller` 命令行——版本注入、`version_info.txt`
生成、`version.json` 产出都在脚本里统一处理。

```bash
python build/build.py 3.0.4