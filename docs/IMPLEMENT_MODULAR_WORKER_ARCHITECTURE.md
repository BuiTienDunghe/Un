# PROMPT TRIỂN KHAI MODULAR WORKER ARCHITECTURE CHO LOCAL AI CORE

## Vai trò của bạn

Bạn là kỹ sư backend/AI system senior đang làm việc trực tiếp trên repository hiện tại.

Hãy kiểm tra code thực tế trước khi sửa. Không được giả định tên file, framework, class, bảng dữ liệu hoặc luồng xử lý nếu chưa xác minh trong repository.

Mục tiêu là nâng cấp document/RAG pipeline hiện tại sang kiến trúc **Modular Worker Architecture**, nhưng vẫn giữ chung một codebase và không chuyển thành microservices hoàn chỉnh.

Repository dự kiến nằm tại:

```text
C:\Users\dungbt06\Ún promax\local-ai-core
```

Nếu đường dẫn thực tế khác, hãy dùng repository đang được mở trong workspace.

---

# 1. Bối cảnh hệ thống hiện tại

Luồng tài liệu hiện tại có dạng:

```text
Upload file
→ lưu file gốc
→ tạo metadata SQLite
→ index tài liệu
→ trích xuất text theo trang
→ OCR fallback cho trang cần thiết
→ chia chunks
→ tạo embedding
→ lưu SQLite + Qdrant
→ dùng cho RAG
```

Các đặc điểm hiện tại:

- Hỗ trợ PDF, DOCX, TXT và MD.
- Giới hạn file khoảng 50 MB.
- PDF được đọc native text trước.
- Trang có chất lượng text thấp mới được OCR.
- OCR chạy qua model hiện có trên Ollama.
- Embedding hiện dùng `qwen3-embedding:0.6b`.
- Qdrant lưu vector và metadata nhẹ.
- SQLite lưu metadata tài liệu và nội dung đầy đủ của chunks.
- RAG sử dụng dense retrieval và lexical/BM25 retrieval.
- OCR test pipeline là luồng riêng với document ingestion.
- File gốc và OCR artefact đang được lưu trong thư mục local.

Không được tự ý đổi OCR model, embedding model hoặc LLM model. Hãy đọc cấu hình hiện tại và chuyển chúng thành biến môi trường nếu đang bị hard-code.

---

# 2. Kiến trúc đích bắt buộc

Triển khai kiến trúc sau:

```text
Frontend / Discord / CLI
          ↓
       FastAPI
          ↓
 ┌────────┼───────────────┐
 │        │               │
PostgreSQL Redis        Qdrant
 │        │               │
 │     Job Queue          │
 │        ↓               │
 │  ┌──────────────────┐  │
 │  │ OCR Worker       │  │
 │  │ Index Worker     │  │
 │  │ Cleanup Worker   │  │
 │  │ Outbox Dispatcher│  │
 │  └──────────────────┘  │
 │                        │
 └────── Local Storage ───┘
```

Các nguyên tắc:

1. **PostgreSQL là source of truth.**
2. **Qdrant chỉ là retrieval index**, có thể xây dựng lại từ PostgreSQL.
3. **Redis chỉ dùng cho hàng đợi và trạng thái job tạm thời**, không phải nơi lưu dữ liệu chuẩn.
4. FastAPI không trực tiếp thực hiện OCR hoặc embedding dài.
5. OCR Worker và Index Worker chạy bằng process/container riêng nhưng dùng chung codebase.
6. Mỗi lần index phải có version riêng.
7. Version mới chỉ được active sau khi toàn bộ chunks đã được embedding và upsert Qdrant thành công.
8. Phải có transactional outbox để tránh mất job hoặc lệch PostgreSQL–Qdrant.
9. Mọi job phải idempotent, có thể retry mà không tạo dữ liệu trùng.
10. Không phá API hoặc UI hiện tại nếu không thật sự cần thiết.

---

