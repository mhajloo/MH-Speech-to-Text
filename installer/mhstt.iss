; Inno Setup script for MH-Speech to Text (English installer, installs to Program Files).
; Build with tools\build.py, which also signs the files when a certificate is configured.
; Expects the PyInstaller output in build\dist\MH-Speech to Text.

#define AppName "MH-Speech to Text"
#define AppVersion "1.0.0"
#define AppExe "MH-Speech to Text.exe"

[Setup]
AppId={{6F1C8E2A-4B7D-4E53-9A0C-8D2E5B7A31F4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Mohammad Hajloo
AppPublisherURL=https://www.hajloo.ir
AppSupportURL=https://github.com/mhajloo/
AppUpdatesURL=https://www.hajloo.ir
AppCopyright=Copyright (c) 2026 Mohammad Hajloo
; a normal machine-wide install into Program Files (asks for administrator rights once);
; "/CURRENTUSER" on the command line still allows a per-user install without admin rights
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
LicenseFile=..\LICENSE
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=..\assets\icons\app.ico
WizardStyle=modern dynamic windows11
WizardImageFile=wizard_large.bmp
WizardSmallImageFile=wizard_small.bmp
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
OutputDir=..\build\installer
OutputBaseFilename=MH-Speech-to-Text-Setup-{#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Mohammad Hajloo
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}
VersionInfoCopyright=Copyright (c) 2026 Mohammad Hajloo
#ifdef SIGN
SignTool=mhsign
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
WelcomeExtra=Dictate in Persian in any application: hold a hotkey, speak, and release. Speech recognition runs entirely on your computer and no audio ever leaves it.
DeleteUserData=Do you also want to remove the downloaded speech model and GPU pack (up to 2.4 GB), your settings and your dictation history?%n%nChoose No if you plan to reinstall, so they do not have to be downloaded again.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\build\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; runasoriginaluser: the app must not inherit the installer's administrator rights
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
procedure CloseRunningApp();
var
  ResultCode: Integer;
begin
  { the app lives in the tray and has nothing unsaved: end it so its files can be replaced }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "{#AppExe}"', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
end;

procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption := WizardForm.WelcomeLabel2.Caption + #13#10#13#10 +
    ExpandConstant('{cm:WelcomeExtra}');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  CloseRunningApp();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { the app may have enabled "start with Windows" from its own settings }
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
    if (not UninstallSilent) and
       (DirExists(ExpandConstant('{localappdata}\{#AppName}')) or
        DirExists(ExpandConstant('{userappdata}\{#AppName}'))) then
      if MsgBox(ExpandConstant('{cm:DeleteUserData}'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(ExpandConstant('{localappdata}\{#AppName}'), True, True, True);
        DelTree(ExpandConstant('{userappdata}\{#AppName}'), True, True, True);
      end;
  end;
end;
