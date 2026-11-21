# 桌面日历

一款基于 PyQt6 的 Windows 桌面日历与效率工具，支持农历、日程、考勤、天气和快捷侧栏。主窗体默认固定为 460 × 660 像素；打开侧栏时，侧栏显示在主窗体右侧。

## 功能

- **日历视图**：月、周、年视图；展示农历、节假日、纪念日和日程标记，可快速跳转到今天。
- **日程管理**：添加和管理日程，在日历中查看日程标记，并接收日程提醒。
- **壁纸与主题**：为日历视图设置壁纸，调整覆盖效果；支持浅色、深色、樱花等主题。
- **天气与快捷侧栏**：查看所选城市的天气和湿度，以及每日一言、今日状态和常用操作。
- **考勤**：上班 / 下班拆成两个按钮，按当日状态自动启用（已打过或过截止时间会禁用并说明原因）；侧栏显示本周出勤摘要，点「统计」查看周 / 月明细。可选自动打卡，自动打卡仅在应用运行期间生效，不补记启动前错过的时间。
- **效率工具**：番茄钟、每日心情记录和专注记录。
- **QQ 音乐**：侧栏提供内嵌 QQ 音乐网页入口；需要网络连接，登录及音乐播放能力以 QQ 音乐网页提供的服务为准。
- **桌面集成**：系统托盘、快捷键、窗口位置记忆、开机启动和自动更新。

## 环境要求

- Windows
- Python 3.11 或更高版本
- 网络功能（天气、节假日数据、每日一言、QQ 音乐网页）需要可用的网络连接

