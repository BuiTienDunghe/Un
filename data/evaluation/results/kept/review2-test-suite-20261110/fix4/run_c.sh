#!/usr/bin/env bash
# (c) runs for review2 fix4: each mutation on the edited tests (new) and on the pre-edit copies (old).
# Usage: bash run_c.sh [new|old|both]
set -u
source "C:/Users/dungbt06/AppData/Local/Temp/claude/ee2371d0a8cf6a43/e6e8417c-7768-4bfa-af3c-88aece6116c1/scratchpad/check-c57/env_fix.sh"
ROOT="C:/Users/dungbt06/local-ai-core"
KEEP="$ROOT/data/evaluation/results/kept/review2-test-suite-20261110/fix4"
SCRATCH="C:/Users/dungbt06/AppData/Local/Temp/claude/ee2371d0a8cf6a43/e6e8417c-7768-4bfa-af3c-88aece6116c1/scratchpad/fix4"
T="$ROOT/backend/tests"

cp "$SCRATCH/test_review2_tmp_fix4.py" "$T/test_review2_tmp_fix4.py"
cp "$KEEP/before/review2_support.py" "$T/review2_tmp_old_support.py"
sed 's/^from review2_support import/from review2_tmp_old_support import/' "$KEEP/before/test_review2_bot_backend.py" > "$T/test_review2_tmp_old_bot_backend.py"
cp "$KEEP/before/test_review2_auth.py" "$T/test_review2_tmp_old_auth.py"
cp "$KEEP/before/test_review2_discord_turns.py" "$T/test_review2_tmp_old_discord_turns.py"

declare -A SELECT=(
  [a_msg2]="test_a5_ or test_a6_ or test_a7_ or test_a8_"
  [a_msg1]="test_a6_ or test_a7_"
  [a5_msg1]="test_a5_"
  [r5_one]="test_r5_1"
  [r5_both]="test_r5_1"
  [r3_500]="test_r3_1 or test_r3_2"
  [r3_409]="test_r3_1 or test_r3_2"
  [n4_appended]="test_n4_1"
  [n4_exact]="test_n4_1"
)
ORDER="a_msg2 a_msg1 a5_msg1 r5_one r5_both r3_500 r3_409 n4_appended n4_exact"
case "${1:-both}" in new) SOURCES="new";; old) SOURCES="old";; *) SOURCES="new old";; esac

cd "$ROOT/backend"
for source in $SOURCES; do
  for mode in $ORDER; do
    out="$KEEP/c-$source-$mode.txt"
    echo "== REVIEW2_FIX4=$mode REVIEW2_FIX4_SOURCE=$source  start $(date '+%H:%M:%S')" > "$out"
    REVIEW2_FIX4="$mode" REVIEW2_FIX4_SOURCE="$source" ../.venv/Scripts/python.exe -m pytest tests/test_review2_tmp_fix4.py \
      -p no:cacheprovider -rA --tb=short -k "${SELECT[$mode]}" 2>&1 | grep -vE "^\s*$" >> "$out"
    echo "== end $(date '+%H:%M:%S')" >> "$out"
    echo "--- $source $mode: $(grep -E '^=+ .*(passed|failed|xfailed|skipped|error).* in ' "$out" | tail -1)"
  done
done

rm -f "$T/test_review2_tmp_fix4.py" "$T/review2_tmp_old_support.py" "$T/test_review2_tmp_old_bot_backend.py" \
      "$T/test_review2_tmp_old_auth.py" "$T/test_review2_tmp_old_discord_turns.py"
ls "$T"/*tmp* 2>/dev/null || echo "temp files removed"
