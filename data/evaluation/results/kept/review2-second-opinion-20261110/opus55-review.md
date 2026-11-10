claude-opus-5-5

(Bản báo cáo duyệt độc lập 9 lỗi, nhận 10/11/2026, chép nguyên văn.)

**Thật ra chuyện này là gì.** Cả 9 lỗi đều có thật, nhưng chỉ lỗi 1 làm hỏng ngay việc dùng hằng ngày. Trong hai server cũ, hễ ai trả lời (reply) một tin rồi gọi Ún là backend vỡ. Mỗi kênh có một hàng đợi, và lượt đầu hàng chỉ chạy tiếp khi chính bot đã gửi nó quay lại gọi. Bot không quay lại, nên kênh đó đứng im cho tới khi bot được bật hoặc tắt lại. Tôi còn thấy một lỗi khác có thể nặng hơn. Bot sửa tin "⏳ đang làm" của chính nó, và hệ thống hiểu việc sửa đó như một người dùng vừa sửa tin. Hệ quả là kênh tự quên lịch sử sau mỗi câu trả lời.

| # | Có thật? | Bằng chứng (file:line) | Mức thực tế | Hướng sửa của tôi | Đồng ý hướng được nghiêng? |
|---|---|---|---|---|---|
| 1 | Có. Đã chạy: cả hai lớp ném `AttributeError` | turn_service.py:602-604; speaker_context.py:55-79 không có `created_at`; migration :38-42; bot: api_client.py:824 → main.py:548-550 báo lỗi rồi bỏ lượt; repositories.py:345-361 chỉ lượt đầu hàng mới được nhận | Cao: mọi @Ún dạng reply ở 2 server cũ hỏng; kênh kẹt, lượt sau chờ 360 s rồi báo hết hạn | Lọc ngay trong `_resolve_reply_target`, nơi còn bản ghi gốc. Reply tin bot thì so giờ của lượt gốc (`originating_turn`), không so giờ giao. Kiểm thêm tombstone. Trả trạng thái "không xác định" thay cho None. Bọc phần sau claim bằng try → `fail()` | Đồng ý. Nhưng lưới này không phủ những lượt mồ côi do bot bỏ (A). Lần thử lại chạy lại `prepare_turn`: tin "quên" sẽ nhận câu báo lượt cũ thay vì biên nhận |
| 2 | Có. Chỉ đọc | auth.py:96-101 lấy vai trò từ token; dùng ở auth.py:148, conversations.py:16, research.py:44 | Thấp: phải bật đăng nhập và có nhiều tài khoản; cửa sổ ≤ 15 phút | Đọc vai trò từ DB một lần mỗi request trong `resolve_identity` | Đồng ý 2a. Cạm bẫy: dự án do admin tạo có chủ rỗng (research.py:101 → research_service.py:637), nên khi bị hạ quyền người đó mất luôn dự án của mình |
| 3 | Có, về logic. Chỉ đọc | turn_service.py:542-554, 649-650, 707-718 | Thấp lúc này: bot bỏ đáp án khi lượt đã `completed` (main.py:404-406) | Kiểm `is_retracted` cùng với mốc | Đồng ý, và phải sửa cùng lúc với lưới của 1/A, vì lưới đó làm nhánh gửi lại chạy trở lại |
| 4 | Có. Chỉ đọc | chat_service.py:125-126, 165; source_memory.py:118-129 | Rất thấp | Lấy giờ gửi bằng `clock_timestamp()` ở đầu transaction snapshot; `save()` từ chối nếu giờ gửi ≤ mốc | Nghiêng 4b hơn 4a (ý kiến riêng): cùng chi phí mà không phụ thuộc hai đồng hồ |
| 5 | Có. Chỉ đọc | auth_service.py:138-142: đếm rồi cập nhật, READ COMMITTED, không khoá | Thấp; gỡ được bằng X-API-Key | Advisory lock | Đồng ý 5a. 5b phải khoá từng dòng; Postgres không cho `FOR UPDATE` đi cùng `count(*)` |
| 6 | Có. Chỉ đọc | ocr_job_service.py:211-214; worker hỏng ở :102 → :116-118 gọi `_save` dạng upsert (postgres_auxiliary_store.py:390) | Thấp-vừa | Giữ tập mã đã xoá dưới `self._lock`; kiểm cờ và ghi DB trong cùng một khoá; worker tự dọn thư mục khi thoát | Đồng ý 6-7a |
| 7 | Có. Chỉ đọc | :212-213 chỉ `rmtree` khi job còn trong RAM | Vừa, vì riêng tư | Dựng `runs_path/job_id` sau khi khớp `^ocr_[0-9a-f]{32}$`, rồi `resolve()` kiểm nằm trong `runs_path` | Đồng ý. Thiếu kiểm định dạng thì `rmtree(runs_path/"..")` xoá cả thư mục cha |
| 8 | Có. Chỉ đọc | ocr.py:18; `OcrJobOptions` (ocr_schema.py:4-7) không chỗ nào dùng, nên `page_range` và `output_format` cũng không được kiểm | Vừa | `Query(ge=72, le=400)` và dùng lại `OcrJobOptions` | Đồng ý nhưng chưa đủ: còn `page_range` (C) và cỡ tệp (D) |
| 9 | Có. Đã chạy | ocr_reader.py:51 dùng `next()`; :21 | Vừa với tài liệu thật | Gộp kết quả mọi luật khớp; nới regex cho số quốc tế; thêm nhãn | Đồng ý; "ĐT: 0912…", "Di động:", "Hotline" bị loại; câu hỏi "e-mail" không khớp luật nào |

