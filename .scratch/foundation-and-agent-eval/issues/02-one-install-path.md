# 02 — Một cách cài, xoá hack sys.path (M1b)

Status: chờ
Type: task
Blocked by: 01

## Vì sao

Code có hai gốc import (gốc repo và `backend/`). CI cài editable (`.github/workflows/ci.yml`, bước
"Verify the editable install"), còn launcher thì không (`run-local-ai-core.bat:118`), nên có 19 chỗ
`sys.path.insert` vá tay: `backend/alembic/env.py`; `backend/scripts/` forget_member, memory_e2e_eval,
migrate_document_storage, migrate_sqlite_documents_to_postgres, migrate_sqlite_to_postgres,
recover_discord_memory_jobs, recover_stale_jobs; `backend/tests/` test_eval_stack_model_version,
test_passive_listener; `tools/discord_bot_control.py`; `training/common/` eval_heldout, eval_stack,
eval_worker, ingest_corpus, reindex_all; `training/reranker/` build_judgement_tasks, mine_negatives,
remap_judgements.

Kiểm 27/10: `.venv` của máy này **đã** có editable install (từ thư mục ngoài repo, `import app` trỏ
về `backend/app`).

## Việc

1. Launcher chạy `pip install -e . --no-deps` khi chưa cài (idempotent, không cài lại mỗi lần).
2. Xoá từng hack; mỗi file phải chạy được từ đúng thư mục mà docs/launcher dùng.
3. `.venv-eval` và `.venv-train` (training): kiểm chúng có cài editable chưa; nếu chưa thì ghi vào
   `training/README.md` cách cài, không tự cài.

## Nghiệm thu

Launcher chạy được từ venv sạch (ghi cách đã thử); một script `backend/scripts/` và một script
`training/` chạy `--help` được mà không cần hack; test đụng tới vẫn xanh.

## Comments
