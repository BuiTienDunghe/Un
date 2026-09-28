# Web UI v2 — việc backend còn thiếu (checklist)

Giao diện đã gọi đúng từng endpoint dưới đây. Khi máy chủ chưa có, UI hiện trạng thái trung thực
("Máy chủ chưa hỗ trợ …" / khoá nút / cột ẩn), không giả vờ thành công. Làm xong mục nào thì mục đó
tự sống, không phải sửa frontend.

Cách UI dò: 404/405/501 không kèm mã lỗi ⇒ "chưa có"; 422 `INVALID_INPUT` trên PATCH thiếu trường bắt
buộc cũ ⇒ "chưa nhận trường mới". UI không bao giờ gửi kèm trường cũ để lách (ví dụ không gửi `title`
khi chỉ ghim, không gửi `role` khi chỉ đổi mật khẩu) — làm vậy sẽ đổi nhầm dữ liệu.

---

## 1. Tài liệu — mở khoá nhiều chỗ nhất

- [ ] **`GET /documents` trả thêm** `tags: [str]`, `file_size: int`, `total_pages: int|null`, `created_at`, `updated_at`
      (đã có trong DB, chỉ chưa trả ra: `postgres/models.py` Document).
      *Chưa có:* cột Tag ẩn, cột "Cập nhật" là "—", thẻ "Dung lượng" là "—", dòng phụ tên tệp thiếu kích thước.
- [ ] **`PATCH /documents/{id}/tags`** `{tags: [str]}` → 200 Document. *Chưa có:* nút "+ thêm tag" chỉ hiện toast.
- [ ] **`GET /documents?tag=<t>`** lọc theo tag (UI vẫn lọc lại ở máy khách, nên an toàn cả khi máy chủ bỏ qua tham số).
- [ ] **`GET /documents/{id}/versions`** → `[{version_id, index_version, content_hash, created_at, status: active|archived|staging|failed, chunks_count}]`.
      *Chưa có:* panel chi tiết chỉ dựng được 1 thẻ version từ `active_index_version`.
- [ ] **`GET /documents/{id}/history`** → `[{at, kind: upload|extract|ocr|index|replace|failed, title, detail, ok}]`.
      *Chưa có:* timeline dựng tạm từ lần chạy mới nhất.
- [ ] **`GET /documents/{id}/source`** tải tệp gốc (Content-Disposition). *Chưa có:* nút "Tải file gốc" bị khoá.
- [ ] **`GET /documents/{id}/pages/{n}.png`** ảnh trang; tuỳ chọn **`GET /documents/{id}/pages/{n}/boxes?chunk_id=`** → `{boxes:[{x,y,w,h}]}` tỉ lệ 0..1.
      *Chưa có:* popup trích dẫn và panel chi tiết hiện ô sọc "Chưa có ảnh xem trước trang".

## 2. Phân quyền thành viên — README hứa nhưng backend đang chặn

- [ ] **Mở quyền đọc cho member** (không thêm endpoint, chỉ đổi guard): `GET /api/dashboard/stats`, `/api/dashboard/timeseries`,
      `/metrics`, `/agent/activity`, `/api/memory-review/applied`. *Chưa có:* thành viên vào Bảng điều khiển chỉ thấy
      phần Sức khỏe (endpoint `/health` công khai), các ô còn lại hiện "Chỉ quản trị viên xem được mục này";
      tab "Đang hiệu lực" của Ghi nhớ hiện trạng thái khoá.
- [ ] **Thành viên tải tài liệu lên**: hiện `POST /documents/index` là admin-only nên tài liệu member vừa tải kẹt ở
      `uploaded` vĩnh viễn. Chọn một trong hai: tự lập chỉ mục ngay sau khi upload, hoặc cho member gọi index cho
      chính tài liệu mình vừa tải. *Chưa có:* UI báo "Đã tải lên. Cần quản trị viên lập chỉ mục tài liệu này."

## 3. Hội thoại

