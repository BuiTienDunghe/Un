# Kế hoạch bộ test review2 — Opus (claude-opus-5-5), vòng 1, độc lập

**Bản chất.** Mỗi lỗi thành một tình huống "người dùng làm X thì hệ thống phải làm Y", mang dấu "đang hỏng" tới khi được sửa. Phần khó là bảo đảm nó hỏng vì đúng lỗi đó, không vì lỗi khác che lấp hay vì may rủi thời gian.

## 1. Nguyên tắc

**Mức.**
- **Py**, không DB: R9, C, D.
- **HTTP**, không container: FastAPI tối thiểu + `ocr_router` + store giả (mẫu `test_ocr_evidence_api.py`), danh tính tiêm qua middleware: R6, R7, R8, E phía thành viên. Ca admin của E chạy trên `client`, vì bản sửa có thể đọc lại vai trò từ DB.
- **DB**: R1, N2, R3, N4, A, B, F, R4 dùng lại `v2client`, `send`, `queue`, `ledger`, `channel_barrier`, `memory`. R2, R5 dùng `client`, tạo user `r2-*` bằng `AuthService.create_user`.
- **Bot**: `FakeBackend`, `FakeSource`, `run` từ `test_discord_progress_message.py`; không import hàm `test_*`, kẻo chạy hai lần.

**Giả lập.**
- *Đồng hồ:* thay `datetime` cấp module trong `repositories`, `chat_service` và `_utc_now` của store để lệch ±30 s; lệnh quên gọi thật nên mốc theo giờ Postgres; Discord dùng snowflake lệch ±30 s. Không ghi tay `barrier_at`, kẻo bản sửa đúng vẫn hỏng. 30 s ≫ độ lệch đã đo (≤ 3 ms).
- *5xx, timeout:* `FakeBackend` ném lỗi; phía backend, `OllamaClient.chat` ném ở lần đầu.
- *Bot chết:* execute xong, không complete, lùi `lease_expires_at` bằng SQL.
- *Race, không ngủ chờ:* R4 bọc `snapshot` để lệnh quên commit bên trong, sau 50 ms (vượt độ lệch đồng hồ). R5 bọc `_public` (sau lệnh đếm, trước commit) bằng `Barrier(2)` chờ tối đa 2 s, bỏ qua `BrokenBarrierError`, để bản đã sửa vẫn chạy hết. R6 cho `recognize_png` chờ một `Event`.
- *Khởi động lại:* `OcrJobService` mới cùng thư mục, store; Discord gọi `cancel-open`.
- *Khoá tệp Windows:* giữ một handle mở khi xoá; bỏ qua ngoài Windows.
- *`..` trong URL:* TestClient gộp `/..` thành 404 trước route (đã thử), nên dùng `%2e%2e`, `..%5C..%5Cx`.

**xfail phải hỏng đúng lý do.**
1. Thêm `raises=KnownBug` vào `xfail(strict=True, reason="review2 <mã>: …")` của brief (lệch brief, cần họp duyệt). `KnownBug` kế thừa `AssertionError`, chỉ ném ở dòng kiểm triệu chứng; tiền đề dùng `assert` thường nên hỏng là đỏ thật (đã chạy thử).
2. Crash R1 bắt tại đúng lời gọi `execute`, đổi thành `KnownBug`; để `AttributeError` trong `raises=` thì lỗi gõ trong test cũng xfail nhờ may.
3. Một test, một mã. A tạo lượt mồ côi bằng "bot chết", không bằng crash R1, kẻo sửa R1 xong A xanh oan. N2, R3 dùng tin chưa vào sổ bị sửa (vết xoá nằm ở `__deleted__`) và lấy "mốc kênh không đổi" làm tiền đề, vì kiểm mốc sẽ che lỗi.
4. Kiểm điều người dùng thấy, không kiểm cách sửa. Ca chỉ lật theo một hướng sửa thì ghi tên hướng.
5. Lúc viết, mỗi ca xfail được vá tạm một lần để thấy XPASS, ghi nhật ký, rồi bỏ vá.
6. Đầu vào rẻ, vì đường lỗi chạy mọi lần: C đo đỉnh bộ nhớ, không đo giờ; R8 chỉ dùng PNG.

## 2. Bảng ca

Tệp `backend/tests/test_review2_<x>.py`: **dt** discord_turns, **ld** ledger, **ck** clocks, **wm** web_memory, **au** auth, **ocr**, **rd** ocr_reader; **bot** = `tests/test_review2_bot_turns.py`. "(chạy)": đã tái hiện 10/11; không ghi: dự đoán từ đọc code.

