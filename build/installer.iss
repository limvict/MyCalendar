; Inno Setup script. Requires Inno Setup 6.3+ (CloseApplications=force).
; Version consistency: MyAppVersion must match
;   - pyproject.toml [project].version
;   - update_manager.py CURRENT_VERSION
;   - this file's MyAppVersion
; checked by scripts/check_version.py, patched by scripts/patch_updater.py.

#define MyAppName "桌面日历"
#define MyAppVersion "3.0.3"
#define MyAppPublisher "limvict"
#define MyAppExeName "DesktopCalendar.exe"
#define MyAppId "{{8F3C2A10-4B7E-4D91-9F2A-1C5E8B7D3A66}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
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
DisableDirPage=auto

; force is required because the app minimizes to tray: closeEvent calls
; event.ignore() + hide(), so WM_CLOSE is refused. yes would make Inno
; give up and require manual exit. force kills the process; at most
; 500ms of debounced config writes may be lost.
; The app handles UPDATE_READY by calling quit_app(), which sets
; _quitting_for_update and lets closeEvent accept, so in normal updates
; force is only a safety net.
CloseApplications=force
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=no

[Languages]
Name: "chinese"; MessagesFile: ".\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
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
; No skipifsilent: the updater launches the installer with /VERYSILENT,
; and the postinstall entry must still run so the new version starts
; automatically after a silent upgrade.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:RunNow}"; Flags: nowait postinstall

[Registry]
; Key must match auto_start.py _REG_KEY. Legacy key
; DesktopLunarCalendarV3 is auto-migrated by _migrate_legacy_key().
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "DesktopCalendarV3"; \
  ValueData: """{app}\{#MyAppExeName}"""; \
  Flags: uninsdeletevalue; Tasks: autostart

[UninstallDelete]
; Clean .old backup possibly left by the legacy bat-based updater
; (update_bat.py has been removed; new updates go through Inno Setup).
Type: files; Name: "{app}\{#MyAppExeName}.old"