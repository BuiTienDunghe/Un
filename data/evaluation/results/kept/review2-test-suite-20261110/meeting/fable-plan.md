claude-fable-5-2

# Kế hoạch bộ test review2 — Fable, vòng 1 (độc lập)

**Bản chất:** phần khó là để mỗi test "đỏ có chủ đích" đỏ vì đúng một lý do; hai lỗi che nhau thì sửa lỗi này làm test lỗi kia tự xanh và cả bộ đỏ oan.

## 1. Nguyên tắc

**Mức chạy:** **P** Python thuần; **M** app nhỏ `FastAPI()` + router OCR + store giả (mẫu `test_ocr_evidence_api.py:31`); **D** service trên Postgres thật; **H** `TestClient(app)` + Postgres; **B** bot với backend giả. Vùng OCR (R6–R9, C, D) không cần container.

**Giả lập:**
- *Đồng hồ.* Không sửa `barrier_at` trong DB: nếu F được sửa bằng "lấy giờ lượt từ Postgres", test dời mốc sẽ không bao giờ xanh. Chỉ làm lệch **phía ứng dụng**: thay `datetime` của `app.discord.repositories`, `app.services.chat_service` và `_utc_now` của store bằng bản chậm 10 phút (vài giây là cửa sổ may rủi trên máy chậm). Đồng hồ Discord: dựng snowflake theo thời điểm muốn.
- *5xx, timeout.* Bot: `FakeBackend.executions` nhận `Exception`. Backend: `TestClient(client.app, raise_server_exceptions=False)` dựng không `with`.
- *Bot chết.* Lượt `running`, lùi `lease_expires_at` 1 giây; lượt mồ côi "đã lâu": lùi `updated_at`/`available_at` 1 giờ.
- *Đồng thời.* Không thả hai luồng cùng lúc cho lỗi chưa sửa (đỏ theo may). R5: hook `before_cursor_execute` giữ luồng 1 trước `UPDATE users` tới khi luồng 2 cũng tới hoặc hết 2 giây; code cũ chắc chắn ra 0 admin, code đã khoá thì luồng 2 đứng ở khoá. Fixture phải dựng và kiểm đúng hai admin trong cả bảng. R4: một luồng, chèn `forget_actor` vào lần gọi `snapshot` đầu.
- *Khởi động lại.* OCR: `OcrJobService` thứ hai trên cùng `runs_path` và store.
- *Windows giữ khoá tệp.* Mở một tệp trong thư mục job rồi `delete`; `xfail(condition=sys.platform == "win32", strict=True)`.

**Dùng lại:** `v2client`, `send`, `queue`, `ledger`, `channel_barrier`, `memory`, `auth_on`, `register`, `bearer`, `FakeBackend`, `FakeSource`. `review2_support.py` thêm: `snowflake(at)`, `enqueue(reply_to=)`, `seed_history_barrier`, `expire_lease`, `app_clock_behind`, `MemoryOcrStore`, `BlockingOcr`, `CountingUpload`.

**Để xfail không đạt nhờ may:**
1. **Cô lập khỏi R1.** Mọi reply trong kênh có mốc đang chết vì R1. N2 và R3 phải tạo tombstone **không dời mốc kênh**: **sửa** một tin chưa vào sổ và chưa được "nhớ" thì tombstone nằm ở `__deleted__` (`record_edit`, nhánh `row is None`). Xoá kèm guild/kênh thì dời mốc, không dùng được.
2. `xfail(raises=...)`: `AttributeError` cho R1, `AssertionError` cho phần còn lại. Lỗi khác loại làm test đỏ.
3. Chuẩn bị dữ liệu nằm trong fixture: fixture hỏng là lỗi, không phải xfail.
4. Khẳng định trên HTTP, dòng DB, prompt gửi model, tệp trên đĩa; không trên hàm nội bộ.
5. Chỉ tham số đang sai mang `pytest.param(marks=xfail)`.
6. Người viết chạy mỗi xfail một lần **không dấu** và chép dòng lỗi vào nhật ký. Dòng "?" là chỗ kết quả chưa đoán được hoặc tuỳ thiết kế.
7. Ca tài nguyên không nổ thật: C dùng `1-300000` với trần `tracemalloc` (đã chạy: 17 MiB, 0,3 giây); R8 dùng PNG nên không render; D dùng tệp giả.

