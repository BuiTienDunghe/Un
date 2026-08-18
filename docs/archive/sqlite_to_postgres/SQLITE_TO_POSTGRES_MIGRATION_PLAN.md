# Kế hoạch loại bỏ SQLite và chuyển hoàn toàn sang PostgreSQL

## 1. Mục tiêu

Loại bỏ hoàn toàn SQLite khỏi runtime, test và cấu hình của dự án, đồng thời chuyển các dữ liệu còn cần thiết sang PostgreSQL mà không làm mất dữ liệu hoặc phá vỡ các chức năng hiện có.

Trạng thái đích:

- PostgreSQL là database duy nhất của hệ thống.
- Không còn runtime code sử dụng `SQLiteStore`, `sqlite3`, `aiosqlite` hoặc URL `sqlite://`.
- Chat history, memory, request logs, OCR runs và các metadata cần thiết hoạt động trên PostgreSQL.
- Cache và dữ liệu dẫn xuất được migrate hoặc rebuild theo quyết định đã xác minh.
- Integration test sử dụng PostgreSQL.
- Không còn file `.db`, `.sqlite`, `.sqlite3` cần thiết cho runtime.
- Alembic là nguồn quản lý schema PostgreSQL duy nhất.

---

## 2. Hiện trạng đã xác nhận

SQLite hiện vẫn được sử dụng cho nhiều phần ngoài document pipeline:

- Chat history.
- Memory metadata.
- Request logs.
- OCR cache.
- Embedding cache.
- OCR runs.
- Cleanup legacy.
- BM25 legacy.
- Một số API, service và test cũ dựa trên `SQLiteStore`.

Các file database đã phát hiện:

```text
data/sqlite/local_ai_core.db
data/sqlite/local_ai_core.pre_postgres_20260716T175939Z.db
data/sqlite/local_ai_core.pre_postgres_20260716T180021Z.db
data/sqlite/local_ai_core.pre_postgres_20260716T180024Z.db
tests/test_local_ai_core.db
backend/tests/test_local_ai_core.db
```

Không được xóa bất kỳ file nào trước khi migration và verification hoàn tất.

Nguồn migration mặc định dự kiến là:

```text
data/sqlite/local_ai_core.db
```

Các file `pre_postgres_*` chỉ được xem là backup. Không được tự động hợp nhất chúng với database chính vì có nguy cơ trùng dữ liệu.

Hai file database test không được migrate vào PostgreSQL production:

```text
tests/test_local_ai_core.db
backend/tests/test_local_ai_core.db
```

---

## 3. Nguyên tắc bắt buộc

1. Không xóa SQLite trước khi toàn bộ consumer tương ứng đã chuyển sang PostgreSQL.
2. Không sửa hoặc squash các Alembic migration PostgreSQL hiện có.
3. Mọi schema mới phải được tạo bằng Alembic revision mới.
4. Script migration phải idempotent và có `--dry-run`.
5. SQLite nguồn phải được mở ở chế độ chỉ đọc khi migration.
6. Không đo thành công chỉ bằng số lượng bản ghi.
7. Mỗi domain phải được verification riêng trước khi cutover.
8. Dữ liệu có thể tái tạo không mặc định phải migrate.
9. Không giữ fallback âm thầm từ PostgreSQL sang SQLite.
10. Nếu thiếu PostgreSQL hoặc `DATABASE_URL`, ứng dụng phải fail fast với lỗi rõ ràng.
11. Không thay đổi kiến trúc Redis, Qdrant, worker hoặc transactional outbox ngoài phần bắt buộc cho migration.
12. Không tuyên bố hoàn tất khi full regression chưa chạy thành công.

---

## 4. Phân loại dữ liệu

Codex phải audit schema và consumer thực tế trước khi chốt. Phân loại ban đầu:

| Nhóm dữ liệu | Hướng xử lý mặc định | Ghi chú |
|---|---|---|
| Conversations | Migrate | Dữ liệu người dùng, không được mất |
| Messages | Migrate | Phải giữ quan hệ với conversation |
| Memory metadata | Migrate | Phải giữ user/session/source và version nếu có |
| OCR runs | Migrate | Cần cho console, audit hoặc trạng thái xử lý |
| Request logs | Migrate có chọn lọc hoặc archive | Chốt retention sau khi kiểm tra cách sử dụng |
| OCR cache | Migrate có chọn lọc | Ưu tiên cache còn hợp lệ và tốn chi phí tái tạo |
| Embedding cache | Rebuild hoặc migrate | Quyết định theo model/version và chi phí rebuild |
| BM25 legacy | Rebuild hoặc loại bỏ | Không migrate mù nếu kiến trúc mới đã thay thế |
| Cleanup legacy metadata | Audit trước | Migrate nếu còn được runtime sử dụng |
| Test database | Không migrate | Chuyển test sang PostgreSQL rồi xóa |
| Backup `pre_postgres_*` | Archive tạm thời | Chỉ xóa sau nghiệm thu cuối |

