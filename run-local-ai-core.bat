@echo off
setlocal EnableExtensions
title Local AI Core

REM Always run relative to this script, even when launched by double-click.
cd /d "%~dp0"

REM Python tools (pip, uvicorn logs) read and print UTF-8 regardless of the Windows
REM locale codec: requirements/docs carry Vietnamese text and pip would otherwise
REM die decoding them as cp1252 on a fresh machine.
set PYTHONUTF8=1

echo.
echo ==========================================
echo            Local AI Core launcher
echo ==========================================

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

REM The project runs entirely from its own .venv via absolute paths, so PATH
REM does not matter. A system Python (via the py launcher, always present in
REM C:\Windows for python.org installs) is only needed ONCE to create .venv.
if not exist ".venv\Scripts\python.exe" (
    echo [SETUP] Creating Python virtual environment - first run only...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create .venv. Install Python 3.11+ from python.org, then run this file again.
        goto :error
    )
)

REM Install dependencies only when requirements.txt actually changed.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo [SETUP] Installing Python dependencies...
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 goto :error
    copy /y requirements.txt ".venv\requirements.installed" >nul
) else (
    echo [SETUP] Python dependencies are up to date.
)

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
)

REM P4-3: models.yaml ships the cross-encoder reranker ON, but the [rerank]
REM extra (sentence-transformers + torch) is deliberately not in
REM requirements.txt. A machine without it must decide per environment
REM (DEVELOPMENT_PLAN.md 3e); decide it here, once, visibly in .env, instead
REM of letting the API refuse to start behind an already-opened browser tab.
findstr /B /C:"RAG_RERANKER_ENABLED=" ".env" >nul 2>&1
if errorlevel 1 (
    .venv\Scripts\python.exe -c "import sentence_transformers" >nul 2>&1
    if errorlevel 1 (
        echo [SETUP] Reranker extra not installed on this machine: pinning RAG_RERANKER_ENABLED=false in .env
        echo [SETUP] To enable it later: pip install -e .[rerank]  ^(GPU torch recommended^), then remove that line.
        >>".env" echo.
        >>".env" echo # Added by run-local-ai-core.bat - [rerank] extra not installed on this machine, see docs/DEVELOPMENT_PLAN.md
        >>".env" echo RAG_RERANKER_ENABLED=false
    )
)

echo [START] Starting PostgreSQL, Qdrant and Redis...
docker compose --profile postgres up -d
if errorlevel 1 (
    echo [ERROR] Could not start PostgreSQL/Qdrant. Ensure Docker Desktop is running.
    goto :error
)
REM Redis alone keeps /health green; heavy worker containers are not built here.
docker compose --profile workers up -d redis
if errorlevel 1 (
    echo [ERROR] Could not start Redis. Ensure Docker Desktop is running.
    goto :error
)

echo [SETUP] Applying database migrations...
set MIGRATE_TRIES=0
:migrate
.venv\Scripts\python.exe -m alembic upgrade head >nul 2>&1
if not errorlevel 1 goto :migrated
set /a MIGRATE_TRIES+=1
if %MIGRATE_TRIES% GEQ 15 (
    echo [ERROR] Database migration failed. Details:
    .venv\Scripts\python.exe -m alembic upgrade head
    goto :error
)
REM PostgreSQL may still be warming up; retry shortly.
timeout /t 2 /nobreak >nul
goto :migrate
:migrated
echo [SETUP] Database schema is up to date.

ollama list >nul 2>&1
if errorlevel 1 (
    echo [START] Starting Ollama service...
    start "Ollama" /min cmd /c "ollama serve"
    timeout /t 3 /nobreak >nul
)

