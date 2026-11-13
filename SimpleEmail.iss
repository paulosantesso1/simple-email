; Instalador do Simple Email. Gere com build.bat.
#define AppName "Simple Email"
#define AppVersion "1.0"

[Setup]
AppId={{6B1C0E52-3F4A-4D7B-9A55-5E1D2C8F7A10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Simple Email
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=instalador
OutputBaseFilename=SimpleEmail-Setup
LicenseFile=LICENSE
Compression=lzma2/max
SolidCompression=yes
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\SimpleEmail.exe
CloseApplications=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Área de Trabalho"; Flags: unchecked

[Files]
; programa completo (inclui o Python embutido e todas as bibliotecas)
Source: "dist\SimpleEmail\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; documentação
Source: "README.md"; DestDir: "{app}\documentacao"; Flags: ignoreversion
Source: "plano-cliente-email.md"; DestDir: "{app}\documentacao"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}\documentacao"; Flags: ignoreversion
; código-fonte
Source: "*.py"; DestDir: "{app}\codigo-fonte"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}\codigo-fonte"; Flags: ignoreversion
Source: "Simple Email.bat"; DestDir: "{app}\codigo-fonte"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\SimpleEmail.exe"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\SimpleEmail.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SimpleEmail.exe"; Description: "Abrir o {#AppName} agora"; Flags: nowait postinstall skipifsilent
