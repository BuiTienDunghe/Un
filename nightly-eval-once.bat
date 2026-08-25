@echo off
setlocal EnableExtensions
REM Nightly eval of the SHIPPED retrieval config on the lab corpus (D4-lite #4).
REM CI only measures the bare path; this is the watch on what production runs.
REM Registered as "LocalAICore Nightly Eval", daily 03:00. On failure it leaves
REM data\logs\ATTENTION_nightly_eval.txt, which the 09:30 alerts task pops up.
set PYTHONUTF8=1
cd /d "%~dp0backend"
"..\.venv\Scripts\python.exe" -m scripts.nightly_eval
exit /b %errorlevel%
