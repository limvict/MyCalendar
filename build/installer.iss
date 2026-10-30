; 安装脚本。用 Inno Setup 6.x 编译。
; 关键决策：默认装到 %LOCALAPPDATA%\Programs\，保证自动更新有写权限。
;
; 版本号维护：MyAppVersion 与以下三处必须保持一致，由
; scripts/check_version.py 校验，scripts/patch_updater.py 统一注入：
;   - pyproject.toml [project].version
;   - src/desktop_calendar/infrastructure/network/update_manager.py CURRENT_VERSION
;   - 本文件 #define MyAppVersion

#define MyAppName "桌面日历"
#define MyAppVersion "3.0.3"
; 发布者名会显示在"应用和功能"列表，部署前请替换为真实名称
#define MyAppPublisher "limvict"
#define MyAppExeName "DesktopCalendar.exe"
#define MyAppId "{{8F3C2A10-4B7E-4D91-9F2A-1C5E8B7D3A66}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\DesktopCalendar
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=DesktopCalendar_Setup_{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; auto：全新安装显示目录页（允许用户改），升级时沿用上次路径。
; 若希望彻底禁止改目录（避免用户误选 Program Files 导致自更新
; 无写权限），改为 DisableDirPage=yes。
DisableDirPage=auto

; 更新时若旧版本在运行，让 Inno 自动关闭
CloseApplications=yes
; 精确匹配本程序 exe；若用 *.exe，未来往 {app} 加 helper exe 时
; 会连带尝试关闭它
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no

[Languages]
Name: "chinese"; MessagesFile: ".\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
; 无前缀作为 fallback（chinese 走这里），english 显式覆盖。
; 只覆盖安装向导的辅助文案；产品名（AppName / DefaultGroupName）
; 保持中文，属于产品决策。
AdditionalTasks=附加任务:
english.AdditionalTasks=Additional tasks:
CreateDesktopIcon=创建桌面快捷方式
english.CreateDesktopIcon=Create a desktop shortcut
Autostart=开机自启动
english.Autostart=Start with Windows
Uninstall=卸载 %1
english.Uninstall=Uninstall %1
RunNow=立即运行
english.RunNow=Run now

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalTasks}"
Name: "autostart";   Description: "{cm:Autostart}";         GroupDescription: "{cm:AdditionalTasks}"; Flags: unchecked

[Files]
Source: "..\release\DesktopCalendar.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";                Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:Uninstall,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";          Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:RunNow}"; Flags: nowait postinstall skipifsilent

[Registry]
; 开机自启（可选任务）；卸载时自动清理。
; 键名必须与 src/desktop_calendar/infrastructure/platform/auto_start.py
; 的 _REG_KEY 保持一致，否则程序读不到安装器写入的值。
; 历史：旧版程序曾用 DesktopLunarCalendarV3，现由 auto_start.py 的
; _migrate_legacy_key() 自动迁移，安装器无需处理旧键。
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "DesktopCalendarV3"; \
  ValueData: """{app}\{#MyAppExeName}"""; \
  Flags: uninsdeletevalue; Tasks: autostart

[UninstallDelete]
; 清理 update_manager 的 bat 脚本失败时保留的 .old 备份。
; 正常成功路径 bat 会自己删 .old，这里兜底 rollback_failed /
; probe_rollback_failed 的残留（每个几十 MB）。
; Type: files 表示删除单个文件，不存在时静默跳过。
Type: files; Name: "{app}\{#MyAppExeName}.old"