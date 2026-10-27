# 12 — Dọn nhỏ sau 03 (được phép trượt)

Status: chờ
Type: task
Blocked by: 02

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
