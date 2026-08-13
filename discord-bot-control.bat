@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [ERROR] Virtual environment was not found.
    echo         Expected: .venv\Scripts\pythonw.exe
    pause
    exit /b 1
)

if not exist ".env" (
    echo [ERROR] .env was not found.
    echo         Configure DISCORD_TOKEN locally before opening the control panel.
    pause
    exit /b 1
)

start "Discord Bot Control" ".venv\Scripts\pythonw.exe" "tools\discord_bot_control.py"
endlocal
