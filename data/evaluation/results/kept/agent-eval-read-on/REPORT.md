# Bước đọc tiếp và dọn ngữ cảnh trên v0-long.2 (02/11/2026)

Commit `9bae3fa`, Ollama 0.40.13, Qwen 9B, nhiệt độ 0, seed 42, gỡ model trước mỗi bài, cùng ngày, một lần chạy cho mỗi nhánh. Bộ bài tự viết. "Dữ kiện" là số mẫu `must_mention` khớp trong câu trả lời; một bài chỉ đạt khi đủ cả.

| Nhánh | Bài đạt | Dữ kiện | Lần đọc | Lần dọn | Lâu nhất |
|---|---|---|---|---|---|
| ctx-01..04, 3 vòng, không bật gì | 0/4 | 0/13 | 0 | 0 | 7,1 s |
| ctx-01..04, 3 vòng, đọc tiếp | 0/4 | 4/13 | 5 | 0 | 19,5 s |
| ctx-01..04, 3 vòng, đọc tiếp + dọn | 0/4 | 4/13 | 5 | 2 | 15,7 s |
| ctx-01..04, 8 vòng, không bật gì | 0/4 | 0/13 | 0 | 0 | 7,1 s |
| ctx-01..04, 8 vòng, đọc tiếp | 0/4 | 5/13 | 6 | 0 | 14,4 s |
| ctx-01..04, 8 vòng, đọc tiếp + dọn | 0/4 | 3/13 | 7 | 2 | 17,7 s |
| ctx-05..07, 8 vòng, không bật gì | 0/3 | 8/12 | 10 | 0 | 18,5 s |
| ctx-05..07, 8 vòng, chỉ dọn | 0/3 | 8/12 | 10 | 1 | 18,5 s |
| ctx-05..07, 8 vòng, đọc tiếp | 0/3 | 8/12 | 10 | 0 | 24,4 s |
| ctx-05..07, 8 vòng, đọc tiếp + dọn | 0/3 | 8/12 | 10 | 1 | 24,4 s |

66 bài v0, cùng ngày: đối chứng 55, đọc tiếp 55, không bài nào lên hay xuống. Bước này chạy đúng một lần (doc-24, câu trả lời vẫn đúng, 4,5 s thành 9,4 s, và câu trả lời mở đầu bằng "Tôi đã đọc thêm", trái lời dặn không nhắc tới việc kiểm tra). Trung vị 4,40 s và 4,43 s.

- Đọc tiếp: có ích trên ctx-01..04, không ích gì trên ctx-05..07 (bị gửi lại nhưng model không đọc thêm lần nào, số lần đọc giữ nguyên 10). Mẫu nhận biết "đã bỏ cuộc" viết từ chính các câu trả lời của bộ này.
- Thêm vòng: không tự làm model đọc nhiều hơn; không có bước đọc tiếp thì 8 vòng vẫn 0 lần đọc.
- Dọn ngữ cảnh (ticket 44): chạy thật 2-3 lần mỗi cấu hình, chưa có lợi ích nào; ở 8 vòng dữ kiện từ 5 xuống 3. Mẫu quá nhỏ để kết luận là có hại.
