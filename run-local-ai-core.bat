@echo off
setlocal EnableExtensions
title Local AI Core

REM Always run relative to this script, even when launched by double-click.
cd /d "%~dp0"

echo.
echo ==========================================
echo            Local AI Core launcher
echo ==========================================

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found. Install Python 3.11+ and add it to PATH.
    goto :error
)

where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker Desktop was not found. Install and start Docker Desktop first.
    goto :error
)

where ollama >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Ollama was not found. Install Ollama and reopen this launcher.
    goto :error
)

if not exist ".venv\Scripts\python.exe" (
    echo [SETUP] Creating Python virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :error
)

echo [SETUP] Checking Python dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
)

echo [START] Starting Qdrant...
docker compose up -d
if errorlevel 1 (
    echo [ERROR] Could not start Qdrant. Ensure Docker Desktop is running.
    goto :error
)

ollama list >nul 2>&1
if errorlevel 1 (
    echo [START] Starting Ollama service...
    start "Ollama" /min cmd /c "ollama serve"
    timeout /t 3 /nobreak >nul
)

call :ensure_model "qwen3.5:9b"
if errorlevel 1 goto :error
call :ensure_model "qwen2.5-coder:7b"
if errorlevel 1 goto :error
call :ensure_model "qwen3-embedding:0.6b"
if errorlevel 1 goto :error
call :ensure_model "glm-ocr:latest"
if errorlevel 1 goto :error

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Local AI Core is already running. Opening the UI...
    start "" "http://127.0.0.1:8000/ui/"
    goto :done
)

echo [START] Starting FastAPI. Keep this window open while using the system.
echo [START] Opening UI at http://127.0.0.1:8000/ui/
start "" "http://127.0.0.1:8000/ui/"
echo.
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :done

:ensure_model
ollama list | findstr /C:"%~1" >nul
if not errorlevel 1 exit /b 0
echo [SETUP] Downloading Ollama model %~1 ...
ollama pull %~1
exit /b %errorlevel%

:error
echo.
echo Launcher stopped. Resolve the error above, then run this file again.
pause
exit /b 1

:done
endlocal