REM Periodic PostgreSQL backup. It runs on the host because the dump is taken by
REM the PostgreSQL container's own pg_dump, so no image needs a database client.
REM The window is titled so stop-local-ai-core.bat can close exactly this one.
REM `start /d` sets the working directory directly. Wrapping this in `cmd /c "..."`
REM would nest quotes inside an already quoted string, which cmd mis-parses.
tasklist /v /fi "windowtitle eq LocalAICoreBackup*" 2>nul | find /i "python.exe" >nul
if errorlevel 1 (
    echo [START] Starting the periodic backup worker...
    start "LocalAICoreBackup" /min /d "%~dp0backend" "%~dp0.venv\Scripts\python.exe" -m scripts.backup_worker --loop
)

REM Without the cleanup worker, deleted documents stay in status 'deleting'
REM forever: the API only marks them, this worker does the actual removal.
REM The compose cleanup-worker service is not started by this launcher.
tasklist /v /fi "windowtitle eq LocalAICoreCleanup*" 2>nul | find /i "python.exe" >nul
if errorlevel 1 (
    echo [START] Starting the cleanup worker...
    start "LocalAICoreCleanup" /min /d "%~dp0backend" "%~dp0.venv\Scripts\python.exe" -m scripts.cleanup_worker --loop
)

call :ensure_model "qwen3.5:9b"
if errorlevel 1 goto :error
call :ensure_model "qwen3-embedding:0.6b"
if errorlevel 1 goto :error
call :ensure_model "glm-ocr:latest"
if errorlevel 1 goto :error

REM ── Discord memory proposal mode (P1-3) ─────────────────────────────────
REM Only when the .env flag is on: the extractor model, the outbox dispatcher
REM (publishes memory jobs to Redis) and the memory worker (consumes them).
REM Note: document OCR/index jobs use the in-process thread backend by default;
REM a future INGESTION_EXECUTION_BACKEND=rq setup would need these two as well.
findstr /R /C:"^DISCORD_MEMORY_EXTRACTOR_ENABLED=true" .env >nul 2>&1
if not errorlevel 1 (
    REM P2-1b: extractor moved to 9b (benchmark 19/08) - same model chat uses.
    call :ensure_model "qwen3.5:9b"
    if errorlevel 1 goto :error
)
findstr /R /C:"^DISCORD_MEMORY_INGESTION_ENABLED=true" .env >nul 2>&1
if not errorlevel 1 (
    tasklist /v /fi "windowtitle eq LocalAICoreOutbox*" 2>nul | find /i "python.exe" >nul
    if errorlevel 1 (
        echo [START] Starting the outbox dispatcher...
        start "LocalAICoreOutbox" /min /d "%~dp0backend" "%~dp0.venv\Scripts\python.exe" -m scripts.outbox_dispatcher
    )
    tasklist /v /fi "windowtitle eq LocalAICoreMemoryWorker*" 2>nul | find /i "python.exe" >nul
    if errorlevel 1 (
        echo [START] Starting the memory worker...
        start "LocalAICoreMemoryWorker" /min /d "%~dp0backend" "%~dp0.venv\Scripts\python.exe" -m scripts.memory_worker
    )
)

REM ── Tier 3 condensation (memory_design.md 7) ────────────────────────────
REM The only component that sends member text to a third party, so it takes
REM its own flag AND a real GEMINI_API_KEY; the worker itself refuses to run
REM without both and says which one is missing.
findstr /R /C:"^DISCORD_CONDENSATION_ENABLED=true" .env >nul 2>&1
if not errorlevel 1 (
    tasklist /v /fi "windowtitle eq LocalAICoreCondenser*" 2>nul | find /i "python.exe" >nul
    if errorlevel 1 (
        echo [START] Starting the condensation worker...
        start "LocalAICoreCondenser" /min /d "%~dp0backend" "%~dp0.venv\Scripts\python.exe" -m scripts.condensation_worker --loop
    )
)

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
if errorlevel 1 (
    cd ..
    echo.
    echo [ERROR] The API stopped with an error ^(see the traceback above^). The browser tab cannot connect until this is fixed.
    goto :error
)
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