## Lỗi mới tìm thấy

- **A. Lượt mồ côi chặn kênh** (chỉ đọc). Bot thoát vòng chờ main.py:385-417 khi gặp 5xx, timeout hay 409. Khi giao tin hỏng, main.py:572-578 gọi `fail(retryable=True)` rồi ném lỗi. repositories.py:562-565 đưa lượt về `queued` nhưng không ai nhận lại. Cách sửa: bot tiếp tục gọi execute khi gặp lỗi tạm thời trong hạn chờ, hoặc `recover_stale` chuyển lượt sang `failed`.
- **B. Bot tự dời mốc** (chỉ đọc). main.py:919 gửi mọi tin vào sổ, kể cả tin của bot; progress_message.py sửa tin ⏳; sự kiện sửa đi qua main.py:964-974 tới history_service.py:197-198 → `invalidate_in(reader)` không lọc `is_bot`, không so nội dung → dời mốc kênh. Hệ quả: lượt sau mất lịch sử; lượt đang xếp hàng bị coi là cũ; lượt có công cụ bị thay đáp án bằng câu "Nguồn trí nhớ vừa được sửa…" (chat_service.py:256-258). Cách sửa: bỏ qua sửa/xoá tin của bot, và bỏ qua khi nội dung không đổi. **[10/11: đã sửa theo cách a, chưa commit.]**
- **C.** ocr_job_service.py:146-154 dựng toàn bộ tập trang trước khi kiểm biên. Đã chạy: `"1-5000000"` trên PDF 3 trang mất 6 s, đỉnh 281 MiB.
- **D.** Tạo job OCR đọc tệp không giới hạn cỡ (ocr_job_service.py:47); `render_pages` giữ mọi trang PNG trong RAM (ocr_service.py:56-61).
- **E.** Khi bật đăng nhập, thành viên nào cũng xem được lịch sử và tệp OCR của người khác (main.py:289; ocr.py:22-26, 63-79).
- **F.** Hai/ba đồng hồ bị trộn: `turn.created_at` (repositories.py:134) và `Message.created_at` (postgres_auxiliary_store.py:81) theo giờ ứng dụng; mốc theo giờ Postgres; `sent_at` theo giờ Discord (history_service.py:96).
- **Đã loại:** `save()` với tin quá 10 000 ký tự không xảy ra được (discord/schema.py:40).

## Chưa chắc / chưa kiểm

- Không chạy DB, bot hay Discord; A và B chỉ dựa trên đọc code. (Sau đó B đã được tái hiện bằng chạy ở backend.)
- Độ lệch đồng hồ sau khi máy ngủ chưa đo.
- Lỗi 2–8 chỉ đọc code.
