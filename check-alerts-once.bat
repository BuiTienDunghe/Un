@echo off
setlocal EnableExtensions
title Local AI Core - Kiem tra van hanh (dang chay, dung dong)
REM Same reasoning as nightly-eval-once.bat: this window is deliberately
REM visible, so it must introduce itself. 09:30 is working hours -- an
REM unexplained black console is even likelier to get closed here.
REM
REM Morning operational check (D4-lite #4b). The script existed for weeks and
REM nothing ran it -- the alert that fires only when a human remembers to run
REM it is not an alert. Registered as "LocalAICore Alerts", daily 09:30.
REM
REM Exit 2 = a real alert (stale jobs / chunk threshold / dump too old /
REM nightly eval failed) -> popup. Exit 3 = could not reach the DB (Docker
REM still starting?) -> logged only, no popup; the dump-age check ran anyway.
echo.
echo  ==========================================================
echo    Local AI Core - Kiem tra van hanh  ^(09:30^)
echo.
echo    Kiem: job treo, so chunk, tuoi ban backup,
echo          va ket qua eval dem qua.
echo    KHONG dong cua so nay - no tu tat sau vai giay.
echo  ==========================================================
echo.
set PYTHONUTF8=1
cd /d "%~dp0backend"
"..\.venv\Scripts\python.exe" -m scripts.check_operational_alerts --fail-on-alert >> "..\data\logs\alerts_check.log" 2>&1
set RC=%errorlevel%
if "%RC%"=="2" (
  start "" powershell -NoProfile -WindowStyle Hidden -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Local AI Core: co canh bao van hanh. Xem data\logs\alerts_check.log va data\logs\ATTENTION_nightly_eval.txt','Local AI Core - CANH BAO')"
)
exit /b %RC%
