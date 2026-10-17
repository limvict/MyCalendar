; 安装脚本。用 Inno Setup 6.x 编译。
; 关键决策：默认装到 %LOCALAPPDATA%\Programs\，保证自动更新有写权限。

#define MyAppName "桌面日历"
#define MyAppVersion "3.0.5"
#define MyAppPublisher "YourName"
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

; 更新时若旧版本在运行，让 Inno 自动关闭
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"
Name: autostart;   Description: "开机自启动";     GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "..\dist\DesktopCalendar.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}";            Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}";       Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";      Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行"; Flags: nowait postinstall skipifsilent

[Registry]
; 开机自启（可选任务）；卸载时自动清理
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "DesktopCalendarV3"; \
  ValueData: """{app}\{#MyAppExeName}"""; \
  Flags: uninsdeletevalue; Tasks: autostart