# 3. Công nghệ ưu tiên

Ưu tiên dùng:

- FastAPI.
- PostgreSQL.
- SQLAlchemy 2.x.
- Alembic.
- Redis.
- RQ cho queue/worker vì nhẹ và phù hợp triển khai local.
- Qdrant.
- Ollama.
- PyMuPDF cho PDF.
- Pydantic Settings cho biến môi trường.
- Docker Compose để chạy hạ tầng.
- Pytest cho test.

Nếu repository đã dùng thư viện tương đương và thay thế sẽ gây sửa lớn, hãy giữ thư viện hiện tại và giải thích rõ.

Ollama có thể chạy trực tiếp trên Windows. Trong container, hỗ trợ:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Khi chạy backend ngoài Docker:

```env
OLLAMA_BASE_URL=http://localhost:11434
```

---

# 4. Data model bắt buộc

Hãy thiết kế schema PostgreSQL tối thiểu như sau. Có thể đổi tên cho phù hợp convention hiện tại, nhưng không được bỏ chức năng.

## 4.1 `documents`

Lưu thực thể tài liệu logic:

- `id`
- `original_filename`
- `stored_filename`
- `mime_type`
- `file_size`
- `content_hash`
- `status`
- `active_version_id`
- `source_available`
- `created_at`
- `updated_at`
- `indexed_at`
- `last_accessed_at`
- `error_message`

Trạng thái nên gồm:

```text
uploaded
queued
processing
indexed
partial
failed
deleting
deleted
```

## 4.2 `document_versions`

Mỗi lần upload lại hoặc reindex tạo một version:

- `id`
- `document_id`
- `version_number`
- `status`
- `parser_name`
- `parser_version`
- `ocr_model`
- `embedding_model`
- `chunking_config` dạng JSONB
- `created_at`
- `activated_at`
- `superseded_at`

Trạng thái:

```text
staging
active
superseded
failed
deleted
```

## 4.3 `ingestion_runs`

Mỗi lần thử xử lý một version:

- `id`
- `document_id`
- `version_id`
- `status`
- `current_stage`
- `total_pages`
- `processed_pages`
- `ocr_pages`
- `total_chunks`
- `embedded_chunks`
- `progress_percent`
- `attempt`
- `started_at`
- `completed_at`
- `error_code`
- `error_message`

Các stage:

```text
queued
parsing
ocr
chunking
embedding
qdrant_upsert
activating
completed
failed
cancelled
```

## 4.4 `document_pages`

- `id`
- `document_id`
- `version_id`
- `page_number`
- `native_text`
- `ocr_text`
- `selected_text`
- `extraction_method`
- `native_quality_score`
- `ocr_quality_score`
- `render_dpi`
- `status`
- `error_message`

`extraction_method` hỗ trợ:

```text
native
ocr
hybrid
```

## 4.5 `document_chunks`

- `id`
- `chunk_uid`
- `document_id`
- `version_id`
- `chunk_index`
- `content`
- `content_hash`
- `page_start`
- `page_end`
- `section_title`
- `block_type`
- `token_count`
- `extraction_method`
- `status`
- `created_at`

Ràng buộc bắt buộc:

```text
UNIQUE(document_id, version_id, chunk_index)
UNIQUE(chunk_uid)
```

## 4.6 `jobs`

Lưu trạng thái bền vững của job:

- `id`
- `job_type`
- `document_id`
- `version_id`
- `ingestion_run_id`
- `status`
- `priority`
- `attempts`
- `max_attempts`
- `available_at`
- `started_at`
- `completed_at`
- `worker_id`
- `error_message`
- `payload` JSONB

## 4.7 `outbox_events`

- `id`
- `event_type`
- `aggregate_type`
- `aggregate_id`
- `payload` JSONB
- `status`
- `attempts`
- `available_at`
- `published_at`
- `processed_at`
- `last_error`
- `created_at`

Trạng thái:

