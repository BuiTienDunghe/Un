# Opus phản biện kế hoạch của Fable — vòng 2 (claude-opus-5-5)

**Bản chất.** Hai bản trùng phần lớn ca. Chỗ khác là cách bảo đảm một test "biết là hỏng" hỏng vì đúng lý do, và vài tình huống hai bên đoán khác nhau về hành vi đúng.

## 1. Nguyên tắc

**Nhận của Fable:**
- Chỉ tham số đang sai mang dấu xfail (`pytest.param(marks=…)`).
- R5 móc `before_cursor_execute` trước `UPDATE users`, ít bám cấu trúc hàm hơn cách bọc `_public` của tôi.
- C dùng `1-300000`, trần 1 MiB.
- R7-3: đóng tệp, xoá lại thì thư mục mất.

**Không đồng ý:**
- **`raises=AssertionError` (Fable) hay `raises=KnownBug` (tôi).** Đã chạy thử: với `raises=AssertionError`, một `assert` hỏng trong fixture vẫn bị báo XFAIL; với `KnownBug` nó thành ERROR. Vậy nguyên tắc 3 của Fable ("fixture hỏng là lỗi") không đứng được cùng nguyên tắc 2. `raises=AttributeError` cũng nuốt lỗi gõ sai tên thuộc tính trong chính test. Tôi giữ `KnownBug`. Chỗ này lệch brief, cần chủ dự án duyệt.
- **R1 dùng cùng lúc `raise_server_exceptions=False` và `raises=AttributeError`.** Lỗi khi đó thành HTTP 500, test hỏng bằng `AssertionError`, nên đỏ thật thay vì xfail. Phải chọn một trong hai.
- **Đồng hồ.** Đồng ý: chỉ lệch phía ứng dụng, 10 phút. Nhưng chỉ lệch "chậm" thì mất chiều nguy hiểm hơn: đồng hồ nhanh làm câu nói trước lúc quên lọt vào lịch sử.
- **Bot chết.** `recover_stale` ghi lại `updated_at` và `available_at` khi đưa lượt về hàng chờ, nên lùi giờ trước đó là vô ích. Cho `recover_stale` chạy trước, rồi lùi **mọi** cột giờ. Nếu không, bản sửa dựa vào cột khác sẽ để test xfail mãi.
- **R4.** Cần ngủ khoảng 50 ms trước khi chèn lệnh quên. Postgres có lúc chậm hơn ứng dụng 3 ms, nên không đệm thì bản sửa 4a lúc đạt lúc không.
- **Path traversal.** TestClient gộp `/..` thành 404 trước route (đã thử). Phần HTTP của R7-2 với `..` vì vậy xanh mà không chạm code. Phải dùng `%2e%2e`, `..%5C..%5Cx`.

## 2. Ca của Fable nên nhận

- **R1-1:** tham số "mới hơn mốc" cho tin bot.
- **R1-3:** `outside_session`, `not_found`.
- **N2-2:** kỳ vọng "cả câu hỏi lẫn đáp án cũ đều không vào prompt".
- **N4-2:** lượt quên đã lưu đáp án, giao hỏng thì gửi lại đúng đáp án đó. Bản sửa R3 dễ làm hỏng ca này.
- **N4-3:** ghi rõ là đang đạt nhờ chính lỗi N4.
- **A-10:** hết hạn chờ khi lượt còn `queued`. Đây là nguồn lượt mồ côi tôi bỏ sót.
- **F-2:** phía Web, đồng hồ chậm.
- **R8-1:** thêm "không tạo job".
- **E ở mức H:** thêm `events`, chủ job, người chưa đăng nhập.
- **R7-2:** thêm đường dẫn tuyệt đối, thư mục anh em.
- **R9-5:** thêm ba kiểu viết số Việt Nam.

## 3. Ca nên bỏ hoặc sửa

| ID | Lý do |
|---|---|
| A-1, A-7 | trùng `test_max_attempts_…` và `test_atomic_claim_…` |
| A-8, phần timeout | `test_discord_progress_message.py:294` ghim "timeout thì không thử lại" |
| A-5 "?" | `cancel-open` huỷ mọi lượt mở, chắc chắn đạt |
| N2-3 | mã lỗi là R1, nên đổi ID |
| R6-1 | hướng 6b (trả 409) sẽ xfail mãi; phải nhận cả kết cục "409, job còn nguyên" |
| R9-2, `1900 1234` không nhãn | xung đột R9-5; dùng `Hotline: 1900 1234` |
| D-2, 30 trang | tốn ở mọi lần chạy; 6 trang, dpi 72 là đủ |
| R4-1 ‡ | đúng cho cả 4a lẫn 4b khi có khoảng đệm |

## 4. Mâu thuẫn kỳ vọng

| Tình huống | Fable | Opus | Đề xuất |
|---|---|---|---|
| Người khác sửa tin khi lượt đang chờ (B-5) | đạt, câu báo cố định | chưa biết | Câu báo nói sai với người hỏi; để ngoài, ghi câu hỏi thiết kế |
| Lệnh xoá tin bot tới trước khi tin vào sổ | ? | xfail B | Theo Fable: có thể chỉ sửa được ở bot |
| Đồng hồ nhanh, câu nói trước lúc quên | ? | xfail F | xfail F: "đã quên thì không nhắc lại" là lời hứa cốt lõi |
| Snowflake chậm, tin gửi sau lúc quên | ? | xfail F | xfail F, đối xứng với F-1 của Fable |
| Lỗi bất ngờ khi chuẩn bị lượt | A ‡ | R1 | Mã A: sửa R1 theo hướng 1b thì không có lưới này |
| Admin bị hạ dùng token cũ | 404 | 404 | 401, 403 hoặc 404, không có nội dung; hướng 2c trả 401 |

## 5. Ca phụ thuộc thiết kế

**Đồng ý** chỉ kiểm kết quả cho mọi ca xfail. Test gắn với một cơ chế sẽ xfail mãi nếu chủ dự án chọn cơ chế khác, nên cứ báo "còn hỏng" dù lỗi đã sửa. Kèm ba điều kiện:

1. **A cần thêm một mức test.** Bot thật (`DiscordConversationGateway` + `LocalAgentClient`) nối với backend thật qua `httpx.ASGITransport` (httpx 0.28.1 có sẵn). Chỉ ở mức này mới kiểm được "tin sau lượt mồ côi được trả lời trong hạn chờ" cho cả A-a, A-b, A-c.
2. **Ca đang đạt mà brief yêu cầu giữ thì tách hai.** Với "người sửa tin làm quên cả kênh": phần "chữ cũ không quay lại" vào bộ; phần "quên cả kênh" chỉ vào khi chủ dự án chốt giữ thiết kế này.
3. **Ca để ngoài phải ghi vào một danh sách kèm lý do**, để không mất dấu.

Áp vào từng ca:
- Các ca A cơ chế của hai bản gộp thành ca tích hợp.
- R2 kiểm "không đọc được"; R4 giữ; R6 nhận hai kết cục.
- D-1 chỉ vào khi có trần cỡ tệp.
- D-2 để ngoài: thứ tự render là cơ chế, và bản sửa bằng trần số trang nhân DPI sẽ không làm nó xanh.
