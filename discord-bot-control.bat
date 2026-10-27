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

REM -m from the repository root (the cd above), not the file path: run as a file,
REM Python puts tools\ on sys.path instead of the root, so `import discord_bot`
REM then needs the editable install, and on a .venv that predates it pythonw
REM exits without a window or a word. From the root it imports regardless.
start "Discord Bot Control" ".venv\Scripts\pythonw.exe" -m tools.discord_bot_control
endlocal