## 安装与运行

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,build]"
python main.py
```

`PyQt6-WebEngine` 用于内嵌 QQ 音乐网页。若运行环境不支持内嵌页面，可使用播放器窗口中的“在浏览器打开”入口。

## 测试与检查

```powershell
pytest            # 单元 / 集成测试
ruff format .     # 统一排版（行长 100）
ruff check .      # 静态检查
lint-imports      # 分层依赖契约（需先 pip install -e .）
```

CI 还会执行 `python scripts/check_version.py`（版本号一致性）和 `python scripts/check_i18n.py`（文案键完整性）。

## 打包

项目使用 PyInstaller 生成单文件程序。安装开发和打包依赖后，在仓库根目录运行：

```powershell
python -m PyInstaller --noconfirm --clean --distpath release build/app.spec
```

生成的程序位于 `release/DesktopCalendar.exe`。该包包含 Qt WebEngine，文件体积会明显大于不含网页引擎的桌面应用。

如需构建正式安装包，需安装 Inno Setup 6.3 或更高版本，并运行：

```powershell
python scripts/build.py <版本号>
```

例如 `python scripts/build.py 3.1.1`。该脚本会同步项目版本号、构建程序和安装包，并执行发布产物校验；请在干净的发布工作区中运行。

## 更新机制

- **检测**：打包版启动 5 秒后拉取 `version.json`。先请求 GitHub 主地址，失败后依次尝试 `ghproxy` 镜像（`UPDATE_MANIFEST_MIRROR_PREFIXES`），全部失败才记一条 warning 并放弃本次检测——不会因为 GitHub 不可达而静默失效。
- **手动检测**：设置 →「更新」→「检查更新」，或托盘右键菜单「检查更新」。立即重试并直接反馈结果（已是最新 / 失败原因），不受启动检测失败的影响。
- **安装**：下载安装包 → 校验 sha256 → 以 `/VERYSILENT` 静默启动 Inno Setup 安装器。安装器先结束旧进程树并等待 AppMutex 释放，再比对注册表中的已装版本：旧版本直接升级、同版本询问是否重装、更高版本需显式确认（静默调用直接拒绝降级）。
- **跳过版本**：在更新提示里选「忽略此版本」会写入 `update_skipped_version`，同版本不再打扰。
- **清单只读**：`release/version.json` 是发布产物，生成时由 `patch_updater.py --manifest` 标记为只读；客户端与 `check_version.py` 只读校验、不回写。字段用正则严格校验——`version` 必须 `X.Y.Z`、`sha256` 必须 64 位十六进制、`download_url`/镜像必须是 https 且不含空白与引号；任何一项不合规就整体拒绝本次更新，而不是就地修正。

## 数据文件

应用数据保存在 `%APPDATA%\MyCalendarApp\`：

`config.json`、`schedules.json`、`attendance.json`、`moods.json`、`focus_log.json`、`holiday_cache.json`、`weather_cache.json`

这些文件**写入后即被标记为只读**：程序每次落盘前自动解锁、写完重新置只读，用户直接编辑会被系统拒绝，避免手改造成数据损坏或字段漂移。需要手动查看没有问题；需要彻底重置时删除对应文件即可（只读属性不阻止删除），或先清除只读属性再改。

新增应用数据文件时统一走 `atomic_write_json(path, data, protect=True)`；用户可编辑的导出路径（设置导出、纪念日备份）用默认的 `protect=False`。

## 应用图标

一枚「日历卡」：圆角页面 + 顶部色带 + 两个装订环，页面正中是日期数字 `15`，色带右上角一枚弯月点出「农历」。几何只有一套，三套配色跟随主题切换（`light` / `dark` / `sakura`），只换颜色不换结构，所以在任意主题下都是同一个图标。

| 文件 | 用途 |
| --- | --- |
| `assets/<theme>/icon_<name>.png` | 256×256 预览 / 高分屏缩放 |
| `assets/<theme>/theme_{16,32,48}.ico` | 单尺寸，兼容旧调用 |
| `assets/<theme>/theme_256x256.ico` | 多尺寸（16–256），任务栏与 Alt+Tab 各档都清晰 |
| `assets/app.ico` | `IconManager` 终极兜底 + PyInstaller `icon=` + Inno Setup `SetupIconFile` |
| `assets/app.png` | 512×512 高清图（文档 / 商店） |

图标由脚本生成，改配色或形状后重新跑一次即可（需要 Pillow，已在 dev 依赖里）：

```powershell
python scripts/make_icons.py
```

`tests/test_icons.py` 用标准库校验 ICO 内含尺寸、PNG 为 256 带 alpha、以及 `IconManager` 映射的文件全部存在，防止换图后出现"打包没图标"的回归。

## 项目结构

```text
src/desktop_calendar/
├── __main__.py           启动流程：单实例、日志、异常兜底
├── config/
│   ├── constants.py      默认主题、尺寸常量
│   ├── translations.py   界面文案（i18n 字典）
│   └── manager/          配置层：storage（原子写/缓存）、normalize、ConfigManager
├── contracts/            事件总线与数据契约（不依赖 Qt 视图）
├── core/
│   ├── attendance/       考勤：models（结构体）、rules（规则）、store（持久化）
│   ├── memorial/         纪念日：normalize（归一化）、recurrence（下次日期）、index（索引表）
│   ├── reminder_rules.py 提醒规则：配置读取、下次时间戳、命中签名（纯逻辑）
│   └── ...               日程、提醒调度、番茄钟、心情、农历
├── infrastructure/
│   ├── network/
│   │   ├── weather_source/  天气：codes（代码表）、parsing（解析）、source（请求+缓存）
│   │   ├── holiday_parsing.py  节假日多种源格式 → {date: kind}
│   │   ├── update_*.py      更新：检查、下载、文件操作（files）、重试判定（retry）、异常（errors）
│   │   └── ...              每日一言
│   └── platform/         Windows 平台能力（DWM 阴影、开机启动）
├── ui/
│   ├── main_window/      主窗口：组合根 + 按职责拆分的 mixin
│   ├── theme/            主题装配层（metrics 数据声明 + bundle 装配 + manager 切换）
│   │   └── qss/          QSS 规则，按界面区域分包
│   ├── dialogs/          对话框（纪念日三个弹窗再拆成子包）
│   ├── calendar_views/   周 / 年视图
│   ├── widgets/          可复用控件（天气卡、侧栏信息服务、省略标签、城市/图标表）
│   ├── controllers/      与窗口解耦的 UI 控制器（设置、更新、窗口状态）
│   └── panel/            日程面板
├── utils/                通用工具：路径、日志、类型归一化
assets/                   应用图标（三套主题）、音频和主题资源
build/                    PyInstaller 与安装程序配置
scripts/                  构建、版本、i18n 检查与图标生成脚本
tests/                    自动化测试
```

## 代码组织约定

**分层。** 依赖方向自上而下：`__main__` → `ui` → `core` / `infrastructure` → `contracts` → `config` → `utils`。`pyproject.toml` 里的 import-linter 契约会拦截反向依赖；新增模块时若必须破例，请像既有契约那样写明原因，而不是放宽全局规则。

**主窗口。** `ui/main_window/` 是组合根：`window.py` 里的 `MainWindow` 只负责组装和生命周期，具体能力分散在同级 mixin 中，新增逻辑时先判断它属于哪一类：

| 模块 | 职责 |
| --- | --- |
| `layout.py` | 控件搭建、快捷键、尺寸与阴影 |
| `styling.py` | 主题与 QSS 刷新 |
| `screen.py` | 多屏与缩放适配 |
| `sidebar.py` | 快捷侧栏显隐 |
| `navigation.py` | 月 / 周 / 年视图导航与标题 |
| `status.py` | 信息栏、日程标记、心情与专注状态 |
| `attendance.py` | 考勤菜单与打卡交互 |
| `actions.py` | 日程、番茄钟、音乐等对话框入口 |
| `events.py` | 事件总线订阅与分发 |

**主题与样式。** 界面代码不写裸样式，统一走 `ThemeBundle`；QSS 规则放在 `ui/theme/qss/` 对应区域的文件里，由 `qss/__init__.py` 汇总导出，调用方仍用 `qss.xxx(r)`。

**文案。** 界面文案集中在 `config/translations.py`，通过 `tr()` 读取；新增或改名后运行 `python scripts/check_i18n.py`，确保键在两种语言里都齐全。

**大方法。** 对话框和主窗口的界面搭建按"区块"拆成私有 `_build_*` 方法：`MainWindow.build_ui` 只剩编排（`_build_shell` / `_build_top_bar` / `_build_calendar_panel` / `_build_sidebar_cards` / `_finish_layout`），`SettingDialog.__init__` 与 `AttendanceDialog.__init__` 同理。新增界面区块时照此追加，不要在 `__init__` 里继续堆控件。

**排版。** 由 `ruff format` 统一（行长 100，`# coding: utf-8` 头保留）；import 顺序由 `ruff check --fix` 的 isort 规则维护。提交前跑一遍测试、格式和契约检查即可。
