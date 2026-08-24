@echo off
setlocal EnableExtensions
REM Decrypt data\backups\env\.env.enc back to .env.restored. Double-click, type
REM the passphrase, then COMPARE .env.restored with .env before replacing it --
REM the script never overwrites .env itself, on purpose.
REM
REM Pass a different .enc path as the first argument if the file lives
REM elsewhere:  restore-env.bat "D:\somewhere\.env.enc"
set "ENC=%~1"
if "%ENC%"=="" set "ENC=%~dp0data\backups\env\.env.enc"
if not exist "%ENC%" (
    echo [LOI] Khong tim thay file ma hoa: %ENC%
    echo       Chay backup-env-once.bat truoc de tao no.
    pause >nul
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0restore-env.ps1" -EncFile "%ENC%"
set RC=%errorlevel%
echo.
echo Nhan phim bat ky de dong cua so...
pause >nul
exit /b %RC%
