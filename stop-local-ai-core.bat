@echo off
setlocal EnableExtensions
title Local AI Core - Stop

REM Always run relative to this script, even when launched by double-click.
cd /d "%~dp0"

echo.
echo ==========================================
echo         Local AI Core - Tat he thong
echo ==========================================

echo [STOP] Dung backend va cac worker nen...
.venv\Scripts\python.exe -m tools.supervisor --stop
if errorlevel 1 echo [WARN] Khong dung kip trong 15 giay: hay dong cua so Local AI Core.
REM A copy started before the supervisor existed, or by hand, is not under it.
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"

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
