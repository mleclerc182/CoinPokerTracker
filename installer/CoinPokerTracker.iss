; CoinPoker Tracker Windows installer
; Built with Inno Setup

#define MyAppName "CoinPoker Tracker"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "mleclerc182"
#define MyAppExeName "CoinPokerTracker.exe"

[Setup]
; Keep this AppId permanently the same for future versions.
; This allows future installers to upgrade the existing installation.
AppId={{302552F9-E834-4FD1-ABC1-102A8B919F23}

AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}

; Install only for the current Windows user.
; No administrator prompt is required.
DefaultDirName={localappdata}\Programs\{#MyAppName}
PrivilegesRequired=lowest

UninstallDisplayIcon={app}\{#MyAppExeName}

; The application build is 64-bit.
ArchitecturesAllowed=x64compatible

; Keep the install process simple.
DisableProgramGroupPage=yes

; Installer output
OutputDir=Output
OutputBaseFilename=CoinPokerTracker-Setup

; Compression
Compression=lzma2
SolidCompression=yes

; Installer appearance
WizardStyle=modern dynamic

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; \
    Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; \
    Flags: unchecked

[Files]
; The .iss file lives in installer\
; The PyInstaller build lives in ..\dist\CoinPokerTracker\
Source: "..\dist\CoinPokerTracker\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut
Name: "{autoprograms}\{#MyAppName}"; \
    Filename: "{app}\{#MyAppExeName}"

; Optional desktop shortcut
Name: "{autodesktop}\{#MyAppName}"; \
    Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
; Give the user the option to launch the tracker after installation.
Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent