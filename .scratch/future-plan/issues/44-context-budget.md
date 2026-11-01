# 44 — Đếm độ dài ngữ cảnh, bỏ kết quả công cụ cũ

Status: mở
Type: task
Blocked by: 41, 42, 43, 47, 48

Bản chất: bàn làm việc của model có hạn; khi đầy, nên dọn thứ cũ nhất bằng code trước, không tốn lượt model.

Việc: ước lượng độ dài từ `pastes.CHARS_PER_TOKEN` hoặc tốt hơn nếu đo được; trước mỗi vòng, nếu sát trần thì thay kết quả
công cụ cũ bằng ghi chú có thể đọc lại, luôn giữ từng lệnh gọi đi cùng kết quả. Nguồn: khảo sát harness mục 2. Mặc định tắt. Đo cô
lập so với mốc 41, thêm bài hội thoại dài nếu bộ hiện tại không chạm trần.