---

## 5. Kiến trúc truy cập dữ liệu đích

Không để API hoặc service phụ thuộc trực tiếp vào `SQLiteStore`.

Tách repository theo domain, tùy theo cấu trúc thực tế của repository:

```text
ConversationRepository
MessageRepository
MemoryRepository
RequestLogRepository
OCRRunRepository
OCRCacheRepository
EmbeddingCacheRepository
```

Mỗi repository cần có PostgreSQL implementation.

Nếu dự án đã có abstraction tương đương thì tái sử dụng, không tạo lớp trùng lặp.

Các nguyên tắc thiết kế:

- API/service chỉ phụ thuộc interface hoặc service domain.
- PostgreSQL transaction được quản lý rõ ràng.
- Timestamp dùng timezone.
- Dữ liệu JSON cần truy vấn dùng `JSONB`.
- Có unique constraint cho các khóa chống trùng.
- Có foreign key và cascade phù hợp.
- Có index dựa trên query thực tế, không tạo index theo phỏng đoán.
- ID cũ nên được giữ nguyên khi khả thi.
- Nếu phải đổi ID, phải có bảng hoặc mapping xác định.

---

## 6. Lộ trình triển khai

### Phase 0 — Safety snapshot

Mục tiêu: bảo đảm có thể phục hồi trước khi thay đổi.

Công việc:

- Kiểm tra `git status`.
- Tạo branch migration riêng.
- Ghi checksum, dung lượng và thời gian sửa đổi của toàn bộ file SQLite.
- Sao chép nguyên trạng `data/sqlite/` sang thư mục backup ngoài vùng runtime hoặc tạo archive.
- Ghi lại PostgreSQL migration head hiện tại.
- Chạy baseline test hiện có và lưu kết quả.
- Không sửa dữ liệu SQLite.

Kết quả bắt buộc:

- Có danh sách file và checksum.
- Có backup đọc được.
- Có baseline test report.
- Có rollback point rõ ràng.

---

### Phase 1 — Audit đầy đủ

Mục tiêu: lập bản đồ chính xác từ bảng SQLite đến code và schema PostgreSQL.

Công việc:

1. Liệt kê toàn bộ bảng, view, trigger và index trong database chính.
2. Với mỗi bảng, ghi:
   - Số bản ghi.
   - Cột, kiểu dữ liệu, nullability.
   - Primary key.
   - Foreign key.
   - Unique constraint.
   - Index.
   - Giá trị mẫu đã che dữ liệu nhạy cảm.
3. Tìm toàn bộ code đọc hoặc ghi:
   - File.
   - Class.
   - Function.
   - API endpoint.
   - Worker/script.
   - Test.
4. Kiểm tra PostgreSQL đã có bảng tương đương hay chưa.
5. Phân loại từng bảng:
   - `MIGRATE_REQUIRED`
   - `MIGRATE_SELECTIVE`
   - `REBUILD`
   - `ARCHIVE`
   - `DROP_AFTER_CUTOVER`
6. Xác định thứ tự phụ thuộc giữa các bảng.
7. Xác định dữ liệu nào thuộc production và dữ liệu nào là test/legacy.

Deliverable:

```text
docs/sqlite_to_postgres_audit.md
```

Acceptance criteria:

- Mọi bảng SQLite đều có owner/consumer hoặc được đánh dấu orphan.
- Mọi bảng đều có quyết định xử lý.
- Không còn kết luận dựa trên tên bảng בלבד.
- Chưa sửa runtime và chưa xóa file.

---

### Phase 2 — Thiết kế schema PostgreSQL

Mục tiêu: bổ sung các bảng còn thiếu vào PostgreSQL.

Công việc:

- Thiết kế schema đích dựa trên dữ liệu và query thực tế.
- Tạo Alembic revision mới.
- Không chỉnh sửa migration cũ.
- Thêm constraint, foreign key và index cần thiết.
- Đảm bảo migration chạy được trên database sạch và database hiện tại.
- Viết migration downgrade an toàn nếu khả thi.

Các domain ưu tiên:

1. Conversations và messages.
2. Memory metadata.
3. OCR runs.
4. Request logs.
5. OCR cache.
6. Embedding cache.
7. Cleanup/BM25 legacy nếu còn cần.

Acceptance criteria:

