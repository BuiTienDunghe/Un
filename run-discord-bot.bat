@echo off
setlocal EnableExtensions
title Local AI Core Discord Bot

REM Always run relative to this script, including when double-clicked.
cd /d "%~dp0"

echo.
echo ==========================================
echo        Local AI Core Discord Bot
echo ==========================================

where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop was not found. Start Docker Desktop first.
    goto :error
)

if not exist ".env" (
    echo [ERROR] .env was not found. Copy .env.example to .env and set DISCORD_TOKEN.
    goto :error
)

findstr /R /C:"^[ ]*DISCORD_TOKEN=." ".env" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] DISCORD_TOKEN is empty or missing in .env.
    echo         Create a new token in Discord Developer Portal and keep it local.
    goto :error
)

echo [CHECK] Checking Local AI Core backend health...
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Backend is not reachable at http://127.0.0.1:8000/health.
    echo        The bot will start, but /ask will fail until the backend is running.
) else (
    echo [CHECK] Backend is healthy.
)

echo [START] Building and running Discord bot in this window...
echo [INFO] Keep this window open while using the bot.
echo [INFO] Press Ctrl+C or close this window to stop the bot.
echo.
docker compose --profile discord up --build discord-bot

echo.
echo [STOP] Discord bot has stopped.
goto :done

:error
echo.
echo Launcher stopped. Resolve the error above, then run this file again.
pause
exit /b 1

:done
endlocal
