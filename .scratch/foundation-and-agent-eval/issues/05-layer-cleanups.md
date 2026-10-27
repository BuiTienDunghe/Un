# 05 — Dời job_*, query dashboard vào service (M1d)

Status: chờ
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