```text
pending
published
processing
completed
failed
```

---

# 5. State machine và logic xử lý

## 5.1 Upload

FastAPI chỉ thực hiện:

```text
validate file
→ tính SHA-256
→ lưu file gốc
→ tạo document
→ tạo document_version ở trạng thái staging
→ tạo ingestion_run
→ tạo job hoặc outbox event
→ trả document_id + run_id
```

Các thao tác tạo document, version, run và outbox event phải nằm trong cùng một PostgreSQL transaction.

Không được thực hiện OCR hoặc embedding trong HTTP request.

## 5.2 OCR Worker

OCR Worker xử lý:

```text
load source file
→ parse native text
→ đánh giá chất lượng từng trang
→ OCR trang cần thiết
→ lưu document_pages
→ cập nhật progress
→ tạo event TEXT_EXTRACTION_COMPLETED
```

Yêu cầu:

- Retry theo trang.
- Một trang lỗi không làm mất kết quả của các trang đã hoàn tất.
- Không giữ transaction PostgreSQL trong khi gọi Ollama.
- Ghi kết quả theo batch hoặc transaction ngắn.
- Hỗ trợ hủy job.
- Dùng model OCR hiện có trong repository, cấu hình bằng `OCR_MODEL`.
- Không thay model nếu không có yêu cầu riêng.
- Lưu model, prompt version và DPI vào metadata.

## 5.3 Index Worker

Index Worker xử lý:

```text
load selected_text của pages
→ normalize
→ structure-aware chunking
→ batch insert staging chunks
→ batch embedding
→ deterministic Qdrant point IDs
→ upsert Qdrant
→ verify count
→ active version mới
```

Yêu cầu:

- Không chia chunk thuần theo ký tự nếu code hiện tại có thể nâng cấp an toàn.
- Ưu tiên heading → paragraph → sentence → token fallback.
- Giữ `page_start`, `page_end`, `section_title`, `extraction_method`.
- Embedding theo batch.
- Không giữ transaction PostgreSQL khi gọi Ollama hoặc Qdrant.
- Qdrant point ID phải deterministic từ `document_id + version_id + chunk_index` hoặc `chunk_uid`.
- Retry không tạo vector trùng.
- Chỉ activate version sau khi số chunks trong PostgreSQL và số vector dự kiến đã khớp.
- Nếu index version mới lỗi, version active cũ vẫn phải hoạt động.

## 5.4 Kích hoạt version

Trong một transaction ngắn:

```text
version mới: staging → active
version cũ: active → superseded
documents.active_version_id = version mới
documents.status = indexed
ingestion_run.status = completed
```

Retrieval chỉ được dùng version active.

## 5.5 Cleanup Worker

Cleanup Worker chạy định kỳ và xử lý riêng:

1. Xóa OCR artefact tạm quá hạn.
2. Xóa request log quá hạn.
3. Retry hoặc đánh dấu job bị treo.
4. Dọn version staging/failed cũ.
5. Xóa Qdrant points của version superseded khi đã qua thời gian an toàn.
6. Reconcile PostgreSQL và Qdrant.
7. Không tự động xóa file gốc của tài liệu active chỉ vì quá 30 ngày.

Phải phân biệt:

```text
xóa artefact tạm
xóa file gốc nhưng giữ tri thức
xóa hoàn toàn tài liệu
```

---

# 6. Transactional outbox

Không được giả định PostgreSQL và Redis/Qdrant có transaction chung.

Luồng bắt buộc:

```text
PostgreSQL transaction:
  lưu dữ liệu
  + tạo outbox event
COMMIT

Outbox Dispatcher:
  đọc pending events
  → publish Redis queue
  → cập nhật published
```

Worker nhận job phải kiểm tra trạng thái trong PostgreSQL trước khi xử lý.

Các event tối thiểu:

