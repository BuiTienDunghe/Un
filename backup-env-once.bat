@echo off
setlocal EnableExtensions
REM Encrypt .env into data\backups\env\.env.enc. Double-click this file, or run
REM it from a prompt; it asks for a passphrase twice and writes nothing else.
REM
REM Why a .bat around a .ps1: the same reason the launcher is a .bat -- double
REM clicking a .ps1 opens Notepad instead of running it, and ExecutionPolicy
REM can refuse it. -ExecutionPolicy Bypass applies to THIS process only; the
REM machine's policy is left alone.
REM
REM Run it once now, and again whenever .env changes (a new token, a new
REM password). It is deliberately NOT on the nightly schedule: it needs the
REM passphrase typed in, and that passphrase belongs off this machine.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup-env-once.ps1"
set RC=%errorlevel%
echo.
if not "%RC%"=="0" (
    echo [LOI] Ma hoa that bai - xem thong bao ben tren.
) else (
    echo [OK] Xong.
)
echo Nhan phim bat ky de dong cua so...
pause >nul
exit /b %RC%