- `alembic upgrade head` thành công trên PostgreSQL sạch.
- Upgrade thành công trên PostgreSQL hiện tại.
- Schema có test tối thiểu.
- Không còn schema mới được tạo bằng `create_all()` trong production.

---

### Phase 3 — Công cụ migration dữ liệu

Mục tiêu: chuyển dữ liệu an toàn, có thể chạy lại.

Tạo script:

```text
scripts/migrate_sqlite_to_postgres.py
```

Yêu cầu:

```text
--dry-run
--domain <name|all>
--batch-size <number>
--source <sqlite-path>
--resume
--verify-only
```

Hành vi bắt buộc:

- Mở SQLite ở chế độ read-only.
- Không tự động đọc các file `pre_postgres_*`.
- Migrate theo batch.
- Dùng upsert hoặc khóa idempotency phù hợp.
- Không tạo bản ghi trùng khi chạy lại.
- Log số bản ghi:
  - đọc;
  - insert;
  - update;
  - skip;
  - fail.
- Rollback batch khi có lỗi.
- Ghi checkpoint cho domain lớn.
- Không log nội dung nhạy cảm.
- Có exit code khác 0 khi migration lỗi.

Acceptance criteria:

- `--dry-run` không thay đổi PostgreSQL.
- Chạy hai lần không nhân đôi dữ liệu.
- Có test cho success, duplicate và failure.
- Có báo cáo migration theo domain.

---

### Phase 4 — Verification

Mục tiêu: chứng minh dữ liệu PostgreSQL đúng và sử dụng được.

Kiểm tra tối thiểu:

- Row count theo bảng.
- Count theo parent, ví dụ số message của mỗi conversation.
- Nullability và required fields.
- Foreign-key integrity.
- Unique key integrity.
- Timestamp và timezone.
- ID hoặc mapping ID.
- JSON field.
- Cache key, model name và version nếu có.
- Sample comparison giữa SQLite và PostgreSQL.
- Checksum trên nội dung chuẩn hóa cho dữ liệu quan trọng.
- API/service đọc từ PostgreSQL cho kết quả tương đương.

Tạo báo cáo:

```text
docs/sqlite_to_postgres_verification.md
```

Không được cutover domain nếu verification domain đó chưa đạt.

---

### Phase 5 — Cutover theo domain

Thứ tự đề xuất:

```text
Conversations/messages
→ Memory
→ OCR runs
→ Request logs
→ OCR cache
→ Embedding cache
→ Cleanup/BM25 legacy
```

Với mỗi domain:

1. Chuyển repository/service sang PostgreSQL.
2. Xóa write path sang SQLite của domain đó.
3. Không dùng dual-write trừ khi được triển khai có thời hạn và có verification rõ ràng.
4. Chạy unit test.
5. Chạy integration test.
6. Chạy API regression.
7. Kiểm tra restart.
8. Kiểm tra concurrency nếu domain có ghi đồng thời.
9. Xác nhận SQLite không còn thay đổi cho domain đó.

Nếu cần feature flag tạm thời, phải có:

- Tên rõ ràng.
- Giá trị mặc định PostgreSQL.
- Ngày hoặc phase phải xóa.
- Test cho cả cutover và rollback.

---

### Phase 6 — Chuyển toàn bộ test sang PostgreSQL

Mục tiêu: không còn test dùng file SQLite hoặc in-memory SQLite.

Công việc:

- Xóa fixture `sqlite:///:memory:`.
- Xóa fixture tạo `.db`.
- Dùng PostgreSQL test database hoặc container.
- Chạy Alembic migration cho test schema.
- Dùng transaction rollback hoặc schema isolation giữa các test.
- Tách unit test không cần database khỏi integration test.
- Thêm test cho transaction, constraint và concurrency quan trọng.

Không migrate dữ liệu từ:

```text
tests/test_local_ai_core.db
backend/tests/test_local_ai_core.db
```

Acceptance criteria:

- Test không tạo file `.db`.
- Full regression chạy bằng PostgreSQL.
- Transactional outbox test không dùng SQLite.
- Không còn dependency `aiosqlite` chỉ để phục vụ test.

---

### Phase 7 — Loại bỏ SQLite code và cấu hình

Chỉ bắt đầu khi tất cả domain đã cutover và verification thành công.

Xóa:

- `SQLiteStore` và file implementation tương ứng.
- `sqlite3`, `aiosqlite`.
- `sqlite://`.
- `check_same_thread`.
- `StaticPool` nếu chỉ dùng cho SQLite.
- SQLite fallback.
- SQLite health check.
- Metrics chỉ phục vụ SQLite.
- Script legacy không còn cần.
- Documentation cũ.
- Docker/config volume chỉ phục vụ SQLite.

