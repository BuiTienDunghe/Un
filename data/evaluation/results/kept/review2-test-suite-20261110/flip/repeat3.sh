#!/usr/bin/env bash
# Three consecutive runs of every review2 test file (backend files in one pytest call, then the root file).
source "C:/Users/dungbt06/AppData/Local/Temp/claude/ee2371d0a8cf6a43/e6e8417c-7768-4bfa-af3c-88aece6116c1/scratchpad/check-c57/env_fix.sh"
OUT="C:/Users/dungbt06/AppData/Local/Temp/claude/ee2371d0a8cf6a43/e6e8417c-7768-4bfa-af3c-88aece6116c1/scratchpad/repeat3.txt"
: > "$OUT"
ROOT="C:/Users/dungbt06/local-ai-core"
for i in 1 2 3; do
  echo "== run $i $(date '+%H:%M:%S')" >> "$OUT"
  (cd "$ROOT/backend" && ../.venv/Scripts/python.exe -m pytest tests/test_review2_discord_turns.py tests/test_review2_bot_backend.py \
     tests/test_review2_ledger.py tests/test_review2_clocks.py tests/test_review2_auth.py tests/test_review2_ocr_jobs.py \
     tests/test_review2_ocr_access.py tests/test_review2_ocr_reader.py -q -p no:cacheprovider -rfEX 2>&1 | grep -E "^(FAILED|ERROR|XPASS)|passed|failed" >> "$OUT")
  (cd "$ROOT" && .venv/Scripts/python.exe -m pytest tests/test_review2_bot_turns.py -q -p no:cacheprovider -rfEX 2>&1 | grep -E "^(FAILED|ERROR|XPASS)|passed|failed" >> "$OUT")
done
echo "== end $(date '+%H:%M:%S')" >> "$OUT"