```text
DOCUMENT_UPLOADED
TEXT_EXTRACTION_REQUESTED
TEXT_EXTRACTION_COMPLETED
INDEX_BUILD_REQUESTED
VECTOR_UPSERT_REQUESTED
INDEX_VERSION_READY
DOCUMENT_DELETE_REQUESTED
QDRANT_DELETE_REQUESTED
```

Phải có cơ chế chống publish trùng và xử lý trùng:

- deterministic job key;
- unique constraint;
- idempotency key;
- kiểm tra trạng thái trước khi chạy;
- retry với exponential backoff;
- dead-letter hoặc trạng thái failed sau số lần thử tối đa.

---

# 7. Qdrant

Qdrant payload tối thiểu:

```json
{
  "workspace_id": null,
  "document_id": "...",
  "version_id": "...",
  "chunk_id": "...",
  "chunk_index": 0,
  "page_start": 1,
  "page_end": 1,
  "section_title": null,
  "extraction_method": "native"
}
```

Không lưu content đầy đủ trong Qdrant nếu PostgreSQL đã là source of truth.

Retrieval phải filter theo:

```text
version_id = documents.active_version_id
```

hoặc filter theo `document_id + active version`.

Tạo payload index cho các trường filter thường xuyên:

- `document_id`
- `version_id`
- `workspace_id` nếu có
- `extraction_method` nếu được dùng để lọc

Sau Qdrant search, lấy chunks từ PostgreSQL bằng một batch query, không query từng chunk riêng lẻ.

---

# 8. RAG retrieval

Giữ hoặc nâng cấp retrieval hiện tại theo nguyên tắc:

```text
query
→ dense retrieval
→ lexical retrieval
→ fusion
→ deduplicate
→ optional rerank
→ lấy content PostgreSQL
→ build context
→ LLM
```

Nếu lexical retrieval hiện tại đang dùng SQLite FTS5, hãy chuyển sang một trong hai cách:

1. PostgreSQL full-text search bằng `tsvector` + GIN; hoặc
2. Qdrant dense + sparse hybrid nếu hệ thống hiện tại đã có sparse representation.

Ưu tiên lựa chọn ít phá code nhất.

Không được gọi `LIKE '%query%'` là BM25.

Nếu score lexical và dense khác thang điểm, dùng Reciprocal Rank Fusion thay vì cộng trực tiếp raw score.

Retrieval phải:

- chỉ dùng version active;
- loại chunk trùng do overlap;
- gộp các chunk liền kề khi phù hợp;
- giữ nguồn, trang và extraction method;
- không trả chunk thuộc document đang deleting/deleted.

---

# 9. API và progress

Giữ tương thích endpoint hiện có nếu có thể.

Cần có hoặc bổ sung:

```text
POST   /documents/upload
POST   /documents/{id}/index
GET    /documents/{id}
GET    /documents/{id}/status
GET    /ingestion-runs/{run_id}
POST   /ingestion-runs/{run_id}/retry
POST   /ingestion-runs/{run_id}/cancel
DELETE /documents/{id}
POST   /documents/{id}/reindex
```

Response trạng thái cần có:

```json
{
  "document_id": "...",
  "version_id": "...",
  "run_id": "...",
  "status": "processing",
  "stage": "ocr",
  "progress_percent": 45,
  "processed_pages": 9,
  "total_pages": 20,
  "ocr_pages": 4,
  "embedded_chunks": 0,
  "total_chunks": 0,
  "error": null
}
```

Nếu frontend hiện polling, tiếp tục hỗ trợ polling. WebSocket/SSE là tùy chọn, không bắt buộc ở lần triển khai đầu.

---

# 10. Storage

Giai đoạn hiện tại ưu tiên local storage có abstraction rõ ràng:

```text
StorageService
├── LocalStorageBackend
└── MinIOStorageBackend trong tương lai
```

Không hard-code đường dẫn khắp codebase.

Cấu trúc gợi ý:

