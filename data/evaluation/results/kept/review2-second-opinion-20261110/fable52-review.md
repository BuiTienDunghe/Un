claude-fable-5-2

(Bản báo cáo duyệt độc lập 9 lỗi, nhận 10/11/2026, chép nguyên văn.)

**Bản chất, nói thường:** cả 9 lỗi đều có thật trong code, nhưng nặng nhẹ rất khác nhau. Lỗi 1 là lỗi duy nhất làm hỏng việc dùng hằng ngày: cứ trả lời (reply) một tin rồi gọi bot là lượt đó chết, và vì hàng đợi mỗi kênh chỉ cho lượt đứng đầu chạy, cả kênh kẹt theo. Lỗi này lộ ra một điểm yếu rộng hơn: bất kỳ lượt nào bị bot bỏ giữa chừng cũng chặn kênh, và lưới an toàn đang đề xuất chỉ che được một phần. Các lỗi còn lại cần hai người thao tác cùng tích tắc, hoặc cần người gọi thẳng API.

"Chạy" = Python thuần, tệp `fable52_check.py`. "Đọc" = chỉ đọc code. Tôi không chạy gì cần database.

| # | Có thật? | Bằng chứng | Mức thực tế | Hướng sửa của tôi | Đồng ý hướng nghiêng? |
|---|---|---|---|---|---|
| 1 | CÓ (chạy: cả hai lớp ném `AttributeError`) | `turn_service.py:603`; `_resolve_reply_target` :423-499 luôn trả khác None khi có reply id; bot `main.py:386`, `api_client.py:824` (5xx → bỏ, không gọi fail) | Nặng nhất. Mọi reply ở server đã có mốc. Lượt kẹt `running`, hết lease về `queued` đứng đầu, không ai execute lại (`repositories.py:355-361`) | Mang `created_at` và message id của lượt gốc vào context; bọc khối chuẩn bị bằng `fail()` | Đồng ý 1a, chưa đủ (xem N1). Bẫy: loại "không tìm thấy" có `created_at=None`, so với mốc ra `TypeError` (chạy); `BotReplyTargetContext` chưa có message id gốc để tra tombstone; thử lại sẽ chạy lại `prepare_turn` (xem N4) |
| 2 | CÓ (đọc) | `auth.py:99,148`; `conversations.py:16`; `research.py:44` | Trung bình: tối đa 15 phút, chỉ khi bật tài khoản | Đọc vai trò từ database trong `_resolve`, mất user → 401 | Đồng ý 2a: 3 chỗ dùng chung một nguồn. Bẫy: `postgres_sessions=None` trong test, phải chọn đóng hay mở |
| 3 | CÓ trong code, khó chạm (đọc) | `:552`, `:649`; bot bỏ đáp án lượt `completed` (`main.py:404`) và không execute lại lượt đã có đáp án | Thấp: sửa/xoá tin đã ghi sổ thì mốc đã dời nên đã bị chặn; hở khi tombstone nằm ở `__deleted__` hoặc gọi thẳng API | Thêm `is_retracted` ở `_safe_replay`; nhánh gửi lại dùng luôn cờ `stale` đã tính ở :585 | Đồng ý, ưu tiên thấp |
| 4 | CÓ (đọc) | `chat_service.py:124-125`, `:163`; `save()` chỉ kiểm epoch | Rất thấp: cửa sổ cỡ mili giây, cùng một người, hai request | Như `prepare_turn`: bỏ lưu khi `sent_at <= barrier` | Nghiêng 4b hơn 4a. API chạy trên Windows, Postgres trong Docker, tức hai đồng hồ. Bẫy 4b: giờ database phải lấy dưới khoá state, nếu không cuộc đua chỉ đổi chỗ |
| 5 | CÓ (đọc) | `auth_service.py:135-142` | Thấp: khoá API vẫn qua `require_admin` (`auth.py:121`) nên cứu được | Advisory lock, đếm sau khi có khoá | Đồng ý 5a. Bẫy: `database.get(User)` đang đứng trước khoá, nên đưa khoá lên đầu |
| 6 | CÓ (đọc) | `ocr_job_service.py:118` `_save` trong `finally`; `:212-214` | Thấp: hiện lại một dòng `failed`; model vẫn chạy hết trang | Cờ xoá, để worker tự dọn trong `finally` | Đồng ý a. Bẫy: `rmtree(ignore_errors)` khi worker còn mở tệp trên Windows sẽ xoá dở; `view()` :158 nạp lại job từ database. Bẫy của b: job kẹt `running` sau khởi động lại sẽ không bao giờ xoá được |
| 7 | CÓ (đọc) | `:212-213` | Trung bình về riêng tư: ảnh và chữ còn trên đĩa | `rmtree(runs_path/job_id)` sau regex, kèm kiểm thư mục cha sau `resolve()` | Đồng ý; regex là bắt buộc: route nhận `..` và `..\..\x` thành một `job_id` (chạy trên Starlette) |
| 8 | CÓ (đọc) | `ocr.py:18`; `ocr_schema.py:5` không được dùng | Thấp–trung bình, cần quyền ghi | `Query(ge=72, le=400)` | Đồng ý, nhưng thiếu (xem N5). Bẫy: kẹp ngầm trong service làm đổi `config_hash` |
| 9 | CÓ (chạy) | `ocr_reader.py:51` `next(...)`; regex :21 | Trung bình: hỏi "điện thoại và email" chỉ đưa cho model khối điện thoại; `1900 1234`, `+1 415…`, `ĐT: 028…`, `(84-28)…` bị loại | Hợp các luật khớp; thêm nhãn `hotline`, `đt`, `mobile`, `di động` | Đồng ý. Bẫy: nới regex sẽ bắt nhầm số tài khoản, ngày tháng; "What phone model…" kích nhầm luật điện thoại (chạy) |

