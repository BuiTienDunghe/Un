**KÝ KÈM SỬA** — Opus (claude-opus-5-5), vòng 3

## 1. Ca kiểm cơ chế hoặc kỳ vọng sai

| ID | Vấn đề | Sửa |
|---|---|---|
| A-5..A-8 | Mức T chưa lật với mọi hướng sửa: lease mặc định làm bản sửa phía bot vượt hạn chờ; không lùi giờ thì bản sửa phía backend không gỡ kịp lượt mồ côi | `lease_seconds` = 3, hạn chờ của bot ≥ 4 lần lease. Khi tin 1 xong: cho `recover_stale` chạy, lùi mọi cột giờ của lượt còn mở 1 giờ, rồi mới gửi tin 2 |
| A-1 | "Không 5xx" là cơ chế lưới backend. Nếu có người gọi lại sau khi lease hết, kênh hôm nay đã được gỡ | Chuyển vào "để ngoài"; thêm tham số "lỗi lặp lại mãi" cho A-6 |
| R8-1 | "422" loại mất bản sửa bằng kẹp DPI. `output_format` và `page_range` dài không thuộc mã nào | Kỳ vọng: "422, hoặc job tạo ra có dpi trong 72–400". Đưa hai tham số kia ra ngoài |
| N4-1 | "Model được gọi" là cơ chế | "Biên nhận 'đã quên' có trong prompt hoặc trong đáp án" |

Đồng ý để R4 và D ở ngoài. Với 4b, giờ gửi lấy sau lệnh quên, nên không có điểm chèn nào đúng cho mọi cách sửa. R4 vẫn có test đang đạt cho trường hợp "quên sau lúc chụp" (`test_source_memory.py`); cần ghi điều này khi giao bộ test.

## 2. Ca rơi không lý do

Không có. Nên thêm `evaluate` làm tham số thứ 8 của E-1.

## 3. Hướng xử lý A-1, A-8

**Đồng ý**, kèm điều kiện:

- Hai núm thời gian ở mục 1 là bắt buộc. Thiếu chúng, mức T chỉ chuyển sự phụ thuộc từ cơ chế backend sang cơ chế bot.
- A-1 không cần ca riêng: A-6 với "lỗi lặp lại mãi" chính là bản kiểm kết quả của nó.
- A-8 cần bước khởi động lại bot (`create_bot(...)` rồi `await bot.on_ready()`), vì "bot dọn lượt khi khởi động" cũng là một cách sửa hợp lệ. Hiện chỉ `control.py` gọi `cancel-open`. Nếu không chạy được ngoài Discord, A-8 chuyển ra ngoài và kiểm tay; không giữ bản backend.

Nếu không nối được `ASGITransport`, tôi chấp nhận phương án dự phòng, với `reason` ghi "chỉ lật khi sửa ở backend". bb sẽ chạy khoảng 60 giây.