Cấu hình đích:

- `DATABASE_URL` bắt buộc.
- Chỉ chấp nhận PostgreSQL URL.
- Fail fast nếu URL sai hoặc PostgreSQL không truy cập được.

Kiểm tra remnants:

```powershell
git grep -n -i -E "sqlite|sqlite3|aiosqlite|sqlite://|check_same_thread|StaticPool|SQLiteStore"
```

Mọi kết quả còn lại phải được giải thích rõ.

---

### Phase 8 — Archive và xóa file SQLite

Điều kiện bắt buộc trước khi xóa:

- Full regression thành công.
- API smoke test thành công.
- Worker và outbox hoạt động bình thường.
- Verification report đạt.
- Không còn runtime access đến SQLite.
- Đã lưu backup và checksum.
- PostgreSQL backup/restore test thành công.

Thứ tự xử lý:

1. Xóa hai database test.
2. Di chuyển database production SQLite sang archive.
3. Giữ archive trong thời gian nghiệm thu.
4. Chỉ xóa archive khi đã được xác nhận không cần rollback.
5. Không xóa các file `pre_postgres_*` trước database runtime chính.

File dự kiến xử lý cuối cùng:

```text
tests/test_local_ai_core.db
backend/tests/test_local_ai_core.db
data/sqlite/local_ai_core.db
data/sqlite/local_ai_core.pre_postgres_20260716T175939Z.db
data/sqlite/local_ai_core.pre_postgres_20260716T180021Z.db
data/sqlite/local_ai_core.pre_postgres_20260716T180024Z.db
```

---

## 7. Rollback

Mỗi phase phải có rollback cụ thể.

Rollback tối thiểu:

- Code rollback bằng Git.
- PostgreSQL schema downgrade hoặc restore backup.
- SQLite source không bị sửa.
- Feature flag chỉ được dùng nếu đã có test.
- Không rollback bằng cách hợp nhất tùy tiện các file backup SQLite.
- Nếu cutover domain thất bại, khôi phục consumer cũ trước khi nhận thêm write mới.

Không được tiếp tục phase sau khi rollback của phase hiện tại chưa được kiểm chứng.

---

## 8. Kiểm thử bắt buộc

### Database

- Alembic upgrade trên database sạch.
- Alembic upgrade trên database hiện tại.
- Constraint.
- Foreign key.
- Unique key.
- JSONB.
- Timestamp.
- Transaction rollback.

### Migration script

- Dry run.
- Empty source.
- Duplicate run.
- Partial failure.
- Resume.
- Invalid record.
- Batch boundary.
- PostgreSQL unavailable.

### Runtime

- Chat create/read.
- Conversation history.
- Memory create/update/delete/search.
- OCR run create/update/read.
- Request logging.
- OCR cache hit/miss.
- Embedding cache hit/miss hoặc rebuild.
- Cleanup.
- BM25 legacy behavior nếu còn duy trì.
- Worker restart.
- Outbox dispatch.
- API health.
- Metrics.

### Regression

- Unit tests.
- Integration tests.
- Full test suite.
- Docker smoke test.
- Restart test.
- Backup/restore test.

---

## 9. Definition of Done

Migration chỉ được coi là hoàn tất khi tất cả điều kiện sau đạt:

- PostgreSQL là database runtime duy nhất.
- Không còn API/service/worker ghi hoặc đọc SQLite.
- Không còn test dùng SQLite.
- Không còn SQLite fallback.
- Không còn dependency `aiosqlite`.
- Không còn file SQLite cần cho runtime.
- Chat, memory, logging, OCR console và cache hoạt động đúng.
- Dữ liệu bắt buộc đã được migrate và verification.
- Dữ liệu dẫn xuất đã được rebuild hoặc có quyết định loại bỏ rõ ràng.
- Full regression thành công.
- Docker smoke test thành công.
- Backup và restore PostgreSQL đã được thử.
- Báo cáo cuối liệt kê:
  - file đã sửa;
  - migration đã thêm;
  - số bản ghi theo domain;
  - verification;
  - test đã chạy;
  - file SQLite đã archive/xóa;
  - vấn đề còn lại.

---

## 10. Báo cáo sau mỗi phase

Sau mỗi phase, Codex phải báo cáo:

```text
Phase:
Trạng thái: completed | partial | blocked

Đã thực hiện:
- ...

File đã sửa:
- ...

Lệnh/test đã chạy:
- ...

Kết quả:
- ...

Rủi ro hoặc vấn đề còn lại:
- ...

Điều kiện để sang phase tiếp theo:
- ...
```

Không được tuyên bố hoàn tất nếu còn mục bắt buộc chưa đạt.
