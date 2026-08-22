@echo off
setlocal EnableExtensions
REM One PostgreSQL dump, then exit. This is the second safety net (debt T14):
REM the launcher's backup worker only lives while the launcher window is open,
REM so a Windows Scheduled Task runs this file daily regardless of the launcher.
REM
REM Register it once (run in an elevated prompt; adjust the path if the clone
REM lives elsewhere):
REM   schtasks /Create /TN "LocalAICore Backup" /SC DAILY /ST 02:00 ^
REM     /TR "\"%~dp0backup-postgres-once.bat\"" /F
REM
REM The dump is taken by pg_dump inside the running PostgreSQL container, so
REM Docker Desktop must be up; the worker reports and exits non-zero otherwise.
REM
REM --force: a second net must produce a dump even when the launcher's own
REM worker already did today (otherwise "recent backup exists" skips it, and a
REM dump merely COPIED into the folder looks recent by mtime). Rotation
REM (storage.backups_ttl_days / backups_keep_minimum) bounds the disk cost.
set PYTHONUTF8=1
cd /d "%~dp0backend"
"..\.venv\Scripts\python.exe" -m scripts.backup_worker --once --force
exit /b %errorlevel%