## Lỗi mới tìm thấy

- **N1 — Lượt bị bỏ chặn kênh, không riêng lỗi 1 (đọc).** `main.py:572-578`: gửi Discord hỏng → `fail(retryable=True)` → lượt về `queued` rồi bot `raise`, không ai execute lại. Bot hết 360 giây hoặc timeout HTTP cũng để lại lượt mồ côi. `recover_stale` chỉ xử lý `running`; lối thoát duy nhất là `cancel-open` khi dừng bot. Các cách: (a) bot gọi fail không thử lại ở mọi lối thoát; (b) backend cho hết hạn lượt `queued` đứng đầu đã từng chạy và quá lâu; (c) cả hai. Nghiêng (c), là ý kiến.
- **N2 — Reply không kiểm tombstone (đọc).** `:602-604` chỉ định so mốc; nội dung tin gốc đã sửa/xoá nằm ở `__deleted__` vẫn vào prompt.
- **N3 — Ba đồng hồ so với `barrier_at` (đọc).** Giờ Python: `repositories.py:148` → `discord/source_memory.py:30`, `turn_service.py:552,595,649`; `postgres_auxiliary_store.py:81` → `source_memory.py:292`. Giờ snowflake của Discord: `discord/source_memory.py:63`. Nếu Postgres chạy nhanh hơn, lượt gửi ngay sau một lần sửa/xoá/quên bị coi là cũ.
- **N4 — Lượt "quên" bị thử lại (đọc).** Lần 2 `prepare_turn` thấy mốc do chính nó đặt, nên trả câu "tin đã bị xoá/sửa" dù đã quên xong.
- **N5 — OCR thiếu giới hạn khác.** `page_range="1-20000000"` trên PDF 3 trang tốn 1,2 giây CPU rồi mới bị từ chối (chạy bản sao `_select_pages`); `create` đọc cả tệp, không có trần (:47); `_pages` render mọi trang vào RAM trước khi OCR (đọc).
- **N6 — OCR không có chủ sở hữu (đọc).** `/history`, `/jobs/{id}`, `/files`, `/export` chỉ có `read_guard` (`main.py:289`); member nào đăng nhập cũng đọc được chữ và ảnh của mọi job.
- **N7 — `record_edit` không bỏ qua nội dung không đổi (đọc, `history_service.py:186-205`).** Mọi sự kiện sửa có `content` đều dời mốc cả kênh.

## Chưa chắc / chưa kiểm

- N1 và mọi kết luận về lease, trạng thái lượt: không chạy với database.
- Độ lệch đồng hồ Windows ↔ Docker sau khi máy ngủ: chưa đo.
- N7: chưa kiểm Discord có gửi `content` khi chỉ bung embed của link hay không.
- DPI rất lớn: không chạy PyMuPDF để xem nổ ở đâu.
- Đường RAG với `identity.role`, UI web có gọi `view()` trước khi xoá hay không: chưa lần.
- Đã loại: `save()` ném `ValueError` khi quá 10 000 ký tự không tới được từ Discord (`discord/schema.py:40`).
