@echo off
setlocal EnableExtensions
title Local AI Core - Stop

REM Always run relative to this script, even when launched by double-click.
cd /d "%~dp0"

echo.
echo ==========================================
echo         Local AI Core - Tat he thong
echo ==========================================

echo [STOP] Dung backend FastAPI (cong 8000)...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"

echo [STOP] Dung worker backup va cleanup...
taskkill /fi "windowtitle eq LocalAICoreBackup*" /t /f >nul 2>&1
taskkill /fi "windowtitle eq LocalAICoreCleanup*" /t /f >nul 2>&1

echo [STOP] Dung cac container PostgreSQL, Qdrant, Redis (giu nguyen du lieu)...
docker compose --profile postgres --profile workers --profile discord stop

echo.
echo [DONE] Da tat backend va cac container. Du lieu duoc giu nguyen.
echo [INFO] Muon giai phong not RAM: chuot phai bieu tuong Docker Desktop
echo        o khay he thong roi chon Quit Docker Desktop.
echo [INFO] Ollama tu giai phong VRAM sau 5 phut khong dung; muon tat han
echo        thi chuot phai bieu tuong Ollama o khay he thong roi chon Quit.
echo.
pause
endlocal
