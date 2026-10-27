# 02 — Một cách cài, xoá hack sys.path (M1b)

Status: chờ duyệt — Nhân viên của Ún 1, nhánh `wip/02-one-install-path`
Type: task
Blocked by: — (kiểm 27/10: 01 không đụng file nào của 02)

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

### 27/10 — Nhân viên của Ún 1

Bản chất: trước đây mỗi script tự chỉ đường cho Python tới code của dự án. Giờ dự án được
"cài" vào môi trường Python một lần, nên script nào chạy từ đâu cũng tìm được code. Launcher tự
cài khi chưa có, và lần sau thì bỏ qua.

Kết quả: gỡ 18/19 chỗ vá, giữ 1 (đã duyệt).

| Nhóm | Gỡ | Ghi chú |
|---|---|---|
| `backend/alembic/env.py` | có | Vốn thừa: `alembic.ini` đã có sẵn `prepend_sys_path = . backend` |
| 7 file `backend/scripts/` | có | Chạy dạng file từ gốc repo, `app` lấy từ bản cài |
| `backend/tests/test_passive_listener.py` | có | `discord_bot` nằm trong bản cài |
| `tools/discord_bot_control.py` | có | Như trên |
| 8 file `training/` | có | 3 file lấy `api_key_headers` từ nơi mới (xem dưới) |
| `backend/tests/test_eval_stack_model_version.py` | **giữ** | Cách b3 điều phối chọn; có comment lý do trong file |

- `api_key_headers` dời sang `backend/app/security/api_key.py`, docstring giữ nguyên.
  `evaluate_rag.py` import lại đúng tên cũ. `docs/FAILURE_MODES.md` đã trỏ về chỗ mới.
  Hệ quả: import `scripts.evaluate_rag` giờ kéo theo fastapi, jwt và các model SQLAlchemy (đo
  0,87 s). Trước đây nó chỉ cần httpx. Mọi nơi chạy nó đều có đủ requirements.
- Launcher: kiểm `import app` bằng `python -I` (không có thư mục hiện tại trên sys.path), và phải
  trỏ đúng checkout này. Sai hoặc thiếu thì chạy `pip install -e . --no-deps`. Bỏ `pushd backend`
  quanh lệnh registry, vì đường dẫn Modelfile vốn đã là tuyệt đối. Lần cài đầu cần mạng (để tải
  setuptools).
- Không đụng tới chỗ chỉnh sys.path có chủ đích: `prepend_sys_path` của alembic.
- `.venv-eval` / `.venv-train`: chưa có bản cài editable, và thiếu pydantic_settings và
  sqlalchemy. Không file nào chỉ chạy được dưới hai venv đó, nên không giữ chỗ vá nào vì lý do
  này. Cách cài cho `build_judgement_tasks` / `remap_judgements` đã ghi trong
  `training/README.md`. Chưa cài gì vào hai venv đó.

Cách kiểm. Venv sạch tạo trong scratchpad, cài `requirements.txt`. Bản cài editable của nó trỏ về
worktree, nên không lẫn với checkout chính. Mọi URL phụ thuộc trỏ vào cổng chết.

| Kiểm | Kết quả |
|---|---|
| Đoạn cài của launcher (trích nguyên văn, chỉ thay đường dẫn venv), venv sạch | lần 1 cài, 10,2 s; lần 2 bỏ qua, 0,1 s |
| `--help` của 7 script `backend/scripts/` chạy dạng file từ gốc | 7/7 exit 0 |
| `python -m training...` từ gốc: 6 `--help`, import `remap_judgements`, `eval_worker` không tham số | đều chạy; `eval_worker` in usage, exit 2 như cũ |
| `model_registry --ollama-pull-list` và `alembic upgrade head --sql` từ gốc | exit 0 |
| Gỡ bản cài rồi chạy lại | `No module named 'app'`; đoạn launcher cài lại, sau đó exit 0 |
| Bộ test ở gốc (bot + tools), venv sạch | 65 xanh |
| 4 file test backend không cần DB, `.venv` + `PYTHONPATH=<worktree>\backend` | 24 xanh |
| 14 file test backend đụng module đã sửa (migration, schema drift, evaluate_rag, …), DB test | 47 xanh, 0 skip |

Chưa kiểm: chạy trọn launcher (nó bật container và DB, ngoài quy tắc).

Hệ quả cần biết: `discord-bot-control.bat` chạy `tools\discord_bot_control.py` dạng file bằng
`pythonw`, và giờ cần bản cài editable. Trên một máy có `.venv` cũ mà chưa chạy launcher mới lần
nào, bảng điều khiển sẽ không hiện, và cũng không báo lỗi (`pythonw` không có console). Máy này
không dính, vì `.venv` đã có bản cài. File `.bat` đó nằm ngoài ticket; đã báo điều phối.