| ID | Vùng | Nếu… | Thì… | Mức | Hiện tại | Tệp |
|---|---|---|---|---|---|---|
| R1-1 | reply | server có mốc; reply tin người, đáp án bot cũ hơn mốc, hoặc mã không tồn tại | 200, model được gọi, chữ cũ không vào prompt | DB | xfail R1 (chạy) | dt |
| R1-2 | reply | reply tin mới hơn mốc | chữ tin gốc có trong prompt | DB | xfail R1 | dt |
| R1-3 | reply | server chưa có mốc | chữ tin gốc có trong prompt | DB | đạt | dt |
| R1-4 | reply | lỗi bất ngờ khi chuẩn bị lượt | không 500; lần 3 thành `failed`, lượt sau chạy | DB | xfail R1; chỉ hướng 1a | dt |
| N2-1 | reply | tin gốc chưa vào sổ bị sửa, kênh không mốc; reply nó hoặc đáp án bot của nó | chữ cũ không vào prompt | DB | xfail N2 | dt |
| R1-5 | reply | tin gốc đã vào sổ rồi bị xoá (mốc dời); reply vào nó | 200, chữ đã xoá không vào prompt | DB | xfail R1 | dt |
| R3-1 | phát lại | lượt xong, tin chưa vào sổ bị sửa, execute lại | không trả đáp án cũ | DB | xfail R3 (chạy) | dt |
| R3-2 | gửi lại | đáp án đã lưu, giao hỏng, tin chưa vào sổ bị sửa, execute lại | không trả đáp án cũ | DB | xfail R3 | dt |
| R3-3 | gửi lại | như R3-2, tin đã vào sổ hoặc bị xoá kèm kênh (mốc dời) | câu cố định thay đáp án cũ | DB | đạt | dt |
| N4-1 | thử lại | "Hãy quên…", model hỏng lần đầu, execute lại | không ra câu "tin đã bị xoá/sửa" | DB | xfail N4 | dt |
| N4-2 | thử lại | "Hãy nhớ…", model hỏng lần đầu | biên nhận "đã lưu", đúng một nguồn | DB | đạt | dt |
| A-1 | mồ côi | bot chết sau execute; sau khi lượt mồ côi về hàng chờ, lùi mọi cột giờ của nó 1 giờ | lượt sau chạy, hoặc lượt mồ côi `failed` | DB | xfail A; lật với hướng A-b, A-c | dt |
| A-2 | mồ côi | như A-1, xét kênh khác; hoặc sau `cancel-open` | vẫn chạy | DB | đạt | dt |
| A-3 | mồ côi | lease hết, bot gọi lại execute chính lượt đó | gửi lại đáp án đã lưu, không gọi model lại | DB | đạt | dt |
| A-4 | bot | execute trả 5xx một lần rồi có đáp án | bot gọi lại trong hạn chờ, giao đáp án | Bot | xfail A; chỉ hướng A-a | bot |
| A-5 | bot | gửi Discord hỏng (lỗi thường) | lượt không nằm `queued` không chủ | Bot | xfail A; chỉ hướng phía bot | bot |
| A-6 | bot | tin gốc bị xoá trước khi giao | `fail(retryable=False)` | Bot | đạt | bot |
| B-1 | sổ | bot sửa "⏳" khi lượt khác đang xếp hàng | lượt đó trả lời thường, còn lịch sử | DB | đạt (nhờ sửa B) | ld |
| B-2 | sổ | người sửa chữ một tin không liên quan | mốc dời, Ún quên cả kênh (thiết kế) | DB | đạt | ld |
| B-3 | sổ | lệnh xoá tin bot tới trước khi tin vào sổ | mốc không dời | DB | xfail B; có thể phải sửa ở bot | ld |
| B-4 | sổ | người xoá đáp án của bot | ? | DB | chưa biết: đáp án vẫn vào lịch sử | ld |
| B-5 | sổ | người sửa tin, lượt người khác đang chờ ra câu "đã bị sửa" | ? | DB | chưa biết (thiết kế) | ld |
| F-1 | đồng hồ | ứng dụng nhanh 30 s; nói mã, quên, hỏi lại | mã không vào prompt | DB | xfail F | ck |
| F-2 | đồng hồ | ứng dụng chậm 30 s; quên rồi gửi tin mới | trả lời thường | DB | xfail F | ck |
| F-3 | đồng hồ | snowflake nhanh 30 s, ghi trước khi quên; chậm 30 s, ghi sau | tìm lịch sử bỏ tin trước, trả tin sau | DB | xfail F | ck |
| F-4 | đồng hồ | như F-1 trên Web | mã không vào lịch sử | DB | xfail F | wm |
| R4-1 | Web | "quên" commit giữa giờ gửi và lúc chụp trạng thái của "Hãy nhớ…" | không lưu; biên nhận "Chưa lưu" | DB | xfail R4 | wm |
| R2-1 | quyền | admin B bị hạ, token cũ xem hội thoại, dự án của A | 404; danh sách chỉ của B | DB | xfail R2 | au |
| R2-2 | quyền | như trên, gọi `/auth/users` | 403 | DB | đạt | au |
| R2-3 | quyền | dự án B tạo khi còn admin (chủ rỗng), sau khi bị hạ | ? | DB | chưa biết (bẫy hướng 2a) | au |
| R5-1 | quyền | đúng hai admin (tiền đề); hai luồng gọi `set_role` hạ nhau cùng lúc | một thành công, một 409, còn ≥ 1 admin | DB | xfail R5 | au |
| R6-1 | OCR | xoá job đang chạy, có hoặc không huỷ trước | không hiện lại, thư mục mất; hoặc 409, job nguyên | HTTP | xfail R6 | ocr |
| R6-2 | OCR | xoá job đã xong | mất khỏi lịch sử và đĩa | HTTP | đạt | ocr |
| R7-1 | OCR | khởi động lại rồi xoá ngay | thư mục mất | HTTP | xfail R7 | ocr |
| R7-2 | OCR | khởi động lại, mở job, rồi xoá | thư mục mất | HTTP | đạt | ocr |
| R7-3 | OCR | xoá `%2e%2e`, `..%5C..%5Cx` | thư mục cha nguyên vẹn | HTTP | đạt (chặn bản sửa vội) | ocr |
| R7-4 | OCR | `root` lưu trong DB trỏ ra ngoài thư mục OCR | không xoá ngoài đó | HTTP | xfail R7 | ocr |
| R7-5 | OCR | Windows: một tệp của job đang mở khi xoá | không trả 204 khi còn sót tệp | HTTP | xfail R7 | ocr |
| R8-1 | OCR | dpi 50000, 401, 71, 0, −1; `output_format=evil`; `page_range` > 100 ký tự | 422 | HTTP | xfail R8 (chạy) | ocr |
| R8-2 | OCR | dpi 72, 200, 400 | 201 | HTTP | đạt | ocr |
| C-1 | OCR | `1-1000000` trên PDF 3 trang | `ValueError`, đỉnh bộ nhớ < 8 MiB | Py | xfail C (chạy: 67 MiB) | ocr |
| C-2 | OCR | `1-3`, `1,1,2`; `5-1`, `0`, `-1`, `1-2-3`, `a`, `4` | đúng trang; `ValueError` | Py | đạt | ocr |
| D-1 | OCR | tệp tải lên khai 10 GiB | từ chối trước khi đọc quá 256 MiB | Py | xfail D | ocr |
| D-2 | OCR | PDF 4 trang | trang 1 được OCR trước khi trang 4 được vẽ | Py | xfail D | ocr |
| E-1 | OCR | thành viên B xem, huỷ, export, promote job của A; xem lịch sử | 404, không thấy | HTTP | xfail E | ocr |
| E-2 | OCR | admin hoặc khoá API xem job của A | 200 | DB | đạt | ocr |
| E-3 | OCR | job cũ không có chủ | chỉ admin thấy | DB | xfail E | ocr |
| R9-1 | đọc OCR | hỏi "điện thoại và email", cả hai thứ tự | cả hai khối tới model | Py | xfail R9 (chạy) | rd |
| R9-2 | đọc OCR | `+1 415…`, `ĐT:`, `Di động:`, `Hotline 1900…`, `(84-28)…` | khối tới model | Py | xfail R9 (chạy) | rd |
| R9-3 | đọc OCR | "What phone model…"; hỏi "e-mail" khi không có email | lần lượt: gọi model; không gọi | Py | xfail R9 (chạy) | rd |
| R9-4 | đọc OCR | hỏi điện thoại, chỉ có `STK: 0123 456 789` và ngày | không gọi model | Py | đạt (chặn nới quá tay) | rd |

