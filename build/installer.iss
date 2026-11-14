; Inno Setup script for MedStatix Pro
#define MyAppName "MedStatix Pro"
#define MyAppVersion "1.1.1"
#define MyAppExe "MedStatixPro.exe"

[Setup]
AppId={{8C5D3B7A-4F1E-4C6B-9B1A-2D7E5F3A9C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=MedStatix
DefaultDirName={autopf}\MedStatix Pro
DefaultGroupName=MedStatix Pro
OutputDir=..\dist\installer
OutputBaseFilename=MedStatixPro-Setup-{#MyAppVersion}
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\MedStatixPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.sav\OpenWithProgids"; ValueType: string; ValueName: "MedStatixPro.data"; ValueData: ""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
