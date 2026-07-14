@echo off
setlocal EnableDelayedExpansion
title FireSense — Build .exe
color 0A

echo.
echo  ============================================
echo   FireSense - Build Windows .exe
echo   Powered by PyInstaller
echo  ============================================
echo.

:: ── 0. Cek Python tersedia ──────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python tidak ditemukan di PATH Windows.
    echo         Install Python dari https://python.org dan centang "Add to PATH"
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK] %%v

:: ── 0b. Aktifkan Windows Long Path (perlu Admin) ────────────────────────────
echo [..] Mengaktifkan Windows Long Path support...
reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" ^
    /v LongPathsEnabled /t REG_DWORD /d 1 /f
if %errorlevel% equ 0 ( echo [OK] Long Path support diaktifkan. ) else (
    echo [WARN] Gagal aktifkan Long Path ^(mungkin bukan Admin^). Lanjut dengan venv pendek. )

:: ── 1. Cek WSL bisa diakses ─────────────────────────────────────────────────
set "WSL_TA=\\wsl.localhost\Ubuntu\home\wecant\TA"
if not exist "%WSL_TA%\" set "WSL_TA=\\wsl$\Ubuntu\home\wecant\TA"
if not exist "%WSL_TA%\" (
    echo [ERROR] Tidak bisa menjangkau WSL. Jalankan "wsl" di PowerShell dulu lalu coba lagi.
    pause & exit /b 1
)
echo [OK] WSL path: %WSL_TA%

:: ── 1b. Tutup FireSense yang sedang berjalan ────────────────────────────────
:: File .exe/.dll/.pyd yang sedang dipakai proses akan terkunci Windows sehingga
:: rd/xcopy gagal (Access is denied / Sharing violation). Tutup dulu prosesnya.
echo [..] Menutup FireSense yang sedang berjalan (jika ada)...
taskkill /IM FireSense.exe /F >nul 2>&1
if %errorlevel% equ 0 ( echo [OK] Proses FireSense ditutup. ) else ( echo [OK] Tidak ada proses FireSense berjalan. )
:: beri Windows waktu melepas kunci file
ping -n 3 127.0.0.1 >nul

:: ── 2. Folder build & venv di path pendek (hindari MAX_PATH) ────────────────
set "BUILD=C:\FSbuild"
set "VENV=C:\FSvenv"
if exist "%BUILD%" rd /s /q "%BUILD%"
mkdir "%BUILD%"
echo [OK] Build dir: %BUILD%

:: ── 3. Copy source files dari WSL ke Windows ────────────────────────────────
echo.
echo [1/5] Copying source files dari WSL...
echo   ^> FireSense\ -^> %BUILD%\src
xcopy /E /I /Y "%WSL_TA%\FireSense"              "%BUILD%\src"
if %errorlevel% neq 0 goto :err_copy
mkdir "%BUILD%\src\FireSenseCli" 2>nul
echo   ^> FireSenseCli\*.py -^> %BUILD%\src\FireSenseCli\
xcopy /Y "%WSL_TA%\FireSenseCli\*.py"        "%BUILD%\src\FireSenseCli\"
if %errorlevel% neq 0 goto :err_copy
mkdir "%BUILD%\src\checkpoints" 2>nul
echo   ^> checkpoints\dqn_final.weights.h5 -^> %BUILD%\src\checkpoints\
copy  /Y "%WSL_TA%\checkpoints\dqn_final.weights.h5" "%BUILD%\src\checkpoints\"
echo   ^> scaler.pkl -^> %BUILD%\src\
copy  /Y "%WSL_TA%\scaler.pkl"                        "%BUILD%\src\"
if %errorlevel% neq 0 goto :err_copy
echo [OK] Source files copied.

:: ── 4. Virtual environment di C:\FSvenv ─────────────────────────────────────
echo.
echo [2/5] Membuat virtual environment di %VENV%...
if not exist "%VENV%\Scripts\python.exe" (
    if exist "%VENV%" rd /s /q "%VENV%"
    python -m venv "%VENV%"
    if %errorlevel% neq 0 ( echo [ERROR] Gagal membuat venv. & pause & exit /b 1 )
) else ( echo [OK] Venv sudah ada, dipakai ulang. )

:: ── 5. Install dependencies ─────────────────────────────────────────────────
echo.
echo [3/5] Installing Python dependencies ke %VENV%...
echo       (proses ini bisa 5-15 menit tergantung kecepatan internet)
echo.
"%VENV%\Scripts\python" -m pip install --upgrade pip --disable-pip-version-check
"%VENV%\Scripts\pip" install ^
    PyQt6 pyqtgraph tensorflow numpy pandas scikit-learn scipy requests joblib openpyxl pyinstaller ^
    --disable-pip-version-check
if %errorlevel% neq 0 (
    echo. & echo [ERROR] pip install gagal. Lihat pesan error di atas.
    pause & exit /b 1
)
echo. & echo [OK] Dependencies installed.

:: ── 6. PyInstaller ──────────────────────────────────────────────────────────
echo.
echo [4/5] Running PyInstaller (bisa 5-15 menit)...
cd /d "%BUILD%\src"