- [ ] **`PATCH /conversations/{id}`** nhận `pinned?: bool`, `folder_id?: str|null` (hiện bắt buộc `title`, thiếu → 422).
- [ ] **`GET /conversations`** trả thêm `pinned`, `folder_id`, và `has_sources: bool` (có tin trợ lý kèm trích dẫn).
      *Chưa có:* không có nhóm "Đã ghim", không có chấm màu thư mục, không có icon sách cho hội thoại hỏi tài liệu.
- [ ] **`GET/POST/PATCH/DELETE /folders[/{id}]`** → `{id, name, color}`. *Chưa có:* menu chuột phải khoá mục thư mục.

## 4. Thông báo (chuông ở header)

- [ ] **`GET /notifications?unread=1`** → `{items:[{id, kind, tone: ok|accent|danger|muted, title, detail, created_at, read, link?}], unread_count}`
- [ ] **`POST /notifications/read`** `{ids?: [..]}` (bỏ trống = tất cả) → 204.
      *Chưa có:* chuông không có chấm đỏ, mở ra hiện "Máy chủ chưa hỗ trợ thông báo".
      Sự kiện nên đẩy: index xong, index/OCR lỗi, đề xuất ghi nhớ mới, sao lưu xong, bot dừng.

## 5. Tài khoản

- [ ] **`PATCH /auth/users/{id}`** nhận thêm `password?`, `disabled?: bool` (hiện chỉ `role`, thiếu `role` → 422);
      user public trả thêm `disabled`. *Chưa có:* menu ⋯ khoá mục "Đặt lại mật khẩu" và "Khoá tài khoản".
- [ ] **`POST /auth/me/password`** `{current_password, new_password}` → 204 (sai mật khẩu hiện tại → 422, đừng dùng 401
      vì common.js sẽ tưởng hết phiên và đá người dùng ra). *Chưa có:* nút "Đổi mật khẩu" trong Cài đặt chỉ hiện toast.

## 6. Model

- [ ] **`POST /models/{role}/promote`** `{version}`, **`POST /models/{role}/revert`** → 200 registry row (có hiệu lực sau khi khởi động lại).
- [ ] **`GET /models/check`** → `{ok, problems: [str], output}` (bọc lại CLI `python -m app.config.model_registry --check`).
- [ ] **`GET /models`** thêm `registry[role].versions: [{id, name, status}]` (đọc từ `model_versions.yaml`).
      *Chưa có:* nút Promote/Revert/Kiểm tra registry khoá; danh sách version dựng tạm từ active/requested/loaded.

## 7. Bot Discord

- [ ] **`POST /api/bot/restart`** (hiện 404). *Chưa có:* nút "Khởi động lại" khoá sẵn.
- [ ] **`GET /api/bot/status`** thêm `started_at`, `uptime_seconds`, `guild_count`, `member_count`.
      *Chưa có:* dòng trạng thái chỉ có "đang chạy".
- [ ] **`GET /api/bot/config`** → `{persistent_sessions, memory_ingestion, member_context_limit}`.
      *Chưa có:* 3 công tắc cấu hình khoá kèm ghi chú (riêng "nạp ghi nhớ" suy từ `/health.memory_ingestion`).

## 8. Ghi nhớ

- [ ] **`GET /api/memory-review/count`** → `{pending}`. *Chưa có:* huy hiệu cạnh mục "Ghi nhớ" đếm số dòng của trang đầu
      (`candidates?limit=100`), nên tối đa hiển thị "99+" và tốn một lần tải 100 bản ghi mỗi phút.
- [ ] (tuỳ chọn) **`GET /api/memory-review/applied?limit=&offset=`** — hiện service chặn cứng 20 dòng, không phân trang.

## 9. Nhỏ hơn, không chặn giao diện

- [ ] Độ trễ riêng cho Discord trong `/api/dashboard/timeseries` (hiện gộp web + Discord nên thẻ "Độ trễ p50" của màn Bot để "—").
- [ ] `/agent/activity` trả thêm `message_id` cho dòng `agent_answer` để mở được `/agent/traces/{message_id}`.
- [ ] `heading_path` của chunk còn dính dấu `**` của markdown (lỗi chunker, UI hiện nguyên văn).
