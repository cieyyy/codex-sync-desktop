#define MyAppName "Codex Sync Desktop"
#define MyAppVersion GetEnv("APP_VERSION")
#define MyAppExeName "Codex Sync Desktop.exe"

[Setup]
AppId={{7F16E1D5-660E-4C28-8F62-86935FD88277}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=cieyyy
AppPublisherURL=https://github.com/cieyyy/codex-sync-desktop
AppSupportURL=https://github.com/cieyyy/codex-sync-desktop/issues
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Codex-Sync-Desktop-Windows-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\LICENSE

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\Codex Sync Desktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
