#!/usr/bin/env bash
W=~/local-ai-core-wt/check-c57aa3e
PY=~/local-ai-core/.venv/Scripts/python.exe
OUT="~/AppData/Local/Temp/claude/ee2371d0a8cf6a43/e6e8417c-7768-4bfa-af3c-88aece6116c1/scratchpad/check-c57"
PW=$(cat "$TEMP/claude_check_pw")
export POSTGRES_TEST_URL="postgresql+psycopg://local_ai:$PW@127.0.0.1:55441/local_ai_core_test"
export REDIS_TEST_URL="redis://127.0.0.1:56381/15"
export DATABASE_URL="$POSTGRES_TEST_URL"
export QDRANT_URL="http://127.0.0.1:56334"
export OLLAMA_BASE_URL="http://127.0.0.1:9" MODEL_STARTUP_PROBES=false CUDA_VISIBLE_DEVICES=-1 PYTHONUTF8=1
export DISCORD_MEMORY_EXTRACTOR_MODEL=
export PYTHONPATH="$(cygpath -w $W);$(cygpath -w $W/backend)"
cd $W && "$PY" -m alembic upgrade head > "$OUT/alembic.log" 2>&1; echo "alembic exit $?" >> "$OUT/alembic.log"
cd $W/backend && "$PY" -m pytest tests -q -p no:cacheprovider --junitxml="$OUT/backend-full.xml" > "$OUT/backend-full.log" 2>&1; echo "backend exit $?"
cd $W && "$PY" -m pytest tests -q -p no:cacheprovider --junitxml="$OUT/root.xml" > "$OUT/root.log" 2>&1; echo "root exit $?"