```text
data/
├── documents/<document_id>/<version_id>/original.ext
├── ingestion_runs/<run_id>/
├── ocr_runs/<ocr_run_id>/
└── exports/
```

Phải chống path traversal và không dùng trực tiếp filename của người dùng làm đường dẫn vật lý.

---

# 11. Docker Compose và cấu hình

Bổ sung hoặc cập nhật Docker Compose với:

```text
postgres
redis
qdrant
api
worker-ocr
worker-index
worker-cleanup
outbox-dispatcher
```

Không bắt buộc đưa Ollama vào container nếu hiện đang chạy tốt trên Windows.

Các biến môi trường tối thiểu:

```env
DATABASE_URL=postgresql+psycopg://...
REDIS_URL=redis://redis:6379/0
QDRANT_URL=http://qdrant:6333
OLLAMA_BASE_URL=http://host.docker.internal:11434

OCR_MODEL=<đọc từ cấu hình hiện tại>
EMBEDDING_MODEL=qwen3-embedding:0.6b
LLM_MODEL=<đọc từ cấu hình hiện tại>

DOCUMENT_STORAGE_ROOT=/app/data
MAX_UPLOAD_SIZE_MB=50
OCR_DEFAULT_DPI=200
OCR_RETRY_DPI=300

JOB_MAX_ATTEMPTS=3
JOB_RETRY_BASE_SECONDS=10
```

Tạo `.env.example`, không ghi secret vào Git.

Thêm healthcheck cho PostgreSQL, Redis và Qdrant.

Worker chỉ khởi động sau khi dependency sẵn sàng.

---

# 12. Migration SQLite sang PostgreSQL

Không được xóa SQLite hoặc dữ liệu cũ ngay.

Thực hiện:

1. Backup file SQLite hiện tại.
2. Tạo Alembic schema PostgreSQL.
3. Viết script migration có dry-run.
4. Di chuyển documents.
5. Di chuyển chunks.
6. Bảo toàn document ID và chunk mapping khi có thể.
7. Ghi lại bản ghi không migrate được.
8. Kiểm tra count trước và sau.
9. Không đánh dấu document indexed nếu Qdrant mapping không hợp lệ.
10. Chỉ chuyển ứng dụng sang PostgreSQL sau khi validation thành công.

Script gợi ý:

```text
scripts/migrate_sqlite_to_postgres.py
```

Hỗ trợ:

```bash
python scripts/migrate_sqlite_to_postgres.py --dry-run
python scripts/migrate_sqlite_to_postgres.py --execute
python scripts/migrate_sqlite_to_postgres.py --verify
```

Nếu schema SQLite hiện tại khác mô tả, hãy đọc schema thật và tạo mapping tương ứng.

---

# 13. Cấu trúc code gợi ý

Không bắt buộc giống hoàn toàn, nhưng phải tách trách nhiệm rõ:

```text
app/
├── api/
├── core/
│   ├── config.py
│   ├── database.py
│   ├── redis.py
│   └── logging.py
├── models/
├── schemas/
├── repositories/
├── services/
│   ├── document_service.py
│   ├── ingestion_service.py
│   ├── ocr_service.py
│   ├── chunking_service.py
│   ├── embedding_service.py
│   ├── qdrant_service.py
│   ├── retrieval_service.py
│   ├── storage_service.py
│   └── outbox_service.py
├── workers/
│   ├── ocr_worker.py
│   ├── index_worker.py
│   ├── cleanup_worker.py
│   └── outbox_dispatcher.py
├── jobs/
├── migrations/
└── tests/
```

Không sao chép logic OCR hoặc embedding giữa API và worker. Mọi luồng phải dùng chung service layer.

---

# 14. Logging, lỗi và quan sát hệ thống

Dùng structured logging.

Mỗi log quan trọng cần có:

```text
request_id
document_id
version_id
run_id
job_id
worker_id
stage
```

Không log toàn bộ nội dung tài liệu hoặc prompt nhạy cảm mặc định.

Phân loại lỗi:

