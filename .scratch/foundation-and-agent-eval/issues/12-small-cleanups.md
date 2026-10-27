# 12 — Dọn nhỏ sau 03 (được phép trượt)

Status: đã gộp vào main (27/10), fable 5.1 duyệt
Type: task
Blocked by: — (kiểm 27/10: không chung file với 02; mục 6 và 05 cùng đụng operational_service.py nhưng khác dòng)

Gom các phát hiện ngoài phạm vi khi làm và duyệt ticket 03:

1. Constructor `DiscordMemoryWorkerService` còn mặc định `extractor_schema_version="v1"`
   (`discord_memory_worker_service.py:77`); `discord_memory_extractor.py:499` cũng vậy. Hiện
   `memory_tasks.py` luôn truyền từ Settings nên chưa hỏng, nhưng đây là chỗ thứ ba giữ mặc định.
2. `.env.example` vẫn chép nhiều mặc định của Settings (NUM_CTX, TEMPERATURE, SEED…). Ai chép file
   này thành `.env` sẽ ghim các giá trị đó, và sẽ lệch khi Settings đổi mặc định.
3. Regex lấy mặc định trong `test_compose_defaults.py` (`[^}]*`) đọc sai mặc định lồng kiểu
   `${A:-${B}}`. Hiện chỉ `CONTAINER_DATABASE_URL` (không phải field của Settings) có dạng lồng.
4. `test_postgres_cleanup_lifecycle.py::test_postgres_log_and_ocr_retention_execute_only_due_rows`
   đếm cả bản ghi OcrRun cũ còn sót trong DB test (`assert 3 == 1` ở mốc test 27/10). Test chỉ nên
   đếm bản ghi do chính nó tạo.

## Comments
- 27/10 (từ duyệt 01): (5) kiểm Ollama trước trong `nightly_eval.py` (hiện chỉ Postgres/Qdrant/Redis);
  (6) docstring `_qdrant_ok` nên ghi: Qdrant chậm hơn 3 s thì báo `unavailable`, nên
  `check_operational_alerts` buổi sáng có thể báo động một lần.

**27/10 — Nhân viên của Ún 3: xong 6/6.**

- (1) Chọn (a) theo opus. `DiscordMemoryWorkerService(extractor_schema_version=)` và
  `DiscordMemoryExtractorAdapter(schema_version=)` không còn mặc định. Đây là **lệch thật**, không
  chỉ chép trùng: hai constructor mặc định `v1`, còn Settings là `v2`. 22 chỗ giờ truyền `"v1"`
  tường minh:
  - `test_discord_memory_outbox_worker.py`: 11.
  - `test_discord_memory_extractor.py`: 8.
  - `test_discord_memory_verifier.py`: 1.
  - `test_memory_auto_apply.py`: 1.
  - `scripts/benchmark_discord_memory_extractor.py`: 1, kèm comment giải thích vì sao vẫn là v1.
    Cả 1401 mục `schema_version` trong `data/benchmarks/` đều là `v1`.
  
  `memory_tasks.py` vốn đã truyền giá trị từ Settings nên không đổi.
- (2) `.env.example`: comment 36 dòng có giá trị trùng mặc định của Settings, có một đoạn đầu file
  giải thích. Lệch đã có sẵn: file ghi `CONVERSATION_HISTORY_LIMIT=12`, Settings là `40` từ 27/08
  (commit 95b61f1). `.env` của máy này không đặt khoá đó, chỉ kiểm có hay không, không đọc giá trị.
- (3) `compose_default()` đọc mặc định tới đúng dấu ngoặc đóng của nó; test
  `test_a_nested_default_is_read_to_its_own_closing_brace`.
- (4) `cleanup_expired_ocr_runs() >= 1`. Assert theo từng dòng cho cả hai chiều đã có sẵn ở
  `test_postgres_cleanup_lifecycle.py:220-221` (OcrRun cũ của test bị xoá, OcrRun mới còn), và
  `:218-219` cho RequestLog.
- (5) Preflight eval đêm hỏi `/api/version` của Ollama, không gọi model; test
  `test_ollama_is_asked_its_version_never_a_model`.
- (6) **Đính chính ticket:** `check_operational_alerts` không đọc `/health`. Những nơi thấy Qdrant
  chậm thành `degraded` là `discord_bot/control.py` (`backend_healthy`) và `smoke-test-local.ps1`.
  Docstring `_qdrant_ok` ghi đúng như vậy. Chỉ sửa docstring, không đụng import.
- Test, chạy với Postgres trên `local_ai_core_test` khi opus cho phép:
  `pytest tests/test_discord_memory_outbox_worker.py tests/test_discord_memory_extractor.py tests/test_discord_memory_verifier.py tests/test_memory_auto_apply.py tests/test_compose_defaults.py tests/test_postgres_cleanup_lifecycle.py`.
  Trước khi sửa mục 1: 88 passed. Sau: 88 passed, kết quả từng test giống hệt (so bằng diff). Thêm
  `test_nightly_preflight.py` và `test_nightly_registry_gate.py`: 19 passed.
