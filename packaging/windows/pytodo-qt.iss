; Inno Setup script for pytodo-qt Windows installer.
;
; Built from release.yml via ISCC after the PyInstaller onedir output
; lands at dist\pytodo-qt\. APP_VERSION is threaded in from the
; release workflow through /DAppVersion on the ISCC command line;
; the #if guard fails the compile if the workflow ever forgets to
; pass it, so a missing version never produces a broken installer.
;
; All relative paths below are resolved against this .iss file's
; own location (packaging\windows\), so `..\..\` walks up to the
; repository root where PyInstaller output and the license live.

#ifndef AppVersion
  #error "AppVersion not defined — pass /DAppVersion=x.y.z to ISCC"
#endif

#define MyAppName "PyTodo-Qt"
#define MyAppPublisher "Michael Berry"
#define MyAppURL "https://github.com/berrym/pytodo-qt"
#define MyAppSupportURL "https://github.com/berrym/pytodo-qt/issues"
#define MyAppUpdatesURL "https://github.com/berrym/pytodo-qt/releases"
#define MyAppExeName "pytodo-qt.exe"
#define MyAppDescription "A modern to-do list application with secure synchronization"

[Setup]
; AppId uniquely identifies this application across install/upgrade
; cycles. Derived once from the repo URL via
;   uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/berrym/pytodo-qt")
; Must never change — Inno Setup uses it to detect and upgrade
; previous installations.
AppId={{62AFF0A2-5EE0-5510-BD68-74E7D0FFEFB5}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppSupportURL}
AppUpdatesURL={#MyAppUpdatesURL}
AppComments={#MyAppDescription}

; VersionInfoVersion is intentionally omitted. It requires a strict
; 4-part numeric format (e.g. 1.2.3.4) and would reject any PEP 440
; pre-release suffix we ship (0.3.11.dev6, 0.3.11b1, 0.3.11rc1).
; AppVersion above is the user-visible version in Add/Remove
; Programs and the uninstaller — that's the display we actually
; care about.

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#AppVersion}

; GPLv3 license text. Inno reads it as plain text regardless of
; extension, so the repository's COPYING file works directly.
LicenseFile=..\..\COPYING

; Per-user install by default — no admin rights required, which
; matches the self-signed / ad-hoc nature of pytodo-qt on other
; platforms. The user can still elevate via the command-line
; install switches if they want a machine-wide install.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; x64-only. The Windows runner builds a 64-bit binary.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Output settings — write the installer into the repo root so the
; release workflow can find it with a predictable name.
OutputDir=..\..
OutputBaseFilename=pytodo-qt-{#AppVersion}-windows-x86_64-setup
SetupIconFile=..\..\src\pytodo_qt\gui\icons\pytodo-qt.ico

; Modern wizard UI, solid compression for a smaller download.
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire PyInstaller onedir output. recursesubdirs + createallsubdirs
; preserves the _internal/ tree exactly as it landed in dist\.
Source: "..\..\dist\pytodo-qt\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch right after install finishes; skipped on /SILENT.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