```text
VALIDATION_ERROR
FILE_PARSE_ERROR
OCR_ERROR
CHUNKING_ERROR
EMBEDDING_ERROR
QDRANT_ERROR
DATABASE_ERROR
JOB_TIMEOUT
CANCELLED
```

Lưu error code và message đã làm sạch vào PostgreSQL.

---

# 15. Test bắt buộc

Viết unit test và integration test cho tối thiểu:

1. Upload file hợp lệ.
2. Từ chối extension/MIME sai.
3. Từ chối file quá lớn.
4. PDF native text.
5. PDF scan cần OCR.
6. PDF mixed native + scan.
7. OCR lỗi một trang và retry.
8. Worker chết giữa embedding và retry.
9. Upsert Qdrant lặp không tạo vector trùng.
10. Index version mới lỗi nhưng version cũ vẫn active.
11. Activate version thành công.
12. Retrieval chỉ lấy active version.
13. Delete document không còn xuất hiện trong RAG.
14. Outbox event bị publish lặp.
15. Hai worker không xử lý cùng một job.
16. Migration SQLite → PostgreSQL dry-run.
17. Batch load chunks tránh N+1 query.
18. Cleanup không xóa file gốc của document active ngoài chính sách.

Tạo fixtures nhỏ, không phụ thuộc model lớn cho mọi unit test. Mock Ollama và Qdrant ở unit test; dùng integration test riêng cho service thật.

---

# 16. Thứ tự triển khai bắt buộc

Không sửa tất cả trong một lần lớn. Chia thành các phase sau.

## Phase 0 — Audit

- Đọc repository.
- Vẽ lại luồng hiện tại.
- Liệt kê schema SQLite thật.
- Liệt kê endpoint và service hiện tại.
- Xác định OCR, embedding, Qdrant adapter.
- Xác định test hiện có.
- Tạo tài liệu `docs/current_architecture.md`.
- Đưa ra danh sách file dự kiến sửa.

Không thay code lớn trước khi audit xong.

## Phase 1 — PostgreSQL foundation

- Thêm PostgreSQL, SQLAlchemy, Alembic.
- Tạo schema mới.
- Thêm repository layer.
- Tạo migration script từ SQLite.
- Giữ API hiện tại hoạt động.
- Thêm test database.

## Phase 2 — Versioned ingestion

- Thêm document versions và ingestion runs.
- Tách status/stage rõ ràng.
- Reindex không ghi đè version active.
- Retrieval lọc active version.

## Phase 3 — Redis queue và workers

- Thêm Redis + RQ.
- Tách OCR Worker.
- Tách Index Worker.
- FastAPI chỉ enqueue.
- Thêm progress, cancel và retry.

## Phase 4 — Transactional outbox

- Thêm outbox events.
- Thêm dispatcher.
- Idempotency.
- Retry/backoff.
- Reconciliation PostgreSQL–Qdrant.

## Phase 5 — Cleanup và delete lifecycle

- Cleanup Worker.
- Xóa artefact tạm.
- Delete document theo trạng thái.
- Xóa Qdrant theo event.
- Không để orphan data.

## Phase 6 — Hardening

- Integration tests.
- Healthchecks.
- Logging.
- Docker Compose.
- `.env.example`.
- Tài liệu chạy hệ thống.
- Benchmark PDF 20 trang.

Sau mỗi phase:

1. Chạy lint nếu repo có.
2. Chạy type check nếu repo có.
3. Chạy test.
4. Ghi rõ lỗi còn lại.
5. Không sang phase tiếp theo nếu phase hiện tại chưa chạy được.

---

# 17. Quy tắc làm việc bắt buộc cho Codex

