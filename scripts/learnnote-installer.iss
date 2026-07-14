#define MyAppName "LearnNote"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.20"
#endif

[Setup]
AppId={{A173D688-10E4-46FB-8B34-596A9A9BD08E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=LearnNote
DefaultDirName=D:\LearnNote
DefaultGroupName=LearnNote
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist-installer
OutputBaseFilename=LearnNote-Setup-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\LearnNote.exe

[Files]
Source: "..\dist\LearnNote\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "data\*"

[Icons]
Name: "{group}\LearnNote"; Filename: "{app}\LearnNote.exe"
Name: "{autodesktop}\LearnNote"; Filename: "{app}\LearnNote.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts"

[Code]
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if CompareText(ExtractFileDrive(WizardDirValue), 'C:') = 0 then
    begin
      MsgBox('LearnNote stores large video and model files. Choose D: or another non-system drive.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;
