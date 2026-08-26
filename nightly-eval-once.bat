@echo off
setlocal EnableExtensions
title Local AI Core - Nightly Eval (dang chay, dung dong)
REM ASCII only, no diacritics: the console codepage (cp437/cp1252) mangles them
REM and a banner nobody can read is worse than no banner.
REM
REM The banner exists because of a real incident. On the first scheduled night
REM (26/08 03:00) this window opened while the user was chatting with the bot,
REM looked like a stray black console, and got closed -- the eval died 13 s in
REM with 0xC000013A and produced nothing. The window is deliberately NOT hidden
REM (a task you can see is a task you know ran), so it has to say what it is.
REM
REM Nightly eval of the SHIPPED retrieval config on the lab corpus (D4-lite #4).
REM CI only measures the bare path; this is the watch on what production runs.
REM Registered as "LocalAICore Nightly Eval", daily 03:00. On failure it leaves
REM data\logs\ATTENTION_nightly_eval.txt, which the 09:30 alerts task pops up.
echo.
echo  ==========================================================
echo    Local AI Core - Nightly Eval  ^(03:00^)
echo.
echo    Dang do chat luong RAG tren corpus lab.
echo    KHONG dong cua so nay - no tu tat sau vai phut.
echo.
echo    Ket qua: data\logs
ightly_eval.log
echo    Neu hong: data\logs\ATTENTION_nightly_eval.txt
echo  ==========================================================
echo.
set PYTHONUTF8=1
cd /d "%~dp0backend"
"..\.venv\Scripts\python.exe" -m scripts.nightly_eval
set RC=%errorlevel%
echo.
if "%RC%"=="0" (echo  [OK] Eval dat. Cua so tu dong dong.) else (echo  [LOI] Eval HONG - ma %RC%. Xem ATTENTION_nightly_eval.txt)
exit /b %RC%
