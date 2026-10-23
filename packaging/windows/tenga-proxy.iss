; Установщик Tenga Proxy для Windows. Версию передаёт build_windows.sh:
;   iscc /DAppVersion=0.17.0 packaging\windows\tenga-proxy.iss

#ifndef AppVersion
  #error AppVersion is not defined
#endif

[Setup]
; Не менять: по AppId установщик находит прежнюю версию.
AppId={{23089B2F-C5D8-45CE-A943-89C573F63388}
AppName=Tenga Proxy
AppVersion={#AppVersion}
AppPublisher=Artem G.
AppPublisherURL=https://github.com/vebulogmetra/tenga-proxy
DefaultDirName={autopf}\Tenga Proxy
DefaultGroupName=Tenga Proxy
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\windows
OutputBaseFilename=tenga-proxy-{#AppVersion}-windows-x64-setup
SetupIconFile=..\..\assets\tenga-proxy.ico
UninstallDisplayIcon={app}\tenga-proxy.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ru.AutoStart=Запускать Tenga Proxy при входе в систему
en.AutoStart=Start Tenga Proxy when I sign in
ru.RegisterService=Регистрация службы Tenga Proxy...
en.RegisterService=Registering the Tenga Proxy service...

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "autostart"; Description: "{cm:AutoStart}"; Flags: unchecked

[Files]
Source: "..\..\dist\windows\tenga-proxy\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Tenga Proxy"; Filename: "{app}\tenga-proxy.exe"
Name: "{autodesktop}\Tenga Proxy"; Filename: "{app}\tenga-proxy.exe"; Tasks: desktopicon

[Registry]
; Автозапуск — для того пользователя, который ставит, без прав администратора при входе.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Tenga Proxy"; ValueData: """{app}\tenga-proxy.exe"""; Tasks: autostart; Flags: uninsdeletevalue
; Ссылки импорта: аналог MimeType в tenga-proxy.desktop.
Root: HKCU; Subkey: "Software\Classes\veblock"; ValueType: string; ValueData: "URL:veblock"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\veblock"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\veblock\shell\open\command"; ValueType: string; ValueData: """{app}\tenga-proxy.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\wingeon"; ValueType: string; ValueData: "URL:wingeon"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\wingeon"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\wingeon\shell\open\command"; ValueType: string; ValueData: """{app}\tenga-proxy.exe"" ""%1"""

[Run]
Filename: "{app}\tenga-proxy-svc.exe"; Parameters: "install"; StatusMsg: "{cm:RegisterService}"; Flags: runhidden waituntilterminated
Filename: "{app}\tenga-proxy.exe"; Description: "{cm:LaunchProgram,Tenga Proxy}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
; remove останавливает службу, и она сама откатывает сеть; cleanup — страховка,
; если служба не ответила.
Filename: "{app}\tenga-proxy-svc.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveService"
Filename: "{app}\tenga-proxy-svc.exe"; Parameters: "cleanup"; Flags: runhidden waituntilterminated; RunOnceId: "CleanupNetwork"

[Code]
// Обновление поверх установленной версии: служба держит свой exe, её нужно
// остановить до копирования файлов и зарегистрировать заново после.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\sc.exe'), 'stop TengaProxySvc', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\sc.exe'), 'delete TengaProxySvc', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
  Result := '';
end;
