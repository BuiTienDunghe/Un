@echo off
title LocalAICoreDecided
REM The decided model, in WSL with the Fine-tune environment. See tools/decided_server.py.
set "HERE=%~dp0"
for /f "delims=" %%P in ('wsl.exe -d Ubuntu wslpath -a "%HERE%tools\decided_server.py"') do set "SERVER=%%P"
wsl.exe -d Ubuntu -- bash -c "cd /mnt/c/Users/dungbt06/Fine-tune && HF_HUB_OFFLINE=1 HF_HUB_DISABLE_PROGRESS_BARS=1 TRANSFORMERS_VERBOSITY=error PYTHONUTF8=1 .venv/bin/python -u '%SERVER%'"
