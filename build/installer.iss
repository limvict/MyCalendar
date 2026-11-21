; Inno Setup script. Requires Inno Setup 6.3+ (CloseApplications=force).
; Version consistency: MyAppVersion must match
;   - pyproject.toml [project].version
;   - update_manager.py CURRENT_VERSION
;   - this file's MyAppVersion
; checked by scripts/check_version.py, patched by scripts/patch_updater.py.

#define MyAppName "桌面日历"
#define MyAppVersion "3.1.5"
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
AppMutex=DesktopCalendar_App_Mutex
RestartIfNeededByRun=no

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

[Code]
const
  APP_MUTEXES = 'DesktopCalendar_App_Mutex';
  // 卸载项注册表路径。GUID 必须与上方 #define MyAppId 一致
  // （MyAppId 在 [Setup] 里用 {{ }} 转义成单个 { }）；
  // tests/test_version.py 会校验两处 GUID 相同。
  APP_UNINSTALL_KEY =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
    '{8F3C2A10-4B7E-4D91-9F2A-1C5E8B7D3A66}_is1';

{ 取版本号的一段（点分隔），并把 Sys 指向剩余部分。 }
function TakeVersionPart(var Sys: String): Integer;
var
  P: Integer;
begin
  P := Pos('.', Sys);
  if P = 0 then
  begin
    Result := StrToIntDef(Sys, 0);
    Sys := '';
  end
  else
  begin
    Result := StrToIntDef(Copy(Sys, 1, P - 1), 0);
    Delete(Sys, 1, P);
  end;
end;

{ 按 X.Y.Z 数值比较：A<B 返回 -1，A=B 返回 0，A>B 返回 1。 }
function CompareVersions(A, B: String): Integer;
var
  I: Integer;
  PA, PB: Integer;
  SA, SB: String;
begin
  Result := 0;
  SA := Trim(A);
  SB := Trim(B);
  for I := 1 to 3 do
  begin
    PA := TakeVersionPart(SA);
    PB := TakeVersionPart(SB);
    if PA < PB then
    begin
      Result := -1;
      Exit;
    end;
    if PA > PB then
    begin
      Result := 1;
      Exit;
    end;
  end;
end;

{ 已安装版本（无记录返回空串）。 }
function GetInstalledVersion(): String;
begin
  if not RegQueryStringValue(HKCU, APP_UNINSTALL_KEY, 'DisplayVersion', Result) then
    Result := '';
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  I: Integer;
  Installed: String;
  Cmp: Integer;
begin
  Result := True;

  // 1. 先优雅结束旧进程树（/T 包含子进程）
  Exec('taskkill.exe', '/IM DesktopCalendar.exe /T', '',
       SW_HIDE, ewWaitUntilTerminated, ResultCode);

  // 2. 轮询等待 AppMutex 释放，最多约 5 秒
  for I := 1 to 25 do
  begin
    Sleep(200);
    if not CheckForMutexes(APP_MUTEXES) then
      Break;
  end;

  // 3. 若仍存在，强制结束并再等一会儿
  if CheckForMutexes(APP_MUTEXES) then
  begin
    Exec('taskkill.exe', '/F /IM DesktopCalendar.exe /T', '',
         SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(800);
  end;

  // 4. 版本检测：升级直接装、同版本询问、降级阻止
  Installed := GetInstalledVersion();
  if Installed = '' then
    Exit;

  Cmp := CompareVersions(Installed, '{#MyAppVersion}');
  if Cmp > 0 then
  begin
    // 已装版本更高：降级会丢功能，交互模式必须明确确认
    Log('检测到已安装更高版本 ' + Installed + '，安装包为 {#MyAppVersion}');
    if WizardSilent then
    begin
      Log('静默模式：阻止降级安装');
      Result := False;
      Exit;
    end;
    if MsgBox('当前已安装更高版本 ' + Installed + '，继续安装会把程序降级到 {#MyAppVersion}。' + #13#10 + #13#10 +
              '确定要继续吗？',
              mbError, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    begin
      Result := False;
      Exit;
    end;
  end
  else if Cmp = 0 then
  begin
    // 同版本：静默模式（应用内升级/覆盖安装）直接继续，交互模式问一句
    Log('检测到同版本已安装：' + Installed);
    if not WizardSilent then
    begin
      if MsgBox('检测到已安装相同版本 {#MyAppVersion}，是否重新安装？',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
      begin
        Result := False;
        Exit;
      end;
    end;
  end
  else
    Log('检测到旧版本 ' + Installed + '，按升级安装到 {#MyAppVersion}');
end;