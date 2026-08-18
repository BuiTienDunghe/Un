# Backup và restore PostgreSQL

PostgreSQL là nguồn dữ liệu chuẩn duy nhất của Local AI Core. Mất nó là mất hội thoại,
tài liệu, version, job và citation — Qdrant chỉ là chỉ mục và dựng lại được từ PostgreSQL.
Tài liệu này mô tả backup tự động đang chạy và **bài diễn tập restore** phải làm mỗi quý.

## 1. Backup tự động

`run-local-ai-core.bat` khởi động một worker nền cùng lúc với backend:

```
backend/scripts/backup_worker.py --loop
```

| Điều | Giá trị mặc định | Chỉnh ở đâu |
| --- | --- | --- |
| Chu kỳ | 24 giờ | `backend/app/config/models.yaml` → `storage.backup_interval_hours` |
| Giữ lại | 14 ngày | `storage.backups_ttl_days` |
| Tối thiểu luôn giữ | 3 bản mới nhất | `storage.backups_keep_minimum` |
| Thư mục | `data/backups/postgres` | `BACKUP_DIR` trong `.env` |

Tệp có dạng `local-ai-YYYYMMDD-HHMMSS.dump`, định dạng custom của `pg_dump`.

**Vì sao worker chạy trên host chứ không trong container:** bản dump được tạo bằng chính
`pg_dump` bên trong container PostgreSQL (`docker compose exec -T postgres pg_dump`), nên
phiên bản client luôn khớp server. Nếu đóng gói vào image ứng dụng thì phải cài thêm
`postgresql-client` đúng phiên bản 16 — thêm phụ thuộc mà không được gì.

`backups_keep_minimum` tồn tại vì một lý do cụ thể: máy để không quá 14 ngày vẫn phải còn
điểm phục hồi. Xoay vòng là chính sách lưu trữ, không phải cái cớ để về con số 0.

### Kiểm tra backup còn tươi

```bash
curl -s http://127.0.0.1:8000/health
```

Trường `backup` có ba giá trị: `ok` (bản mới nhất trong hạn), `stale` (quá 1.5 lần chu kỳ),
`unavailable` (chưa có bản nào). Kèm theo là `backup_age_hours`. Trường này **không** làm
`/health` chuyển sang `degraded` — thiếu backup là vấn đề vận hành, không phải sự cố phục vụ.

### Chạy tay một bản backup

```bash
cd backend && ..\.venv\Scripts\python.exe -m scripts.backup_worker --once
```

## 2. Diễn tập restore (mỗi quý)

Mục tiêu: chứng minh bản dump mới nhất **thật sự khôi phục được**, mà không đụng vào
database đang chạy. Toàn bộ bài diễn tập thực hiện trên một database tạm.

### Bước 1 — chọn bản dump

```powershell
Get-ChildItem data\backups\postgres\local-ai-*.dump | Sort-Object LastWriteTime -Descending | Select-Object -First 3
```

### Bước 2 — tạo database diễn tập (KHÔNG phải database chạy thật)

```bash
docker exec un-postgres-1 psql -U local_ai -d postgres -c "CREATE DATABASE local_ai_restore_drill OWNER local_ai"
```

### Bước 3 — nạp bản dump vào database đó

`pg_restore` chạy bên trong container nên phải đưa tệp vào container trước. Các lệnh dưới
đây viết cho PowerShell; nếu bạn dùng Git Bash, đặt `MSYS_NO_PATHCONV=1` trước lệnh, nếu
không Git Bash sẽ đổi `/tmp/drill.dump` thành đường dẫn Windows và `pg_restore` báo
"could not open input file".

```bash
docker cp data/backups/postgres/local-ai-20260818-030000.dump un-postgres-1:/tmp/drill.dump
```

```bash
docker exec un-postgres-1 pg_restore -U local_ai -d local_ai_restore_drill --no-owner /tmp/drill.dump
```

### Bước 4 — nghiệm thu

Bản restore phải có schema ở đúng head và dữ liệu không rỗng:

```bash
docker exec un-postgres-1 psql -U local_ai -d local_ai_restore_drill -tAc "select version_num from alembic_version"
```

```bash
docker exec un-postgres-1 psql -U local_ai -d local_ai_restore_drill -tAc "select (select count(*) from conversations), (select count(*) from documents), (select count(*) from document_chunks)"
```

Bài diễn tập **đạt** khi: `version_num` bằng head hiện tại của repo, và các con số khớp
xấp xỉ database thật tại thời điểm dump. Nếu `pg_restore` báo lỗi hoặc bảng rỗng bất
thường, bản backup đó **không phải** điểm phục hồi — điều tra ngay chứ đừng chờ sự cố thật.

### Bước 5 — dọn dẹp

```bash
docker exec un-postgres-1 psql -U local_ai -d postgres -c "DROP DATABASE local_ai_restore_drill"
```

```bash
docker exec un-postgres-1 rm -f /tmp/drill.dump
```

Ghi ngày diễn tập và kết quả vào `docs/phase6_operations.md`.

## 3. Khôi phục thật khi sự cố

Chỉ làm khi database thật đã hỏng và bạn đã chấp nhận mất dữ liệu sau thời điểm dump.

1. Dừng hệ thống: `stop-local-ai-core.bat`.
2. Khởi động riêng PostgreSQL: `docker compose --profile postgres up -d postgres`.
3. **Đổi tên** database hỏng thay vì xóa — nó vẫn có thể chứa dữ liệu cứu được:
   `ALTER DATABASE local_ai_core RENAME TO local_ai_core_broken_<ngày>`.
4. `CREATE DATABASE local_ai_core OWNER local_ai`, rồi `pg_restore` như bước 3 ở trên.
5. Chạy `run-local-ai-core.bat`; launcher tự chạy `alembic upgrade head`.
6. Dựng lại chỉ mục vector nếu Qdrant lệch: `cd backend && ..\.venv\Scripts\python.exe -m scripts.rebuild_qdrant`.
7. Chỉ xóa `local_ai_core_broken_<ngày>` sau khi đã dùng hệ thống bình thường vài ngày.

## 4. Điều tài liệu này cố tình không hứa

- Backup **không** gồm Qdrant. Vector dựng lại được từ chunk trong PostgreSQL nên không
  cần backup riêng; đổi lại, sau restore phải chạy `rebuild_qdrant`.
- Backup **không** gồm tệp gốc trong `data/documents`. Dùng `backend/scripts/backup_sources.py`
  nếu cần giữ cả bản gốc.
- Bản dump nằm cùng ổ đĩa với database. Muốn chống hỏng ổ đĩa, trỏ `BACKUP_DIR` sang ổ khác
  hoặc sao chép định kỳ ra nơi khác — đây là việc ngoài phạm vi hệ thống.
