; installer.iss — Inno Setup script untuk membungkus FireSense jadi setup.exe
; Dikompilasi otomatis oleh build.bat (memanggil ISCC.exe) SETELAH PyInstaller
; menghasilkan folder dist\FireSense. Menghasilkan installer wizard + uninstaller
; (muncul di "Apps & features" / Add-Remove Programs), seperti aplikasi biasa.
;
; Working dir saat dikompilasi = C:\FSbuild\src (build.bat cd ke sana), jadi path
; sumber di bawah ini relatif terhadap folder itu.

#define MyAppName      "FireSense"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "FireRL"
#define MyAppExeName   "FireSense.exe"

[Setup]
; AppId unik — JANGAN diubah antar versi agar update menimpa instalasi lama.
AppId={{A7F3C2E1-5B9D-4E8A-9C6F-1D2B3A4C5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppComments=FireSense - DQN Firewall Monitor
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
DisableProgramGroupPage=yes
; Install per-user (tanpa UAC/admin), seperti installer VS Code.
; {autopf} → %LOCALAPPDATA%\Programs saat privileges lowest.
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=FireSense_Setup
SetupIconFile=assets\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Seluruh isi hasil PyInstaller (--onedir) → folder instalasi
Source: "dist\FireSense\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[UninstallDelete]
; Data runtime yang dibuat SETELAH instalasi (log keputusan, snapshot trafik,
; config app) tidak dianggap milik installer. Hapus juga saat uninstall agar
; folder instalasi bersih total — jika tidak, folder sisa akan tertinggal.
; CATATAN: window_decisions.csv (bukti pemantauan) ikut terhapus — cadangkan dulu bila perlu.
Type: filesandordirs; Name: "{app}\results"
Type: filesandordirs; Name: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