1. Đọc code trước khi sửa.
2. Không bịa tên module hoặc hành vi.
3. Không xóa code đang hoạt động nếu chưa có phương án thay thế.
4. Ưu tiên thay đổi nhỏ, có migration.
5. Không hard-code model name, URL hoặc đường dẫn.
6. Không giữ database transaction khi gọi OCR, embedding hoặc Qdrant.
7. Mọi retry phải idempotent.
8. Không gọi raw lexical score và cosine score rồi cộng trực tiếp nếu chưa normalize.
9. Không tự động xóa file gốc của tài liệu active.
10. Không lưu full content trong Qdrant nếu PostgreSQL đã giữ content.
11. Không dùng Redis làm source of truth.
12. Không chuyển sang microservices hoặc Kubernetes.
13. Không thêm Kafka, RabbitMQ, OpenSearch hoặc MinIO nếu chưa cần.
14. Không thay OCR model chỉ để hoàn thành migration.
15. Nếu phát hiện code hiện tại khác mô tả, ưu tiên code thực tế và ghi rõ khác biệt.
16. Mọi thay đổi schema phải đi qua Alembic.
17. Mọi cấu hình mới phải có trong `.env.example`.
18. Tất cả command phải phù hợp môi trường Windows/Docker hiện tại.
19. Không yêu cầu người dùng xác nhận từng file nhỏ; tự thực hiện theo phase và báo cáo rõ.
20. Nếu một phần chưa thể hoàn thành, giữ hệ thống chạy được và ghi rõ blocker thực tế.

---

# 18. Definition of Done

Công việc chỉ được coi là hoàn tất khi:

- Ứng dụng dùng PostgreSQL thay SQLite cho pipeline mới.
- Có migration script và backup hướng dẫn.
- Upload API không chờ OCR/index hoàn tất.
- OCR và index chạy bằng worker riêng.
- Redis queue hoạt động.
- Có progress theo stage.
- Có retry và cancel cơ bản.
- Có document version và active version.
- Index lỗi không làm hỏng version active trước đó.
- Qdrant point ID deterministic.
- Transactional outbox hoạt động.
- Retrieval chỉ dùng active version.
- Delete không để orphan chunks/vector/file.
- Cleanup không xóa nguồn active sai chính sách.
- Docker Compose khởi động được các service.
- Test chính vượt qua.
- Có tài liệu chạy local.
- Có báo cáo migration và thay đổi kiến trúc.

---

# 19. Báo cáo cuối cùng Codex phải trả

Sau khi hoàn thành mỗi phase, trả theo mẫu:

```markdown
## Phase đã hoàn thành

### Những gì đã thay đổi
- ...

### File đã tạo/sửa
- `path/to/file`: lý do

### Schema/API thay đổi
- ...

### Lệnh đã chạy
```bash
...
```

### Kết quả test
- Passed:
- Failed:
- Skipped:

### Rủi ro hoặc việc chưa hoàn tất
- ...

### Bước tiếp theo
- ...
```

Ở cuối toàn bộ công việc, bổ sung:

- sơ đồ kiến trúc cuối;
- luồng upload/index/RAG/delete;
- hướng dẫn `.env`;
- hướng dẫn Docker Compose;
- hướng dẫn migrate SQLite;
- cách rollback;
- cách kiểm tra PostgreSQL, Redis, Qdrant và workers;
- kết quả benchmark nếu có.

---

# 20. Lệnh bắt đầu

Bắt đầu bằng việc audit repository, không sửa kiến trúc ngay.

Thực hiện lần lượt:

```text
1. Xem cây thư mục.
2. Xác định entrypoint FastAPI.
3. Tìm toàn bộ code SQLite.
4. Tìm toàn bộ code Qdrant.
5. Tìm OCR adapter và model config.
6. Tìm embedding adapter.
7. Tìm document upload/index endpoints.
8. Tìm cleanup logic.
9. Tìm tests.
10. Viết báo cáo audit và kế hoạch patch theo phase.
```

Sau audit, triển khai Phase 1 ngay nếu không có blocker nghiêm trọng. Không dừng chỉ để hỏi lại những chi tiết có thể xác định từ repository.