**Ca gắn với một cách sửa (‡):** nếu chọn cách sửa khác, ca đó phải viết lại chứ không tự xanh. Cần chốt ở vòng 2.

**Không viết lại** ca đã có trong `test_source_memory_discord.py` và `test_source_memory.py`: bot sửa/xoá tin của mình, sửa không đổi chữ, "quên" trong lúc model chạy, lượt bị thu hồi khi đang xếp hàng.

## 2. Bảng ca

Tệp đích: **RP** `test_review2_discord_reply.py`, **OR** `…_discord_orphans.py`, **ME** `…_discord_memory.py`, **AU** `…_auth_roles.py`, **OA** `…_ocr_access.py`, **OJ** `…_ocr_jobs.py`, **OF** `…_ocr_fields.py` (đều ở `backend/tests/`), **BT** `tests/test_review2_bot_turns.py`.

| ID | Vùng | Nếu… | Thì… | Mức | Hiện tại | Tệp |
|---|---|---|---|---|---|---|
| R1-1 | reply | server có mốc `__history__`; reply tin người / tin bot / tin không có; tin gốc cũ hơn mốc (3 tham số) / mới hơn mốc (2) | 200, có đáp án; chữ tin gốc không vào prompt / có vào | H | xfail R1 | RP |
| R1-3 | reply | server chưa có mốc; reply tin có thật / tin phiên khác / tin không tồn tại | chạy; tin gốc vào prompt hoặc trạng thái `outside_session`, `not_found` | H | đạt | RP |
| N2-1 | reply | tin gốc bị sửa, tombstone ở `__deleted__`, kênh không mốc | chữ tin gốc không vào prompt | H | xfail N2 | RP |
| N2-2 | reply | reply câu trả lời của bot mà tin hỏi gốc bị sửa (cùng đường `__deleted__`) | cả câu hỏi gốc lẫn đáp án cũ không vào prompt | H | xfail N2 | RP |
| N2-3 | reply | reply vào tin đã xoá, tin đó từng được "nhớ" (mốc kênh dời) | 200, không lộ chữ cũ | H | xfail R1 | RP |
| A-1 | lượt | model lỗi 3 lần | 200 ba lần, lượt `failed`, tin sau chạy | H | đạt | OR |
| A-2 ‡ | lượt | bước chuẩn bị ném lỗi bất ngờ (chèn vào `build_discord_speaker_context`) | không 5xx, lượt không nằm `running` | H | xfail A | OR |
| A-3 ‡ | lượt | lượt đầu hàng không ai gọi lại đã 1 giờ: `queued` sau `fail(retryable)` / `running` hết lease (bot chết) | tin sau cùng kênh được nhận | H | xfail A | OR |
| A-5 | lượt | lượt mồ côi ở kênh một; sau đó `cancel-open` | kênh hai vẫn chạy; sau `cancel-open` kênh một chạy lại | H | đạt / ? | OR |
| A-7 | lượt | hai execute đồng thời cho một lượt | đúng một bên nhận token | H | đạt | OR |
| A-8 ‡ | bot | execute ném 5xx/timeout một lần rồi trả đáp án | đáp án vẫn tới người hỏi | B | xfail A | BT |
| A-9 | bot | gửi Discord hỏng (500); test nuốt lỗi giao tin mà `answer_mention` ném lại | sau `fail(retryable=True)` bot còn gọi execute lại hoặc đóng lượt | B | xfail A | BT |
| A-10 | bot | hết hạn chờ khi lượt còn `queued` | lượt không bị bỏ lại mở | B | ? | BT |
| A-11 | bot | `completed` / `failed` / tin gốc đã xoá (`NotFound`) | không gửi lại / báo lỗi / `fail` không thử lại | B | đạt | BT |
| N4-1 | lượt | "quên", lần 1 model lỗi, thử lại | lần 2 gọi model kèm biên nhận, không phải câu "tin đã bị xoá/sửa" | H | xfail N4 | OR |
| N4-2 | lượt | "quên", đáp án đã lưu, giao hỏng, thử lại | trả đúng đáp án đã lưu | H | xfail N4 | OR |
| N4-3 | lượt | thử lại lượt "quên" sau khi người đó "nhớ" điều mới ở kênh khác / thử lại lượt "nhớ" | không quên thêm lần nữa / đúng một ghi chú | H | đạt | OR |
| R3-1 | phát lại | lượt xong; tin hỏi bị sửa (tombstone `__deleted__`); execute lại | không trả đáp án cũ | H | xfail R3 | ME |
| R3-2 | phát lại | đáp án đã lưu, giao hỏng, tin hỏi bị sửa (`__deleted__`), execute lại | không trả đáp án cũ | H | xfail R3 | ME |
| R3-3 | phát lại | lượt xong, execute lại: không ai sửa gì / sau một lần "quên" | trả đúng đáp án cũ / trả câu báo | H | đạt | ME |
| B-3 | sổ | người sửa nội dung / xoá tin | mốc dời, lượt sau không thấy lịch sử cũ | H | đạt | ME |
| B-4 | sổ | bot sửa tin "⏳" khi lượt khác đang xếp hàng | lượt đó vẫn được trả lời bình thường | H | đạt | ME |
| B-5 | sổ | người sửa tin khác khi một lượt đang xếp hàng | lượt đó nhận câu báo cố định, model không được gọi | H | đạt | ME |
| B-6 | sổ | lệnh xoá tin của bot tới trước khi tin vào sổ | mốc đứng yên | H | ? (cần chốt thiết kế) | ME |
| F-1 | đồng hồ | giờ ứng dụng chậm 10 phút; "quên" rồi gửi tin mới | tin mới được trả lời bình thường | H | xfail F | ME |
| F-2 | đồng hồ | Web, giờ ứng dụng chậm 10 phút; "quên", nói câu A, hỏi lại | câu A có trong lịch sử | D | xfail F | ME |
| F-3 | đồng hồ | snowflake chậm 10 phút, tin gửi sau khi quên / giờ ứng dụng nhanh 10 phút, tin gửi trước khi quên | `search_history` thấy tin / tin không vào lịch sử | D | ? (cần chốt thiết kế) | ME |
| R4-1 ‡ | Web | "quên" commit giữa lúc đóng dấu giờ gửi và `snapshot` | không ghi chú nào được lưu | D | xfail R4 | ME |
| R2-1..3 | quyền | admin bị hạ quyền, token cũ còn hạn: danh sách hội thoại / mở hội thoại người khác / danh sách dự án nghiên cứu | chỉ thấy của mình / 404 / chỉ của mình | H | xfail R2 | AU |
| R2-4 | quyền | như trên, gọi route admin | 403 | H | đạt | AU |
| R2-5 | quyền | member được nâng quyền, token cũ / tài khoản đã xoá, token còn hạn | thấy toàn bộ ngay / 401 | H | ? | AU |
| R5-1 | quyền | đúng hai admin hạ quyền chéo, giữ luồng 1 sau khi đếm / hạ quyền tuần tự | đúng một lệnh thành công, còn ≥ 1 admin | D | xfail R5 / đạt | AU |
| R6-1 | OCR | xoá job khi worker đang kẹt trong `recognize_png` | sau khi worker thoát: không dòng DB, không thư mục, `view` báo không có | P | xfail R6 | OJ |
| R7-1 | OCR | job xong, tạo service mới, xoá | thư mục job biến mất | P | xfail R7 | OJ |
| R7-2 | OCR | xoá `..`, `..\..\x`, đường dẫn tuyệt đối, tên thư mục anh em, `ocr_` + 32 ký tự sai | tệp canh ngoài `runs_path` và thư mục anh em còn nguyên | P+M | đạt (chặn cách sửa ẩu) | OJ |
| R7-3 | OCR | Windows giữ một tệp mở lúc xoá; đóng tệp; xoá lại | thư mục biến mất | P | xfail R7 (chỉ win32) | OJ |
| R8-1 | OCR | `dpi` = 50000, 71, 401, 0, −1 / 72, 200, 400 | 422 và không tạo job / 201 | M | xfail R8 / đạt | OJ |
| R8-3 ‡ | OCR | `output_format` lạ; `page_range` dài hơn 100 ký tự | 422 | M | xfail R8 | OJ |
| C-1 | OCR | `1-300000` trên tài liệu 3 trang | từ chối, đỉnh bộ nhớ < 1 MiB | P | xfail C | OJ |
| C-2 | OCR | `2-1`, `0`, `a-b`, `1-2-3`, `1,`, `4` / `1-3`, ` 1 - 2 `, `1,1` | từ chối / chấp nhận đúng tập trang | P | đạt | OJ |
| D-1 ‡ | OCR | tệp tải lên rất lớn (tệp giả đếm lượt đọc) | bị từ chối, không có lượt đọc không giới hạn | P | xfail D | OJ |
| D-2 ‡ | OCR | PDF 30 trang | lúc trang đầu được nhận dạng, số trang đã render ≤ 2 | P | xfail D | OJ |
| E-1 | OCR | member B gọi lịch sử / job / sự kiện / tệp / xuất của job do A tạo (5 tham số) | không thấy / 404 | H | xfail E | OA |
| E-2 | OCR | chủ job, admin, khoá dịch vụ / chưa đăng nhập | đọc được / 401 | H | đạt | OA |
| R9-1 | lọc | hỏi điện thoại và email | cả hai khối tới model | P | xfail R9 | OF |
| R9-2 | lọc | `+1 415…`, `1900 1234`, nhãn `ĐT:`, `Di động:`, `Hotline:` | khối tới model | P | xfail R9 (5 tham số) | OF |
| R9-3 | lọc | "What phone model is shown?", khối không có số / hỏi "e-mail", chỉ có khối tên | model được hỏi / báo thiếu trường, không gọi model | P | xfail R9 | OF |
| R9-5 | lọc | hỏi điện thoại, chỉ có tên / số tài khoản / ngày tháng; số Việt Nam ba kiểu viết; hỏi riêng email, tài khoản | báo thiếu trường, không gọi model / đúng khối, không lẫn | P | đạt (chặn nới regex quá tay) | OF |

Đã chạy thật: R9, C (Python thuần, lần này); R1, R3-1, B (sổ đo 10/11). Mọi dòng khác là dự đoán từ đọc code.

## 3. Ưu tiên và ước lượng

Viết theo mức chạm người dùng, số test tính cả tham số: `review2_support.py` → RP 11 → OR 10 → ME 11 → BT 6 → OJ 25 → OF 15 → AU 8 → OA 10. Tổng khoảng 96 test; phần có container ước 70 giây, phần không container dưới 15 giây. R5-1 đợi tối đa 2 giây theo thiết kế.

## 4. Không tự động hoá được

| Việc | Thay thế |
|---|---|
| Discord thật có gửi sự kiện sửa khi chỉ bung xem trước link không | kiểm tay ở server thử, xem log; B-1 canh phía backend |
| Lệch đồng hồ Windows ↔ Docker sau khi máy ngủ | chạy `clock.py` trước và sau một lần ngủ, ghi sổ đo; F-1, F-2 canh hệ quả |
| Bot bị giết thật giữa lượt | A-3 mô phỏng bằng lease; kiểm tay một lần sau khi sửa A |
| DPI lớn làm nổ RAM khi render thật | R8-1 chặn ở cửa; không render thật trên máy dùng chung |
