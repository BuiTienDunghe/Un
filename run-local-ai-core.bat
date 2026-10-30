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

REM One install path: this checkout as an editable package, so `app` (under
REM backend/), discord_bot and tools import from any directory -- the scripts,
REM tools and training modules no longer patch sys.path. Checked, not
REM re-run: -I keeps the current directory off sys.path so only the install can
REM answer, and it must answer with THIS checkout (a .venv copied from another
REM folder would otherwise run that folder's code). --no-deps: requirements.txt
REM stays the one dependency list. Building needs network once (setuptools).
.venv\Scripts\python.exe -I -c "import app, os, sys; here = os.path.normcase(os.path.realpath(os.path.dirname(app.__file__))); sys.exit(here != os.path.normcase(os.path.realpath(sys.argv[1])))" "%~dp0backend\app" >nul 2>&1
if errorlevel 1 (
    echo [SETUP] Installing this checkout as an editable package...
    .venv\Scripts\python.exe -m pip install -e . --no-deps
    if errorlevel 1 goto :error
)

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
)

REM P4-3: models.yaml ships the cross-encoder reranker ON, but the [rerank]
REM extra (sentence-transformers + torch) is deliberately not in
REM requirements.txt. A machine without it must decide per environment
REM (docs/history.md#DEVELOPMENT_PLAN 3e); decide it here, once, visibly in .env, instead
REM of letting the API refuse to start behind an already-opened browser tab.
findstr /B /C:"RAG_RERANKER_ENABLED=" ".env" >nul 2>&1
if errorlevel 1 (
    .venv\Scripts\python.exe -c "import sentence_transformers" >nul 2>&1
    if errorlevel 1 (
        echo [SETUP] Reranker extra not installed on this machine: pinning RAG_RERANKER_ENABLED=false in .env
        echo [SETUP] To enable it later: pip install -e .[rerank]  ^(GPU torch recommended^), then remove that line.
        >>".env" echo.
        >>".env" echo # Added by run-local-ai-core.bat - [rerank] extra not installed on this machine, see docs/history.md#DEVELOPMENT_PLAN
        >>".env" echo RAG_RERANKER_ENABLED=false
    )
)

REM The model picked on the web UI's Model screen (data/model_choice.env, this machine
REM only). Loaded into this window, so every process started below inherits the pin, and
REM the evals, which never start through this launcher, keep grading the registry's active.
if exist "data\model_choice.env" (
    for /f "usebackq tokens=1,* delims==" %%A in ("data\model_choice.env") do (
        set "%%A=%%B"
        echo [MODEL] %%A=%%B ^(chosen on the Model screen^)
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

REM ── Ollama models, from the registry ────────────────────────────────────
REM backend/app/config/model_versions.yaml names every tag: the active version of
REM each role that is on, plus the versions it may fall back to (a fallback can
REM only work on a clean machine if its tag is already here). Pulled BEFORE the
REM workers start so none of them meets an absent tag. The extractor's tag is in
REM the list exactly when DISCORD_MEMORY_EXTRACTOR_ENABLED=true (off roles are
REM omitted), which replaces the flag-conditional pull that used to live below.
REM The second list is "tag<TAB>Modelfile" and the delimiter below is a literal tab.
for /f "usebackq delims=" %%T in (`.venv\Scripts\python.exe -m app.config.model_registry --ollama-pull-list`) do (
    call :ensure_model "%%T"
    if errorlevel 1 goto :error
)
for /f "usebackq tokens=1,2 delims=	" %%T in (`.venv\Scripts\python.exe -m app.config.model_registry --ollama-create-list`) do call :ensure_created "%%T" "%%U"

REM Everything long-running from here is one process: the API and the workers run
REM under tools/supervisor.py, in this window, with their logs in data/logs/services/.
.venv\Scripts\python.exe -m tools.supervisor --running
if not errorlevel 1 (
    echo [INFO] Local AI Core is already running in another window. 127.0.0.1:8000/ui
    REM Not opened: it is printed above.
    goto :done
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo [ERROR] Another program is already using port 8000, so the API could not start.
    echo         Close that program, or run stop-local-ai-core.bat if it is an older copy of this one.
    goto :error
)

echo [START] Starting the API and the workers. Keep this window open while using the system.
echo [START] The web UI at http://127.0.0.1:8000/ui/
REM Not opened: it is printed above.
echo.
.venv\Scripts\python.exe -m tools.supervisor
if errorlevel 1 (
    echo.
    echo [ERROR] The supervisor stopped with an error ^(see above^).
    goto :error
)
goto :done

:ensure_model
ollama list | findstr /C:"%~1" >nul
if not errorlevel 1 exit /b 0
echo [SETUP] Downloading Ollama model %~1 ...
ollama pull %~1
exit /b %errorlevel%

REM :ensure_created tag modelfile — a tag built with `ollama create` (no hub
REM tag exists to pull). Never halts the boot: a missing Modelfile or a failed
REM build only means the resolver marks that role missing/disabled and BM25 keeps
REM serving, which is exactly what a one-click launcher on a clean machine needs.
:ensure_created
ollama list | findstr /C:"%~1" >nul
if not errorlevel 1 exit /b 0
if not exist "%~2" (
    echo [SETUP] %~1 must be built by hand ^(%~2 not found^); the role resolves missing until then
    exit /b 0
)
echo [SETUP] Building Ollama model %~1 from %~2 ...
ollama create %~1 -f "%~2"
if errorlevel 1 echo [SETUP] WARNING: ollama create %~1 failed; the role resolves missing until it is built by hand
exit /b 0

:error
echo.
echo Launcher stopped. Resolve the error above, then run this file again.
pause
exit /b 1

:done
endlocal
