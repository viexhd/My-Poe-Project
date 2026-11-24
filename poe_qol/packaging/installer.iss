; Inno Setup 6 script for the Twice Corrupted installer.
; Built by packaging\build_windows.ps1, which passes:
;   /DAppVersion=1.2.3  /DSourceDir=<dist\TwiceCorrupted>  /DOutputDir=<dist\release>
;
; Installs per user (no admin prompt) into
; %LOCALAPPDATA%\Programs\Twice Corrupted, because the app writes its
; settings (config\user.yaml), slot profiles and logs next to the exe.
; Upgrading in place keeps those: user.yaml is never shipped, and the
; slot profile folders are only filled on first install.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\TwiceCorrupted"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\release"
#endif
#define AppName "Twice Corrupted"
#define AppExe "TwiceCorrupted.exe"

[Setup]
AppId={{9AA70A1C-C930-4298-9894-60CEF8C767BE}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
AppPublisherURL=https://github.com/viexhd/Twice-Corrupted
AppSupportURL=https://github.com/viexhd/Twice-Corrupted/issues
AppUpdatesURL=https://github.com/viexhd/Twice-Corrupted/releases
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=TwiceCorrupted-Setup-{#AppVersion}
SetupIconFile={#SourceDir}\assets\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The app itself (exe + _internal\ + assets\ + README).
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "\config"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
; Shipped defaults: always updated.
Source: "{#SourceDir}\config\default.yaml"; DestDir: "{app}\config"; Flags: ignoreversion
Source: "{#SourceDir}\config\map_mods.yaml"; DestDir: "{app}\config"; Flags: ignoreversion
Source: "{#SourceDir}\config\profiles\*"; DestDir: "{app}\config\profiles"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
; Slot profiles are user-editable: only add them on first install.
Source: "{#SourceDir}\config\slot_profiles\*"; DestDir: "{app}\config\slot_profiles"; \
    Flags: onlyifdoesntexist recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "{#SourceDir}\config\slot_profiles_map_stash\*"; DestDir: "{app}\config\slot_profiles_map_stash"; \
    Flags: onlyifdoesntexist recursesubdirs createallsubdirs skipifsourcedoesntexist

[Dirs]
Name: "{app}\config\slot_profiles"
Name: "{app}\config\slot_profiles_map_stash"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\{#AppName} (admin, for in-game hotkeys)"; Filename: "{app}\{#AppExe}"; \
    Parameters: "--elevate"; WorkingDir: "{app}"; \
    Comment: "Use this when Path of Exile runs as administrator"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
