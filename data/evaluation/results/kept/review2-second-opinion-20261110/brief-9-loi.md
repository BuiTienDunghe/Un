# Brief: đánh giá độc lập 9 lỗi trên main `ed60401` (local-ai-core, v1.6.0)

Repo: `C:\Users\dungbt06\local-ai-core`, nhánh `main`, commit `ed60401`. Cây làm việc có vài tệp bẩn không liên quan; code backend ở `backend/app/`, bot ở `discord_bot/`.

Bối cảnh ngắn: v1.6.0 bật "trí nhớ nguồn v2" (`backend/app/services/source_memory.py`): mỗi tenant/audience có epoch và mốc (`barrier_at`); quên/sửa/xoá tạo tombstone (`status="retracted"`) và dời mốc. Migration `backend/alembic/versions/20261109_39_source_memory.py` dòng 38 đặt sẵn một mốc `__history__` cho mọi tenant cũ (database thật có 2 server Discord + 1 web). Lượt Discord đi theo vòng claim → execute → save_response → complete (`backend/app/discord/turn_service.py`, `repositories.py`), bot gọi ở `discord_bot/main.py` + `api_client.py`.

## 9 lỗi một bản nhận xét bên ngoài đã nêu

| # | Lỗi được nêu | Chỗ |
|---|---|---|
| 1 | Lượt reply Discord đọc `reply_target.created_at` nhưng `ReplyTargetContext`/`BotReplyTargetContext` không có trường này → `AttributeError` khi đã có mốc | `turn_service.py:602-604`, `speaker_context.py:56-79` |
| 2 | Admin bị hạ quyền vẫn đọc hội thoại/dự án của người khác vì vai trò lấy từ access token (sống 15 phút); chỉ `require_admin` đọc lại database | `security/auth.py:68-158`, `routers/conversations.py:16`, `routers/research.py:44` |
| 3 | `_safe_replay` chỉ kiểm mốc, không kiểm tombstone → lượt đã xong được gọi lại trả nguyên đáp án của tin đã sửa/xoá; nhánh gửi lại (`response_text is not None`) cũng vậy | `turn_service.py:542-554`, `649-650`, `707-718` |
| 4 | Web: "nhớ" vẫn được lưu nếu "quên" commit giữa `sent_at` và `v2.snapshot` | `services/chat_service.py:123-170`, `source_memory.py:118-143`, `221-238` |
| 5 | Hai lần hạ quyền đồng thời có thể làm hết admin (đếm rồi cập nhật, không khoá) | `services/auth_service.py:131-143` |
| 6 | Xoá job OCR đang chạy: worker vẫn `_save` → job hiện lại | `services/ocr_job_service.py:70-119`, `211-220` |
| 7 | Xoá lịch sử OCR sau khi khởi động lại: `self.jobs` rỗng nên không `rmtree`, ảnh và chữ còn trên đĩa | `ocr_job_service.py:211-214` |
| 8 | API OCR nhận DPI không giới hạn (schema có `ge=72, le=400` nhưng route không dùng) | `routers/ocr.py:17-20`, `security/api_key.py` |
| 9 | Bộ lọc trường OCR chỉ lấy luật khớp đầu tiên (hỏi điện thoại + email chỉ giữ điện thoại); regex điện thoại chỉ nhận số Việt Nam | `services/ocr_reader.py` (`FIELD_RULES`, ~dòng 40-60) |

## Bằng chứng đã có (đọc SAU khi tự đánh giá xong, để không bị dẫn dắt)

- `docs/SO_DO.md`, hai mục đầu ngày 10/11 (tái hiện 9 lỗi; kiểm ý kiến thứ hai).
- `data/evaluation/results/kept/review2-second-opinion-20261110/` — test tạm cho lỗi 1 và kết quả in ra: lượt reply hỏng ở `running`, hết lease về `queued`, tin thường kế tiếp cùng kênh nằm `queued` mãi; kênh khác chạy được.

## Các hướng sửa đang được đề xuất (đọc SAU khi tự đề xuất)

| Lỗi | Cách | Ghi chú |
|---|---|---|
| 1 | a. Kiểm mốc + tombstone theo bản ghi lượt gốc cho cả 3 loại reply (tin người, tin bot, không tìm thấy), **và** thêm lưới: lỗi bất ngờ ở bước chuẩn bị → `fail(retryable=True)` trả HTTP 200 như đường gọi model, sau 3 lần thì `failed` (được nghiêng về) | |
| | b. Chỉ vá `created_at` | |
| | c. Lưới đặt ở bot: bot gọi lại execute khi gặp 5xx | |
| 2 | a. Đọc lại vai trò từ database ở `_resolve`/`resolve_identity` (cache theo request) (được nghiêng về) | thêm 1 truy vấn mỗi request Bearer |
| | b. Sửa riêng 3 chỗ | |
| | c. Thu hồi token khi hạ quyền (thêm cột/phiên bản token) | |
| 3 | Kiểm mốc + `is_retracted` ở cả `_safe_replay` lẫn nhánh gửi lại | |
| 4 | a. Trong `save()`, dưới khoá, từ chối nếu giờ gửi ≤ mốc; giữ kiểm `expected_epoch` (được nghiêng về) | |
| | b. Như a nhưng giờ gửi lấy từ đồng hồ database | hiện giờ gửi là đồng hồ Python, mốc là `clock_timestamp()` của Postgres |
| 5 | a. `pg_advisory_xact_lock` chung cho thao tác đổi quyền (đã có tiền lệ `BOOTSTRAP_LOCK_KEY`) (được nghiêng về) | |
| | b. Khoá các dòng admin `FOR UPDATE` theo thứ tự cố định | |
| 6-7 | a. Cờ "đã xoá" kiểm cùng khoá với `_save`; sau khởi động lại suy thư mục từ `runs_path/job_id` sau khi kiểm định dạng mã `ocr_[0-9a-f]{32}` (được nghiêng về) | |
| | b. Từ chối xoá job đang chạy, bắt huỷ trước | |
| 8 | `Query(ge=72, le=400)` ở route + kẹp trong service | |
| 9 | Giữ bằng chứng cho mọi luật khớp (hợp), nới regex điện thoại cho số quốc tế | |