Ca đã có test, không viết lại: quên sau lúc chụp, hạ admin cuối, execute trùng, lease hết, bot sửa/xoá tin.

## 3. Ưu tiên và ước lượng

| Thứ tự | Tệp | Số test, tính tham số | Thời gian |
|---|---|---:|---:|
| 1 | `review2_support.py` | — | — |
| 2 | dt | 18 | ~25 s |
| 3 | ocr | 32 | ~8 s |
| 4 | rd | 10 | < 1 s |
| 5 | ld | 3 | ~4 s |
| 6 | ck, wm | 6 | ~8 s |
| 7 | au | 5 | ~10 s |
| 8 | bot | 3 | ~2 s |

Kênh kẹt hại nhất nên trước; OCR không cần container nên sớm; bot chờ chốt hướng A. Tổng khoảng 77 test, dưới 1,5 phút.

**Cần họp chốt:**
- Bỏ biến thể timeout của A-4, vì `test_discord_progress_message.py:294` ghim "timeout → báo lỗi, không thử lại"; chọn A-a thì phải sửa test đó, ngoài phạm vi brief.
- D-1 giả định trần tải lên ≤ 256 MiB; trần thật do chủ dự án định.

## 4. Không tự động hoá được

| Tình huống | Thay thế |
|---|---|
| Discord thật: bung link; hai server đã có mốc | server thử: dán link xem mốc có dời; sửa R1 xong, reply một tin mỗi server |
| Bot chết thật giữa lượt | tắt bot khi đang "⏳", bật lại, gọi Ún cùng kênh |
| Máy ngủ làm lệch đồng hồ Windows và Docker | F dùng lệch giả; đo tay bằng `clock.py` trước, sau khi ngủ |
| PDF lớn, DPI cao, RAM thật | D-2 kiểm thứ tự; đo tay một PDF 300 trang |
