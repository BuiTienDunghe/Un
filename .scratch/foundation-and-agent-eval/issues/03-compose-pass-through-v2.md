# 03 — Compose chỉ chuyển tiếp, Docker sang v2 (M1c, đổi hành vi có chủ đích)

Status: đã giao — Nhân viên của Ún 2
Type: task
Blocked by: —

## Vì sao

`docker-compose.yml` tự khai 31 mặc định dạng `${VAR:-default}`, trong đó 16 biến trùng tên với một
field của `backend/app/config/settings.py`. Một biến đã lệch:
`DISCORD_MEMORY_EXTRACTOR_SCHEMA_VERSION` có mặc định v1 ở `docker-compose.yml:87` và
`.env.example:25`, nhưng v2 ở `settings.py:82` (từ ca52d39, 28/08: thêm từ vựng sinh nhật, đồ ăn,
đồ uống ưa thích). `.env` không đặt biến này. Hệ quả: container memory-worker trích theo v1, worker
trên máy (launcher) trích theo v2. Mục tiêu: Settings là nơi duy nhất giữ mặc định.

## Việc

1. Bỏ các mặc định trùng với Settings. **Bẫy:** `${VAR}` không có mặc định, khi VAR chưa đặt, sẽ
   thành chuỗi rỗng, và `settings.py:250` ném lỗi khi schema version rỗng. Chọn cách khiến biến
   chưa đặt **vắng hẳn** trong container (vd `environment: [VAR]` dạng chỉ tên, hoặc `env_file`),
   rồi kiểm bằng `docker compose --profile <p> config`. Nếu dùng `env_file`, ghi rõ hệ quả: mọi khoá
   trong `.env` sẽ vào mọi container. Ghi lựa chọn và lý do vào Comments.
2. Giữ nguyên các giá trị riêng của container (vd `LOCAL_AGENT_BASE_URL=http://api:8000`,
   `CONTAINER_DATABASE_URL`) — chúng không phải mặc định trùng.
3. `.env.example`: sửa v1 thành v2, hoặc bỏ dòng và để chú thích "mặc định trong Settings".
4. Test tĩnh (không cần Docker): đọc `docker-compose.yml`, fail nếu có `${VAR:-x}` mà VAR là field
   của Settings. Test phải đỏ trên `main` hiện tại và xanh sau khi sửa.
5. Test hạ nguồn: phiên bản pipeline (v2) đi vào khoá idempotency (lượt, phiên bản). **Đừng** dựa
   vào hằng `"v1"` trong JSON — định dạng gửi đi vẫn ghi `"v1"` ngay cả khi pipeline là v2
   (`discord_memory_extractor.py:24-35`), nên test hiện có ở `test_discord_memory_extractor.py:136,146`
   vẫn xanh dù có đổi. Test cần Postgres thì ghi "cần stack".

## File được đụng

`docker-compose.yml`, `.env.example`, test mới trong `backend/tests/`.

## Nghiệm thu

- `docker compose config` cho thấy memory-worker không còn nhận v1.
- 15 biến trùng còn lại: giá trị mà container thấy bằng mặc định của Settings (liệt kê trong Comments).
- Message commit nói rõ đây là **đổi hành vi** cho đường chạy bằng Docker.

## Comments
