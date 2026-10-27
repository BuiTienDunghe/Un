# 05 — Dời job_*, query dashboard vào service (M1d)

Status: đã gộp vào main (27/10), fable 5.1 duyệt
Type: task
Blocked by: 02 (02 sửa các script recover_* có import những module này)

## Việc

1. `backend/app/postgres/discord_memory_job_repository.py:19-20` import `services/job_errors.py`
   và `services/job_routing.py` (hai file hằng số). Dời hai file này ra khỏi `services/` (tầng dữ
   liệu không được phụ thuộc tầng nghiệp vụ); sửa mọi chỗ import.
2. `backend/app/routers/dashboard.py:12-135` viết truy vấn SQLAlchemy ngay trong router. Chuyển phần
   này vào một service, router chỉ gọi.

Không đổi hành vi; test hiện có của dashboard và job phải giữ nguyên kết quả.

## Comments

### 27/10 — Nhân viên của Ún 1: phương án (đọc trên main 218bc91)

Bản chất: hai tầng đang dựa vào nhau sai chiều. Tầng lưu dữ liệu mượn "từ vựng" của các job
(tên loại job, job đi hàng đợi nào, chờ bao lâu thì thử lại) từ tầng nghiệp vụ, trong khi đáng lẽ
tầng nghiệp vụ dựa vào tầng dữ liệu. Cách sửa là đặt từ vựng đó ở một chỗ thấp hơn cả hai. Còn
dashboard thì đang viết truy vấn ngay trong lớp nhận yêu cầu web; truy vấn được dời vào một service
như phần còn lại của app.

Q1, nơi đặt job_errors / job_routing:
- (A) `app/postgres/`, cạnh `discord_memory_constants.py`. Không thêm khái niệm mới, nhưng route
  queue, đường dẫn task và chính sách retry không phải chuyện cơ sở dữ liệu.
- (B) Gói mới `app/jobs/`, nằm dưới postgres, services và workers. Đặt tên đúng khái niệm, chiều
  phụ thuộc sạch, nhưng thêm một gói cho 64 dòng.
- (C) `app/utils/`. Tầng sẵn có, nhưng dễ thành ngăn kéo tạp.
- (D) `app/workers/`. Ngược chiều phụ thuộc; không khuyên.

Q2, service cho dashboard:
- (1) `DashboardService` mới, nằm trên `app.state`.
- (2) Thêm hàm vào `OperationalService`.
- (3) Router tự dựng service mỗi request.
- (4) Một module truy vấn trong `app/postgres/`.

**Điều phối chốt:** Q1 = (B), với `app/jobs/retry.py` + `app/jobs/routing.py`, kèm luật một dòng
trong docstring và một test tĩnh. Q2 = (1), service trả dữ liệu thô, router dựng schema (theo quy
ước 43/44 service).

### 27/10 — Nhân viên của Ún 1: đã làm

- `git mv`: `services/job_errors.py` → `jobs/retry.py`; `services/job_routing.py` →
  `jobs/routing.py`. Nội dung không đổi. Có thêm `app/jobs/__init__.py` mang luật "chỉ import
  stdlib và sqlalchemy".
- Đổi import ở 7 file nguồn và 6 file test, gồm import muộn ở `job_recovery_service.py:62`. Chỗ vá
  bằng chuỗi ở `test_rq_resilience_integration.py:173` đổi cùng lượt, thành
  `"app.jobs.retry.retry_delay"`. Docstring ở `model_router.py:25` cũng đổi theo. Không còn chỗ nào
  nhắc tên cũ, ngoài `docs/archive`.
- `tests/test_jobs_layer.py` (đọc mã nguồn, gồm cả import muộn trong hàm):
  (1) `app/jobs` chỉ import stdlib, sqlalchemy, và không import `app.*` nào khác ngoài chính nó;
  (2) `app/postgres` không import `app.services`. Bài (2) nằm ngoài yêu cầu, nhưng nó khoá đúng
  mục tiêu của ticket. Đã cho cả hai đỏ bằng một import thật lên tầng trên, rồi trả lại.
- `app/services/dashboard_service.py`: `DashboardService(sessions, auxiliary_store)` có
  `timeseries(days)` và `stats()`. Thân truy vấn chép nguyên từ router, và trả dict. Router chỉ
  gọi service rồi dựng `DashboardStats.model_validate(...)`. `main.py` thêm 2 dòng, cạnh
  `chunk_inspection_service`.

| Kiểm | Kết quả |
|---|---|
| Import `app.main`, `app.workers.tasks`, `memory_tasks`, router dashboard | được |
| Test không cần DB (tầng, job routing, worker hardening, model router, compose defaults, health, nightly) | 36 xanh |
| 17 file test DB (dashboard, timeseries, outbox, rq_*, stale recovery, reconciliation, auth, …), 18:08 | 154 xanh, 0 skip |
| Chỗ vá bằng chuỗi còn tác dụng: bỏ dòng `"app.jobs.retry.retry_delay"` trong `test_stale_worker_job_is_recovered_and_completed` | đỏ ở `reconcile_queued() == 1` (ra 0, vì job phải chờ 10 s); trả lại thì xanh |