"%VENV%\Scripts\pyinstaller" ^
    --onedir ^
    --windowed ^
    --name=FireSense ^
    --icon=assets\icon.ico ^
    --paths=. ^
    --add-data "assets;assets" ^
    --add-data "FireSenseCli;FireSenseCli" ^
    --add-data "checkpoints;checkpoints" ^
    --add-data "scaler.pkl;." ^
    --add-data "ui;ui" ^
    --hidden-import=PyQt6.sip ^
    --hidden-import=PyQt6.QtSvg ^
    --hidden-import=config_manager ^
    --hidden-import=stages ^
    --hidden-import=worker ^
    --hidden-import=provision ^
    --hidden-import=ui ^
    --hidden-import=ui.main_window ^
    --hidden-import=ui.styles ^
    --hidden-import=pyqtgraph ^
    --hidden-import=openpyxl ^
    --hidden-import=tensorflow ^
    --hidden-import=sklearn ^
    --hidden-import=sklearn.utils._cython_blas ^
    --hidden-import=sklearn.neighbors._typedefs ^
    --hidden-import=sklearn.neighbors._quad_tree ^
    --hidden-import=sklearn.tree._utils ^
    --hidden-import=scipy.ndimage ^
    --collect-all=pyqtgraph ^
    --collect-all=tensorflow ^
    --noconfirm ^
    main.py

if %errorlevel% neq 0 goto :err_build
echo [OK] Build berhasil.

:: ── 7. Bungkus jadi installer setup.exe (Inno Setup) ────────────────────────
echo.
echo [5/5] Membuat installer setup.exe dengan Inno Setup...
taskkill /IM FireSense.exe /F >nul 2>&1

:: Cari kompiler Inno Setup (ISCC.exe) di lokasi umum (single-line if → aman utk %ProgramFiles(x86)%)
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe"

if not defined ISCC (
    echo.
    echo [WARN] Inno Setup tidak ditemukan di sistem ini.
    echo        Untuk menghasilkan FireSense_Setup.exe, install Inno Setup ^(gratis, sekali saja^):
    echo          https://jrsoftware.org/isdl.php
    echo        lalu jalankan build.bat lagi.
    echo.
    echo        Sementara ini FireSense dipasang LANGSUNG tanpa installer...
    goto :direct_install
)
echo [OK] Inno Setup: %ISCC%

"%ISCC%" /Q "%BUILD%\src\installer.iss"
if %errorlevel% neq 0 ( echo [ERROR] Kompilasi installer gagal. & goto :err_build )

set "SETUP_SRC=%BUILD%\src\installer_output\FireSense_Setup.exe"
if not exist "%SETUP_SRC%" ( echo [ERROR] File installer tidak terbentuk. & goto :err_build )

:: Installer ditaruh di folder tempat build.bat ini dijalankan (%~dp0),
:: bukan di Desktop atau di WSL /TA — agar mudah ditemukan di samping .bat.
set "SETUP_OUT=%~dp0FireSense_Setup.exe"
copy /Y "%SETUP_SRC%" "%SETUP_OUT%" >nul

rd /s /q "%BUILD%" 2>nul
echo.
echo  ============================================
echo   SELESAI - INSTALLER SIAP!
echo.
echo   Installer : %SETUP_OUT%
echo   ^(dibuat di folder tempat build.bat dijalankan^)
echo.
echo   Jalankan / bagikan FireSense_Setup.exe untuk memasang aplikasi:
echo   wizard Next-Install, shortcut otomatis, dan bisa di-uninstall
echo   lewat "Apps ^& features" - seperti aplikasi biasa.
echo.
echo   (Venv tersimpan di %VENV% untuk rebuild lebih cepat)
echo  ============================================
echo.
pause
exit /b 0

:: ── Fallback: pasang langsung tanpa installer (Inno Setup belum terpasang) ───
:direct_install
set "OUT=%LOCALAPPDATA%\Programs\FireSense"
ping -n 3 127.0.0.1 >nul
if exist "%OUT%" rd /s /q "%OUT%"
if exist "%OUT%" (
    echo [ERROR] Tidak bisa menghapus %OUT% ^(masih terkunci proses lain^).
    echo         Tutup FireSense secara manual, lalu jalankan build lagi.
    goto :err_copy
)
echo   ^> dist\FireSense\ -^> %OUT%
xcopy /E /I /Y "%BUILD%\src\dist\FireSense" "%OUT%"
if %errorlevel% neq 0 goto :err_copy

set "EXE=%OUT%\FireSense.exe"
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\FireSense.lnk"
set "DESKTOP=%USERPROFILE%\Desktop\FireSense.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w=New-Object -ComObject WScript.Shell;" ^
  "foreach($p in @('%STARTMENU%','%DESKTOP%')){" ^
  "  $s=$w.CreateShortcut($p);" ^
  "  $s.TargetPath='%EXE%';" ^
  "  $s.WorkingDirectory='%OUT%';" ^
  "  $s.IconLocation='%EXE%,0';" ^
  "  $s.Description='FireSense - DQN Firewall Monitor';" ^
  "  $s.Save() }"
if %errorlevel% equ 0 ( echo [OK] Shortcut dibuat ^(Start Menu + Desktop^). ) else (
    echo [WARN] Gagal membuat shortcut otomatis. )

rd /s /q "%BUILD%" 2>nul
echo.
echo  ============================================
echo   SELESAI ^(pasang langsung, tanpa installer^)!
echo   Aplikasi : %OUT%
echo   Shortcut : Start Menu ^& Desktop ^(cari "FireSense"^)
echo   Tips     : install Inno Setup agar build berikutnya menghasilkan setup.exe
echo  ============================================
echo.
pause
exit /b 0

:err_copy
echo [ERROR] Gagal copy file. Pastikan WSL berjalan dan path benar.
pause & exit /b 1
:err_build
echo [ERROR] PyInstaller gagal. Lihat pesan error di atas.
pause & exit /b 1
