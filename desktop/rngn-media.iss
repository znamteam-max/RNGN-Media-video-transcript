#define MyAppName "RNGN Media"
#ifndef MyAppVersion
#define MyAppVersion "0.4.0"
#endif
#define MyAppPublisher "RNGN"
#define MyAppExeName "RNGN Media.exe"

[Setup]
AppId={{8F68A2D7-0B4E-4A4E-A6E8-1B5B2AA20E42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\RNGN Media
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\installer-dist
OutputBaseFilename=RNGN-Media-Setup-{#MyAppVersion}
SetupIconFile=assets\rngn-media.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
SetupLogging=yes

[InstallDelete]
; 0.3.x shipped a different Python runtime; start from a clean program folder.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\RNGN Media\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\RNGN Media"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\RNGN Media"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить RNGN Media"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2Key = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM, WebView2Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, WebView2Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  Result := True;
  if not WebView2Installed() then
  begin
    if MsgBox('Для окна RNGN Media нужен компонент Microsoft Edge WebView2 (он уже есть в Windows 11).' + #13#10 + #13#10 +
              'Открыть страницу загрузки? Установка RNGN Media продолжится, а программа заработает после установки WebView2.',
              mbConfirmation, MB_YESNO) = IDYES then
      ShellExec('open', 'https://go.microsoft.com/fwlink/p/?LinkId=2124703', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
  end;
end;
